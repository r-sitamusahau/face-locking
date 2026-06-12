"""Download ArcFace ONNX model (InsightFace w600k_r50) into models/."""
from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

MODEL_URL = (
    "https://huggingface.co/public-data/insightface/resolve/main/"
    "models/buffalo_l/w600k_r50.onnx"
)
EXPECTED_SHA256 = "4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43"
OUT_PATH = Path(__file__).resolve().parent.parent / "models" / "embedder_arcface.onnx"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    if OUT_PATH.exists():
        digest = sha256_file(OUT_PATH)
        if digest == EXPECTED_SHA256:
            print(f"Model already present: {OUT_PATH}")
            return
        print("Existing model checksum mismatch; re-downloading...")

    print(f"Downloading ArcFace model to {OUT_PATH} (~174 MB)...")
    req = urllib.request.Request(MODEL_URL, headers={"User-Agent": "FaceLocking/1.0"})
    with urllib.request.urlopen(req, timeout=600) as resp, OUT_PATH.open("wb") as out:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total:
                pct = 100.0 * done / total
                print(f"\r  {done // (1024 * 1024)} / {total // (1024 * 1024)} MB ({pct:.1f}%)", end="")
        print()

    digest = sha256_file(OUT_PATH)
    if digest != EXPECTED_SHA256:
        OUT_PATH.unlink(missing_ok=True)
        raise SystemExit(f"Download failed checksum verification: {digest}")

    print("Model ready.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
