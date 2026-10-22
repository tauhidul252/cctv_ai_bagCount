import time
import math
from typing import Dict, List, Tuple, Optional

def line_intersection(p1: Tuple[float, float], p2: Tuple[float, float],
                      p3: Tuple[float, float], p4: Tuple[float, float],
                      margin: float = 120.0) -> bool:
    """
    Check if line segment p1-p2 intersects line segment p3-p4.
    p3-p4 is extended by margin along its direction to ensure side-by-side workers
    walking near the edges of the doorway threshold are never missed.
    """
    dx = p4[0] - p3[0]
    dy = p4[1] - p3[1]
    length = math.hypot(dx, dy) or 1.0
    ux = dx / length
    uy = dy / length
    ep3 = (p3[0] - ux * margin, p3[1] - uy * margin)
    ep4 = (p4[0] + ux * margin, p4[1] + uy * margin)

    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])
    return (ccw(p1, ep3, ep4) != ccw(p2, ep3, ep4)) and (ccw(p1, p2, ep3) != ccw(p1, p2, ep4))

def cross_product(p1: Tuple[float, float], p2: Tuple[float, float], p: Tuple[float, float]) -> float:
    """Signed cross product of vector (p2 - p1) with vector (p - p1)."""
    return (p2[0] - p1[0]) * (p[1] - p1[1]) - (p2[1] - p1[1]) * (p[0] - p1[0])

class DirectionalBagCounter:
    """
    Robust directional counter for bags/sacks passing across a configurable tripwire line.
    Supports IN and OUT detection with debounce and trajectory validation.
    """

    def __init__(self,
                 line_start: Tuple[int, int] = (520, 230),
                 line_end: Tuple[int, int] = (220, 230),
                 in_direction: str = "down", # or "up", "left", "right", or based on normal
                 debounce_seconds: float = 2.0,
                 count_out: bool = False):
        self.line_start = line_start
        self.line_end = line_end
        self.in_direction = in_direction
        self.debounce_seconds = debounce_seconds
        self.count_out = count_out

        # State tracking: track_id -> dict(history=[(x, y, timestamp)], counted=direction, last_side=val)
        self.tracks: Dict[int, dict] = {}
        self.total_in = 0
        self.total_out = 0
        self.recent_events: List[dict] = []

    def set_line(self, x1: int, y1: int, x2: int, y2: int, in_direction: str = "down"):
        self.line_start = (x1, y1)
        self.line_end = (x2, y2)
        self.in_direction = in_direction

    def reset_counts(self):
        self.total_in = 0
        self.total_out = 0
        self.tracks.clear()
        self.recent_events.clear()

    def update(self,
               track_id: int,
               bbox: Tuple[float, float, float, float],
               confidence: float = 1.0,
               sack_count: int = 1,
               sack_bbox: Optional[List[int]] = None,
               sack_label: str = "") -> Optional[dict]:
        """
        bbox: (x1, y1, x2, y2)
        sack_count: 0 (no sack - do not count), 1 (single sack), 2 (stacked sacks)
        Returns event dict if a valid bag crossing occurred.
        """
        now = time.time()
        # For tracking crossing, use sack center if available, otherwise upper-torso/head center
        if sack_bbox is not None and sack_count > 0:
            cx = (sack_bbox[0] + sack_bbox[2]) / 2.0
            cy = (sack_bbox[1] + sack_bbox[3]) / 2.0
        else:
            cx = (bbox[0] + bbox[2]) / 2.0
            cy = bbox[1] + (bbox[3] - bbox[1]) * 0.25 # head/shoulder level

        current_pos = (cx, cy)
        side = cross_product(self.line_start, self.line_end, current_pos)

        if track_id not in self.tracks:
            self.tracks[track_id] = {
                "history": [(cx, cy, now)],
                "counted": None,
                "initial_side": side,
                "last_side": side,
                "last_seen": now,
                "sack_votes": [sack_count] if sack_count > 0 else [],
                "last_sack_box": sack_bbox
            }
            return None

        track_data = self.tracks[track_id]
        track_data["last_seen"] = now
        track_data["history"].append((cx, cy, now))
        if len(track_data["history"]) > 30:
            track_data["history"].pop(0)

        if sack_count > 0:
            track_data["sack_votes"].append(sack_count)
            if len(track_data["sack_votes"]) > 20:
                track_data["sack_votes"].pop(0)
            if sack_bbox is not None:
                track_data["last_sack_box"] = sack_bbox

        prev_pos = (track_data["history"][-2][0], track_data["history"][-2][1])
        prev_side = track_data["last_side"]
        track_data["last_side"] = side

        # Check if crossed the line
        crossed = False
        if track_data["counted"] is None:
            if prev_side * side < 0:
                if line_intersection(prev_pos, current_pos, self.line_start, self.line_end, margin=120.0):
                    crossed = True
            elif len(track_data["history"]) >= 3:
                # Fallback trajectory check for fast-moving side-by-side workers
                first_pos = (track_data["history"][0][0], track_data["history"][0][1])
                first_side = track_data["initial_side"]
                if first_side * side < 0:
                    if line_intersection(first_pos, current_pos, self.line_start, self.line_end, margin=120.0):
                        crossed = True

        if crossed and track_data["counted"] is None:
            # STRICT CHECK: Must actively carry a sack at crossing time!
            if sack_count == 0:
                track_data["counted"] = "SKIPPED_EMPTY"
                return None

            # Each carrying worker carries strictly 1 sack on head
            effective_sacks = 1

            # Robust trajectory vector (from entry/approach position to current crossing position)
            # Avoids 1-frame jitter misclassifying IN as OUT
            start_pos = track_data["history"][0]
            tx = current_pos[0] - start_pos[0]
            ty = current_pos[1] - start_pos[1]

            lx = self.line_end[0] - self.line_start[0]
            ly = self.line_end[1] - self.line_start[1]

            # Clockwise normal: (-ly, lx)
            dot = tx * (-ly) + ty * lx
            direction = "IN" if dot > 0 else "OUT"

            # Workers returning outside are empty-handed.
            # In warehouse unloading, sacks only enter (IN). Completely ignore OUT direction.
            if direction == "OUT" and not self.count_out:
                track_data["counted"] = "SKIPPED_OUT"
                return None

            track_data["counted"] = direction
            if direction == "IN":
                self.total_in += effective_sacks
            else:
                self.total_out += effective_sacks

            actual_sack_box = sack_bbox or track_data.get("last_sack_box")
            event = {
                "direction": direction,
                "count": effective_sacks,
                "track_id": track_id,
                "bbox": [int(v) for v in bbox],
                "sack_bbox": [int(v) for v in actual_sack_box] if actual_sack_box else [int(v) for v in bbox],
                "centroid": [int(cx), int(cy)],
                "confidence": float(confidence),
                "timestamp": now,
                "notes": "1x বস্তা (Sack on Head)"
            }
            self.recent_events.append(event)
            if len(self.recent_events) > 50:
                self.recent_events.pop(0)

            return event

        return None

    def clean_old_tracks(self, max_age_seconds: float = 10.0):
        """Clean up lost tracks."""
        now = time.time()
        expired = [tid for tid, data in self.tracks.items() if (now - data["last_seen"]) > max_age_seconds]
        for tid in expired:
            del self.tracks[tid]
