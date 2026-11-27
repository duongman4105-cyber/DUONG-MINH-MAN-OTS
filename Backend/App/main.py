import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

import models
import schemas
from config import (
    CORS_ORIGINS,
    HEARTBEAT_OFFLINE_SEC,
    JOB_MAX_RETRIES,
    JOB_TIMEOUT_SEC,
    MAX_CAMERAS,
    MAX_PENDING_JOBS,
    MAX_UPLOAD_MB,
    STATIC_DIR,
    UPLOADS_DIR,
    WORKER_API_KEY,
)
from database import engine, get_db
from services.tracking_logic import (
    ensure_camera_exists,
    ingest_ai_v1_payload,
    match_or_create_global_id,
    now_vn_naive,
    run_batch_matching_background,
    to_vn_iso,
)

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="MTMCT Backend API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# =====================================================================
# BẢO MẬT WORKER & QUẢN LÝ JOB TREO
# =====================================================================

def verify_worker_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> str:
    if not x_api_key or x_api_key != WORKER_API_KEY:
        raise HTTPException(status_code=401, detail="Thiếu hoặc sai X-API-Key")
    return x_api_key


def _clean_optional_str(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "string":
        return None
    return cleaned


def _upsert_worker_heartbeat(
    db: Session,
    worker_id: str,
    current_job_id: Optional[str] = None,
    progress: Optional[int] = None,
) -> None:
    now = now_vn_naive()
    hb = (
        db.query(models.WorkerHeartbeat)
        .filter(models.WorkerHeartbeat.worker_id == worker_id)
        .first()
    )
    if not hb:
        hb = models.WorkerHeartbeat(
            worker_id=worker_id,
            current_job_id=current_job_id,
            progress=progress,
            last_seen_at=now,
        )
        db.add(hb)
        db.flush()
    else:
        hb.last_seen_at = now
        hb.current_job_id = current_job_id
        hb.progress = progress


def reclaim_stale_jobs(db: Session) -> int:
    """Thu hồi các job đang processing nhưng quá hạn heartbeat về lại pending (tối đa JOB_MAX_RETRIES lần)."""
    cutoff = now_vn_naive() - timedelta(seconds=JOB_TIMEOUT_SEC)
    stale_jobs = (
        db.query(models.Job)
        .filter(models.Job.status == "processing")
        .all()
    )
    reclaimed = 0
    for job in stale_jobs:
        last_ping = job.last_heartbeat_at or job.started_at or job.updated_at
        if last_ping and last_ping < cutoff:
            job.retry_count = (job.retry_count or 0) + 1
            job.worker_id = None
            job.progress = None
            if job.retry_count >= JOB_MAX_RETRIES:
                job.status = "failed"
                job.error_message = (
                    f"Job bị treo quá {JOB_MAX_RETRIES} lần (quá {JOB_TIMEOUT_SEC}s không có heartbeat)"
                )
            else:
                job.status = "pending"
                job.error_message = f"Tự trả về hàng chờ lần {job.retry_count} do worker mất tín hiệu"
            reclaimed += 1
    if reclaimed:
        db.flush()
    return reclaimed


def _maybe_trigger_batch_matching(
    db: Session,
    batch_id: Optional[str],
    background_tasks: BackgroundTasks,
) -> bool:
    """Chỉ kích hoạt matching.py nền khi batch đã chốt và mọi job trong batch đều đã done."""
    if not batch_id:
        return False
    batch = db.query(models.Batch).filter(models.Batch.batch_id == batch_id).first()
    if not batch or batch.match_status == "matching":
        return False

    jobs = db.query(models.Job).filter(models.Job.batch_id == batch_id).all()
    if not jobs:
        return False

    all_done = all(j.status == "done" for j in jobs)
    reached_target = batch.is_sealed or (batch.total_jobs > 0 and len(jobs) >= batch.total_jobs)

    if all_done and reached_target:
        batch.is_sealed = True
        batch.match_status = "matching"
        db.commit()
        background_tasks.add_task(run_batch_matching_background, batch_id)
        return True
    return False


# =====================================================================
# 1. QUẢN LÝ CAMERA & BATCH (CHO FRONTEND)
# =====================================================================

@app.get("/api/v1/cameras", tags=["Cameras"])
def list_cameras(db: Session = Depends(get_db)):
    cams = db.query(models.Camera).all()
    return {"status": "success", "total": len(cams), "max_cameras": MAX_CAMERAS, "data": cams}


@app.post("/api/v1/cameras", tags=["Cameras"])
def create_camera(cam: schemas.CameraCreate, db: Session = Depends(get_db)):
    if db.query(models.Camera).filter(models.Camera.cam_id == cam.cam_id).first():
        raise HTTPException(status_code=409, detail=f"Camera {cam.cam_id} đã tồn tại")
    current_count = db.query(models.Camera).count()
    if current_count >= MAX_CAMERAS:
        raise HTTPException(
            status_code=400,
            detail=f"Hệ thống chỉ cho phép tối đa {MAX_CAMERAS} camera.",
        )
    new_cam = models.Camera(**cam.model_dump())
    db.add(new_cam)
    db.commit()
    return {"status": "success", "camera": cam}


@app.post("/api/v1/batches", tags=["Batches & Jobs"])
def create_batch(req: schemas.BatchCreate, db: Session = Depends(get_db)):
    batch_id = _clean_optional_str(req.batch_id) or f"batch_{uuid.uuid4().hex[:8]}"
    if db.query(models.Batch).filter(models.Batch.batch_id == batch_id).first():
        raise HTTPException(status_code=409, detail=f"Batch {batch_id} đã tồn tại")
    batch = models.Batch(
        batch_id=batch_id,
        name=_clean_optional_str(req.name) or batch_id,
        total_jobs=req.total_jobs,
        is_sealed=False,
        match_status="waiting",
    )
    db.add(batch)
    db.commit()
    return {
        "status": "success",
        "batch_id": batch.batch_id,
        "total_jobs": batch.total_jobs,
        "match_status": batch.match_status,
    }


@app.post("/api/v1/batches/{batch_id}/seal", tags=["Batches & Jobs"])
def seal_batch(
    batch_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Frontend gọi sau khi đã upload xong hết các clip của đợt để chốt số lượng và chạy ghép nếu đã đủ."""
    batch = db.query(models.Batch).filter(models.Batch.batch_id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Không tìm thấy batch")
    actual_jobs = db.query(models.Job).filter(models.Job.batch_id == batch_id).count()
    batch.total_jobs = actual_jobs
    batch.is_sealed = True
    db.commit()
    triggered = _maybe_trigger_batch_matching(db, batch_id, background_tasks)
    return {
        "status": "success",
        "batch_id": batch_id,
        "total_jobs": actual_jobs,
        "matching_triggered": triggered,
    }


@app.post("/api/v1/batches/{batch_id}/match", tags=["Batches & Jobs"])
def trigger_batch_match_manually(
    batch_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Cho phép bấm chạy ghép tay (VD: khi 1 cam trong đợt bị failed hẳn và vẫn muốn ghép các cam còn lại)."""
    batch = db.query(models.Batch).filter(models.Batch.batch_id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Không tìm thấy batch")
    batch.match_status = "matching"
    db.commit()
    background_tasks.add_task(run_batch_matching_background, batch_id)
    return {"status": "success", "batch_id": batch_id, "match_status": "matching"}


@app.get("/api/v1/batches/{batch_id}", tags=["Batches & Jobs"])
def get_batch_status(batch_id: str, db: Session = Depends(get_db)):
    reclaim_stale_jobs(db)
    db.commit()
    batch = db.query(models.Batch).filter(models.Batch.batch_id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Không tìm thấy batch")
    jobs = (
        db.query(models.Job)
        .filter(models.Job.batch_id == batch_id)
        .order_by(models.Job.created_at.asc())
        .all()
    )
    return {
        "batch_id": batch.batch_id,
        "name": batch.name,
        "total_jobs": batch.total_jobs,
        "is_sealed": batch.is_sealed,
        "match_status": batch.match_status,
        "match_summary": batch.match_summary,
        "match_error": batch.match_error,
        "jobs": [
            {
                "job_id": j.job_id,
                "video_id": j.video_id,
                "camera_id": j.camera_id,
                "start_time": j.start_time,
                "status": j.status,
                "worker_id": j.worker_id,
                "progress": j.progress,
                "retry_count": j.retry_count,
                "error_message": j.error_message,
            }
            for j in jobs
        ],
    }


# =====================================================================
# 2. UPLOAD VIDEO TỪ WEB (STREAM CHỐNG TRÀN RAM) & TRẠNG THÁI WORKER
# =====================================================================

@app.post("/api/v1/jobs/upload", tags=["Batches & Jobs"])
async def upload_video_job(
    video_file: UploadFile = File(..., description="File video mp4 (~10 phút, tối đa MAX_UPLOAD_MB)"),
    camera_id: str = Form(..., description="Mã camera (VD: CAM_01)"),
    start_time: str = Form(..., description="Giờ bắt đầu quay chuẩn ISO +07:00 (VD: 2026-11-27T08:30:00+07:00)"),
    batch_id: Optional[str] = Form(None, description="Mã đợt quay (bỏ trống sẽ tự tạo batch 1 video)"),
    video_id: Optional[str] = Form(None, description="Mã video tùy chọn"),
    db: Session = Depends(get_db),
):
    reclaim_stale_jobs(db)
    pending_count = (
        db.query(models.Job)
        .filter(models.Job.status.in_(["pending", "processing"]))
        .count()
    )
    if pending_count >= MAX_PENDING_JOBS:
        raise HTTPException(
            status_code=429,
            detail=f"Hàng chờ đang đầy ({pending_count}/{MAX_PENDING_JOBS} clip). Vui lòng đợi AI xử lý bớt.",
        )

    cam_id_clean = camera_id.strip()
    if not db.query(models.Camera).filter(models.Camera.cam_id == cam_id_clean).first():
        if db.query(models.Camera).count() >= MAX_CAMERAS:
            raise HTTPException(status_code=400, detail=f"Đã đạt giới hạn tối đa {MAX_CAMERAS} camera.")
        ensure_camera_exists(db, cam_id_clean)

    # Tạo hoặc kiểm tra batch
    batch_id_clean = _clean_optional_str(batch_id)
    if batch_id_clean:
        batch = db.query(models.Batch).filter(models.Batch.batch_id == batch_id_clean).first()
        if not batch:
            batch = models.Batch(
                batch_id=batch_id_clean,
                name=batch_id_clean,
                total_jobs=1,
                is_sealed=False,
                match_status="waiting",
            )
            db.add(batch)
            db.flush()
    else:
        batch_id_clean = f"batch_{uuid.uuid4().hex[:8]}"
        batch = models.Batch(
            batch_id=batch_id_clean,
            name=batch_id_clean,
            total_jobs=1,
            is_sealed=True,
            match_status="waiting",
        )
        db.add(batch)
        db.flush()

    job_id = f"job_{uuid.uuid4().hex[:10]}"
    vid_id = _clean_optional_str(video_id) or f"vid_{cam_id_clean}_{uuid.uuid4().hex[:6]}"
    ext = Path(video_file.filename or "video.mp4").suffix.lower() or ".mp4"
    save_path = UPLOADS_DIR / f"{job_id}{ext}"

    # Stream ghi từng khối 1MB để không làm tràn RAM VPS
    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    total_written = 0
    try:
        with save_path.open("wb") as out_f:
            while True:
                chunk = await video_file.read(1024 * 1024)
                if not chunk:
                    break
                total_written += len(chunk)
                if total_written > max_bytes:
                    out_f.close()
                    save_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File vượt quá giới hạn {MAX_UPLOAD_MB} MB.",
                    )
                out_f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        save_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Lỗi lưu file video: {e}")

    job = models.Job(
        job_id=job_id,
        batch_id=batch_id_clean,
        video_id=vid_id,
        camera_id=cam_id_clean,
        start_time=start_time.strip(),
        video_path=str(save_path),
        status="pending",
    )
    db.add(job)
    db.commit()

    return {
        "status": "success",
        "job_id": job.job_id,
        "batch_id": job.batch_id,
        "video_id": job.video_id,
        "camera_id": job.camera_id,
        "start_time": job.start_time,
        "job_status": job.status,
        "size_mb": round(total_written / (1024 * 1024), 2),
    }


@app.get("/api/v1/jobs/{job_id}", tags=["Batches & Jobs"])
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    reclaim_stale_jobs(db)
    db.commit()
    job = db.query(models.Job).filter(models.Job.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy job")
    return {
        "job_id": job.job_id,
        "batch_id": job.batch_id,
        "video_id": job.video_id,
        "camera_id": job.camera_id,
        "start_time": job.start_time,
        "status": job.status,
        "worker_id": job.worker_id,
        "progress": job.progress,
        "retry_count": job.retry_count,
        "error_message": job.error_message,
    }


@app.get("/api/v1/worker/status", tags=["Worker Queue"])
def get_worker_status(db: Session = Depends(get_db)):
    """Frontend gọi để biết máy AI của Khiêm đang Online hay Offline."""
    now = now_vn_naive()
    cutoff = now - timedelta(seconds=HEARTBEAT_OFFLINE_SEC)
    workers = db.query(models.WorkerHeartbeat).all()

    active_workers = []
    for w in workers:
        is_online = w.last_seen_at >= cutoff
        active_workers.append(
            {
                "worker_id": w.worker_id,
                "online": is_online,
                "current_job_id": w.current_job_id if is_online else None,
                "progress": w.progress if is_online else None,
                "last_seen_at": to_vn_iso(w.last_seen_at),
            }
        )

    any_online = any(w["online"] for w in active_workers)
    return {
        "online": any_online,
        "offline_threshold_sec": HEARTBEAT_OFFLINE_SEC,
        "workers": active_workers,
    }


# =====================================================================
# 3. BỘ 5 API HÀNG CHỜ CHO WORKER.PY CỦA KHIÊM (ĐỀU CÓ X-API-Key)
# =====================================================================

@app.post("/api/v1/jobs/next", tags=["Worker Queue"], dependencies=[Depends(verify_worker_key)])
def claim_next_job(req: schemas.JobNextRequest, db: Session = Depends(get_db)):
    """Lấy 1 job pending cũ nhất, gắn worker_id và chuyển sang processing. Hết việc trả 204."""
    reclaim_stale_jobs(db)

    job = (
        db.query(models.Job)
        .filter(models.Job.status == "pending")
        .order_by(models.Job.created_at.asc())
        .with_for_update()
        .first()
    )
    if not job:
        _upsert_worker_heartbeat(db, worker_id=req.worker_id, current_job_id=None, progress=None)
        db.commit()
        return Response(status_code=204)

    now = now_vn_naive()
    job.status = "processing"
    job.worker_id = req.worker_id
    job.started_at = now
    job.last_heartbeat_at = now
    job.progress = 0

    _upsert_worker_heartbeat(db, worker_id=req.worker_id, current_job_id=job.job_id, progress=0)
    db.commit()

    return {
        "job_id": job.job_id,
        "video_id": job.video_id,
        "camera_id": job.camera_id,
        "start_time": job.start_time,
        "batch_id": job.batch_id,
        "status": job.status,
        "download_url": f"/api/v1/jobs/{job.job_id}/video",
    }


@app.get("/api/v1/jobs/{job_id}/video", tags=["Worker Queue"], dependencies=[Depends(verify_worker_key)])
def download_job_video(job_id: str, db: Session = Depends(get_db)):
    job = db.query(models.Job).filter(models.Job.job_id == job_id).first()
    if not job or not job.video_path:
        raise HTTPException(status_code=404, detail="Không tìm thấy video của job này")
    path = Path(job.video_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File video đã bị xóa hoặc không tồn tại trên server")
    return FileResponse(path=str(path), filename=path.name, media_type="application/octet-stream")


@app.post("/api/v1/worker/heartbeat", tags=["Worker Queue"], dependencies=[Depends(verify_worker_key)])
def worker_heartbeat(req: schemas.WorkerHeartbeatRequest, db: Session = Depends(get_db)):
    now = now_vn_naive()
    _upsert_worker_heartbeat(
        db,
        worker_id=req.worker_id,
        current_job_id=req.current_job_id,
        progress=req.progress,
    )
    if req.current_job_id:
        job = db.query(models.Job).filter(models.Job.job_id == req.current_job_id).first()
        if job and job.status == "processing" and job.worker_id == req.worker_id:
            job.last_heartbeat_at = now
            if req.progress is not None:
                job.progress = req.progress
    db.commit()
    return {"ok": True, "server_time": to_vn_iso(now)}


@app.post("/api/v1/jobs/{job_id}/fail", tags=["Worker Queue"], dependencies=[Depends(verify_worker_key)])
def fail_job(job_id: str, req: schemas.JobFailRequest, db: Session = Depends(get_db)):
    job = db.query(models.Job).filter(models.Job.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy job")

    if job.status != "processing" or job.worker_id != req.worker_id:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Job không còn ở trạng thái processing của worker '{req.worker_id}' "
                f"(hiện tại: status={job.status}, worker={job.worker_id})."
            ),
        )

    trimmed_log = req.error_log[-10000:] if req.error_log else None
    job.error_message = req.error_message[:500]
    job.error_log = trimmed_log
    job.progress = None

    if req.retryable and (job.retry_count or 0) + 1 < JOB_MAX_RETRIES:
        job.retry_count = (job.retry_count or 0) + 1
        job.status = "pending"
        job.worker_id = None
    else:
        job.status = "failed"

    _upsert_worker_heartbeat(db, worker_id=req.worker_id, current_job_id=None, progress=None)
    db.commit()
    return {"job_id": job.job_id, "status": job.status, "retry_count": job.retry_count}


@app.post("/api/v1/ingest-file", tags=["AI Integration"], dependencies=[Depends(verify_worker_key)])
async def ingest_ai_json_file(
    background_tasks: BackgroundTasks,
    json_file: UploadFile = File(..., description="File JSON v1.0 xuất từ AI Engine"),
    crops_zip: Optional[UploadFile] = File(None, description="File _crops.zip đi kèm"),
    job_id: Optional[str] = Form(None, description="Bắt buộc truyền khi gọi từ worker.py"),
    worker_id: Optional[str] = Form(None, description="Bắt buộc truyền kèm job_id"),
    batch_id: Optional[str] = Form(None, description="Dùng khi nạp tay không qua job_id"),
    cam_id_override: Optional[str] = Form(None, description="Ghi đè mã camera (nếu cần)"),
    skip_stationary: bool = Form(True, description="Bỏ qua xe đứng yên (is_moving=false)"),
    db: Session = Depends(get_db),
):
    job: Optional[models.Job] = None
    clean_job_id = _clean_optional_str(job_id)
    clean_worker_id = _clean_optional_str(worker_id)
    effective_batch_id = _clean_optional_str(batch_id)
    effective_cam_override = _clean_optional_str(cam_id_override)

    if clean_job_id:
        if not clean_worker_id:
            raise HTTPException(status_code=400, detail="Thiếu worker_id khi nộp kết quả cho job_id")

        job = db.query(models.Job).filter(models.Job.job_id == clean_job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Không tìm thấy job_id")

        # 1. Kiểm tra đã done trước -> trả 200 luôn, không nạp lại lần 2 (chống lỗi rớt mạng retry)
        if job.status == "done":
            return {
                "status": "success",
                "already_done": True,
                "job_id": job.job_id,
                "batch_id": job.batch_id,
                "job_status": "done",
            }

        # 2. Kiểm tra đúng quyền sở hữu processing của worker -> sai trả 409 Conflict
        if job.status != "processing" or job.worker_id != clean_worker_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Job không còn ở trạng thái processing của worker '{clean_worker_id}' "
                    f"(hiện tại: status={job.status}, worker={job.worker_id})."
                ),
            )

        effective_batch_id = job.batch_id
        effective_cam_override = effective_cam_override or job.camera_id

    try:
        raw_bytes = await json_file.read()
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"File JSON không hợp lệ: {e}")

    try:
        zip_bytes = await crops_zip.read() if crops_zip is not None else None
        ingest_stats = ingest_ai_v1_payload(
            db=db,
            payload=payload,
            zip_bytes=zip_bytes,
            cam_id_override=effective_cam_override,
            batch_id=effective_batch_id,
            job_id=job.job_id if job else None,
            skip_stationary=skip_stationary,
        )

        video_to_delete: Optional[Path] = None
        if job:
            job.status = "done"
            job.progress = 100
            job.error_message = None
            job.error_log = None
            if job.video_path:
                video_to_delete = Path(job.video_path)
                job.video_path = None
            _upsert_worker_heartbeat(db, worker_id=clean_worker_id, current_job_id=None, progress=None)

        db.commit()

        # Xóa video gốc tạm trên VPS sau khi đã commit DB thành công
        if video_to_delete and video_to_delete.exists():
            video_to_delete.unlink(missing_ok=True)

        # Kiểm tra nếu toàn bộ job trong batch đã done thì chạy nền g310/matching.py
        matching_triggered = _maybe_trigger_batch_matching(db, effective_batch_id, background_tasks)

        return {
            "status": "success",
            "already_done": False,
            "job_id": job.job_id if job else None,
            "batch_id": effective_batch_id,
            "job_status": "done" if job else None,
            "matching_triggered": matching_triggered,
            **ingest_stats,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Lỗi khi nạp dữ liệu AI: {str(e)}")


# =====================================================================
# 4. API DUYỆT ỨNG VIÊN CHƯA CHẮC (HUMAN-IN-THE-LOOP)
# =====================================================================

@app.get("/api/v1/batches/{batch_id}/candidates", tags=["Matching Review"])
def list_match_candidates(
    batch_id: str,
    status: Optional[str] = Query("pending", description="pending | same | different | all"),
    db: Session = Depends(get_db),
):
    q = db.query(models.MatchCandidate).filter(models.MatchCandidate.batch_id == batch_id)
    if status and status != "all":
        q = q.filter(models.MatchCandidate.status == status)
    items = q.order_by(models.MatchCandidate.score.desc()).all()
    return {"status": "success", "total": len(items), "data": items}


@app.post("/api/v1/candidates/{candidate_id}/decide", tags=["Matching Review"])
def decide_candidate(
    candidate_id: int,
    req: schemas.CandidateDecisionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Người dùng xác nhận 1 cặp ứng viên là same hoặc different -> tự chạy ghép lại batch nền."""
    cand = db.query(models.MatchCandidate).filter(models.MatchCandidate.id == candidate_id).first()
    if not cand:
        raise HTTPException(status_code=404, detail="Không tìm thấy cặp ứng viên")

    cand.status = req.decision
    batch = db.query(models.Batch).filter(models.Batch.batch_id == cand.batch_id).first()
    if batch:
        batch.match_status = "matching"
    db.commit()

    background_tasks.add_task(run_batch_matching_background, cand.batch_id)
    return {
        "status": "success",
        "candidate_id": cand.id,
        "decision": cand.status,
        "batch_id": cand.batch_id,
        "rematch_triggered": True,
    }


# =====================================================================
# 5. API TRA CỨU LỘ TRÌNH QUA ĐA CAMERA (SEARCH API)
# =====================================================================

@app.get("/api/v1/events/search", tags=["Search"])
def search_events(
    plate_text: Optional[str] = Query(None, description="Tìm theo biển số"),
    cam_id: Optional[str] = Query(None, description="Lọc theo mã camera"),
    global_id: Optional[str] = Query(None, description="Lọc theo ID chung qua nhiều camera"),
    batch_id: Optional[str] = Query(None, description="Lọc theo đợt quay (batch_id)"),
    vehicle_type: Optional[str] = Query(None, description="Lọc loại xe (car, motorcycle, truck...)"),
    start_time: Optional[datetime] = Query(None, description="Thời gian bắt đầu (YYYY-MM-DDTHH:MM:SS)"),
    end_time: Optional[datetime] = Query(None, description="Thời gian kết thúc (YYYY-MM-DDTHH:MM:SS)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        query = (
            db.query(models.Event, models.Vehicle, models.Camera)
            .outerjoin(models.Vehicle, models.Event.vehicle_id == models.Vehicle.vehicle_id)
            .outerjoin(models.Camera, models.Event.cam_id == models.Camera.cam_id)
        )

        if plate_text:
            query = query.filter(models.Vehicle.plate_text.ilike(f"%{plate_text.strip()}%"))
        if cam_id:
            query = query.filter(models.Event.cam_id == cam_id.strip())
        if global_id:
            query = query.filter(models.Event.global_id == global_id.strip())
        if batch_id:
            query = query.filter(models.Event.batch_id == batch_id.strip())
        if vehicle_type:
            query = query.filter(models.Vehicle.vehicle_type == vehicle_type.strip())
        if start_time:
            query = query.filter(models.Event.timestamp >= start_time)
        if end_time:
            query = query.filter(models.Event.timestamp <= end_time)

        total = query.count()
        results = (
            query.order_by(models.Event.timestamp.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        data = [
            {
                "event_id": event.event_id,
                "batch_id": event.batch_id,
                "global_id": event.global_id,
                "match_method": event.match_method,
                "vehicle_id": event.vehicle_id,
                "plate_text": vehicle.plate_text if vehicle else None,
                "plate_conf": vehicle.plate_conf if vehicle else None,
                "vehicle_type": vehicle.vehicle_type if vehicle else None,
                "color": vehicle.color if vehicle else None,
                "cam_id": event.cam_id,
                "cam_name": camera.cam_name if camera else None,
                "location": camera.location if camera else None,
                "timestamp": to_vn_iso(event.timestamp),
                "t_end": to_vn_iso(event.t_end),
                "entry_edge": event.entry_edge,
                "exit_edge": event.exit_edge,
                "confidence_score": event.confidence_score,
                "image_path": event.image_path,
            }
            for event, vehicle, camera in results
        ]

        return {"status": "success", "total": total, "limit": limit, "offset": offset, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi truy vấn lộ trình: {str(e)}")


# =====================================================================
# 6. LEGACY APIs (GIỮ LẠI ĐỂ TEST RỜI TỪNG EVENT / FEATURE)
# =====================================================================

@app.post("/api/v1/events", tags=["Legacy Ingestion"])
def create_event(event: schemas.EventData, db: Session = Depends(get_db)):
    try:
        ensure_camera_exists(db, event.cam_id)
        db_vehicle = db.query(models.Vehicle).filter(models.Vehicle.vehicle_id == event.vehicle_id).first()
        if not db_vehicle:
            db.add(
                models.Vehicle(
                    vehicle_id=event.vehicle_id,
                    plate_text=event.plate_text,
                    color=event.color,
                    vehicle_type=event.vehicle_type,
                )
            )
            db.flush()
        db.add(models.Event(cam_id=event.cam_id, vehicle_id=event.vehicle_id, timestamp=now_vn_naive()))
        db.commit()
        return {"status": "success", "message": "Đã lưu sự kiện vào Database thành công!"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/features", tags=["Legacy Ingestion"])
def receive_feature(
    data: schemas.FeatureData,
    threshold: float = Query(0.55, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
):
    try:
        ensure_camera_exists(db, data.cam_id)
        db_vehicle = db.query(models.Vehicle).filter(models.Vehicle.vehicle_id == data.vehicle_id).first()
        if not db_vehicle:
            db_vehicle = models.Vehicle(vehicle_id=data.vehicle_id, plate_text=data.plate_text)
            db.add(db_vehicle)
            db.flush()
        elif data.plate_text and not db_vehicle.plate_text:
            db_vehicle.plate_text = data.plate_text

        global_id, score, is_matched, reason = match_or_create_global_id(
            db=db,
            new_vector=data.embedding_data,
            current_cam_id=data.cam_id,
            plate_text=data.plate_text,
            plate_conf=0.95 if data.plate_text else None,
            threshold=threshold,
        )

        db.add(models.FeatureVector(cam_id=data.cam_id, vehicle_id=data.vehicle_id, embedding_data=data.embedding_data))
        updated_rows = (
            db.query(models.Event)
            .filter(models.Event.vehicle_id == data.vehicle_id, models.Event.cam_id == data.cam_id)
            .update({"global_id": global_id, "match_method": reason})
        )
        if updated_rows == 0:
            db.add(
                models.Event(
                    cam_id=data.cam_id,
                    vehicle_id=data.vehicle_id,
                    global_id=global_id,
                    match_method=reason,
                    timestamp=now_vn_naive(),
                )
            )

        db.commit()
        return {
            "status": "success",
            "vehicle_id": data.vehicle_id,
            "cam_id": data.cam_id,
            "global_id": global_id,
            "matched": is_matched,
            "match_reason": reason,
            "similarity_score": score,
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))