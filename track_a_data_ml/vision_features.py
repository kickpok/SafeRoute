"""
Street-level image features via Mapillary (free tier, no billing needed).

Falls back to a neutral default if no Mapillary token is set or no image is
found nearby, so the pipeline never hard-fails during a live demo.
"""
import io
import requests
import numpy as np
from PIL import Image
from config import MAPILLARY_TOKEN

_yolo_model = None


def _get_yolo():
    global _yolo_model
    if _yolo_model is None:
        from ultralytics import YOLO
        _yolo_model = YOLO("yolov8n.pt")  # auto-downloads (~6MB) on first run
    return _yolo_model


def fetch_nearest_image(lat, lon, radius=50):
    if not MAPILLARY_TOKEN:
        return None
    url = "https://graph.mapillary.com/images"
    params = {
        "access_token": MAPILLARY_TOKEN,
        "fields": "id,thumb_1024_url",
        "closeto": f"{lon},{lat}",
        "radius": radius,
        "limit": 1,
    }
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json().get("data", [])
    if not data:
        return None
    img_bytes = requests.get(data[0]["thumb_1024_url"], timeout=15).content
    return Image.open(io.BytesIO(img_bytes)).convert("RGB")


def brightness_score(image: Image.Image) -> float:
    arr = np.asarray(image.convert("L"), dtype=np.float32)
    return round(float(arr.mean() / 255.0), 3)


def crowd_count(image: Image.Image) -> int:
    model = _get_yolo()
    results = model(image, classes=[0], verbose=False)  # COCO class 0 = person
    return len(results[0].boxes)


def vision_features_for_point(lat, lon):
    """Returns brightness (lighting proxy, 0-1) and person_count, or neutral
    defaults if no image is available at this point."""
    img = fetch_nearest_image(lat, lon)
    if img is None:
        return {"brightness": 0.5, "person_count": None}
    return {"brightness": brightness_score(img), "person_count": crowd_count(img)}
