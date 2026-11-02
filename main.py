# main.py: FastAPI 서버의 진입점(Entry point)입니다. 앱을 실행하고, CORS를 설정하며, 각 라우터(Router)들을 연결하는 메인 파일입니다.

from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import farm_router, weather_router, analysis_router, sms_router

app = FastAPI(title="Smart Farm Analysis & Harvest Predictor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 각 도메인별 라우터 등록
app.include_router(farm_router.router)
app.include_router(weather_router.router)
app.include_router(analysis_router.router)
app.include_router(sms_router.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)