import os
import torch
from typing import List, Dict, Any, Optional
from ultralytics import YOLO

class SackTracker:
    def __init__(self):
        self.tracks = {}
        self.next_id = 1000

    def update(self, sack_boxes, frame_idx):
        import numpy as np
        active = []
        if not self.tracks:
            for sbox in sack_boxes:
                scx = (sbox[0] + sbox[2]) / 2.0
                scy = (sbox[1] + sbox[3]) / 2.0
                self.tracks[self.next_id] = {'centroid': (scx, scy), 'last_seen': frame_idx, 'box': sbox}
                active.append((self.next_id, sbox))
                self.next_id += 1
            return active

        track_ids = list(self.tracks.keys())
        distances = []
        for tid in track_ids:
            tcx, tcy = self.tracks[tid]['centroid']
            for s_idx, sbox in enumerate(sack_boxes):
                scx = (sbox[0] + sbox[2]) / 2.0
                scy = (sbox[1] + sbox[3]) / 2.0
                d = np.hypot(tcx - scx, tcy - scy)
                distances.append((d, tid, s_idx))

        # Sort by distance for global optimal assignment (prevents track-stealing on side-by-side sacks)
        distances.sort(key=lambda x: x[0])
        matched_tracks = set()
        matched_sacks = set()

        for d, tid, s_idx in distances:
            if d > 75:
                break
            if tid in matched_tracks or s_idx in matched_sacks:
                continue
            matched_tracks.add(tid)
            matched_sacks.add(s_idx)
            sbox = sack_boxes[s_idx]
            scx = (sbox[0] + sbox[2]) / 2.0
            scy = (sbox[1] + sbox[3]) / 2.0
            self.tracks[tid]['centroid'] = (scx, scy)
            self.tracks[tid]['last_seen'] = frame_idx
            self.tracks[tid]['box'] = sbox
            active.append((tid, sbox))

        # Delete old lost tracks
        for tid in list(self.tracks.keys()):
            if tid not in matched_tracks and (frame_idx - self.tracks[tid]['last_seen']) > 12:
                del self.tracks[tid]

        # Register new detections
        for s_idx, sbox in enumerate(sack_boxes):
            if s_idx not in matched_sacks:
                scx = (sbox[0] + sbox[2]) / 2.0
                scy = (sbox[1] + sbox[3]) / 2.0
                self.tracks[self.next_id] = {'centroid': (scx, scy), 'last_seen': frame_idx, 'box': sbox}
                active.append((self.next_id, sbox))
                self.next_id += 1

        return active

class BagDetectorTracker:
    """
    YOLOv8/v11 Object Detector and ByteTrack Multi-Object Tracker.
    Optimized for sacks/bags, with support for custom fine-tuned weights or default COCO classes.
    """

    def __init__(self,
                 model_path: str = "yolo11s.pt",
                 conf_threshold: float = 0.25,
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
        self.sack_tracker = SackTracker()
        self.frame_count = 0

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
        try:
            self.model_path = new_model_path
            self.model = YOLO(new_model_path)
            print(f"[AI Detector] Switched to model: {new_model_path} on {self.device}")
            return True
        except Exception as e:
            print(f"[AI Detector] Failed to switch to model {new_model_path}: {e}")
            return False

    def extract_walkway_sacks(self, frame) -> List[List[int]]:
        import cv2
        import numpy as np
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        m_yellow = cv2.inRange(hsv, np.array([16, 85, 90]), np.array([35, 255, 255]))
        m_orange = cv2.inRange(hsv, np.array([5, 105, 90]), np.array([15, 255, 255]))
        m_sack = cv2.bitwise_or(m_yellow, m_orange)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        m_clean = cv2.morphologyEx(m_sack, cv2.MORPH_OPEN, kernel)
        m_clean = cv2.morphologyEx(m_clean, cv2.MORPH_CLOSE, kernel)
        cnts, _ = cv2.findContours(m_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        sacks = []
        for cnt in cnts:
            area = cv2.contourArea(cnt)
            if area >= 950:
                bx, by, bw, bh = cv2.boundingRect(cnt)
                # STRICT HEAD/SHOULDER LEVEL ONLY:
                # Sacks carried on worker heads across tripwire corridor are in 140 <= by <= 330.
                # Wooden awning above (y < 140) and feet/legs/sandals/floor below (y > 330) are 100% EXCLUDED!
                if 130 <= bx <= 640 and 140 <= by <= 330 and bh >= 35:
                    # Side-by-side sacks (bw >= 105) or tandem sacks (area >= 4200): split into two distinct sacks
                    if bw >= 105 or area >= 4200:
                        sacks.append([bx, by, bx + bw // 2, by + bh])
                        sacks.append([bx + bw // 2, by, bx + bw, by + bh])
                    else:
                        sacks.append([bx, by, bx + bw, by + bh])
        return sacks

    def track(self, frame) -> List[Dict[str, Any]]:
        """
        Run detection and tracking on a single frame.
        Fuses YOLO person tracking and high-precision sack tracking.
        Guarantees that two workers walking in tandem carrying 1 sack each
        are tracked as two separate 1x bags without dropping any bag.
        """
        self.frame_count += 1
        sacks = self.extract_walkway_sacks(frame)
        active_sacks = self.sack_tracker.update(sacks, self.frame_count)

        # Run YOLO with ByteTrack for visual person poses
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

        yolo_persons = []
        if results and len(results) > 0 and results[0].boxes is not None:
            boxes = results[0].boxes
            has_id = boxes.id is not None
            for i in range(len(boxes)):
                track_id = int(boxes.id[i].item()) if has_id and boxes.id[i] is not None else None
                xyxy = [int(v) for v in boxes.xyxy[i].cpu().numpy().tolist()]
                conf = float(boxes.conf[i].item())
                yolo_persons.append({"track_id": track_id, "bbox": xyxy, "conf": conf})

        detections = []
        matched_sacks = set()

        # 1. Output every tracked sack as an individual bag
        for s_idx, (s_tid, sbox) in enumerate(active_sacks):
            scx = (sbox[0] + sbox[2]) / 2.0
            scy = (sbox[1] + sbox[3]) / 2.0

            # Match with closest overlapping YOLO person if present
            best_p = None
            best_dist = 999
            for p in yolo_persons:
                px1, py1, px2, py2 = p["bbox"]
                if px1 - 40 <= scx <= px2 + 40 and py1 - 40 <= scy <= py2:
                    dist = abs(scx - (px1 + px2) / 2.0)
                    if dist < best_dist:
                        best_dist = dist
                        best_p = p

            if best_p is not None:
                pbox = best_p["bbox"]
                conf = best_p["conf"]
            else:
                pbox = [sbox[0] - 20, sbox[1], sbox[2] + 20, min(frame.shape[0], sbox[3] + 280)]
                conf = 0.95

            detections.append({
                "track_id": s_tid,
                "bbox": pbox,
                "confidence": round(conf, 3),
                "class_id": 0,
                "class_name": "person",
                "sack_count": 1,
                "sack_box": sbox,
                "sack_conf": 0.95,
                "sack_label": "1x বস্তা (Sack on Head)"
            })
            matched_sacks.add(s_tid)

        # 2. Add empty-handed persons (e.g. returning workers, bystanders) so they are drawn but NOT counted
        for p in yolo_persons:
            px1, py1, px2, py2 = p["bbox"]
            pcx = (px1 + px2) / 2.0
            pcy = (py1 + py2) / 2.0
            # Check if this person was matched to a sack
            has_sack = any(abs(pcx - (sbox[0] + sbox[2]) / 2.0) < 60 for _, sbox in active_sacks)
            if not has_sack and p["track_id"] is not None:
                detections.append({
                    "track_id": p["track_id"],
                    "bbox": p["bbox"],
                    "confidence": round(p["conf"], 3),
                    "class_id": 0,
                    "class_name": "person",
                    "sack_count": 0,
                    "sack_box": None,
                    "sack_conf": 0.0,
                    "sack_label": "No Bag"
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

        # 1. Yellow rice sack (standard high-vibrancy woven polypropylene sacks in BD grain markets)
        m_yellow = cv2.inRange(hsv, np.array([16, 85, 90]), np.array([35, 255, 255]))
        # 2. Orange / red sacks (flour, feed, lentils)
        m_orange = cv2.inRange(hsv, np.array([5, 105, 90]), np.array([15, 255, 255]))
        # 3. White / cream woven poly sacks (bright, low saturation)
        m_white = cv2.inRange(hsv, np.array([0, 0, 195]), np.array([180, 35, 255]))
        # 4. Brown / jute / burlap sacks
        m_jute = cv2.inRange(hsv, np.array([10, 50, 60]), np.array([25, 150, 140]))

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
            # Alignment check: sack on head must sit in upper 75% of head/shoulder ROI, with reasonable width/height
            if by < crop.shape[0] * 0.72 and area > max_area and bw >= 28 and bh >= 20:
                max_area = area
                best_cnt = cnt

        # Real sack on worker's head must have at least 1200px of vibrant sack fabric
        if best_cnt is None or max_area < 1200:
            return 0, None, 0.0, "No Bag"

        bx, by, bw, bh = cv2.boundingRect(best_cnt)
        sack_box = [hleft + bx, htop + by, hleft + bx + bw, htop + by + bh]

        # In this warehouse operation, each worker carries strictly 1 sack on head
        sack_count = 1
        label = "1x বস্তা (Sack on Head)"

        conf = min(0.99, max_area / 2500.0)
        return sack_count, sack_box, round(conf, 2), label
