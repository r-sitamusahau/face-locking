"""
vision_node.py
BENAX Vision Node — single-speaker face tracking + MQTT motor commands.
Topic: vision/rusi123/movement
"""

import time
import argparse
import cv2
import json
import paho.mqtt.client as mqtt
from pathlib import Path
import sys
import base64

sys.path.append(str(Path(__file__).parent.parent))

from src.haar_5pt import Haar5ptDetector
from src.recognize import ArcFaceEmbedderONNX, FaceDBMatcher, load_db_npz
from src.face_locking import FaceLockSystem
from src.camera_util import open_camera, DEFAULT_EXTERNAL_CAMERA, EXTERNAL_CAMERA_ID
from src.evidence_logger import EvidenceLogger
from src.command_smoother import MotorCommandSmoother
from src.speaker_select import resolve_target_name, default_db_path

DEFAULT_BROKER = "127.0.0.1"
PORT = 1884
TEAM_ID = "rusi123"
TOPIC_MOVEMENT = f"vision/{TEAM_ID}/movement"
TOPIC_HEARTBEAT = f"vision/{TEAM_ID}/heartbeat"

# BENAX motor commands (horizontal pan only)
BENAX_COMMANDS = (
    "SCAN",
    "OUT_OF_FRAME",
    "MOVED_LEFT",
    "MOVED_RIGHT",
    "CENTERED",
    "STOPPED",
)


class VisionNode:
    def __init__(self, broker, port, target_name, camera_index=DEFAULT_EXTERNAL_CAMERA):
        self.client = mqtt.Client(client_id=f"{TEAM_ID}_vision_node")
        self.client.on_connect = self.on_connect
        self.client.connect(broker, port, 60)
        self.client.loop_start()

        print("Initializing Face Recognition...")
        self.det = Haar5ptDetector(min_size=(70, 70))
        self.embedder = ArcFaceEmbedderONNX(input_size=(112, 112))

        db_path = Path(__file__).parent.parent / "data/db/face_db.npz"
        if not db_path.exists():
            print(f"ERROR: Face DB not found at {db_path}. Run enroll.py first!")
            sys.exit(1)

        db = load_db_npz(db_path)
        if target_name not in db:
            print(f"WARNING: Target '{target_name}' not in database. Available: {list(db.keys())}")

        self.matcher = FaceDBMatcher(db, dist_thresh=0.60)
        self.system = FaceLockSystem(target_name, self.matcher, self.det)
        self.evidence = EvidenceLogger()
        self.smoother = MotorCommandSmoother(hold_frames=4)

        self.running = True
        self.last_heartbeat = 0
        self.last_publish_time = 0
        self.last_status = None
        self.last_locked = False
        self.mqtt_topic = TOPIC_MOVEMENT
        self.snapshot_sent = False
        self.camera_index = int(camera_index)

    def on_connect(self, client, userdata, flags, rc):
        print(f"Connected to MQTT Broker with result code {rc}")
        self.publish_heartbeat()

    def publish_movement(
        self,
        status,
        confidence=0.0,
        target=None,
        locked=False,
        face_image=None,
        offset_x=0.0,
        offset_y=0.0,
        searching=False,
        *,
        log_evidence=True,
        force_log=False,
    ):
        payload = {
            "status": status,
            "confidence": confidence,
            "target": target,
            "locked": locked,
            "searching": searching,
            "offset_x": round(offset_x, 3),
            "offset_y": round(offset_y, 3),
            "timestamp": time.time(),
        }

        if face_image is not None:
            _, buffer = cv2.imencode(".jpg", face_image, [cv2.IMWRITE_JPEG_QUALITY, 70])
            payload["face_image"] = base64.b64encode(buffer).decode("utf-8")

        self.client.publish(self.mqtt_topic, json.dumps(payload))
        print(f"Published: {status} (search={searching}, conf={confidence:.2f})")

        if log_evidence:
            self.evidence.log(
                speaker_id=target or self.system.target_name,
                confidence=confidence,
                motor_command=status,
                locked=locked,
                force=force_log,
            )

    def publish_heartbeat(self):
        payload = {
            "node": "pc_vision",
            "status": "ONLINE",
            "timestamp": time.time(),
        }
        self.client.publish(TOPIC_HEARTBEAT, json.dumps(payload))

    def run(self):
        cap = open_camera(self.camera_index)

        print(f"Vision Node Started. Tracking target: {self.system.target_name}")
        print(f"Publishing BENAX commands to {TOPIC_MOVEMENT}")
        print(f"Commands: {', '.join(BENAX_COMMANDS)}")
        print("Evidence logs -> data/logs/evidence_*.csv")

        while self.running:
            ret, frame = cap.read()
            if not ret:
                break

            frame = cv2.flip(frame, 1)
            H, W = frame.shape[:2]

            result = self.system.process_frame(frame, self.embedder)
            face_crop = None

            if result.target_face and not self.snapshot_sent:
                f = result.target_face
                pad = 20
                x1 = max(0, int(f.x1) - pad)
                y1 = max(0, int(f.y1) - pad)
                x2 = min(W, int(f.x2) + pad)
                y2 = min(H, int(f.y2) + pad)
                face_crop = frame[y1:y2, x1:x2]
                self.snapshot_sent = True

            if result.should_search and self.snapshot_sent:
                self.snapshot_sent = False

            raw_status = result.movement
            immediate = raw_status in ("SCAN", "OUT_OF_FRAME", "STOPPED") or (
                result.locked and not self.last_locked
            )
            status = self.smoother.filter(raw_status, immediate=immediate)

            current_time = time.time()
            status_changed = status != self.last_status
            lock_changed = result.locked != self.last_locked
            rate_ok = current_time - self.last_publish_time >= 0.08

            if lock_changed and result.locked and not result.should_search:
                self.publish_movement(
                    "STOPPED",
                    confidence=result.confidence,
                    target=self.system.target_name,
                    locked=True,
                    face_image=face_crop,
                    offset_x=result.offset_x,
                    offset_y=result.offset_y,
                    searching=False,
                    force_log=True,
                )
                self.last_publish_time = current_time
                self.last_status = "STOPPED"
                self.last_locked = True
                face_crop = None

            elif status_changed or rate_ok:
                self.publish_movement(
                    status,
                    confidence=result.confidence,
                    target=self.system.target_name,
                    locked=result.locked,
                    face_image=face_crop,
                    offset_x=result.offset_x,
                    offset_y=result.offset_y,
                    searching=result.should_search,
                    force_log=status_changed,
                )
                self.last_publish_time = current_time
                self.last_status = status
                self.last_locked = result.locked
                face_crop = None

            if time.time() - self.last_heartbeat > 5:
                self.publish_heartbeat()
                self.last_heartbeat = time.time()

            cv2.imshow("Vision Node (Locked)", result.vis)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

        cap.release()
        cv2.destroyAllWindows()
        self.client.loop_stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="BENAX vision node — lock onto one enrolled speaker and publish motor commands."
    )
    parser.add_argument("--broker", type=str, default=DEFAULT_BROKER, help="MQTT Broker Address")
    parser.add_argument(
        "--name",
        type=str,
        default=None,
        help="Speaker to lock (skip menu). Omit or use --pick to choose at startup.",
    )
    parser.add_argument(
        "--pick",
        action="store_true",
        help="Always show enrolled speaker menu before starting",
    )
    parser.add_argument(
        "--camera",
        type=int,
        default=DEFAULT_EXTERNAL_CAMERA,
        help=f"External USB camera index (default: {EXTERNAL_CAMERA_ID})",
    )
    args = parser.parse_args()

    target = resolve_target_name(args.name, pick=args.pick, db_path=default_db_path())
    print(f"\n>>> Speaker lock target: {target.upper()} <<<\n")

    node = VisionNode(args.broker, PORT, target, camera_index=args.camera)
    node.run()
