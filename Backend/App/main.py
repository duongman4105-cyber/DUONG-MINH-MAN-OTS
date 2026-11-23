from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
from database import engine, get_db
import models
import schemas

# Tự động tạo các bảng trong MySQL nếu chưa tồn tại
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="MTMCT Backend API", version="1.0.0")


# 1. API TIẾP NHẬN LUỒNG SỰ KIỆN (AI INGESTION)
@app.post("/api/v1/events")
def create_event(event: schemas.EventData, db: Session = Depends(get_db)):
    try:
        # Kiểm tra xe đã tồn tại chưa
        db_vehicle = db.query(models.Vehicle).filter(models.Vehicle.vehicle_id == event.vehicle_id).first()
        if not db_vehicle:
            new_vehicle = models.Vehicle(
                vehicle_id=event.vehicle_id,
                plate_text=event.plate_text,
                color=event.color
            )
            db.add(new_vehicle)
            db.commit()

        # Ghi nhận sự kiện
        new_event = models.Event(
            cam_id=event.cam_id,
            vehicle_id=event.vehicle_id
        )
        db.add(new_event)
        db.commit()

        return {"status": "success", "message": "Đã lưu sự kiện vào Database thành công!"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# 2. API TIẾP NHẬN VECTOR ĐẶC TRƯNG 2048 CHIỀU (RE-ID INGESTION)
@app.post("/api/v1/features")
def receive_feature(data: schemas.FeatureData, db: Session = Depends(get_db)):
    try:
        # Kiểm tra và thêm xe mới nếu chưa có trong DB
        db_vehicle = db.query(models.Vehicle).filter(models.Vehicle.vehicle_id == data.vehicle_id).first()
        if not db_vehicle:
            new_vehicle = models.Vehicle(
                vehicle_id=data.vehicle_id,
                plate_text=data.plate_text
            )
            db.add(new_vehicle)
            db.commit()

        # Lưu vector 2048 chiều vào bảng FeatureVectors
        new_feature = models.FeatureVector(
            cam_id=data.cam_id,
            vehicle_id=data.vehicle_id,
            embedding_data=data.embedding_data  # MySQL JSON tự động convert
        )
        db.add(new_feature)
        db.commit()

        return {"status": "success", "message": f"Đã nhận thành công vector của xe {data.vehicle_id}!"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# 3. API TRA CỨU LỘ TRÌNH DI CHUYỂN QUA ĐA CAMERA (SEARCH API)
@app.get("/api/v1/events/search")
def search_events(
    plate_text: Optional[str] = Query(None, description="Tìm theo biển số (VD: 43A-529.54 hoặc 43A)"),
    cam_id: Optional[str] = Query(None, description="Lọc theo mã camera (VD: CAM_01)"),
    global_id: Optional[str] = Query(None, description="Lọc theo ID chung qua nhiều camera (VD: G_100)"),
    vehicle_type: Optional[str] = Query(None, description="Lọc loại xe (car, motorcycle, truck...)"),
    start_time: Optional[datetime] = Query(None, description="Thời gian bắt đầu (YYYY-MM-DDTHH:MM:SS)"),
    end_time: Optional[datetime] = Query(None, description="Thời gian kết thúc (YYYY-MM-DDTHH:MM:SS)"),
    limit: int = Query(50, ge=1, le=200, description="Số bản ghi mỗi trang"),
    offset: int = Query(0, ge=0, description="Vị trí bắt đầu phân trang"),
    db: Session = Depends(get_db)
):
    try:
        # Join 3 bảng Events - Vehicles - Cameras
        query = (
            db.query(models.Event, models.Vehicle, models.Camera)
            .outerjoin(models.Vehicle, models.Event.vehicle_id == models.Vehicle.vehicle_id)
            .outerjoin(models.Camera, models.Event.cam_id == models.Camera.cam_id)
        )

        # Áp dụng các bộ lọc linh hoạt
        if plate_text:
            query = query.filter(models.Vehicle.plate_text.ilike(f"%{plate_text.strip()}%"))
        if cam_id:
            query = query.filter(models.Event.cam_id == cam_id.strip())
        if global_id:
            query = query.filter(models.Event.global_id == global_id.strip())
        if vehicle_type:
            query = query.filter(models.Vehicle.vehicle_type == vehicle_type.strip())
        if start_time:
            query = query.filter(models.Event.timestamp >= start_time)
        if end_time:
            query = query.filter(models.Event.timestamp <= end_time)

        # Đếm tổng số bản ghi khớp điều kiện
        total = query.count()

        # Sắp xếp theo thời gian tăng dần (ASC) để ra đúng lộ trình di chuyển
        results = (
            query.order_by(models.Event.timestamp.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        data = [
            {
                "event_id": event.event_id,
                "global_id": event.global_id,
                "vehicle_id": event.vehicle_id,
                "plate_text": vehicle.plate_text if vehicle else None,
                "vehicle_type": vehicle.vehicle_type if vehicle else None,
                "color": vehicle.color if vehicle else None,
                "cam_id": event.cam_id,
                "cam_name": camera.cam_name if camera else None,
                "location": camera.location if camera else None,
                "timestamp": event.timestamp,
                "confidence_score": event.confidence_score,
                "image_path": event.image_path,
            }
            for event, vehicle, camera in results
        ]

        return {
            "status": "success",
            "total": total,
            "limit": limit,
            "offset": offset,
            "data": data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi truy vấn lộ trình: {str(e)}")