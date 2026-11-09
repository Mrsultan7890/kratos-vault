"""
Image Analysis Engine — YOLOv8n
Detects objects in uploaded images.
Also runs face detection using OpenCV haar cascades (no extra model needed).
"""
import io
import os
from typing import Dict, List, Any
from pathlib import Path

_YOLO_PATH = Path.home() / ".kratos_vault" / "yolov8n.pt"
_yolo_model = None

# YOLO classes that are investigation-relevant
_RELEVANT_CLASSES = {
    "person", "car", "truck", "bus", "motorcycle", "bicycle",
    "laptop", "cell phone", "book", "backpack", "handbag",
    "knife", "scissors", "gun", "weapon",
    "tv", "monitor", "keyboard", "mouse",
    "bottle", "cup", "clock", "watch",
    "dog", "cat",
}


def _get_yolo():
    global _yolo_model
    if _yolo_model is None:
        from ultralytics import YOLO
        _yolo_model = YOLO(str(_YOLO_PATH))
    return _yolo_model


def analyze_image(image_bytes: bytes) -> Dict[str, Any]:
    """
    Run YOLOv8n object detection on image bytes.
    Returns:
    {
        "objects": [{"label": "person", "confidence": 0.92, "bbox": [x1,y1,x2,y2]}, ...],
        "summary": "Detected: 2x person, 1x car",
        "relevant": ["person", "car"],
        "face_count": 1,
        "risk_flags": ["weapon detected"],
    }
    """
    result = {
        "objects": [],
        "summary": "No objects detected",
        "relevant": [],
        "face_count": 0,
        "face_boxes": [],
        "risk_flags": [],
    }

    if not _YOLO_PATH.exists():
        result["summary"] = ("YOLOv8n model not found — place yolov8n.pt in "
                             "~/.kratos_vault/ (auto-downloads on first run of "
                             "`ultralytics`)")
        result["model_missing"] = True
        return result

    try:
        from PIL import Image
        import numpy as np

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_array = np.array(img)

        model = _get_yolo()
        detections = model(img_array, verbose=False, conf=0.35)

        objects = []
        label_counts = {}

        for det in detections:
            if det.boxes is None:
                continue
            for box in det.boxes:
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                label = model.names[cls_id].lower()
                bbox = [round(float(x), 1) for x in box.xyxy[0].tolist()]
                objects.append({
                    "label":      label,
                    "confidence": round(conf, 3),
                    "bbox":       bbox,
                })
                label_counts[label] = label_counts.get(label, 0) + 1

        result["objects"] = objects

        # Summary
        if label_counts:
            parts = [f"{v}x {k}" for k, v in sorted(label_counts.items(),
                                                      key=lambda x: -x[1])]
            result["summary"] = "Detected: " + ", ".join(parts)
        else:
            result["summary"] = "No objects detected"

        # Relevant objects
        result["relevant"] = [l for l in label_counts if l in _RELEVANT_CLASSES]

        # Risk flags
        weapon_words = {"knife", "gun", "weapon", "scissors", "rifle", "pistol"}
        for label in label_counts:
            if any(w in label for w in weapon_words):
                result["risk_flags"].append(f"⚠ Potential weapon: {label}")

        # Face detection via OpenCV haar cascade
        face_boxes = detect_face_boxes(img_array)
        result["face_boxes"] = face_boxes
        result["face_count"] = len(face_boxes)
        if result["face_count"] > 0:
            result["risk_flags"].append(f"👤 {result['face_count']} face(s) detected")

    except Exception as e:
        result["summary"] = f"Analysis error: {e}"

    return result


def _detect_faces(img_array) -> int:
    """OpenCV haar-cascade frontal face detection; falls back to 0 if cv2
    or the cascade files are unavailable (was: skin-tone heuristic that
    false-positived on any warm-coloured image)."""
    try:
        import cv2

        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if cascade.empty():
            return 0
        faces = cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        return len(faces)
    except Exception:
        return 0


def detect_face_boxes(img_array):
    """Face rectangles [[x, y, w, h], ...] for annotation; empty on failure."""
    try:
        import cv2

        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if cascade.empty():
            return []
        faces = cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        return [[int(v) for v in face] for face in faces]
    except Exception:
        return []


def draw_detections(image_bytes: bytes, objects: List[Dict],
                    face_boxes: List[List[int]] = None) -> bytes:
    """Draw YOLO boxes + face boxes on the image, return PNG bytes."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io as _io

        img = Image.open(_io.BytesIO(image_bytes)).convert("RGB")
        draw = ImageDraw.Draw(img)

        colors = {
            "person": "#ef4444", "car": "#3b82f6", "truck": "#f59e0b",
            "laptop": "#10b981", "cell phone": "#8b5cf6",
        }

        for obj in objects:
            bbox = obj["bbox"]
            label = obj["label"]
            conf = obj["confidence"]
            color = colors.get(label, "#6366f1")
            draw.rectangle(bbox, outline=color, width=2)
            draw.text((bbox[0] + 2, max(0, bbox[1] - 14)),
                      f"{label} {conf:.0%}", fill=color)

        for (x, y, w, h) in (face_boxes or []):
            draw.rectangle([x, y, x + w, y + h], outline="#fbbf24", width=2)
            draw.text((x + 2, max(0, y - 14)), "face", fill="#fbbf24")

        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return image_bytes
