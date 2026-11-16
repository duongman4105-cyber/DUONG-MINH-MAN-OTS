from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from database import engine, get_db
import models
import schemas

# Lệnh này sẽ tự động tạo bảng FeatureVectors trong MySQL nếu chưa có
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="MTMCT Backend API", version="1.0.0")

# API CŨ (Giữ nguyên logic của bạn)
@app.post("/api/v1/events")
def create_event(event: schemas.EventData, db: Session = Depends(get_db)):
    # 1. Kiểm tra xe đã tồn tại chưa
    db_vehicle = db.query(models.Vehicle).filter(models.Vehicle.vehicle_id == event.vehicle_id).first()
    if not db_vehicle:
        new_vehicle = models.Vehicle(
            vehicle_id=event.vehicle_id,
            plate_text=event.plate_text,
            color=event.color
        )
        db.add(new_vehicle)
        db.commit()

    # 2. Ghi nhận sự kiện
    new_event = models.Event(
        cam_id=event.cam_id,
        vehicle_id=event.vehicle_id
    )
    db.add(new_event)
    db.commit()

    return {"status": "success", "message": "Đã lưu sự kiện vào Database thành công!"}


# API MỚI DÀNH CHO BO-SORT CỦA KHIÊM ĐỂ ĐẨY VECTOR VỀ
@app.post("/api/v1/features")
def receive_feature(data: schemas.FeatureData, db: Session = Depends(get_db)):
    try:
        # Bước 1: Vẫn phải kiểm tra và thêm xe mới nếu nó chưa có trong DB
        db_vehicle = db.query(models.Vehicle).filter(models.Vehicle.vehicle_id == data.vehicle_id).first()
        if not db_vehicle:
            new_vehicle = models.Vehicle(
                vehicle_id=data.vehicle_id,
                plate_text=data.plate_text
            )
            db.add(new_vehicle)
            db.commit()

        # Bước 2: Lưu cục vector 2048 chiều vào bảng FeatureVectors
        new_feature = models.FeatureVector(
            cam_id=data.cam_id,
            vehicle_id=data.vehicle_id,
            embedding_data=data.embedding_data # MySQL JSON tự động convert
        )
        db.add(new_feature)
        db.commit()

        return {"status": "success", "message": f"Đã nhận thành công vector của xe {data.vehicle_id}"}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))