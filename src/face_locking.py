"""
face_locking.py
"""
import time
import argparse
import cv2
import numpy as np
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict
from enum import Enum
import mediapipe as mp

# Import existing modules
# We need to ensure we can import from . if run as a module or direct
try:
    from .haar_5pt import Haar5ptDetector, align_face_5pt, _bbox_from_5pt, _clip_box_xyxy
    from .recognize import ArcFaceEmbedderONNX, FaceDBMatcher, load_db_npz
    from .camera_util import open_camera, DEFAULT_EXTERNAL_CAMERA, EXTERNAL_CAMERA_ID
    from .speaker_select import resolve_target_name, default_db_path
except ImportError:
    import sys
    sys.path.append(str(Path(__file__).parent.parent))
    from src.haar_5pt import Haar5ptDetector, align_face_5pt, _bbox_from_5pt, _clip_box_xyxy
    from src.recognize import ArcFaceEmbedderONNX, FaceDBMatcher, load_db_npz
    from src.camera_util import open_camera, DEFAULT_EXTERNAL_CAMERA, EXTERNAL_CAMERA_ID
    from src.speaker_select import resolve_target_name, default_db_path

# ---------------------------------------------------------
# Action Logic
# ---------------------------------------------------------
@dataclass
class FaceAction:
    timestamp: float
    action_type: str
    details: str

class FaceActionDetector:
    def __init__(self):
        # MediaPipe Landmark Indices
        # Left Eye (for EAR)
        self.P_LEFT_EYE = [33, 160, 158, 133, 153, 144] 
        # Right Eye (for EAR)
        self.P_RIGHT_EYE = [362, 385, 387, 263, 373, 380]
        # Mouth (for SMILE/MAR) - 61=left corner, 291=right corner, 0=upper lip, 17=lower lip
        self.P_MOUTH = [61, 291, 0, 17]
        # Nose for pose
        self.P_NOSE_TIP = 1
        
        # Thresholds
        self.EAR_THRESH = 0.22  # Below this -> closed
        self.MAR_THRESH = 0.45  # Above this -> smile/open (simplified smile detection)
        # Smile can also be detected by mouth corner width relative to face width

        self.last_blink_time = 0.0
        self.blink_cooldown = 0.3
        
        self.last_nose_x = None

    def _ear(self, lm, idxs):
        # eye aspect ratio
        # vertical dists
        v1 = np.linalg.norm(lm[idxs[1]] - lm[idxs[5]])
        v2 = np.linalg.norm(lm[idxs[2]] - lm[idxs[4]])
        # horizontal
        h = np.linalg.norm(lm[idxs[0]] - lm[idxs[3]])
        return (v1 + v2) / (2.0 * h + 1e-6)

    def detect(self, mp_landmarks, frame_w, frame_h) -> List[Tuple[str, str]]:
        """
        Input: mp_landmarks (list of normalized x,y,z) from MediaPipe
        Returns: list of (ActionType, Description)
        """
        actions = []
        now = time.time()
        
        # Convert necessary landmarks to np arrays for calculation
        coords = np.array([[p.x, p.y] for p in mp_landmarks])
        
        # 1. Blink Detection
        left_ear = self._ear(coords, self.P_LEFT_EYE)
        right_ear = self._ear(coords, self.P_RIGHT_EYE)
        avg_ear = (left_ear + right_ear) / 2.0
        
        if avg_ear < self.EAR_THRESH:
            if (now - self.last_blink_time) > self.blink_cooldown:
                actions.append(("BLINK", f"EAR={avg_ear:.2f}"))
                self.last_blink_time = now

        # 2. Smile Detection (Simple width checks or mouth alignment)
        # Check if mouth corners are 'wide' or mouth is open
        # Better simple smile: check if corners (61, 291) are higher than usual relative to upper lip (0)?
        # Or just use mouth width / jaw width ratio?
        # Let's use simple aspect ratio of mouth for "laugh/smile" (open mouth)
        # and maybe specific corner comparison for closed smile.
        # Simplest: Mouth width (61-291) vs Face Width (234-454 for cheeks)
        left_cheek = coords[234]
        right_cheek = coords[454]
        face_width = np.linalg.norm(right_cheek - left_cheek)
        
        mouth_l = coords[61]
        mouth_r = coords[291]
        mouth_width = np.linalg.norm(mouth_r - mouth_l)
        
        ratio = mouth_width / (face_width + 1e-6)
        if ratio > 0.45: # Tweak this
             actions.append(("SMILE", f"ratio={ratio:.2f}"))

        # 3. Head Movement (Left/Right)
        # Check nose x relative to frame center (0.5 in normalized coords)
        nose = coords[self.P_NOSE_TIP]
        if nose[0] < 0.50:
             actions.append(("MOVED_LEFT", f"nose_x={nose[0]:.2f}"))
        elif nose[0] > 0.60:
             actions.append(("MOVED_RIGHT", f"nose_x={nose[0]:.2f}"))
             
        return actions

# ---------------------------------------------------------
# Face Locking System
# ---------------------------------------------------------
class LockState(Enum):
    SEARCHING = 0
    LOCKED = 1


@dataclass
class FrameResult:
    """Per-frame tracking output for vision_node and MQTT."""
    vis: np.ndarray
    target_face: Optional[object]
    state: LockState
    movement: str           # BENAX: SCAN, OUT_OF_FRAME, MOVED_LEFT, MOVED_RIGHT, CENTERED, STOPPED
    should_search: bool     # True → ESP8266 sweeps pan
    offset_x: float = 0.0   # -1 (left) .. +1 (right)
    offset_y: float = 0.0   # -1 (above) .. +1 (below)
    confidence: float = 0.0
    locked: bool = False


class FaceLockSystem:
    def __init__(self, target_name: str, matcher: FaceDBMatcher, detector: Haar5ptDetector):
        self.target_name = target_name
        self.matcher = matcher
        self.det = detector
        self.state = LockState.SEARCHING

        self.action_det = FaceActionDetector()
        self.history: List[FaceAction] = []

        self.lost_frames = 0
        self.last_confidence = 0.0
        self.frames_since_lock = 999  # hold still briefly when target first seen
        self.HOLD_ON_LOCK_FRAMES = 12  # ~0.4s freeze at detection angle
        self.LOST_GRACE_FRAMES = 8

        # Normalized frame center and deadband (face must stay inside to count as centered)
        self.CENTER_X = 0.5
        self.CENTER_Y = 0.5
        self.DEADBAND_X = 0.07
        # Hysteresis: wider band to exit left/right than to enter (reduces MQTT jitter)
        self.HYSTERESIS_X = 0.03
        self._last_movement = "SCAN"

        ts = time.strftime("%Y%m%d%H%M%S")
        safe_name = "".join(c for c in target_name if c.isalnum())
        self.history_file = Path(f"{safe_name}_history_{ts}.txt")

        print(f"[FaceLock] Initialized. Target: {target_name}. Log: {self.history_file}")

    def _compute_movement(self, f, W: int, H: int) -> Tuple[str, float, float]:
        """Horizontal pan only (BENAX spec). Vertical tilt is manual 2-DOF."""
        cx = (f.x1 + f.x2) / 2.0 / W
        cy = (f.y1 + f.y2) / 2.0 / H
        offset_x = (cx - self.CENTER_X) / self.CENTER_X
        offset_y = (cy - self.CENTER_Y) / self.CENTER_Y

        enter_left = self.CENTER_X - self.DEADBAND_X
        enter_right = self.CENTER_X + self.DEADBAND_X
        exit_left = enter_left + self.HYSTERESIS_X
        exit_right = enter_right - self.HYSTERESIS_X

        prev = self._last_movement
        if prev == "MOVED_LEFT":
            if cx > exit_left:
                status = "CENTERED" if cx <= enter_right else "MOVED_RIGHT"
            else:
                status = "MOVED_LEFT"
        elif prev == "MOVED_RIGHT":
            if cx < exit_right:
                status = "CENTERED" if cx >= enter_left else "MOVED_LEFT"
            else:
                status = "MOVED_RIGHT"
        else:
            if cx < enter_left:
                status = "MOVED_LEFT"
            elif cx > enter_right:
                status = "MOVED_RIGHT"
            else:
                status = "CENTERED"

        self._last_movement = status
        return status, offset_x, offset_y

    def _search_result(self, vis: np.ndarray, movement: str = "SCAN") -> FrameResult:
        self._last_movement = movement
        return FrameResult(
            vis=vis,
            target_face=None,
            state=self.state,
            movement=movement,
            should_search=True,
            locked=False,
        )

    def log_action(self, atype: str, details: str):
        now = time.time()
        # Avoid spamming movement logs? Maybe only log on change?
        # For assignment, "record a history" is key.
        # We can implement a simple deduplication: don't log same action within 0.5s
        if self.history:
            last = self.history[-1]
            if last.action_type == atype and (now - last.timestamp) < 1.0:
                return

        act = FaceAction(timestamp=now, action_type=atype, details=details)
        self.history.append(act)
        
        line = f"{time.strftime('%H:%M:%S', time.localtime(now))} | {atype} | {details}\n"
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(line)
        print(f">> ACTION: {atype} ({details})")

    def process_frame(self, frame: np.ndarray, embedder: ArcFaceEmbedderONNX) -> FrameResult:
        vis = frame.copy()
        H, W = vis.shape[:2]

        faces, mp_res = self.det.detect_with_mesh(frame, max_faces=5)

        target_face = None
        target_sim = 0.0

        for f in faces:
            cv2.rectangle(vis, (f.x1, f.y1), (f.x2, f.y2), (100, 100, 100), 1)

            aligned, _ = align_face_5pt(frame, f.kps, out_size=(112, 112))
            emb = embedder.embed(aligned)
            mr = self.matcher.match(emb)

            if mr.accepted:
                is_target = (mr.name == self.target_name)

                if is_target:
                    if mr.similarity > target_sim:
                        target_sim = mr.similarity
                        target_face = f
                else:
                    cv2.rectangle(vis, (f.x1, f.y1), (f.x2, f.y2), (255, 200, 0), 2)
                    cv2.putText(
                        vis,
                        mr.name,
                        (f.x1, f.y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (255, 200, 0),
                        2,
                    )
            else:
                cv2.rectangle(vis, (f.x1, f.y1), (f.x2, f.y2), (0, 0, 255), 2)
                cv2.putText(
                    vis,
                    "Unknown",
                    (f.x1, f.y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 0, 255),
                    2,
                )

        # --- State machine ---
        if self.state == LockState.SEARCHING:
            cv2.putText(
                vis,
                f"SEARCHING: {self.target_name}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 165, 255),
                2,
            )
            if target_face is not None:
                self.state = LockState.LOCKED
                self.lost_frames = 0
                self.frames_since_lock = 0
                self.last_confidence = target_sim
                self.log_action("LOCK_ACQUIRED", f"sim={target_sim:.2f}")
                movement, offset_x, offset_y = self._movement_while_locked(
                    target_face, W, H
                )
                self._draw_locked_target(vis, target_face, movement, offset_x, offset_y, target_sim)
                return FrameResult(
                    vis=vis,
                    target_face=target_face,
                    state=self.state,
                    movement=movement,
                    should_search=False,
                    offset_x=offset_x,
                    offset_y=offset_y,
                    confidence=target_sim,
                    locked=True,
                )
            return self._search_result(vis, "SCAN")

        # LOCKED
        if target_face is not None:
            self.lost_frames = 0
            self.last_confidence = target_sim
            movement, offset_x, offset_y = self._movement_while_locked(target_face, W, H)
            self._draw_locked_target(vis, target_face, movement, offset_x, offset_y, target_sim)
            self._detect_target_actions(vis, target_face, mp_res, W, H)
            return FrameResult(
                vis=vis,
                target_face=target_face,
                state=self.state,
                movement=movement,
                should_search=False,
                offset_x=offset_x,
                offset_y=offset_y,
                confidence=target_sim,
                locked=True,
            )

        # Target not in frame while locked
        self.lost_frames += 1
        cv2.putText(
            vis,
            f"LOCKED: {self.target_name}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2,
        )
        cv2.putText(
            vis,
            f"Target lost ({self.lost_frames}/{self.LOST_GRACE_FRAMES})",
            (10, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 165, 255),
            2,
        )
        self._draw_confidence_hud(vis, self.last_confidence, y=90, label="Last confidence")

        if self.lost_frames <= self.LOST_GRACE_FRAMES:
            return FrameResult(
                vis=vis,
                target_face=None,
                state=self.state,
                movement="STOPPED",
                should_search=False,
                locked=True,
                confidence=self.last_confidence,
            )

        self.state = LockState.SEARCHING
        self.frames_since_lock = 999
        self._last_movement = "OUT_OF_FRAME"
        self.log_action("LOCK_LOST", "Target left frame — searching")
        return self._search_result(vis, "OUT_OF_FRAME")

    def _movement_while_locked(self, f, W: int, H: int) -> Tuple[str, float, float]:
        """Freeze pan at the moment of detection; follow only after hold period."""
        offset_x, offset_y = self._face_offsets(f, W, H)
        if self.frames_since_lock < self.HOLD_ON_LOCK_FRAMES:
            self.frames_since_lock += 1
            self._last_movement = "STOPPED"
            return "STOPPED", offset_x, offset_y
        movement, ox, oy = self._compute_movement(f, W, H)
        return movement, ox, oy

    def _face_offsets(self, f, W: int, H: int) -> Tuple[float, float]:
        cx = (f.x1 + f.x2) / 2.0 / W
        cy = (f.y1 + f.y2) / 2.0 / H
        offset_x = (cx - self.CENTER_X) / self.CENTER_X
        offset_y = (cy - self.CENTER_Y) / self.CENTER_Y
        return offset_x, offset_y

    def _confidence_color(self, confidence: float) -> Tuple[int, int, int]:
        pct = confidence * 100.0
        if pct >= 75:
            return (0, 220, 100)
        if pct >= 55:
            return (0, 200, 255)
        return (0, 140, 255)

    def _draw_confidence_hud(
        self,
        vis: np.ndarray,
        confidence: float,
        y: int = 60,
        label: str = "Confidence",
    ) -> None:
        pct = confidence * 100.0
        color = self._confidence_color(confidence)
        text = f"{label}: {pct:.1f}%"
        cv2.putText(vis, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.72, color, 2)

        bar_x, bar_w, bar_h = 10, 180, 12
        bar_y = y + 10
        cv2.rectangle(vis, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (40, 40, 40), -1)
        fill_w = int(bar_w * max(0.0, min(1.0, confidence)))
        if fill_w > 0:
            cv2.rectangle(vis, (bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h), color, -1)
        cv2.rectangle(vis, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (180, 180, 180), 1)

    def _draw_locked_target(
        self,
        vis: np.ndarray,
        f,
        movement: str,
        offset_x: float,
        offset_y: float,
        confidence: float,
    ) -> None:
        color = self._confidence_color(confidence)
        cv2.rectangle(vis, (f.x1, f.y1), (f.x2, f.y2), color, 3)
        cv2.putText(
            vis,
            f"{self.target_name.upper()}  {confidence * 100:.1f}%",
            (f.x1, max(20, f.y1 - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            color,
            2,
        )
        cv2.putText(
            vis,
            f"FOLLOW: {movement}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2,
        )
        self._draw_confidence_hud(vis, confidence, y=60)
        cx = int((f.x1 + f.x2) / 2)
        cy = int((f.y1 + f.y2) / 2)
        fx, fy = int(vis.shape[1] * self.CENTER_X), int(vis.shape[0] * self.CENTER_Y)
        cv2.drawMarker(vis, (cx, cy), (0, 255, 255), cv2.MARKER_CROSS, 20, 2)
        cv2.drawMarker(vis, (fx, fy), (255, 255, 255), cv2.MARKER_CROSS, 15, 1)

    def _detect_target_actions(self, vis, target_face, mp_res, W, H) -> None:
        if not mp_res or not mp_res.multi_face_landmarks:
            return
        fw_x, fw_y = (target_face.x1 + target_face.x2) / 2, (target_face.y1 + target_face.y2) / 2
        best_lm = None
        min_dist = float("inf")

        for lm_list in mp_res.multi_face_landmarks:
            nose = lm_list.landmark[1]
            nx, ny = nose.x * W, nose.y * H
            dist = ((nx - fw_x) ** 2 + (ny - fw_y) ** 2) ** 0.5
            if dist < min_dist:
                min_dist = dist
                best_lm = lm_list.landmark

        if best_lm and min_dist < max(target_face.x2 - target_face.x1, target_face.y2 - target_face.y1):
            actions = self.action_det.detect(best_lm, W, H)
            for atype, desc in actions:
                self.log_action(atype, desc)
                cv2.putText(
                    vis,
                    f"ACT: {atype}",
                    (10, vis.shape[0] - 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 255),
                    2,
                )


def main():
    cfg = argparse.ArgumentParser(description="Face locking demo (camera only, no MQTT)")
    cfg.add_argument(
        "--name",
        type=str,
        default=None,
        help="Speaker to lock. Omit or use --pick to choose from enrolled list.",
    )
    cfg.add_argument(
        "--pick",
        action="store_true",
        help="Show enrolled speaker menu before starting",
    )
    cfg.add_argument(
        "--camera",
        type=int,
        default=DEFAULT_EXTERNAL_CAMERA,
        help=f"External USB camera index (default: {EXTERNAL_CAMERA_ID})",
    )
    args = cfg.parse_args()

    db_path = Path("data/db/face_db.npz")
    if not db_path.exists():
        print("No database found! Please run enroll.py first.")
        return

    target = resolve_target_name(args.name, pick=args.pick, db_path=db_path)
    print(f"\n>>> Speaker lock target: {target.upper()} <<<\n")

    det = Haar5ptDetector(min_size=(70, 70), debug=False)
    embedder = ArcFaceEmbedderONNX(input_size=(112, 112))

    db = load_db_npz(db_path)
    matcher = FaceDBMatcher(db, dist_thresh=0.60)

    system = FaceLockSystem(target, matcher, det)
    
    cap = open_camera(args.camera)
    print("Mask Locking System Started. Press 'q' to quit.")
    
    while True:
        ok, frame = cap.read()
        if not ok: break
        
        # Mirror the frame (user requested to "remove" the flip, implying they want the opposite of current)
        frame = cv2.flip(frame, 1)
        
        result = system.process_frame(frame, embedder)
        cv2.imshow("Face Locking", result.vis)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
