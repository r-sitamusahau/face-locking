"""MediaPipe FaceMesh compatibility layer for mediapipe >= 0.10.31."""
from __future__ import annotations

import hashlib
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import mediapipe as mp
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core import base_options as base_options_module

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/latest/face_landmarker.task"
)
MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "face_landmarker.task"


@dataclass
class _Landmark:
    x: float
    y: float
    z: float = 0.0


@dataclass
class _FaceLandmarks:
    landmark: List[_Landmark]


@dataclass
class FaceMeshResult:
    multi_face_landmarks: Optional[List[_FaceLandmarks]]


class FaceMesh:
    """Drop-in replacement for mp.solutions.face_mesh.FaceMesh."""

    def __init__(
        self,
        static_image_mode: bool = False,
        max_num_faces: int = 10,
        refine_landmarks: bool = True,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
    ):
        del static_image_mode, refine_landmarks, min_tracking_confidence
        self._max_faces = int(max_num_faces)
        self._landmarker = _create_landmarker(
            self._max_faces, float(min_detection_confidence)
        )

    def process(self, rgb_image):
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)
        result = self._landmarker.detect(mp_image)
        if not result.face_landmarks:
            return FaceMeshResult(multi_face_landmarks=None)

        faces: List[_FaceLandmarks] = []
        for face in result.face_landmarks[: self._max_faces]:
            faces.append(
                _FaceLandmarks(
                    landmark=[
                        _Landmark(x=lm.x, y=lm.y, z=getattr(lm, "z", 0.0))
                        for lm in face
                    ]
                )
            )
        return FaceMeshResult(multi_face_landmarks=faces)

    def close(self):
        self._landmarker.close()


def _ensure_model() -> Path:
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    if MODEL_PATH.exists() and MODEL_PATH.stat().st_size > 1_000_000:
        return MODEL_PATH

    print(f"Downloading MediaPipe face landmarker to {MODEL_PATH}...")
    req = urllib.request.Request(MODEL_URL, headers={"User-Agent": "FaceLocking/1.0"})
    with urllib.request.urlopen(req, timeout=600) as resp, MODEL_PATH.open("wb") as out:
        out.write(resp.read())
    print("Face landmarker model ready.")
    return MODEL_PATH


def _create_landmarker(max_faces: int, min_detection_confidence: float):
    model_path = str(_ensure_model())
    options = vision.FaceLandmarkerOptions(
        base_options=base_options_module.BaseOptions(model_asset_path=model_path),
        running_mode=vision.RunningMode.IMAGE,
        num_faces=max_faces,
        min_face_detection_confidence=min_detection_confidence,
    )
    return vision.FaceLandmarker.create_from_options(options)


def get_face_mesh(**kwargs) -> FaceMesh:
    return FaceMesh(**kwargs)
