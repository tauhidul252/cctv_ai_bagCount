from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class SystemConfig(Base):
    __tablename__ = "system_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(64), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class CountSession(Base):
    __tablename__ = "count_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_name = Column(String(128), default="Live Session")
    source_type = Column(String(32), default="rtsp")  # rtsp, video_file, nvr_playback
    source_uri = Column(String(512), nullable=False)
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    total_in = Column(Integer, default=0)
    total_out = Column(Integer, default=0)
    status = Column(String(32), default="active")  # active, paused, completed, error
    
    events = relationship("BagEvent", back_populates="session", cascade="all, delete-orphan")

class BagEvent(Base):
    __tablename__ = "bag_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("count_sessions.id", ondelete="CASCADE"), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    direction = Column(String(16), nullable=False)  # "IN" or "OUT"
    track_id = Column(Integer, nullable=True)
    confidence = Column(Float, default=1.0)
    snapshot_path = Column(String(512), nullable=True)
    notes = Column(String(255), nullable=True)

    session = relationship("CountSession", back_populates="events")
