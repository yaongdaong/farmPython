from pydantic import BaseModel, Field
from datetime import date
from typing import Optional
from enum import Enum

class EventType(str, Enum):
    PLANTED = "PLANTED"           # 파종일
    TRANSPLANTED = "TRANSPLANTED" # 모종이식일
    FLOWERED = "FLOWERED"         # 개화일
    FRUITED = "FRUITED"           # 열매 처음 열린 날

class EventRegisterRequest(BaseModel):
    user_crop_log_id: int = Field(..., description="사용자 재배 일지 ID")
    event_type: EventType = Field(..., description="발생한 생육 이벤트 종류")
    event_date: date = Field(..., description="사용자가 입력한 실제 발생 날짜")

class EventRegisterResponse(BaseModel):
    user_crop_log_id: int
    event_type: EventType
    event_date: date
    recalculated_gdd: float = Field(..., description="기준일부터 오늘까지 재계산된 누적 GDD")
    estimated_harvest_date: Optional[date] = Field(None, description="새로 보정된 수확 예정일")
    message: str