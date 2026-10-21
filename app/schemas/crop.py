from pydantic import BaseModel, Field
from typing import List, Optional

class WeatherInfo(BaseModel):
    date: Optional[str] = Field(None, description="날짜 (YYYY-MM-DD)")
    temp: float = Field(..., description="현재 기온")
    avg_temp: Optional[float] = Field(None, description="일평균 기온")
    humidity: int = Field(..., description="습도 (%)")
    rain: float = Field(..., description="강수량 (mm)")
    sky: str = Field(..., description="날씨 상태")
    solHours: float = Field(0.0, description="일조시간 (시간)")

class WeatherRequest(BaseModel):
    location_str: str

class CropAnalysisSchema(BaseModel):
    crop_id: str
    crop_name: str
    plant_date: str
    target_gdd: Optional[float] = 1200.0
    base_temp: Optional[float] = 10.0
    recent_weather: Optional[List[WeatherInfo]] = []

class CropAnalysisRequest(BaseModel):
    crop_name: str = Field(..., description="작물 이름")
    area_pyeong: float = Field(100.0, description="재배 면적 (평)")
    status_type: str = Field("growing", description="재배 상태")
    location_str: Optional[str] = Field("서울", description="지역명")
    target_gdd: float = Field(..., description="목표 적산온도")
    plant_date: str = Field(..., description="정식일/파종일")
    base_temp: float = Field(..., description="생육 하한온도")
    recent_weather: List[WeatherInfo] = Field(default=[], description="과거/최근 기상 기록")
    previous_expected_harvest_date: Optional[str] = Field(None, description="이전 예측 수확일")

class FertilizerScheduleItem(BaseModel):
    stage: str
    recommended_date: str
    item_name: str
    amount_kg: float

class NotificationTrigger(BaseModel):
    triggered: bool
    diff_days: int
    message: str
    action: str

class FertilizerRecommendation(BaseModel):
    stage: str
    recommended_date: str
    item_name: str
    fertilizer_type: str
    amount_kg_per_10a: float
    description: str

class CropAnalysisResponse(BaseModel):
    crop_name: str
    crop_category: str
    accuracy_range: str
    accumulated_gdd: float
    target_accumulated_temp: float
    today_effective_gdd: float
    gdd_progress_percent: float
    estimated_harvest_date: str
    harvest_buffer_range: str
    expected_yield_kg: float
    fertilizer_schedule: List[FertilizerScheduleItem]
    fertilizer_recommendation: Optional[FertilizerRecommendation] = None
    notification_trigger: Optional[NotificationTrigger] = None
    analysis_report: Optional[str] = None
    weather: WeatherInfo