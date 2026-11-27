from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.sql import func

from database import Base


class Camera(Base):
    __tablename__ = "Cameras"
    cam_id = Column(String(64), primary_key=True)
    cam_name = Column(String(120), nullable=False)
    location = Column(String(255), nullable=True)
    rtsp_url = Column(String(255), nullable=True)
    status = Column(String(20), default="active")


class Batch(Base):
    __tablename__ = "Batches"
    batch_id = Column(String(64), primary_key=True)
    name = Column(String(150), nullable=True)
    total_jobs = Column(Integer, default=1, nullable=False)
    is_sealed = Column(Boolean, default=False, nullable=False)
    match_status = Column(String(20), default="waiting", index=True)  # waiting | matching | done | failed
    match_summary = Column(JSON, nullable=True)
    match_error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Job(Base):
    __tablename__ = "Jobs"
    job_id = Column(String(64), primary_key=True)
    batch_id = Column(String(64), ForeignKey("Batches.batch_id"), index=True, nullable=False)
    video_id = Column(String(120), nullable=False)
    camera_id = Column(String(64), ForeignKey("Cameras.cam_id"), index=True, nullable=False)
    start_time = Column(String(40), nullable=False)  # ISO giờ VN (+07:00)
    video_path = Column(String(255), nullable=True)
    status = Column(String(20), default="pending", index=True)  # pending | processing | done | failed
    worker_id = Column(String(100), nullable=True, index=True)
    progress = Column(Integer, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    error_message = Column(String(500), nullable=True)
    error_log = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    last_heartbeat_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class WorkerHeartbeat(Base):
    __tablename__ = "WorkerHeartbeats"
    worker_id = Column(String(100), primary_key=True)
    current_job_id = Column(String(64), nullable=True)
    progress = Column(Integer, nullable=True)
    last_seen_at = Column(DateTime, nullable=False)


class Vehicle(Base):
    __tablename__ = "Vehicles"
    vehicle_id = Column(String(120), primary_key=True)
    plate_text = Column(String(30), nullable=True, index=True)
    plate_conf = Column(Float, nullable=True)
    color = Column(String(30), nullable=True)
    color_conf = Column(Float, nullable=True)
    vehicle_type = Column(String(50), nullable=True)
    type_conf = Column(Float, nullable=True)
    first_detected = Column(DateTime, server_default=func.now())


class Event(Base):
    __tablename__ = "Events"
    event_id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String(64), ForeignKey("Batches.batch_id"), nullable=True, index=True)
    job_id = Column(String(64), ForeignKey("Jobs.job_id"), nullable=True, index=True)
    video_id = Column(String(120), nullable=True)
    cam_id = Column(String(64), ForeignKey("Cameras.cam_id"), index=True)
    vehicle_id = Column(String(120), ForeignKey("Vehicles.vehicle_id"), index=True)
    global_id = Column(String(120), nullable=True, index=True)
    timestamp = Column(DateTime, index=True, server_default=func.now())  # t_start (giờ VN)
    t_end = Column(DateTime, nullable=True)
    entry_edge = Column(String(20), nullable=True)
    exit_edge = Column(String(20), nullable=True)
    is_moving = Column(Boolean, default=True)
    n_crops = Column(Integer, default=0)
    image_path = Column(String(255), nullable=True)
    confidence_score = Column(Float, nullable=True)
    match_method = Column(String(50), nullable=True)


class FeatureVector(Base):
    __tablename__ = "FeatureVectors"
    id = Column(Integer, primary_key=True, autoincrement=True)
    cam_id = Column(String(64), ForeignKey("Cameras.cam_id"), index=True)
    vehicle_id = Column(String(120), ForeignKey("Vehicles.vehicle_id"), index=True)
    embedding_data = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class MatchCandidate(Base):
    __tablename__ = "MatchCandidates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String(64), ForeignKey("Batches.batch_id"), index=True, nullable=False)
    tracklet_a = Column(String(120), nullable=False)
    tracklet_b = Column(String(120), nullable=False)
    camera_a = Column(String(64), nullable=False)
    camera_b = Column(String(64), nullable=False)
    crop_a = Column(String(255), nullable=True)
    crop_b = Column(String(255), nullable=True)
    score = Column(Float, nullable=False)
    gap_s = Column(Float, nullable=False)
    kind = Column(String(120), nullable=True)
    global_id_a = Column(String(120), nullable=True)
    global_id_b = Column(String(120), nullable=True)
    status = Column(String(20), default="pending", index=True)  # pending | same | different
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())