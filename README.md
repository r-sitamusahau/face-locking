# BENAX Face Locking — Single-Speaker Vision & Servo Control

AI-powered camera tracking for live presentations: lock onto **one enrolled speaker**, ignore all other faces, and drive a horizontal pan servo over **MQTT**.

**Team:** rusi123  
**Assessment docs:** [ASSESSMENT.md](ASSESSMENT.md) (flowchart, wiring, validation checklist)

---

## System architecture

```
USB Camera (PC)  →  Face detect + ArcFace lock  →  MQTT (1884)  →  ESP8266  →  Pan servo
                              ↓
                    Dashboard :8080 + evidence CSV/JSON
```

| Component | File / URL |
|-----------|------------|
| Enrollment | `src/enroll.py` |
| Speaker lock + tracking | `src/face_locking.py` |
| MQTT publisher + evidence | `src/vision_node.py` |
| MQTT broker | `backend/mqtt_broker.js` |
| Dashboard | `dashboard/index.html` → http://localhost:8080 |
| ESP8266 firmware | `esp8266/vision_servo/vision_servo.ino` |

---

## BENAX motor commands

Published on topic `vision/rusi123/movement`:

| Command | Meaning |
|---------|---------|
| `SCAN` | Searching — no speaker in frame |
| `OUT_OF_FRAME` | Speaker lost — search |
| `MOVED_LEFT` | Pan left to center speaker |
| `MOVED_RIGHT` | Pan right |
| `CENTERED` | Speaker centered — hold |
| `STOPPED` | Lock acquired or brief occlusion — hold |

Vertical aim uses the **manual tilt** on the 2-DOF mount (horizontal servo only).

---

## Quick start

### 1. Dependencies

```powershell
pip install -r requirements.txt
cd backend && npm install
python scripts/download_model.py   # if models/ missing
```

### 2. Enroll speaker (10–30 images)

```powershell
python -m src.enroll --name ruth --auto
```

### 3. Run system (3 terminals)

```powershell
cd backend && npm run broker          # MQTT :1884
cd backend && npm start               # Dashboard :8080
python src\vision_node.py --broker 127.0.0.1 --pick --camera 1
```

**Speaker selection:** When you run without `--name`, or with `--pick`, you get a menu of everyone enrolled in `face_db.npz`. Type the number or name when the assessor says who to lock.

```text
============================================
  SELECT SPEAKER TO LOCK
============================================
    [1]  ruth
    [2]  alice

Your choice: 1
>>> Speaker lock target: RUTH <<<
```

Skip the menu if you already know the name:

```powershell
python src\vision_node.py --broker 127.0.0.1 --name ruth --camera 1
```

### 4. ESP8266

1. Edit Wi-Fi + `mqtt_server` (PC IP) in `esp8266/vision_servo/vision_servo.ino`
2. Upload via Arduino IDE (ESP8266 board, 115200 baud)
3. Serial Monitor: `WiFi connected` → `MQTT ... Connected!`

### 5. Evidence logs

Written live to `data/logs/evidence_*.csv` and `.json`:

- `timestamp`, `speaker_id`, `confidence`, `motor_command`, `locked`

---

## Hardware wiring (summary)

| Servo wire | Connect to |
|------------|------------|
| Signal | ESP8266 **D7 (GPIO13)** |
| V+ | **5V** (VIN or external supply) |
| GND | ESP8266 **GND** |

See [ASSESSMENT.md](ASSESSMENT.md) for full diagram and validation tests.

---

## Project structure

```
FaceLocking/
├── src/
│   ├── enroll.py           # Speaker enrollment
│   ├── face_locking.py     # Single-identity lock + BENAX commands
│   ├── vision_node.py      # Camera + MQTT + evidence logging
│   ├── evidence_logger.py  # CSV/JSON assessor logs
│   └── command_smoother.py # Publish smoothing / hysteresis
├── backend/                # MQTT broker + WebSocket dashboard relay
├── dashboard/              # Live navy UI
├── esp8266/vision_servo/   # Pan servo MQTT subscriber
├── data/db/                # face_db.npz (enrolled embedding)
├── data/logs/              # Evidence CSV/JSON
├── models/                 # embedder_arcface.onnx
└── ASSESSMENT.md           # BENAX submission package
```

---

## MQTT topics

| Topic | Payload |
|-------|---------|
| `vision/rusi123/movement` | `{ status, confidence, target, locked, searching, offset_x, timestamp }` |
| `vision/rusi123/heartbeat` | `{ node, status, timestamp }` |

---

## Validation before submission

Complete all 12 tests in [ASSESSMENT.md](ASSESSMENT.md) and attach the generated evidence CSV.
