from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="MTMCT Backend API", version="1.0.0")


class EventData(BaseModel):
    cam_id: str
    vehicle_id: str
    plate_text: str
    color: str
    timestamp: str

@app.get("/")
def read_root():
    return {"message": "Hệ thống Backend MTMCT đang hoạt động!"}


@app.post("/api/v1/events")
def create_event(event: EventData):
    return {
        "status": "success",
        "message": f"Đã ghi nhận xe biển số {event.plate_text} màu {event.color} từ camera {event.cam_id}"
    }