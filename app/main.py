from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db import connect_db, disconnect_db
from app.api import farms, crops, logs, solar_term

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버 시작 시 DB 연결
    await connect_db()
    yield
    # 서버 종료 시 DB 연결 해제
    await disconnect_db()

app = FastAPI(
    title="Smart Farm Log API",
    description="24절기와 적산온도 기반 스마트 영농일지 백엔드 API",
    version="1.0.0",
    lifespan=lifespan
)

# Next.js 프론트엔드 연동을 위한 CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://*.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우터 등록
app.include_router(farms.router, prefix="/api/farms", tags=["Farm"])
app.include_router(crops.router, prefix="/api/crops",tags=["Crop"])
app.include_router(logs.router, prefix="/api/logs", tags=["FarmLog"])
app.include_router(solar_term.router, prefix="/api/solar-term", tags=["SolarTerm"])

@app.get("/")
async def root():
    return {"message":"Smart Farm Log API Server is running!"}