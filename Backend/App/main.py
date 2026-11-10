from fastapi import FastAPI, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
import models
from database import engine, get_db

# Không cần tạo bảng lại vì bạn đã tạo bằng lệnh SQL trên Workbench
# Nhưng lệnh này đảm bảo an toàn nếu sau này thiếu bảng nào đó
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="MTMCT Backend API", version="1.0.0")

class EventData(BaseModel):
    cam_id: str
    vehicle_id: str
    plate_text: str
    color: str

@app.post("/api/v1/events")
def create_event(event: EventData, db: Session = Depends(get_db)):
    # 1. Kiểm tra xem xe đã tồn tại chưa, chưa có thì thêm mới
    db_vehicle = db.query(models.Vehicle).filter(models.Vehicle.vehicle_id == event.vehicle_id).first()
    if not db_vehicle:
        new_vehicle = models.Vehicle(
            vehicle_id=event.vehicle_id,
            plate_text=event.plate_text,
            color=event.color
        )
        db.add(new_vehicle)
        db.commit()

    # 2. Ghi nhận sự kiện (Xe chạy qua camera)
    new_event = models.Event(
        cam_id=event.cam_id,
        vehicle_id=event.vehicle_id
    )
    db.add(new_event)
    db.commit()

    return {"status": "success", "message": "Đã lưu sự kiện vào Database thành công!"}