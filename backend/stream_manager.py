import cv2
import time
import os
import threading
from datetime import datetime
from typing import Optional, Dict, Any, Callable
from backend.detector import BagDetectorTracker
from backend.counter import DirectionalBagCounter
from backend.database import SessionLocal
from backend.models import BagEvent, CountSession

SNAPSHOTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "snapshots"))
os.makedirs(SNAPSHOTS_DIR, exist_ok=True)

class StreamManager:
    """
    Manages video ingestion, AI detection, tracking, line counting,
    overlay rendering, snapshot saving, and frame streaming.
    """

    def __init__(self,
                 source: str = "demo",
                 detector: Optional[BagDetectorTracker] = None,
                 counter: Optional[DirectionalBagCounter] = None,
                 on_event_callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.source = source
        self.detector = detector or BagDetectorTracker()
        self.counter = counter or DirectionalBagCounter()
        self.on_event_callback = on_event_callback

        self.cap: Optional[cv2.VideoCapture] = None
        self.is_running = False
        self.is_paused = False
        self.thread: Optional[threading.Thread] = None

        self.current_frame = None
        self.processed_frame = None
        self.frame_lock = threading.Lock()

        self.session_id: Optional[int] = None
        self.fps = 0.0
        self.frame_count = 0
        self.source_type = "demo"
        self.connection_state = "DEMO"  # "CONNECTING", "CONNECTED", "ERROR", "DEMO"
        self.last_error = ""

        # Frame resolution cache
        self.frame_width = 1280
        self.frame_height = 720

        # Video Playback, Scrubber Timeline & Seeking
        self.current_time = 0.0
        self.duration = 0.0
        self.current_frame_idx = 0
        self.total_frames = 0
        self.playback_speed = 1.0
        self.is_seekable = True
        self._seek_target: Optional[float] = None
        self.demo_time_offset = 0.0
        self.demo_duration = 300.0  # 5 minutes virtual timeline for demo

    def toggle_pause(self, paused: Optional[bool] = None) -> bool:
        if paused is not None:
            self.is_paused = paused
        else:
            self.is_paused = not self.is_paused
        print(f"[StreamManager] Playback state: {'PAUSED' if self.is_paused else 'PLAYING'}")
        return self.is_paused

    def seek(self, target_time: float) -> float:
        target_time = max(0.0, float(target_time))
        if self.duration > 0:
            target_time = min(self.duration, target_time)
        self._seek_target = target_time
        self.current_time = target_time
        print(f"[StreamManager] Seek requested to {target_time:.2f}s")
        return self.current_time

    def seek_relative(self, delta_seconds: float) -> float:
        new_time = self.current_time + delta_seconds
        return self.seek(new_time)

    def set_speed(self, speed: float) -> float:
        if speed > 0:
            self.playback_speed = float(speed)
        print(f"[StreamManager] Playback speed set to {self.playback_speed}x")
        return self.playback_speed

    def start_session(self, source: str, source_type: str = "rtsp", session_name: str = "Live Session"):
        self.stop()
        self.source = source
        self.source_type = source_type
        self.connection_state = "DEMO" if source == "demo" else "CONNECTING"
        self.last_error = ""
        self._connecting_in_progress = False
        self.counter.reset_counts()

        # Create session in DB
        db = SessionLocal()
        try:
            sess = CountSession(
                session_name=session_name,
                source_type=source_type,
                source_uri=str(source),
                start_time=datetime.utcnow(),
                status="active"
            )
            db.add(sess)
            db.commit()
            db.refresh(sess)
            self.session_id = sess.id
        finally:
            db.close()

        self.is_running = True
        self.is_paused = False
        self.thread = threading.Thread(target=self._process_loop, daemon=True)
        self.thread.start()
        print(f"[StreamManager] Started session {self.session_id} on {source} ({source_type})")

    def stop(self):
        self.is_running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

        if self.session_id:
            db = SessionLocal()
            try:
                sess = db.query(CountSession).filter(CountSession.id == self.session_id).first()
                if sess:
                    sess.end_time = datetime.utcnow()
                    sess.total_in = self.counter.total_in
                    sess.total_out = self.counter.total_out
                    sess.status = "completed"
                    db.commit()
            finally:
                db.close()
            self.session_id = None

        print("[StreamManager] Stopped.")

    def reset_all_data(self, clear_database: bool = True):
        # 1. Reset in-memory counter
        self.counter.reset_counts()
        self.demo_time_offset = 0.0
        self.current_time = 0.0

        # 2. Reset database records if requested
        if clear_database:
            db = SessionLocal()
            try:
                db.query(BagEvent).delete()
                sessions = db.query(CountSession).all()
                for s in sessions:
                    s.total_in = 0
                    s.total_out = 0
                db.commit()
            except Exception as e:
                print(f"[StreamManager] Error clearing DB on reset: {e}")
                db.rollback()
            finally:
                db.close()

        # 3. Broadcast reset to connected web clients
        if self.on_event_callback:
            try:
                self.on_event_callback({
                    "type": "counter_reset",
                    "total_in": 0,
                    "total_out": 0,
                    "net_count": 0
                })
            except Exception:
                pass
        print("[StreamManager] All data & counters reset to 0.")

    def set_line_coordinates(self, x1: int, y1: int, x2: int, y2: int):
        self.counter.set_line(x1, y1, x2, y2)
        print(f"[StreamManager] Line coordinates updated: ({x1}, {y1}) -> ({x2}, {y2})")

    def get_stats(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "is_running": self.is_running,
            "is_paused": self.is_paused,
            "is_seekable": self.is_seekable,
            "current_time": round(self.current_time, 1),
            "duration": round(self.duration, 1),
            "playback_speed": self.playback_speed,
            "connection_state": self.connection_state,
            "last_error": self.last_error,
            "total_in": self.counter.total_in,
            "total_out": self.counter.total_out,
            "net_count": self.counter.total_in - self.counter.total_out,
            "fps": round(self.fps, 1),
            "source": self.source,
            "source_type": self.source_type,
            "line": {
                "start": self.counter.line_start,
                "end": self.counter.line_end
            },
            "recent_events": self.counter.recent_events[-10:]
        }

    def _test_rtsp_host(self, url: str):
        import urllib.parse, socket
        try:
            parsed = urllib.parse.urlparse(url)
            host = parsed.hostname
            port = parsed.port or 554
            if not host:
                return False, "Invalid host in RTSP URL"
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.7)
            sock.connect((host, port))
            sock.close()
            return True, ""
        except socket.timeout:
            return False, f"Host {host}:{port} timed out (Unreachable on LAN)"
        except ConnectionRefusedError:
            return False, f"Port {port} on {host} refused connection"
        except OSError as e:
            return False, f"Network error reaching {host}:{port} ({e})"

    def _trigger_async_connect(self):
        if getattr(self, "_connecting_in_progress", False):
            return
        self._connecting_in_progress = True
        self.connection_state = "CONNECTING"
        t = threading.Thread(target=self._async_connect_worker, args=(self.source,), daemon=True)
        t.start()

    def _async_connect_worker(self, target_source: str):
        if target_source == "demo":
            self.connection_state = "DEMO"
            self.last_error = ""
            self._connecting_in_progress = False
            return

        print(f"[StreamManager] Connecting asynchronously to: {target_source}")
        if target_source.startswith("rtsp://"):
            ok, err = self._test_rtsp_host(target_source)
            if not ok:
                self.connection_state = "ERROR"
                self.last_error = err
                print(f"[StreamManager] Socket pre-check failed: {err}")
                self._connecting_in_progress = False
                return

        try:
            if str(target_source).isdigit():
                new_cap = cv2.VideoCapture(int(target_source))
            else:
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;2000000"
                new_cap = cv2.VideoCapture(target_source)

            if new_cap and new_cap.isOpened():
                ret, _ = new_cap.read()
                if ret:
                    if self.cap:
                        try:
                            self.cap.release()
                        except Exception:
                            pass
                    self.cap = new_cap
                    self.frame_width = int(new_cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
                    self.frame_height = int(new_cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
                    self.connection_state = "CONNECTED"
                    self.last_error = ""
                    print(f"[StreamManager] Connected! {self.frame_width}x{self.frame_height}")
                else:
                    new_cap.release()
                    self.connection_state = "ERROR"
                    self.last_error = "Camera opened but could not read video frames"
            else:
                self.connection_state = "ERROR"
                self.last_error = f"Failed to open video stream on {target_source}"
        except Exception as e:
            self.connection_state = "ERROR"
            self.last_error = str(e)
        finally:
            self._connecting_in_progress = False

    def _generate_connecting_frame(self, t: float):
        import numpy as np
        h, w = 720, 1280
        frame = np.full((h, w, 3), 20, dtype=np.uint8)

        # Header bar
        cv2.rectangle(frame, (0, 0), (w, 70), (40, 50, 60), -1)
        cv2.putText(frame, "CONNECTING TO CCTV CAMERA STREAM...", (40, 46),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 240, 255), 2)

        # Spinner animation
        cx, cy = w // 2, h // 2 - 30
        angle = int((t * 240) % 360)
        cv2.ellipse(frame, (cx, cy), (45, 45), angle, 0, 270, (0, 240, 255), 5)

        # Target URL display
        src_disp = str(self.source)
        if len(src_disp) > 65:
            src_disp = src_disp[:62] + "..."
        cv2.putText(frame, f"Target: {src_disp}", (w // 2 - 250, h // 2 + 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (220, 220, 220), 2)
        cv2.putText(frame, "Checking TCP port 554 and negotiating RTSP feed...", (w // 2 - 280, h // 2 + 100),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (140, 160, 180), 1)

        return frame

    def _generate_offline_frame(self, retry_in_sec: int = 5):
        import numpy as np
        h, w = 720, 1280
        frame = np.full((h, w, 3), 18, dtype=np.uint8)

        # Draw red warning header bar
        cv2.rectangle(frame, (0, 0), (w, 80), (30, 20, 140), -1)
        cv2.putText(frame, "CCTV CAMERA OFFLINE / DISCONNECTED", (40, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.95, (255, 255, 255), 2)

        # Draw error details
        cv2.putText(frame, "Unable to establish connection with camera:", (60, 140),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
        
        src_disp = str(self.source)
        if len(src_disp) > 70:
            src_disp = src_disp[:67] + "..."
        cv2.putText(frame, f"Target URL: {src_disp}", (60, 180),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 255), 2)

        if self.last_error:
            cv2.putText(frame, f"Error: {self.last_error}", (60, 220),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.68, (100, 100, 255), 2)

        # Troubleshooting checklist
        cv2.putText(frame, "QUICK TROUBLESHOOTING CHECKLIST:", (60, 280),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 200, 0), 2)
        tips = [
            "1. Verify the IP address of your CCTV camera / NVR in your router settings.",
            "2. Ensure your Mac and the camera are connected to the SAME Wi-Fi or LAN cable.",
            "3. Confirm camera RTSP port 554 is open and password is correct.",
            "4. To test with simulated bags anytime, select 'Demo Simulation' from the top bar.",
            f"5. Automatically retrying in {retry_in_sec} seconds..."
        ]
        for idx, tip in enumerate(tips):
            color = (160, 240, 160) if idx == 4 else (180, 180, 190)
            cv2.putText(frame, tip, (60, 325 + idx * 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.60, color, 1)

        return frame

    def _generate_synthetic_bag_frame(self, t: float):
        """
        Generates simulated CCTV footage with moving sacks on conveyor/worker path
        when no physical camera is plugged in yet, so the user can test immediately!
        """
        import numpy as np
        h, w = 720, 1280
        # Dark industrial warehouse background with floor and conveyor ramp
        frame = np.full((h, w, 3), 35, dtype=np.uint8)

        # Draw warehouse floor & grid
        cv2.rectangle(frame, (0, 0), (w, 180), (25, 25, 28), -1) # Wall
        cv2.line(frame, (0, 180), (w, 180), (70, 70, 75), 2)
        
        # Conveyor belt / ramp in the center
        pts = np.array([[380, 720], [540, 180], [740, 180], [900, 720]], np.int32)
        cv2.fillPoly(frame, [pts], (50, 52, 58))
        cv2.polylines(frame, [pts], True, (80, 85, 95), 3)

        # Moving belt rollers simulation
        offset = int((t * 120) % 60)
        for y in range(200 + offset, 700, 60):
            # calculate width at y
            ratio = (y - 180) / (720 - 180)
            lx = int(540 - ratio * 160)
            rx = int(740 + ratio * 160)
            cv2.line(frame, (lx, y), (rx, y), (65, 68, 75), 2)

        # Draw 2 simulated moving sacks ("বস্তা") moving down the conveyor (IN)
        # Period 6 seconds per sack
        for idx, phase in enumerate([0.0, 3.0]):
            progress = ((t + phase) % 6.0) / 6.0
            sy = int(220 + progress * 460)
            ratio = (sy - 180) / (720 - 180)
            sx = int(640 + (idx - 0.5) * 50 * ratio)
            bw = int(90 + ratio * 50)
            bh = int(60 + ratio * 40)
            x1, y1 = sx - bw // 2, sy - bh // 2
            x2, y2 = sx + bw // 2, sy + bh // 2

            # Jute / woven sack texture
            cv2.rectangle(frame, (x1, y1), (x2, y2), (90, 130, 175), -1) # Khaki/jute sack tone
            cv2.rectangle(frame, (x1, y1), (x2, y2), (130, 170, 215), 2)
            cv2.putText(frame, "SACK / BASTA", (x1 + 10, y1 + bh//2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (240, 240, 240), 1)

        return frame

    def _process_loop(self):
        if self.source != "demo":
            self._trigger_async_connect()
        t0 = time.time()
        frames_in_sec = 0
        start_time = time.time()
        last_reconnect_time = time.time()

        # Default tripwire line: across the walking passage / conveyor
        if self.counter.line_start in [(100, 300), (300, 450)]:
            self.counter.set_line(480, 80, 480, 750)

        while self.is_running:
            frame = None
            if self.source == "demo":
                self.is_seekable = True
                self.duration = self.demo_duration
                if self._seek_target is not None:
                    self.demo_time_offset = self._seek_target
                    self._seek_target = None

                if not self.is_paused:
                    self.demo_time_offset = (self.demo_time_offset + 0.033 * self.playback_speed) % self.demo_duration

                self.current_time = self.demo_time_offset
                frame = self._generate_synthetic_bag_frame(self.demo_time_offset)
                time.sleep(max(0.01, 0.033 / max(0.2, self.playback_speed)))
            else:
                if self.cap and self.cap.isOpened():
                    fps = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
                    total_f = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    if self.source_type == "video_file" and total_f > 0:
                        self.is_seekable = True
                        self.total_frames = total_f
                        self.duration = total_f / fps
                    else:
                        self.is_seekable = False

                    if self._seek_target is not None and self.is_seekable:
                        target_f = int(self._seek_target * fps)
                        target_f = max(0, min(total_f - 1, target_f))
                        self.cap.set(cv2.CAP_PROP_POS_FRAMES, target_f)
                        self._seek_target = None

                    if self.is_paused:
                        # Hold paused frame
                        with self.frame_lock:
                            if self.processed_frame is not None:
                                time.sleep(0.04)
                                continue
                        ret, frame = self.cap.read()
                    else:
                        ret, frame = self.cap.read()
                        if not ret:
                            if self.source_type == "video_file":
                                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                                ret, frame = self.cap.read()
                            else:
                                self.connection_state = "ERROR"
                                self.last_error = "Video stream read failed or ended."
                                if self.cap:
                                    try:
                                        self.cap.release()
                                    except Exception:
                                        pass
                                    self.cap = None

                        if ret and self.source_type == "video_file":
                            pos_f = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
                            self.current_frame_idx = pos_f
                            self.current_time = pos_f / fps
                            # Pace according to fps and speed
                            time.sleep(max(0.005, (1.0 / (fps * max(0.2, self.playback_speed))) - 0.015))

                if frame is None:
                    now = time.time()
                    elapsed = now - start_time
                    if self.connection_state == "CONNECTING":
                        frame = self._generate_connecting_frame(elapsed)
                    else:
                        time_until_retry = max(1, int(6 - (now - last_reconnect_time)))
                        frame = self._generate_offline_frame(retry_in_sec=time_until_retry)
                        if (now - last_reconnect_time) >= 6.0:
                            last_reconnect_time = now
                            self._trigger_async_connect()

                    time.sleep(0.04)
                    with self.frame_lock:
                        self.current_frame = frame
                        self.processed_frame = frame
                    continue

            self.frame_height, self.frame_width = frame.shape[:2]

            # 1. Detect & Track
            tracked_objects = self.detector.track(frame)

            # If demo mode and standard model didn't detect synthetic box, simulate tracking on synthetic sacks
            if self.source == "demo" and len(tracked_objects) == 0:
                elapsed = time.time() - start_time
                for idx, phase in enumerate([0.0, 3.0]):
                    progress = ((elapsed + phase) % 6.0) / 6.0
                    sy = int(220 + progress * 460)
                    ratio = (sy - 180) / (720 - 180)
                    sx = int(640 + (idx - 0.5) * 50 * ratio)
                    bw = int(90 + ratio * 50)
                    bh = int(60 + ratio * 40)
                    x1, y1 = sx - bw // 2, sy - bh // 2
                    x2, y2 = sx + bw // 2, sy + bh // 2
                    sim_id = 100 + idx + int((elapsed + phase) // 6.0) * 10
                    tracked_objects.append({
                        "track_id": sim_id,
                        "bbox": [x1, y1, x2, y2],
                        "confidence": 0.95,
                        "class_id": 0,
                        "class_name": "bag/sack"
                    })

            # 2. Update Counter
            for obj in tracked_objects:
                tid = obj["track_id"]
                bbox = obj["bbox"]
                conf = obj["confidence"]
                s_count = obj.get("sack_count", 0)
                s_box = obj.get("sack_box")
                s_label = obj.get("sack_label", "")

                event = self.counter.update(
                    track_id=tid,
                    bbox=bbox,
                    confidence=conf,
                    sack_count=s_count,
                    sack_bbox=s_box,
                    sack_label=s_label
                )
                if event:
                    self._record_event(event, frame)

            # Clean old tracks
            self.counter.clean_old_tracks(max_age_seconds=8.0)

            # 3. Draw Overlays
            display_frame = frame.copy()
            self._draw_overlays(display_frame, tracked_objects)

            # FPS calculation
            frames_in_sec += 1
            now = time.time()
            if (now - t0) >= 1.0:
                self.fps = frames_in_sec / (now - t0)
                frames_in_sec = 0
                t0 = now

            with self.frame_lock:
                self.current_frame = frame
                self.processed_frame = display_frame

        if self.cap:
            self.cap.release()
            self.cap = None

    def _record_event(self, event: Dict[str, Any], frame):
        """Save snapshot and write event to DB."""
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
        filename = f"event_{event['direction']}_id{event['track_id']}_{ts_str}.jpg"
        filepath = os.path.join(SNAPSHOTS_DIR, filename)

        # Highlight sack on snapshot
        snap = frame.copy()
        draw_box = event.get("sack_bbox") or event["bbox"]
        x1, y1, x2, y2 = draw_box
        count = event.get("count", 1)
        color = (0, 255, 120) if event["direction"] == "IN" else (0, 100, 255)
        cv2.rectangle(snap, (x1, y1), (x2, y2), color, 3)
        badge_text = f"{event['direction']} +{count} BASTA"
        cv2.putText(snap, badge_text, (x1, max(25, y1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2)
        cv2.imwrite(filepath, snap)

        # Save to DB
        db = SessionLocal()
        try:
            bag_ev = BagEvent(
                session_id=self.session_id,
                timestamp=datetime.utcnow(),
                direction=event["direction"],
                track_id=event["track_id"],
                confidence=event["confidence"],
                snapshot_path=f"/snapshots/{filename}",
                notes=event.get("notes") or f"{count}x বস্তা (Sack on Head)"
            )
            db.add(bag_ev)
            # Update session counts
            if self.session_id:
                sess = db.query(CountSession).filter(CountSession.id == self.session_id).first()
                if sess:
                    sess.total_in = self.counter.total_in
                    sess.total_out = self.counter.total_out
            db.commit()
        except Exception as e:
            print(f"[StreamManager] Error writing event to DB: {e}")
        finally:
            db.close()

        # Trigger callback (for WebSockets)
        if self.on_event_callback:
            event_payload = {
                "type": "bag_counted",
                "direction": event["direction"],
                "count": event.get("count", 1),
                "track_id": event["track_id"],
                "total_in": self.counter.total_in,
                "total_out": self.counter.total_out,
                "net_count": self.counter.total_in - self.counter.total_out,
                "snapshot": f"/snapshots/{filename}",
                "notes": event.get("notes", ""),
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }
            try:
                self.on_event_callback(event_payload)
            except Exception as e:
                print(f"[StreamManager] Callback error: {e}")

    def _draw_overlays(self, frame, tracked_objects):
        # 1. Draw Tripwire Line
        p1 = self.counter.line_start
        p2 = self.counter.line_end
        # Glowing line effect
        cv2.line(frame, p1, p2, (0, 200, 255), 4) # Amber/cyan neon tripwire
        cv2.circle(frame, p1, 7, (0, 255, 0), -1)
        cv2.circle(frame, p2, 7, (0, 0, 255), -1)

        # Direction indicator text / arrow
        mid_x = (p1[0] + p2[0]) // 2
        mid_y = (p1[1] + p2[1]) // 2
        cv2.putText(frame, "TRIPWIRE (COUNT LINE)", (mid_x - 110, mid_y - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        cv2.putText(frame, "IN (DOWN) v", (mid_x - 50, mid_y + 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 120), 2)

        # 2. Draw Tracked Bounding Boxes & Head-Load Bags
        for obj in tracked_objects:
            x1, y1, x2, y2 = obj["bbox"]
            tid = obj["track_id"]
            scount = obj.get("sack_count", 0)
            sbox = obj.get("sack_box")

            if scount > 0 and sbox is not None:
                # SACK DETECTED ON HEAD/SHOULDER
                sx1, sy1, sx2, sy2 = sbox
                sack_color = (0, 255, 120) if scount == 1 else (0, 215, 255) # Gold for 2x stacked!
                cv2.rectangle(frame, (sx1, sy1), (sx2, sy2), sack_color, 3)

                badge = f"BASTA: {scount}x ({'STACKED' if scount == 2 else 'HEAD-LOAD'})"
                (tw, th), _ = cv2.getTextSize(badge, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
                cv2.rectangle(frame, (sx1, sy1 - 24), (sx1 + tw + 10, sy1), sack_color, -1)
                cv2.putText(frame, badge, (sx1 + 5, sy1 - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2, cv2.LINE_AA)

                # Subtle worker outline
                cv2.rectangle(frame, (x1, y1), (x2, y2), (60, 110, 80), 1)
                cx = (sx1 + sx2) // 2
                cy = (sy1 + sy2) // 2
                cv2.circle(frame, (cx, cy), 5, sack_color, -1)
            else:
                # Empty-handed person: subtle gray box, explicitly labeled as skipped
                cv2.rectangle(frame, (x1, y1), (x2, y2), (70, 75, 85), 1)
                label = f"Person #{tid} (No Bag - Skipped)"
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
                cv2.rectangle(frame, (x1, y1 - 18), (x1 + tw + 6, y1), (35, 40, 48), -1)
                cv2.putText(frame, label, (x1 + 3, y1 - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.42, (170, 175, 185), 1, cv2.LINE_AA)

        # 3. HUD Display (Top Bar with live counters)
        h, w = frame.shape[:2]
        hud_h = 55
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, hud_h), (15, 18, 25), -1)
        cv2.addWeighted(overlay, 0.8, frame, 0.2, 0, frame)

        # Display Metrics
        in_text = f"BAG IN: {self.counter.total_in}"
        out_text = f"BAG OUT: {self.counter.total_out}"
        net_text = f"NET: {self.counter.total_in - self.counter.total_out}"
        fps_text = f"FPS: {self.fps:.1f}"

        cv2.putText(frame, in_text, (20, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 120), 2)
        cv2.putText(frame, out_text, (240, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 100, 255), 2)
        cv2.putText(frame, net_text, (480, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 220, 0), 2)
        if self.is_paused:
            cv2.rectangle(frame, (w // 2 - 90, 8), (w // 2 + 90, 46), (30, 30, 200), -1)
            cv2.putText(frame, "❚❚ PAUSED", (w // 2 - 70, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)
        cv2.putText(frame, fps_text, (w - 150, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)

    def get_jpeg_frame(self) -> Optional[bytes]:
        with self.frame_lock:
            if self.processed_frame is None:
                return None
            ret, jpeg = cv2.imencode('.jpg', self.processed_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            if ret:
                return jpeg.tobytes()
        return None
