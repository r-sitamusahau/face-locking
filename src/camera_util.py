"""Shared webcam helper — external USB camera is always index 1 on this project."""
from __future__ import annotations

import cv2

# Global default: external USB webcam (built-in laptop camera is usually index 0).
EXTERNAL_CAMERA_ID = 1
DEFAULT_EXTERNAL_CAMERA = EXTERNAL_CAMERA_ID


def open_camera(camera_id: int = EXTERNAL_CAMERA_ID) -> cv2.VideoCapture:
    """Open the external camera at the given index (default 1)."""
    cap = cv2.VideoCapture(int(camera_id), cv2.CAP_DSHOW)
    if cap.isOpened():
        ret, _ = cap.read()
        if ret:
            print(f"[camera] Using external camera index {camera_id}")
            return cap
        cap.release()

    raise RuntimeError(
        f"External camera (index {camera_id}) not available. "
        "Connect the USB webcam and close other apps using it."
    )
