import os
import csv
import io
import asyncio
from datetime import datetime, date, timedelta
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, Form, Depends, WebSocket, WebSocketDisconnect, HTTPException, Body
from fastapi.responses import StreamingResponse, Response, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.database import init_db, get_db, SessionLocal
from backend.models import BagEvent, CountSession, SystemConfig
from backend.detector import BagDetectorTracker
from backend.counter import DirectionalBagCounter
from backend.stream_manager import StreamManager, SNAPSHOTS_DIR
from backend.nvr_client import NVRStreamHelper

# Initialize directories
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
UPLOADS_DIR = os.path.join(BASE_DIR, "data", "uploads")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(SNAPSHOTS_DIR, exist_ok=True)

# Initialize DB tables
init_db()

app = FastAPI(title="CCTV AI Bag Count & Verification System", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active WebSocket connections and main loop reference
active_websockets: List[WebSocket] = []
main_event_loop: Optional[asyncio.AbstractEventLoop] = None

@app.on_event("startup")
async def startup_event():
    global main_event_loop
    main_event_loop = asyncio.get_running_loop()

def broadcast_event(event_data: dict):
    # Safe broadcast across threads to connected clients
    global main_event_loop
    if not main_event_loop or not active_websockets:
        return
    for ws in list(active_websockets):
        try:
            asyncio.run_coroutine_threadsafe(ws.send_json(event_data), main_event_loop)
        except Exception:
            pass

# Initialize AI & Stream Manager
detector = BagDetectorTracker(model_path="yolo11s.pt", conf_threshold=0.30)
counter = DirectionalBagCounter()
stream_manager = StreamManager(
    source="demo",
    detector=detector,
    counter=counter,
    on_event_callback=broadcast_event
)

# Auto start demo stream on boot
stream_manager.start_session(source="demo", source_type="demo", session_name="Initial Demo Feed")


# Pydantic Schemas
class StartStreamRequest(BaseModel):
    source: str
    source_type: str = "rtsp"  # "rtsp", "file", "webcam", "demo"
    session_name: Optional[str] = "Live Bag Count"

class LineCoordsRequest(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    in_direction: Optional[str] = "down"

class NVRUrlRequest(BaseModel):
    brand: str
    host: str
    port: int = 554
    username: str = "admin"
    password: str = "12345"
    channel: int = 1
    stream_type: str = "main"
    mode: str = "live"  # "live" or "playback"
    start_time: Optional[str] = None
    end_time: Optional[str] = None


# Endpoints
@app.get("/api/status")
def get_status():
    return stream_manager.get_stats()

@app.post("/api/stream/start")
def start_stream(req: StartStreamRequest):
    stream_manager.start_session(
        source=req.source,
        source_type=req.source_type,
        session_name=req.session_name or "Live Feed"
    )
    return {"message": "Stream started successfully", "source": req.source}

class PauseRequest(BaseModel):
    paused: Optional[bool] = None

class SeekRequest(BaseModel):
    time: Optional[float] = None
    delta: Optional[float] = None

class SpeedRequest(BaseModel):
    speed: float

@app.post("/api/stream/pause")
def toggle_pause(req: Optional[PauseRequest] = None):
    p = req.paused if req else None
    state = stream_manager.toggle_pause(p)
    return {"paused": state}

@app.post("/api/stream/seek")
def seek_stream(req: SeekRequest):
    if req.delta is not None:
        new_time = stream_manager.seek_relative(req.delta)
    elif req.time is not None:
        new_time = stream_manager.seek(req.time)
    else:
        new_time = stream_manager.current_time
    return {"current_time": new_time, "duration": stream_manager.duration}

@app.post("/api/stream/speed")
def set_speed(req: SpeedRequest):
    sp = stream_manager.set_speed(req.speed)
    return {"playback_speed": sp}

@app.post("/api/stream/stop")
def stop_stream():
    stream_manager.stop()
    return {"message": "Stream stopped"}

class ResetRequest(BaseModel):
    clear_database: Optional[bool] = True

@app.post("/api/stream/reset-counter")
def reset_counter(req: Optional[ResetRequest] = Body(None)):
    clear_db = True
    if req is not None and req.clear_database is not None:
        clear_db = req.clear_database
    stream_manager.reset_all_data(clear_database=clear_db)
    return {"message": "All counters and data reset successfully", "total_in": 0, "total_out": 0}

@app.post("/api/config/line")
def update_line(req: LineCoordsRequest):
    stream_manager.set_line_coordinates(req.x1, req.y1, req.x2, req.y2)
    return {"message": "Line coordinates saved", "coords": [req.x1, req.y1, req.x2, req.y2]}

class ModelSelectRequest(BaseModel):
    model_name: str

@app.get("/api/models")
def get_models():
    current = getattr(stream_manager.detector, "model_path", "yolo11s.pt")
    return {
        "current_model": current,
        "available_models": [
            {
                "id": "yolo11s.pt",
                "name": "YOLO11 Small (রেকমেন্ডেড - দ্রুত ও নিখুঁত)",
                "speed": "38 FPS (Real-time)",
                "accuracy": "উচ্চ (High Accuracy)",
                "recommended": True
            },
            {
                "id": "yolo11m.pt",
                "name": "YOLO11 Medium (সর্বোচ্চ নিখুঁত)",
                "speed": "15.4 FPS",
                "accuracy": "সর্বোচ্চ (Maximum Precision)",
                "recommended": False
            },
            {
                "id": "yolov8n.pt",
                "name": "YOLOv8 Nano (হালকা মডেল)",
                "speed": "45 FPS",
                "accuracy": "মাঝারি (Standard)",
                "recommended": False
            }
        ]
    }

@app.post("/api/models/select")
def select_model(req: ModelSelectRequest):
    success = stream_manager.detector.update_model(req.model_name)
    if success:
        return {"success": True, "message": f"সফলভাবে {req.model_name} মডেলে পরিবর্তন করা হয়েছে", "current_model": req.model_name}
    raise HTTPException(status_code=400, detail="মডেল লোড করতে ব্যর্থ হয়েছে")

@app.post("/api/upload-video")
async def upload_video(file: UploadFile = File(...)):
    filename = f"{int(datetime.now().timestamp())}_{file.filename}"
    file_path = os.path.join(UPLOADS_DIR, filename)
    with open(file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
    
    # Start stream on this uploaded video file
    stream_manager.start_session(
        source=file_path,
        source_type="video_file",
        session_name=f"Recorded: {file.filename}"
    )
    return {"message": "Video uploaded and analysis started", "file_path": file_path, "filename": file.filename}

@app.post("/api/nvr/build-url")
def build_nvr_url(req: NVRUrlRequest):
    if req.mode == "playback":
        st = datetime.fromisoformat(req.start_time) if req.start_time else None
        et = datetime.fromisoformat(req.end_time) if req.end_time else None
        url = NVRStreamHelper.build_playback_url(
            brand=req.brand,
            host=req.host,
            port=req.port,
            username=req.username,
            password=req.password,
            channel=req.channel,
            start_time=st,
            end_time=et
        )
    else:
        url = NVRStreamHelper.build_live_url(
            brand=req.brand,
            host=req.host,
            port=req.port,
            username=req.username,
            password=req.password,
            channel=req.channel,
            stream_type=req.stream_type
        )
    return {"rtsp_url": url}

@app.get("/api/reports")
def get_reports(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(BagEvent)
    if start_date:
        s_dt = datetime.strptime(start_date, "%Y-%m-%d")
        query = query.filter(BagEvent.timestamp >= s_dt)
    if end_date:
        e_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        query = query.filter(BagEvent.timestamp < e_dt)

    events = query.order_by(BagEvent.timestamp.desc()).limit(200).all()

    total_in = db.query(func.count(BagEvent.id)).filter(BagEvent.direction == "IN").scalar() or 0
    total_out = db.query(func.count(BagEvent.id)).filter(BagEvent.direction == "OUT").scalar() or 0

    return {
        "total_in": total_in,
        "total_out": total_out,
        "net_count": total_in - total_out,
        "events": [
            {
                "id": ev.id,
                "timestamp": ev.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "direction": ev.direction,
                "track_id": ev.track_id,
                "confidence": ev.confidence,
                "snapshot_path": ev.snapshot_path,
                "notes": ev.notes
            }
            for ev in events
        ]
    }

@app.get("/api/reports/export")
def export_reports_csv(db: Session = Depends(get_db)):
    events = db.query(BagEvent).order_by(BagEvent.timestamp.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Timestamp (UTC)", "Direction", "Track ID", "Confidence", "Snapshot File", "Notes"])
    for ev in events:
        writer.writerow([
            ev.id,
            ev.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            ev.direction,
            ev.track_id,
            ev.confidence,
            ev.snapshot_path or "",
            ev.notes or ""
        ])
    output.seek(0)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=bag_count_report.csv"}
    )

@app.get("/api/stream/feed")
def video_feed():
    def frame_generator():
        while True:
            frame_bytes = stream_manager.get_jpeg_frame()
            if frame_bytes is None:
                import time
                time.sleep(0.04)
                continue
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n")
            import time
            time.sleep(0.03)

    return StreamingResponse(frame_generator(), media_type="multipart/x-mixed-replace; boundary=frame")

# WebSocket for real-time live events
@app.websocket("/ws/live")
async def websocket_live_events(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        while True:
            # Keepalive / listen for client ping
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_websockets:
            active_websockets.remove(websocket)

# Static file serving: snapshots & frontend
app.mount("/snapshots", StaticFiles(directory=SNAPSHOTS_DIR), name="snapshots")
app.mount("/css", StaticFiles(directory=os.path.join(FRONTEND_DIR, "css")), name="css")
app.mount("/js", StaticFiles(directory=os.path.join(FRONTEND_DIR, "js")), name="js")

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
