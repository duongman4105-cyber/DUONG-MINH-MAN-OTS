from sqlalchemy import Column, String, Integer, Float, TIMESTAMP, ForeignKey, JSON
from sqlalchemy.sql import func
from database import Base

class Camera(Base):
    __tablename__ = "Cameras"
    cam_id = Column(String(50), primary_key=True)
    cam_name = Column(String(100), nullable=False)
    location = Column(String(255))
    rtsp_url = Column(String(255))
    status = Column(String(20), default='active')

class Vehicle(Base):
    __tablename__ = "Vehicles"
    vehicle_id = Column(String(50), primary_key=True)
    plate_text = Column(String(20))
    color = Column(String(30))
    vehicle_type = Column(String(50))
    first_detected = Column(TIMESTAMP, server_default=func.now())

class Event(Base):
    __tablename__ = "Events"
    event_id = Column(Integer, primary_key=True, autoincrement=True)
    cam_id = Column(String(50), ForeignKey("Cameras.cam_id"))
    vehicle_id = Column(String(50), ForeignKey("Vehicles.vehicle_id"))
    timestamp = Column(TIMESTAMP, server_default=func.now())
    image_path = Column(String(255))
    confidence_score = Column(Float)