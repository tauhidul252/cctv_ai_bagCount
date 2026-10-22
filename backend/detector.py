import os
import torch
from typing import List, Dict, Any, Optional
from ultralytics import YOLO

class BagDetectorTracker:
    """
    YOLOv8/v11 Object Detector and ByteTrack Multi-Object Tracker.
    Optimized for sacks/bags, with support for custom fine-tuned weights or default COCO classes.
    """

    def __init__(self,
                 model_path: str = "yolov8n.pt",
                 conf_threshold: float = 0.35,
                 iou_threshold: float = 0.5,
                 target_classes: Optional[List[int]] = None):
        """
        target_classes: COCO default bag-related classes:
        24: backpack, 26: handbag, 28: suitcase, 0: person (if detecting carrying worker)
        If custom model is loaded (which only has 0: sack), target_classes can be [0] or None for all.
        """
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        # If target_classes is None, default to bag-like COCO classes (24: backpack, 26: handbag, 28: suitcase)
        self.target_classes = target_classes

        # Select Apple Silicon MPS if available, else CPU
        if torch.backends.mps.is_available():
            self.device = "mps"
        elif torch.cuda.is_available():
            self.device = "cuda"
        else:
            self.device = "cpu"

        print(f"[AI Detector] Initializing model {model_path} on device={self.device}...")
        self.model = YOLO(model_path)
        print(f"[AI Detector] Model loaded successfully.")

    def update_model(self, new_model_path: str):
        if os.path.exists(new_model_path):
            self.model_path = new_model_path
            self.model = YOLO(new_model_path)
            print(f"[AI Detector] Switched to new model: {new_model_path}")
            return True
        return False

    def track(self, frame) -> List[Dict[str, Any]]:
        """
        Run detection and tracking on a single frame.
        Returns list of tracked items:
        [
            {
                "track_id": int,
                "bbox": [x1, y1, x2, y2],
                "confidence": float,
                "class_id": int,
                "class_name": str
            }, ...
        ]
        """
        # Run YOLO with ByteTrack
        results = self.model.track(
            frame,
            persist=True,
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            classes=self.target_classes,
            tracker="bytetrack.yaml",
            device=self.device,
            verbose=False
        )

        detections = []
        if not results or len(results) == 0:
            return detections

        r = results[0]
        if r.boxes is None or len(r.boxes) == 0:
            return detections

        boxes = r.boxes
        has_id = boxes.id is not None

        for i in range(len(boxes)):
            box = boxes[i]
            track_id = int(boxes.id[i].item()) if has_id and boxes.id[i] is not None else None
            # If no track_id assigned yet (e.g. newly appeared), skip counting or assign temporary ID
            if track_id is None:
                continue

            xyxy = box.xyxy[0].cpu().numpy().tolist()
            conf = float(box.conf[0].item())
            cls_id = int(box.cls[0].item())
            cls_name = self.model.names.get(cls_id, str(cls_id))

            bbox = [int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3])]

            # Detect sacks/head-load on persons or standalone bags
            sack_count = 0
            sack_box = None
            sack_conf = 0.0
            sack_label = "No Bag"

            if cls_name == "person":
                sack_count, sack_box, sack_conf, sack_label = self.detect_head_load(frame, bbox)
            elif cls_name in ["backpack", "handbag", "suitcase"]:
                sack_count = 1
                sack_box = bbox
                sack_conf = conf
                sack_label = "1x Bag"

            detections.append({
                "track_id": track_id,
                "bbox": bbox,
                "confidence": round(conf, 3),
                "class_id": cls_id,
                "class_name": cls_name,
                "sack_count": sack_count,
                "sack_box": sack_box,
                "sack_conf": sack_conf,
                "sack_label": sack_label
            })

        return detections

    def detect_head_load(self, frame, person_bbox: List[int]) -> tuple:
        """
        Analyzes the head, neck, and shoulder region of a worker to detect:
        1. If a sack/bag (বস্তা) is being carried on the head/shoulder.
        2. How many sacks are being carried:
           - 0: Empty-handed worker (skip/do not count)
           - 1: Single sack on head/shoulder
           - 2: Two stacked sacks (স্ট্যাক অবস্থায় ২টা বস্তা)
        Returns: (sack_count: int, sack_bbox: Optional[List[int]], conf: float, label: str)
        """
        import cv2
        import numpy as np

        x1, y1, x2, y2 = person_bbox
        pw = x2 - x1
        ph = y2 - y1

        if pw < 20 or ph < 40:
            return 0, None, 0.0, "No Bag"

        # Region of Interest: upper body & head area extending above the crown
        # Sacks typically extend above the head bounding box
        htop = max(0, y1 - int(ph * 0.22))
        hbot = min(frame.shape[0], y1 + int(ph * 0.38))
        hleft = max(0, x1 - int(pw * 0.15))
        hright = min(frame.shape[1], x2 + int(pw * 0.15))

        crop = frame[htop:hbot, hleft:hright]
        if crop.size == 0 or crop.shape[0] < 12 or crop.shape[1] < 12:
            return 0, None, 0.0, "No Bag"

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

        # 1. Yellow rice sack (standard woven polypropylene sacks in BD grain markets)
        m_yellow = cv2.inRange(hsv, np.array([15, 50, 60]), np.array([38, 255, 255]))
        # 2. Orange / red sacks (flour, feed, lentils)
        m_orange = cv2.inRange(hsv, np.array([0, 65, 60]), np.array([15, 255, 255]))
        # 3. White / cream woven poly/jute sacks
        m_white = cv2.inRange(hsv, np.array([0, 0, 140]), np.array([180, 45, 255]))
        # 4. Brown / jute / burlap sacks
        m_jute = cv2.inRange(hsv, np.array([10, 40, 40]), np.array([25, 160, 140]))

        m_colored = cv2.bitwise_or(m_yellow, m_orange)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        m_clean = cv2.morphologyEx(m_colored, cv2.MORPH_OPEN, kernel)
        m_clean = cv2.morphologyEx(m_clean, cv2.MORPH_CLOSE, kernel)

        cnts, _ = cv2.findContours(m_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        best_cnt = None
        max_area = 0
        for cnt in cnts:
            area = cv2.contourArea(cnt)
            bx, by, bw, bh = cv2.boundingRect(cnt)
            # Alignment check: sack on head must sit in upper 75% of head/shoulder ROI
            if by < crop.shape[0] * 0.72 and area > max_area:
                max_area = area
                best_cnt = cnt

        # Check white/jute woven sacks if colored sack not found
        if max_area < 700:
            m_alt = cv2.bitwise_or(m_white, m_jute)
            m_alt_clean = cv2.morphologyEx(m_alt, cv2.MORPH_OPEN, kernel)
            cnts_alt, _ = cv2.findContours(m_alt_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in cnts_alt:
                area = cv2.contourArea(cnt)
                bx, by, bw, bh = cv2.boundingRect(cnt)
                if area > max_area and by < crop.shape[0] * 0.70 and bw > crop.shape[1] * 0.45:
                    max_area = area
                    best_cnt = cnt

        if best_cnt is None or max_area < 700:
            return 0, None, 0.0, "No Bag"

        bx, by, bw, bh = cv2.boundingRect(best_cnt)
        sack_box = [hleft + bx, htop + by, hleft + bx + bw, htop + by + bh]

        # Single sack vs 2 Stacked Sacks analysis:
        # Stacked sacks have large vertical height (bh >= 85px or area > 3500 with tall aspect ratio)
        aspect = bh / max(1, bw)
        if (bh >= 85 and max_area > 3500) or max_area > 5000:
            sack_count = 2
            label = "2x Stacked Sacks (২টি বস্তা)"
        else:
            sack_count = 1
            label = "1x Sack (১টি বস্তা)"

        conf = min(0.99, max_area / 2500.0)
        return sack_count, sack_box, round(conf, 2), label
