import math
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class CameraCreate(BaseModel):
    cam_id: str = Field(..., min_length=1, max_length=64)
    cam_name: str = Field(..., min_length=1, max_length=120)
    location: Optional[str] = "Chưa cập nhật"
    rtsp_url: Optional[str] = None
    status: str = "active"


class BatchCreate(BaseModel):
    batch_id: Optional[str] = None
    name: Optional[str] = None
    total_jobs: int = Field(default=3, ge=1, le=20)


class JobNextRequest(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=100, description="Bắt buộc để định danh máy AI")


class JobFailRequest(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=100)
    error_message: str = Field(..., min_length=1, max_length=500)
    error_log: Optional[str] = None
    retryable: bool = False


class WorkerHeartbeatRequest(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=100)
    current_job_id: Optional[str] = None
    progress: Optional[int] = Field(default=None, ge=0, le=100)


class CandidateDecisionRequest(BaseModel):
    decision: Literal["same", "different"]


class EventData(BaseModel):
    cam_id: str
    vehicle_id: str
    plate_text: Optional[str] = None
    color: Optional[str] = None
    vehicle_type: Optional[str] = None
    global_id: Optional[str] = None
    image_path: Optional[str] = None
    confidence_score: Optional[float] = None


class FeatureData(BaseModel):
    cam_id: str
    vehicle_id: str
    plate_text: Optional[str] = None
    embedding_data: List[float] = Field(..., description="Vector Re-ID 2048 chiều, chuẩn hóa L2")

    @field_validator("embedding_data")
    @classmethod
    def validate_vector_2048(cls, v: List[float]) -> List[float]:
        if len(v) != 2048:
            raise ValueError(f"Vector phải có đúng 2048 chiều, hiện tại nhận {len(v)} chiều.")
        if not all(math.isfinite(x) for x in v):
            raise ValueError("Vector chứa giá trị NaN hoặc Infinity không hợp lệ.")

        norm = math.sqrt(sum(x * x for x in v))
        if abs(norm - 1.0) > 1e-2:
            raise ValueError(f"Vector chưa được chuẩn hóa L2 (norm = {norm:.4f}, yêu cầu ≈ 1.0).")
        return v