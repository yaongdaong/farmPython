import asyncio
from datetime import datetime, timedelta
import os
from pathlib import Path
import re
from typing import List, Optional, Dict, Any
from urllib.parse import unquote
import math
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
import httpx
import numpy as np
import pandas as pd
from pydantic import BaseModel,Field
import joblib
import logging
from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Crop,Farm, FarmLog, Prediction, Harvest
logger = logging.getLogger(__name__)

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, Dataset
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


# --- 환경 설정 및 경로 ---
BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "app" / "data" / "weather_history.csv"
MODEL_PATH = BASE_DIR / "app" / "models" / "weather_lstm.pt"
SCALER_SAVE_PATH = BASE_DIR / "app" / "models" / "weather_scaler.joblib"
CSV_PATH = BASE_DIR / "app" / "data" / "kma_coords.csv"

load_dotenv(BASE_DIR / ".env")

app = FastAPI(title="Smart Farm Analysis & Harvest Predictor API")

# --- 0. 기상청 격자 좌표 CSV 로드 ---
try:
    df_grid = pd.read_csv(CSV_PATH, encoding="euc-kr")
except UnicodeDecodeError:
    try:
        df_grid = pd.read_csv(CSV_PATH, encoding="cp949")
    except Exception:
        df_grid = None
except Exception:
    df_grid = None


# --- 1. PyTorch 시계열 LSTM 모델 ---
if TORCH_AVAILABLE:
    class WeatherLSTM(nn.Module):
        def __init__(self, input_size=4, hidden_size=64, num_layers=2, output_days=30):
            super(WeatherLSTM, self).__init__()
            self.lstm = nn.LSTM(
                input_size, hidden_size, num_layers, batch_first=True,
                dropout=0.2 if num_layers > 1 else 0.0
            )
            self.fc = nn.Sequential(
                nn.Linear(hidden_size, 32),
                nn.ReLU(),
                nn.Linear(32, output_days)
            )

        def forward(self, x):
            out, _ = self.lstm(x)
            out = self.fc(out[:, -1, :])
            return out


class WeatherPredictorEngine:
    """PyTorch LSTM 기반 향후 30일 일평균 기온 예측 엔진"""
    def __init__(self, model_path: Path):
        self.model_path = model_path
        self.model = None
        self.output_days = 30
        if TORCH_AVAILABLE and self.model_path.exists():
            try:
                self.model = WeatherLSTM(input_size=4, hidden_size=64, output_days=self.output_days)
                self.model.load_state_dict(torch.load(self.model_path, map_location=torch.device("cpu")))
                self.model.eval()
            except Exception as e:
                print(f"⚠️ 모델 로드 실패 (Fallback 엔진으로 동작): {e}")

    def predict_future_temps(self, recent_weather: List["WeatherInfo"], base_avg_temp: float) -> List[float]:
        if TORCH_AVAILABLE and self.model is not None and len(recent_weather) >= 7:
            try:
                feature_matrix = []
                for w in recent_weather[-14:]:
                    t = w.avg_temp if w.avg_temp is not None else w.temp
                    feature_matrix.append([t, float(w.humidity), float(w.rain), float(w.solHours)])

                input_tensor = torch.tensor([feature_matrix], dtype=torch.float32)
                with torch.no_grad():
                    predictions = self.model(input_tensor).squeeze(0).numpy().tolist()
                    return [round(p, 1) for p in predictions]
            except Exception as e:
                print(f"⚠️ LSTM 추론 오류(Fallback 사용): {e}")

        # Fallback 계절성 패턴 예측
        predicted_temps = []
        current_date = datetime.now()
        start_temp = base_avg_temp

        for i in range(1, self.output_days + 1):
            target_dt = current_date + timedelta(days=i)
            m = target_dt.month
            trend = 0.1 if m in [6, 7, 8] else (-0.2 if m in [9, 10, 11] else (-0.05 if m in [12, 1, 2] else 0.15))
            day_temp = start_temp + (i * trend) + np.sin(i / 2) * 0.8
            predicted_temps.append(round(day_temp, 1))

        return predicted_temps


predictor = WeatherPredictorEngine(MODEL_PATH)


# --- 2. Request / Response Pydantic 모델 ---
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

# 2. CropAnalysisSchema 정의 (에러 해결)
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
    status_type: str = Field("growing", description="재배 상태 ('planned': 계획 중, 'growing': 재배 중)")
    location_str: Optional[str] = Field("서울", description="지역명 또는 주소")
    target_gdd: float = Field(..., description="목표 적산온도")
    plant_date: str = Field(..., description="정식일/파종일 (YYYY-MM-DD)")
    base_temp: float = Field(..., description="생육 하한온도 (Base Temperature)")
    recent_weather: List[WeatherInfo] = Field(default=[], description="과거/최근 기상 기록 (FarmLog 연동 데이터)")
    previous_expected_harvest_date: Optional[str] = Field(None, description="이전 예측 수확일 (YYYY-MM-DD)")

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
    accumulated_gdd: float                   # 누적 적산온도 (수정)
    target_accumulated_temp: float
    today_effective_gdd: float
    gdd_progress_percent: float
    estimated_harvest_date: str             # 예상 수확일 (수정)
    harvest_buffer_range: str
    expected_yield_kg: float
    fertilizer_schedule: List[FertilizerScheduleItem]
    fertilizer_recommendation: Optional[FertilizerRecommendation] = None # Optional 추가
    notification_trigger: Optional[NotificationTrigger] = None 
    analysis_report: Optional[str] = None    # 리포트 문자열 추가
    weather: WeatherInfo


# --- 3. 농업 및 작물 마스터 데이터 (도메인 보정 로직 포함) ---
CROP_TEMP_MASTER = {
    # 과채류 (높은 정확도 90~95%)
    "토마토": {"category": "과채류", "base_temp": 10.0, "target_temp": 1100.0, "yield_per_pyeong": 12.0, "accuracy": "90~95%", "buffer_days": 1},
    "딸기": {"category": "과채류", "base_temp": 5.0, "target_temp": 900.0, "yield_per_pyeong": 8.0, "accuracy": "90~95%", "buffer_days": 1},
    "고추": {"category": "과채류", "base_temp": 13.0, "target_temp": 1300.0, "yield_per_pyeong": 4.0, "accuracy": "90~95%", "buffer_days": 1},
    "수박": {"category": "과채류", "base_temp": 12.0, "target_temp": 1000.0, "yield_per_pyeong": 15.0, "accuracy": "90~95%", "buffer_days": 1},
    # 과수류 (보통~높은 정확도 85~90%)
    "사과": {"category": "과수류", "base_temp": 7.0, "target_temp": 1400.0, "yield_per_pyeong": 10.0, "accuracy": "85~90%", "buffer_days": 2},
    "배": {"category": "과수류", "base_temp": 7.5, "target_temp": 1350.0, "yield_per_pyeong": 11.0, "accuracy": "85~90%", "buffer_days": 2},
    "포도": {"category": "과수류", "base_temp": 10.0, "target_temp": 1200.0, "yield_per_pyeong": 7.0, "accuracy": "85~90%", "buffer_days": 2},
    # 엽채류 (보통 정확도 80~85%)
    "배추": {"category": "엽채류", "base_temp": 5.0, "target_temp": 750.0, "yield_per_pyeong": 15.0, "accuracy": "80~85%", "buffer_days": 3},
    "상추": {"category": "엽채류", "base_temp": 4.0, "target_temp": 500.0, "yield_per_pyeong": 6.0, "accuracy": "80~85%", "buffer_days": 3},
    # 기본값
    "default": {"category": "기타", "base_temp": 10.0, "target_temp": 1000.0, "yield_per_pyeong": 8.0, "accuracy": "85%", "buffer_days": 2},
}

FERTILIZER_MASTER_100_PYEONG = {
    "토마토": [
        {"stage": "밑거름 (식재 14일 전)", "days_offset": -14, "item_name": "퇴비/복합비료", "base_kg": 150.0},
        {"stage": "1차 추비 (식재 30일 후)", "days_offset": 30, "item_name": "요소 비료", "base_kg": 5.0},
        {"stage": "2차 추비 (식재 60일 후)", "days_offset": 60, "item_name": "NK 비료", "base_kg": 6.0},
    ],
    "고추": [
        {"stage": "밑거름 (식재 14일 전)", "days_offset": -14, "item_name": "퇴비/석회", "base_kg": 200.0},
        {"stage": "1차 추비 (식재 25일 후)", "days_offset": 25, "item_name": "고추 전용 추비", "base_kg": 4.0},
        {"stage": "2차 추비 (식재 50일 후)", "days_offset": 50, "item_name": "NK 비료", "base_kg": 5.0},
    ],
    "default": [
        {"stage": "밑거름", "days_offset": -14, "item_name": "일반 복합비료", "base_kg": 100.0},
        {"stage": "1차 추비", "days_offset": 30, "item_name": "요소 비료", "base_kg": 4.0},
    ],
}


# --- 4. Helper 함수 ---
def get_crop_spec(crop_name: str) -> Dict[str, Any]:
    if not crop_name:
        return CROP_TEMP_MASTER["default"]
    for key in CROP_TEMP_MASTER.keys():
        if key in crop_name:
            return CROP_TEMP_MASTER[key]
    return CROP_TEMP_MASTER["default"]


def get_grid_coords(location_str: str) -> tuple[int, int, str]:
    default_nx, default_ny, default_name = 60, 127, "지정 지역"
    if not location_str or df_grid is None:
        return default_nx, default_ny, default_name

    tokens = location_str.split()
    sido = tokens[0] if len(tokens) > 0 else ""
    sigg = tokens[1] if len(tokens) > 1 else sido
    dong = tokens[2] if len(tokens) > 2 else ""

    matched = pd.DataFrame()
    if sido and sigg and dong:
        matched = df_grid[df_grid["1단계"].str.contains(sido, na=False) & 
                          df_grid["2단계"].str.contains(sigg, na=False) & 
                          df_grid["3단계"].str.contains(dong, na=False)]
    if matched.empty and sido and sigg:
        matched = df_grid[df_grid["1단계"].str.contains(sido, na=False) & 
                          df_grid["2단계"].str.contains(sigg, na=False)]
    if matched.empty and sido:
        matched = df_grid[df_grid["1단계"].str.contains(sido, na=False)]

    if not matched.empty:
        row = matched.iloc[0]
        return int(row["격자 X"]), int(row["격자 Y"]), (sigg if sigg else sido)

    return default_nx, default_ny, default_name


RAW_KEY = os.getenv("KMA_API_KEY", "")
SERVICE_KEY = unquote(RAW_KEY)


def get_ultrasrt_datetime():
    now = datetime.now()
    if now.minute < 45:
        now = now - timedelta(hours=1)
    return now.strftime("%Y%m%d"), now.strftime("%H") + "00"


def get_vilage_datetime():
    now = datetime.now()
    check_time = now - timedelta(minutes=20)
    current_hour = check_time.hour     

    # 기상청 단기예보 Base_time 목록
    base_times = [2,5,8,11,14,17,20,23]
    past_times = [t for t in base_times if t <= current_hour]   

    if past_times:
        base_hour = max(past_times)
        base_date = check_time.strftime("%Y%m%d")
    else:
        base_hour = 23
        base_date = (check_time - timedelta(days=1)).strftime("%Y%m%d")

    return base_date, f"{base_hour:02d}00"

def calculate_daily_gdd(avg_temp: float, base_temp: float) -> float:
    """유효 적산온도(GDD) 계산"""
    return max(0.0, avg_temp - base_temp)

# 비료 추천 및 분석 로직
def get_fertilizer_recommendation(progress_percent: float) -> FertilizerRecommendation:
    if progress_percent < 25.0:
        return FertilizerRecommendation(
            stage="기비 (초기 생육기)",
            recommended_date="현재",
    item_name="복합비료",
            fertilizer_type="밑거름 (N-P-K 복합비료)",
            amount_kg_per_10a=20.0,
            description="뿌리 자람을 촉진하기 위해 질소와 인산 함량이 높은 비료를 시비하세요."
        )
    elif progress_percent < 60.0:
        return FertilizerRecommendation(
            stage="추비 1차 (영양 생장기)",
            recommended_date="현재",
            item_name="복합비료",
            fertilizer_type="요소 비료 및 칼륨 비료",
            amount_kg_per_10a=10.0,
            description="줄기와 잎의 성장 촉진을 위해 웃거름을 1차 시비하세요."
        )
    elif progress_percent < 85.0:
        return FertilizerRecommendation(
            stage="추비 2차 (생식 생장기)",
            recommended_date="현재",
            item_name="복합비료",
            fertilizer_type="황산가리 및 칼슘 비료",
            amount_kg_per_10a=8.0,
            description="과실 품질 향상 및 세포벽 강화를 위해 칼슘과 가리를 보충하세요."
        )
    else:
        return FertilizerRecommendation(
            stage="수확 준비기",
            recommended_date="현재",
            item_name="복합비료",
            fertilizer_type="시비 중단",
            amount_kg_per_10a=0.0,
            description="수확 전 착색 및 당도 증진을 위해 질소질 비료 시비를 중단하세요."
        )


async def fetch_weather_data(nx: int, ny: int) -> dict:
    DEFAULT_WEATHER = {"current_temp": 25.5, "avg_temp": 22.5, "humidity": 60, "sky": "맑음", "rain": 0.0}
    u_date, u_time = get_ultrasrt_datetime()
    v_date, v_time = get_vilage_datetime()

    u_url = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtFcst"
    v_url = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"

    u_params = {"serviceKey": SERVICE_KEY, "pageNo": "1", "numOfRows": "1000", "dataType": "JSON", "base_date": u_date, "base_time": u_time, "nx": str(nx), "ny": str(ny)}
    v_params = {"serviceKey": SERVICE_KEY, "pageNo": "1", "numOfRows": "1000", "dataType": "JSON", "base_date": v_date, "base_time": v_time, "nx": str(nx), "ny": str(ny)}

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
        try:
            u_res, v_res = await asyncio.gather(
                client.get(u_url, params=u_params),
                client.get(v_url, params=v_params),
                return_exceptions=True,
            )

            if isinstance(u_res, Exception) or isinstance(v_res, Exception) or u_res.status_code != 200 or v_res.status_code != 200:
                return DEFAULT_WEATHER

            u_json, v_json = u_res.json(), v_res.json()
            u_items = u_json.get("response", {}).get("body", {}).get("items", {}).get("item", [])
            v_items = v_json.get("response", {}).get("body", {}).get("items", {}).get("item", [])

            parsed = {"current_temp": None, "humidity": None, "sky": None, "pty": None, "rain": None}

            for item in u_items:
                cat, val = item.get("category"), item.get("fcstValue")
                if cat == "T1H" and parsed["current_temp"] is None: parsed["current_temp"] = float(val)
                elif cat == "REH" and parsed["humidity"] is None: parsed["humidity"] = int(val)
                elif cat == "SKY" and parsed["sky"] is None:
                    sky_code = int(val)
                    parsed["sky"] = "맑음" if sky_code == 1 else ("구름많음" if sky_code == 3 else "흐림")
                elif cat == "PTY" and parsed["pty"] is None: parsed["pty"] = int(val)
                elif cat == "RN1" and parsed["rain"] is None:
                    if val in ["강수없음", "0"]: parsed["rain"] = 0.0
                    else:
                        num_str = re.sub(r"[^0-9.]", "", str(val))
                        parsed["rain"] = float(num_str) if num_str else 0.0

            temp_list = [float(item["fcstValue"]) for item in v_items if item.get("category") == "TMP"]
            avg_temp = (sum(temp_list[:24]) / len(temp_list[:24])) if temp_list else DEFAULT_WEATHER["avg_temp"]

            final_sky = parsed["sky"] or "맑음"
            if parsed["pty"] and parsed["pty"] > 0:
                final_sky = {1: "비", 2: "비/눈", 3: "눈", 4: "소나기", 5: "비", 6: "비/눈", 7: "눈"}.get(parsed["pty"], "비")

            return {
                "current_temp": round(parsed["current_temp"] if parsed["current_temp"] is not None else DEFAULT_WEATHER["current_temp"], 1),
                "avg_temp": round(avg_temp, 1),
                "humidity": parsed["humidity"] if parsed["humidity"] is not None else DEFAULT_WEATHER["humidity"],
                "sky": final_sky,
                "rain": parsed["rain"] if parsed["rain"] is not None else DEFAULT_WEATHER["rain"],
            }
        except Exception as e:
            print(f"❌ 날씨 데이터 파싱 예외: {e}")
            return DEFAULT_WEATHER


# --- 5. 적산온도 및 일조량/강수량 환경 보정 로직 ---
def calculate_accumulated_temp_with_environmental_factors(
    weather_list: List[WeatherInfo], base_temp: float, crop_category: str
) -> tuple[float, int]:
    """
    적산온도를 계산함과 동시에 일조량 부족 및 장마/강수 여부에 따른 '숙기 지연일(delay_days)'을 함께 산출합니다.
    """
    total_gdd = 0.0
    delay_days = 0

    if not weather_list:
        return 0.0, 0

    for w in weather_list:
        target_t = w.avg_temp if w.avg_temp is not None else w.temp
        
        # 1. 유효 적산온도 누적
        if target_t > base_temp:
            total_gdd += (target_t - base_temp)

        # 2. 일조량/강수량 환경 변수 보정
        # 일조시간 4시간 미만 지속 시 숙기 지연 패널티
        if w.solHours > 0 and w.solHours < 4.0:
            if crop_category in ["과수류", "엽채류"]:
                delay_days += 1
        
        # 장마/연속 강우(20mm 이상) 시 과수류 착색 및 당도 지연 고려
        if w.rain >= 20.0 and crop_category == "과수류":
            delay_days += 1

    return round(total_gdd, 1), delay_days


# --- Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- 6. API Endpoints ---
# FastAPI 백엔드 예시 (GET /api/farm-list)
@app.get("/api/farm-list")
async def get_farm_list(db: Session = Depends(get_db)):

    # 각 Farm별 가장 최근 영농일지 1개를 찾기 위한 서브쿼리
    latest_journal = (
        db.query(
            FarmLog.farmId,
            FarmLog.growthStage,
            FarmLog.createdAt
        )
        .order_by(FarmLog.farmId, FarmLog.createdAt.desc())
        .subquery()
    )

    # Farm + 최근 영농일지 생육상태 조회
    farms = (
        db.query(
            Farm,
            latest_journal.c.growthStage
        )
        .outerjoin(
            latest_journal,
            Farm.id == latest_journal.c.farmId
        )
        .all()
    )

    return [
        {
            # Farm 기본정보
            "id": str(farm.id),
            "name": farm.name,
            "address": farm.address,
            "actualArea": farm.actualArea,
            "totalArea": farm.totalArea,

            # 날짜
            "plantDate": (
                farm.plantDate.isoformat()
                if farm.plantDate
                else ""
            ),

            "bloomDate": (
                farm.bloomDate.isoformat()
                if farm.bloomDate
                else None
            ),

            # 상태
            "statusType": farm.statusType,

            # 최근 영농일지의 생육상태가 있으면 사용
            # 없으면 Farm에 저장된 기본 상태 사용
            "growthStatus": (
                growthStage
                if growthStage
                else farm.growthStatus or "영농생장기"
            ),

            # 적산온도 / GDD
            "accumulatedTemp": farm.accumulatedTemp,
            "targetTemp": farm.targetTemp,
            "baseTemp": farm.baseTemp,
            "targetGdd": farm.targetGdd,

            # 시설
            "facilityType": farm.facilityType,

            # aiReport는 여기서 가져오지 않음
            # /api/analyze-crop에서 현재 기준으로 계산
        }
        for farm, growthStage in farms
    ]

@app.post("/api/weather", response_model=WeatherInfo)
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

# 💡 Next.js에서 호출하는 경로(@app.post("/api/crop-analysis"))가 맞는지 확인
@app.post("/api/crop-analysis")
async def analyze_crop(payload: CropAnalysisSchema):
    return {"status": "success", "data": ...}


@app.post("/api/analyze-crop", response_model=CropAnalysisResponse)
async def analyze_crop(req: CropAnalysisRequest):
    try:
        # 1. 위치 기반 실시간 기상 데이터 수집
        nx, ny, region_name = get_grid_coords(req.location_str)
        weather_data = await fetch_weather_data(nx, ny)
        
        current_weather = WeatherInfo(
            date=datetime.now().strftime("%Y-%m-%d"),
            temp=weather_data["current_temp"],
            avg_temp=weather_data["avg_temp"],
            humidity=weather_data["humidity"],
            rain=weather_data["rain"],
            sky=weather_data["sky"],
            solHours=weather_data.get("solHours", 8.0)
        )

        # 2. 작물 마스터 마스터 정보 및 시비 정보 조회
        crop_spec = get_crop_spec(req.crop_name)
        crop_key = next((k for k in CROP_TEMP_MASTER.keys() if k in req.crop_name), "default")
        fert_spec = FERTILIZER_MASTER_100_PYEONG.get(crop_key, FERTILIZER_MASTER_100_PYEONG["default"])

        base_temp = crop_spec["base_temp"]
        target_temp = crop_spec["target_temp"]
        crop_category = crop_spec["category"]
        buffer_days = crop_spec.get("buffer_days", 3)

        # 오늘 유효 GDD 및 예상 수확량 계산
        current_avg_temp = weather_data["avg_temp"]
        today_effective_gdd = max(0.0, current_avg_temp - base_temp)
        expected_yield = round(req.area_pyeong * crop_spec["yield_per_pyeong"], 1)

        # ----------------------------------------------------
        # CASE A: 식재 계획 단계 (status_type == "planned")
        # ----------------------------------------------------
        if req.status_type == "planned":
            recommended_plant_date = "3월 하순"
            expected_harvest_period = "6월 하순 ~ 7월 초순"

            report = (
                f"📅 [최적 식재 시기 및 기상 분석 리포트 - {region_name}]\n"
                f"• 선택 작물: {req.crop_name} ({crop_category}, 예측 정확도: {crop_spec['accuracy']})\n"
                f"• 현재 지역 일평균 기온: {current_avg_temp:.1f}℃ (오늘 유효 GDD: +{today_effective_gdd:.1f}℃/일)\n"
                f"• 추천 식재 타이밍: [{recommended_plant_date}] (경락 최고가 시기 역산)\n"
                f"• 예상 수확 시기: {expected_harvest_period}\n"
                f"• 예상 총 수확량: 약 {expected_yield}kg ({req.area_pyeong}평 기준)"
            )

            return CropAnalysisResponse(
                crop_name=req.crop_name,
                crop_category=crop_category,
                accuracy_range=crop_spec["accuracy"],
                accumulated_gdd=0.0,  # accumulated_temp -> accumulated_gdd 로 변경
                target_accumulated_temp=target_temp,
                today_effective_gdd=round(today_effective_gdd, 2),
                gdd_progress_percent=0.0,
                estimated_harvest_date=expected_harvest_period,  # expected_harvest_date -> estimated_harvest_date 로 변경
                harvest_buffer_range=expected_harvest_period,
                expected_yield_kg=expected_yield,
                fertilizer_schedule=[],
                fertilizer_recommendation=None, # 추가
                notification_trigger=None,
                analysis_report=report,
                weather=current_weather,
            )

        # ----------------------------------------------------
        # CASE B: 실제 재배 중 단계 (status_type == "growing")
        # ----------------------------------------------------
        # B-1. 과거 적산온도 누적 및 일조량/강수량 환경 보정 지연일 산출
        past_acc_temp, env_delay_days = calculate_accumulated_temp_with_environmental_factors(
            req.recent_weather or [], base_temp, crop_category
        )
        remaining_gdd = max(0.0, target_temp - past_acc_temp)
        progress_percent = min(100.0, round((past_acc_temp / target_temp) * 100, 2)) if target_temp > 0 else 0.0

        # B-2. 미래 기온 예측 (LSTM 예측 모델 / Fallback 사용)
        predicted_future_temps = predictor.predict_future_temps(
            recent_weather=req.recent_weather or [],
            base_avg_temp=current_avg_temp,
        )

        current_gdd_sum = 0.0
        days_to_harvest = 0

        for idx, fut_temp in enumerate(predicted_future_temps, start=1):
            daily_gdd = max(0.0, fut_temp - base_temp)
            current_gdd_sum += daily_gdd
            days_to_harvest = idx
            if current_gdd_sum >= remaining_gdd:
                break

        # 예측 기간을 초과하는 경우 평균 GDD로 잔여 일수 추정
        if current_gdd_sum < remaining_gdd and len(predicted_future_temps) > 0:
            avg_future_gdd = max(1.0, current_gdd_sum / len(predicted_future_temps))
            extra_days = math.ceil((remaining_gdd - current_gdd_sum) / avg_future_gdd)
            days_to_harvest += extra_days

        # B-3. 환경 패널티 지연일 합산 및 최종 수확일 계산
        total_days_to_harvest = days_to_harvest + env_delay_days
        expected_harvest_dt = datetime.now() + timedelta(days=total_days_to_harvest)
        expected_harvest_str = expected_harvest_dt.strftime("%Y-%m-%d")

        # B-4. 안전 발송 버퍼 범위 산출
        buffer_start = expected_harvest_dt - timedelta(days=1)
        buffer_end = expected_harvest_dt + timedelta(days=buffer_days)
        harvest_buffer_range = f"{buffer_start.strftime('%m월 %d일')} ~ {buffer_end.strftime('%m월 %d일')}"

        # B-5. 이전 예측 대비 수확일 변동 알림 트리거 설정
        notification_trigger = None
        if req.previous_expected_harvest_date:
            try:
                prev_dt = datetime.strptime(req.previous_expected_harvest_date, "%Y-%m-%d")
                diff_days = (expected_harvest_dt - prev_dt).days
                if abs(diff_days) >= 1:
                    action_str = "연기" if diff_days > 0 else "당겨"
                    notification_trigger = NotificationTrigger(
                        triggered=True,
                        diff_days=diff_days,
                        message=f"기상 변화로 예측 수확일이 {abs(diff_days)}일 {action_str}졌습니다.",
                        action="UPDATE_SHOPPING_MALL_BANNER_AND_SMS"
                    )
            except ValueError:
                logger.warning(f"잘못된 날짜 포맷 전달됨: {req.previous_expected_harvest_date}")

        # B-6. 면적(평) 맞춤 비료 스케줄 계산
        area_ratio = req.area_pyeong / 100.0
        if req.plant_date and req.plant_date != "-":
            plant_dt = datetime.strptime(req.plant_date, "%Y-%m-%d") 
        else:
            plant_dt = datetime.now()
        
        fertilizer_schedule = [
            FertilizerScheduleItem(
                stage=fert["stage"],
                recommended_date=(plant_dt + timedelta(days=fert["days_offset"])).strftime("%Y-%m-%d"),
                item_name=fert["item_name"],
                amount_kg=round(fert["base_kg"] * area_ratio, 1),
            )
            for fert in fert_spec
        ]

        fert_summary = "\n".join([f"  • {f.stage} ({f.recommended_date}): {f.item_name} [{f.amount_kg}kg]" for f in fertilizer_schedule])

        # B-7. 통합 리포트 생성
        report = (
            f"🌱 [생육 상태 및 환경 보정 예측 리포트 - {region_name}]\n"
            f"• 작물/부류: {req.crop_name} ({crop_category} | 예측 정확도: {crop_spec['accuracy']})\n"
            f"• 생육 진행률: {progress_percent}% (누적 GDD: {past_acc_temp:.1f}℃ / 목표: {target_temp:.1f}℃)\n"
            f"• 일조량/강우 환경 보정: +{env_delay_days}일 숙기 지연 반영\n"
            f"• 최종 예측 수확 확정일: {expected_harvest_dt.strftime('%m월 %d일')} (약 {total_days_to_harvest}일 후)\n"
            f"• 🛡️ 쇼핑몰 권장 발송 버퍼: {harvest_buffer_range}\n"
            f"• 예상 총 수확량: 약 {expected_yield}kg ({req.area_pyeong}평 기준)\n\n"
            f"💊 [{req.crop_name} {req.area_pyeong}평 맞춤 비료 Schedule]\n"
            f"{fert_summary}"
        )

        # B-8. 단일 비료 추천 데이터 생성
        current_fert_recommendation = get_fertilizer_recommendation(
            progress_percent
        )

        return CropAnalysisResponse(
            crop_name=req.crop_name,
            crop_category=crop_category,
            accuracy_range=crop_spec["accuracy"],
            accumulated_gdd=round(past_acc_temp, 2),
            target_accumulated_temp=target_temp,
            today_effective_gdd=round(today_effective_gdd, 2),
            gdd_progress_percent=progress_percent,
            estimated_harvest_date=expected_harvest_str,
            harvest_buffer_range=harvest_buffer_range,
            expected_yield_kg=expected_yield,
            fertilizer_schedule=fertilizer_schedule,
            fertilizer_recommendation=current_fert_recommendation, # 이제 변수가 정상적으로 참조됩니다.
            notification_trigger=notification_trigger,
            analysis_report=report,
            weather=current_weather,
        )

    except Exception as e:
        logger.error(f"작물 분석 처리 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"작물 생육 분석 처리 중 내부 오류가 발생했습니다: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)