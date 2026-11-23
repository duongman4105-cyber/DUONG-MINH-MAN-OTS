from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
import math


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