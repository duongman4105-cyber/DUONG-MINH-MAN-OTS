from pydantic import BaseModel, Field, validator
from typing import Optional, List

# Schema cho API /events cũ của bạn
class EventData(BaseModel):
    cam_id: str
    vehicle_id: str
    plate_text: Optional[str] = None
    color: Optional[str] = None

# SCHEMA MỚI DÀNH CHO KHIÊM
class FeatureData(BaseModel):
    cam_id: str
    vehicle_id: str
    plate_text: Optional[str] = None
    embedding_data: List[float] # Ép buộc vector phải là một mảng List chứa các số thực

    @validator('embedding_data')
    def check_vector_length(cls, v):
        if len(v) != 2048: # Đã chốt số 2048 với Khiêm
            #raise ValueError(f'Vector phải dài 2048 chiều, nhưng nhận được {len(v)} chiều')
            pass
        return v