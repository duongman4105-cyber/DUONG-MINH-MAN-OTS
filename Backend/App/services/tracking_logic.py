import io
import json
import math
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sqlalchemy.orm import Session

import models
from config import CROPS_DIR, MATCH_MAX_GAP_S, MATCH_THR_AUTO, MATCH_THR_CANDIDATE
from database import SessionLocal
from services.matching import Matcher

VN_TZ = timezone(timedelta(hours=7))


def now_vn() -> datetime:
    return datetime.now(VN_TZ)


def now_vn_naive() -> datetime:
    """Giờ hiện tại theo múi giờ +07:00 dạng naive để lưu thống nhất trong MySQL."""
    return datetime.now(VN_TZ).replace(tzinfo=None)


def parse_vn_naive(ts_str: Optional[str]) -> datetime:
    """Chuyển chuỗi ISO (có +07:00 hoặc Z) về datetime naive theo giờ Việt Nam (+07:00)."""
    if not ts_str:
        return now_vn_naive()
    try:
        cleaned = str(ts_str).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is not None:
            dt = dt.astimezone(VN_TZ).replace(tzinfo=None)
        return dt
    except ValueError:
        return now_vn_naive()


def to_vn_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=VN_TZ)
    return dt.isoformat(timespec="milliseconds")


def _parse_embedding(raw: Any) -> Optional[List[float]]:
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return None
    if isinstance(raw, list) and len(raw) == 2048:
        return raw
    return None


def ensure_camera_exists(db: Session, cam_id: str) -> None:
    if not db.query(models.Camera).filter(models.Camera.cam_id == cam_id).first():
        db.add(
            models.Camera(
                cam_id=cam_id,
                cam_name=cam_id,
                location="Chưa cập nhật",
                status="active",
            )
        )
        db.flush()


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if len(vec_a) != len(vec_b):
        return 0.0
    a = np.asarray(vec_a, dtype=np.float32)
    b = np.asarray(vec_b, dtype=np.float32)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def match_or_create_global_id(
    db: Session,
    new_vector: Optional[List[float]],
    current_cam_id: str,
    plate_text: Optional[str] = None,
    plate_conf: Optional[float] = None,
    reference_time: Optional[datetime] = None,
    threshold: float = 0.55,
    min_plate_conf: float = 0.85,
    window_minutes: int = 15,
) -> Tuple[str, float, bool, str]:
    """Dùng cho API lẻ /api/v1/features (có lọc theo cửa sổ thời gian ±15 phút)."""
    ref_ts = reference_time or now_vn_naive()
    t_min = ref_ts - timedelta(minutes=window_minutes)
    t_max = ref_ts + timedelta(minutes=window_minutes)

    if plate_text and plate_conf is not None and plate_conf >= min_plate_conf:
        clean_plate = plate_text.strip().upper()
        matched_plate_event = (
            db.query(models.Event)
            .join(models.Vehicle, models.Event.vehicle_id == models.Vehicle.vehicle_id)
            .filter(
                models.Event.cam_id != current_cam_id,
                models.Event.global_id.isnot(None),
                models.Event.timestamp >= t_min,
                models.Event.timestamp <= t_max,
                models.Vehicle.plate_text == clean_plate,
            )
            .first()
        )
        if matched_plate_event and matched_plate_event.global_id:
            return matched_plate_event.global_id, 1.0, True, "plate_match"

    if new_vector and len(new_vector) == 2048:
        candidates = (
            db.query(models.FeatureVector, models.Event)
            .join(
                models.Event,
                (models.FeatureVector.vehicle_id == models.Event.vehicle_id)
                & (models.FeatureVector.cam_id == models.Event.cam_id),
            )
            .filter(
                models.FeatureVector.cam_id != current_cam_id,
                models.Event.global_id.isnot(None),
                models.Event.timestamp >= t_min,
                models.Event.timestamp <= t_max,
            )
            .all()
        )

        best_score = -1.0
        best_global_id: Optional[str] = None

        for feat, ev in candidates:
            feat_vec = _parse_embedding(feat.embedding_data)
            if feat_vec is None:
                continue
            score = cosine_similarity(new_vector, feat_vec)
            if score > best_score:
                best_score = score
                best_global_id = ev.global_id

        if best_score >= threshold and best_global_id:
            return best_global_id, round(best_score, 4), True, "reid_vector"

        return f"G_{uuid.uuid4().hex[:6].upper()}", round(max(best_score, 0.0), 4), False, "new_vehicle"

    return f"G_{uuid.uuid4().hex[:6].upper()}", 0.0, False, "no_embedding"


def ingest_ai_v1_payload(
    db: Session,
    payload: Dict[str, Any],
    zip_bytes: Optional[bytes] = None,
    cam_id_override: Optional[str] = None,
    batch_id: Optional[str] = None,
    job_id: Optional[str] = None,
    skip_stationary: bool = True,
) -> Dict[str, Any]:
    """
    Chỉ nạp dữ liệu JSON v1.0 + giải nén _crops.zip vào MySQL (KHÔNG nối global_id ngay).
    Bước ghép chéo camera sẽ chạy nền theo cả đợt (batch_id) bằng g310/matching.py.
    """
    clean_override = (
        cam_id_override.strip()
        if cam_id_override and cam_id_override.strip().lower() != "string"
        else None
    )
    video_meta = payload.get("video") or {}
    cam_id = (
        clean_override
        or video_meta.get("camera_id")
        or payload.get("camera_id")
        or payload.get("cam_id")
        or "CAM_UNKNOWN"
    )
    video_id = video_meta.get("video_id")

    ensure_camera_exists(db, cam_id)

    # Giải nén ảnh crop (trong zip đã có thư mục crops/, chỉ lấy basename để tránh crops/crops/)
    extracted_crops = 0
    if zip_bytes:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            for member in zf.namelist():
                if member.lower().endswith(".jpg") and not member.endswith("/"):
                    filename = Path(member).name
                    (CROPS_DIR / filename).write_bytes(zf.read(member))
                    extracted_crops += 1

    tracklets = payload.get("tracklets", [])
    saved_count = 0
    skipped_stationary = 0
    skipped_duplicates = 0

    for t in tracklets:
        is_moving = bool(t.get("is_moving", True))
        if skip_stationary and not is_moving:
            skipped_stationary += 1
            continue

        veh_id = str(t["tracklet_id"])

        # Chống nạp trùng theo cặp (cam_id, vehicle_id)
        exists = (
            db.query(models.Event)
            .filter(models.Event.cam_id == cam_id, models.Event.vehicle_id == veh_id)
            .first()
        )
        if exists:
            skipped_duplicates += 1
            continue

        raw_plate = t.get("plate_text")
        plate_text = str(raw_plate).strip().upper() if raw_plate else None
        plate_conf = t.get("plate_conf")
        color = t.get("color")
        color_conf = t.get("color_conf")
        v_type = t.get("vehicle_type") or "unknown"
        type_conf = t.get("type_conf")

        embeddings = t.get("embeddings") or []
        emb0 = embeddings[0] if embeddings and isinstance(embeddings[0], dict) else None
        vector = emb0.get("vector") if emb0 and len(emb0.get("vector", [])) == 2048 else None
        n_crops = int(emb0.get("n_crops", 0)) if emb0 else 0

        existing_veh = (
            db.query(models.Vehicle).filter(models.Vehicle.vehicle_id == veh_id).first()
        )
        if not existing_veh:
            db.add(
                models.Vehicle(
                    vehicle_id=veh_id,
                    plate_text=plate_text,
                    plate_conf=plate_conf,
                    color=color,
                    color_conf=color_conf,
                    vehicle_type=v_type,
                    type_conf=type_conf,
                )
            )
        else:
            if plate_text:
                existing_veh.plate_text = plate_text
                existing_veh.plate_conf = plate_conf
            if color:
                existing_veh.color = color
                existing_veh.color_conf = color_conf
            if v_type and (not existing_veh.vehicle_type or existing_veh.vehicle_type == "unknown"):
                existing_veh.vehicle_type = v_type
                existing_veh.type_conf = type_conf

        db.flush()

        t_start_dt = parse_vn_naive(t.get("t_start"))
        t_end_dt = parse_vn_naive(t.get("t_end")) if t.get("t_end") else t_start_dt

        crop_rel = t.get("crop_file")
        crop_name = Path(crop_rel).name if crop_rel else None
        image_path = f"static/crops/{crop_name}" if crop_name else None
        conf_score = plate_conf if plate_conf is not None else type_conf

        db.add(
            models.Event(
                batch_id=batch_id,
                job_id=job_id,
                video_id=video_id,
                cam_id=cam_id,
                vehicle_id=veh_id,
                global_id=None,  # Để trống, chờ ghép cả đợt theo batch_id
                timestamp=t_start_dt,
                t_end=t_end_dt,
                entry_edge=t.get("entry_edge"),
                exit_edge=t.get("exit_edge"),
                is_moving=is_moving,
                n_crops=n_crops,
                image_path=image_path,
                confidence_score=conf_score,
            )
        )

        if vector:
            db.add(
                models.FeatureVector(
                    cam_id=cam_id,
                    vehicle_id=veh_id,
                    embedding_data=vector,
                )
            )

        saved_count += 1

    db.flush()
    return {
        "cam_id": cam_id,
        "video_id": video_id,
        "saved_tracklets": saved_count,
        "extracted_crops": extracted_crops,
        "skipped_stationary": skipped_stationary,
        "skipped_duplicates": skipped_duplicates,
    }


def run_batch_matching(
    db: Session,
    batch_id: str,
    cfg_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Chạy thuật toán Matcher (g310/matching.py) cho toàn bộ tracklet thuộc 1 batch_id."""
    batch = db.query(models.Batch).filter(models.Batch.batch_id == batch_id).first()
    if not batch:
        raise ValueError(f"Không tìm thấy batch_id={batch_id}")

    rows = (
        db.query(models.Event, models.Vehicle, models.FeatureVector)
        .outerjoin(models.Vehicle, models.Event.vehicle_id == models.Vehicle.vehicle_id)
        .outerjoin(
            models.FeatureVector,
            (models.Event.vehicle_id == models.FeatureVector.vehicle_id)
            & (models.Event.cam_id == models.FeatureVector.cam_id),
        )
        .filter(models.Event.batch_id == batch_id)
        .all()
    )

    TL: List[Dict[str, Any]] = []
    seen_ids = set()
    event_by_tid: Dict[str, models.Event] = {}

    for ev, veh, feat in rows:
        if ev.vehicle_id in seen_ids:
            continue
        seen_ids.add(ev.vehicle_id)
        event_by_tid[ev.vehicle_id] = ev

        t_start_dt = (ev.timestamp or now_vn_naive()).replace(tzinfo=VN_TZ)
        t_end_dt = (ev.t_end or ev.timestamp or now_vn_naive()).replace(tzinfo=VN_TZ)
        raw_vec = _parse_embedding(feat.embedding_data) if feat else None

        TL.append(
            {
                "tracklet_id": ev.vehicle_id,
                "vehicle_type": (veh.vehicle_type if veh else None) or "unknown",
                "color": veh.color if veh else None,
                "color_conf": veh.color_conf if veh else None,
                "plate_text": veh.plate_text if veh else None,
                "plate_conf": veh.plate_conf if veh else None,
                "entry_edge": ev.entry_edge,
                "exit_edge": ev.exit_edge,
                "crop_file": ev.image_path,
                "is_moving": bool(ev.is_moving),
                "camera_id": ev.cam_id,
                "video_id": ev.video_id,
                "src": None,
                "t_start": t_start_dt.isoformat(timespec="milliseconds"),
                "t_end": t_end_dt.isoformat(timespec="milliseconds"),
                "t0": t_start_dt.timestamp(),
                "t1": t_end_dt.timestamp(),
                "vec": np.asarray(raw_vec, dtype=np.float32) if raw_vec is not None else None,
                "n_crops": int(ev.n_crops or (1 if raw_vec is not None else 0)),
            }
        )

    # Nạp các quyết định người dùng đã duyệt (same / different) trước đó trong batch
    decided_rows = (
        db.query(models.MatchCandidate)
        .filter(
            models.MatchCandidate.batch_id == batch_id,
            models.MatchCandidate.status.in_(["same", "different"]),
        )
        .all()
    )
    decisions = [
        {"tracklet_a": r.tracklet_a, "tracklet_b": r.tracklet_b, "decision": r.status}
        for r in decided_rows
    ]
    decided_pairs = {tuple(sorted([r.tracklet_a, r.tracklet_b])) for r in decided_rows}

    cfg = {
        "thr_auto": MATCH_THR_AUTO,
        "thr_candidate": MATCH_THR_CANDIDATE,
        "max_gap_s": MATCH_MAX_GAP_S,
    }
    if cfg_override:
        cfg.update(cfg_override)

    res = Matcher(cfg).run(TL, decisions=decisions)

    # Ánh xạ method theo từng global_id và gắn tiền tố batch_id để không trùng giữa các đợt
    method_by_gid = {v["global_id"]: v.get("method") for v in res["vehicles"]}
    for tid, raw_gid in res["tracklet_to_global"].items():
        ev = event_by_tid.get(tid)
        if ev:
            ev.global_id = f"{batch_id}_{raw_gid}"
            ev.match_method = method_by_gid.get(raw_gid)

    # Xóa ứng viên pending cũ và lưu danh sách ứng viên pending mới (giữ nguyên các cặp đã duyệt)
    db.query(models.MatchCandidate).filter(
        models.MatchCandidate.batch_id == batch_id,
        models.MatchCandidate.status == "pending",
    ).delete(synchronize_session=False)

    for cd in res["candidates"]:
        pair_key = tuple(sorted([cd["tracklet_a"], cd["tracklet_b"]]))
        if pair_key in decided_pairs:
            continue
        db.add(
            models.MatchCandidate(
                batch_id=batch_id,
                tracklet_a=cd["tracklet_a"],
                tracklet_b=cd["tracklet_b"],
                camera_a=cd["camera_a"],
                camera_b=cd["camera_b"],
                crop_a=cd.get("crop_a"),
                crop_b=cd.get("crop_b"),
                score=float(cd["score"]),
                gap_s=float(cd["gap_s"]),
                kind=cd.get("kind"),
                global_id_a=f"{batch_id}_{cd['global_id_a']}" if cd.get("global_id_a") else None,
                global_id_b=f"{batch_id}_{cd['global_id_b']}" if cd.get("global_id_b") else None,
                status="pending",
            )
        )

    batch.match_status = "done"
    batch.match_summary = res["summary"]
    batch.match_error = None
    db.commit()
    return res["summary"]


def run_batch_matching_background(batch_id: str) -> None:
    """Chạy nền bằng Session riêng (không dùng lại request session để tránh lỗi đóng kết nối)."""
    db = SessionLocal()
    try:
        run_batch_matching(db, batch_id)
    except Exception as e:
        db.rollback()
        batch = db.query(models.Batch).filter(models.Batch.batch_id == batch_id).first()
        if batch:
            batch.match_status = "failed"
            batch.match_error = str(e)[:4000]
            db.commit()
    finally:
        db.close()