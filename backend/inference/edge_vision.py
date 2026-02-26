"""
OmniRoute — Edge Vision Inference (YOLOv8 Nano + OpenCV).

Local object detection using Ultralytics YOLOv8n.
Model auto-downloads on first use (~6 MB).
"""

from __future__ import annotations

import base64
import io
import logging
import time

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger("omniroute.inference.edge_vision")

_model = None


def _load_model():
    global _model
    if _model is None:
        from ultralytics import YOLO

        logger.info("Loading YOLOv8n model (auto-download if needed)...")
        t0 = time.perf_counter()
        _model = YOLO("yolov8n.pt")
        logger.info("YOLOv8n loaded in %.1fs", time.perf_counter() - t0)
    return _model


def _decode_image(b64_data: str) -> np.ndarray:
    """Decode base64 string to OpenCV BGR numpy array."""
    if "," in b64_data:
        b64_data = b64_data.split(",", 1)[1]
    raw = base64.b64decode(b64_data)
    img_pil = Image.open(io.BytesIO(raw)).convert("RGB")
    img_cv = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
    return img_cv


async def detect(image_b64: str, conf_threshold: float = 0.25) -> tuple[list[dict], float]:
    """
    Run YOLOv8n object detection on a base64-encoded image.
    Returns (list_of_detections, latency_ms).
    Each detection: {"label": str, "confidence": float, "bbox": [x1,y1,x2,y2]}
    """
    model = _load_model()
    img = _decode_image(image_b64)
    h, w = img.shape[:2]

    t0 = time.perf_counter()
    results = model(img, conf=conf_threshold, verbose=False)
    latency_ms = (time.perf_counter() - t0) * 1000

    detections = []
    for result in results:
        boxes = result.boxes
        if boxes is None:
            continue
        for i in range(len(boxes)):
            xyxy = boxes.xyxy[i].cpu().numpy()
            conf = float(boxes.conf[i].cpu().numpy())
            cls_id = int(boxes.cls[i].cpu().numpy())
            label = model.names.get(cls_id, f"class_{cls_id}")

            # Normalize bounding box to 0–1 range
            detections.append({
                "label": label,
                "confidence": round(conf, 3),
                "bbox": [
                    round(float(xyxy[0]) / w, 4),
                    round(float(xyxy[1]) / h, 4),
                    round(float(xyxy[2]) / w, 4),
                    round(float(xyxy[3]) / h, 4),
                ],
            })

    logger.info("Edge vision inference: %.0fms, %d objects", latency_ms, len(detections))
    return detections, round(latency_ms, 1)
