# weather_router.py: 기상청 날씨 및 기상 재해 예보 데이터를 조회하는 라우터입니다.

from fastapi import APIRouter
from app.schemas.crop import WeatherRequest, WeatherInfo
from app.services.weather_service import get_grid_coords, fetch_weather_data

router = APIRouter(prefix="/api", tags=["Weather"])

@router.post("/weather", response_model=WeatherInfo)
async def get_current_weather(req: WeatherRequest):
    nx, ny, _ = get_grid_coords(req.location_str)
    realtime = await fetch_weather_data(nx, ny)
    return WeatherInfo(
        temp=realtime["current_temp"],
        avg_temp=realtime["avg_temp"],
        humidity=realtime["humidity"],
        rain=realtime["rain"],
        sky=realtime["sky"],
        solHours=0.0,
    )