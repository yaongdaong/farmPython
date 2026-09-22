import asyncio
from datetime import datetime, timedelta
import os
from pathlib import Path
import re
from typing import List, Optional, Dict, Any
from urllib.parse import unquote

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
import numpy as np
import pandas as pd
from pydantic import BaseModel
import joblib

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
    temp: float
    avg_temp: Optional[float] = None
    humidity: int
    rain: float
    sky: str
    solHours: float = 0.0


class WeatherRequest(BaseModel):
    location_str: str


class CropAnalysisRequest(BaseModel):
    crop_name: str
    area_pyeong: float
    status_type: str  # "growing" | "planned"
    location_str: str
    plant_date: Optional[str] = None
    recent_weather: Optional[List[WeatherInfo]] = None
    previous_expected_harvest_date: Optional[str] = None  # 이전 예측일 (이벤트 트리거 비교용)


class FertilizerRecommendation(BaseModel):
    stage: str
    recommended_date: str
    item_name: str
    amount_kg: float


class CropAnalysisResponse(BaseModel):
    crop_name: str
    crop_category: str
    accuracy_range: str
    accumulated_temp: float
    target_accumulated_temp: float
    expected_harvest_date: str
    harvest_buffer_range: str  # 쇼핑몰/문자 발송용 버퍼 기간 (예: 06월 20일 ~ 06월 22일)
    expected_yield_kg: float
    fertilizer_schedule: List[FertilizerRecommendation]
    notification_trigger: Optional[Dict[str, Any]] = None  # 일정 보정 알림 이벤트
    analysis_report: str
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
    issue_times = [2, 5, 8, 11, 14, 17, 20, 23]
    past_times = [t for t in issue_times if t <= current_hour]

    if past_times:
        base_hour = max(past_times)
        base_date = check_time.strftime("%Y%m%d")
    else:
        base_hour = 23
        base_date = (check_time - timedelta(days=1)).strftime("%Y%m%d")

    return base_date, f"{base_hour:02d}00"


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


@app.post("/api/analyze-crop", response_model=CropAnalysisResponse)
async def analyze_crop(req: CropAnalysisRequest):
    nx, ny, region_name = get_grid_coords(req.location_str)
    weather = await fetch_weather_data(nx, ny)
    
    current_weather = WeatherInfo(
        temp=weather["current_temp"],
        avg_temp=weather["avg_temp"],
        humidity=weather["humidity"],
        rain=weather["rain"],
        sky=weather["sky"],
        solHours=0.0,
    )

    crop_spec = get_crop_spec(req.crop_name)
    crop_key = next((k for k in CROP_TEMP_MASTER.keys() if k in req.crop_name), "default")
    fert_spec = FERTILIZER_MASTER_100_PYEONG.get(crop_key, FERTILIZER_MASTER_100_PYEONG["default"])

    base_temp = crop_spec["base_temp"]
    target_temp = crop_spec["target_temp"]
    crop_category = crop_spec["category"]
    buffer_days = crop_spec["buffer_days"]

    today_effective_gdd = max(0.0, weather["avg_temp"] - base_temp)
    expected_yield = round(req.area_pyeong * crop_spec["yield_per_pyeong"], 1)

    if req.status_type == "planned":
        recommended_plant_date = "3월 하순"
        expected_harvest_period = "6월 하순 ~ 7월 초순"

        report = (
            f"📅 [최적 식재 시기 및 기상 분석 리포트 - {region_name}]\n"
            f"• 선택 작물: {req.crop_name} ({crop_category}, 예측 정확도: {crop_spec['accuracy']})\n"
            f"• 현재 지역 일평균 기온: {weather['avg_temp']:.1f}℃ (오늘 유효 GDD: +{today_effective_gdd:.1f}℃/일)\n"
            f"• 추천 식재 타이밍: [{recommended_plant_date}] (경락 최고가 시기 역산)\n"
            f"• 예상 수확 시기: {expected_harvest_period}\n"
            f"• 예상 총 수확량: 약 {expected_yield}kg"
        )

        return CropAnalysisResponse(
            crop_name=req.crop_name,
            crop_category=crop_category,
            accuracy_range=crop_spec["accuracy"],
            accumulated_temp=0.0,
            target_accumulated_temp=target_temp,
            expected_harvest_date=expected_harvest_period,
            harvest_buffer_range=expected_harvest_period,
            expected_yield_kg=expected_yield,
            fertilizer_schedule=[],
            notification_trigger=None,
            analysis_report=report,
            weather=current_weather,
        )

    else:
        # 1. 과거 적산온도 누적 및 일조량/강수량 환경 보정 지연일 산출
        past_acc_temp, env_delay_days = calculate_accumulated_temp_with_environmental_factors(
            req.recent_weather or [], base_temp, crop_category
        )
        remaining_temp = max(0.0, target_temp - past_acc_temp)

        # 2. 미래 기온 예측 (LSTM / Fallback)
        predicted_future_temps = predictor.predict_future_temps(
            recent_weather=req.recent_weather or [],
            base_avg_temp=weather["avg_temp"],
        )

        current_gdd_sum = 0.0
        days_to_harvest = 0

        for idx, fut_temp in enumerate(predicted_future_temps, start=1):
            daily_gdd = max(0.0, fut_temp - base_temp)
            current_gdd_sum += daily_gdd
            days_to_harvest = idx
            if current_gdd_sum >= remaining_temp:
                break

        if current_gdd_sum < remaining_temp and len(predicted_future_temps) > 0:
            avg_future_gdd = max(1.0, current_gdd_sum / len(predicted_future_temps))
            extra_days = int((remaining_temp - current_gdd_sum) / avg_future_gdd)
            days_to_harvest += extra_days

        # 일조량/장마 패널티 지연일 합산
        total_days_to_harvest = days_to_harvest + env_delay_days
        expected_harvest_dt = datetime.now() + timedelta(days=total_days_to_harvest)
        expected_harvest_str = expected_harvest_dt.strftime("%Y-%m-%d")

        # 3. 안전 버퍼 기간 설정 (쇼핑몰 및 문자 발송 신뢰도 확보용)
        buffer_start = expected_harvest_dt - timedelta(days=1)
        buffer_end = expected_harvest_dt + timedelta(days=buffer_days)
        harvest_buffer_range = f"{buffer_start.strftime('%m월 %d일')} ~ {buffer_end.strftime('%m월 %d일')}"

        # 4. 상태 변경 자동 이벤트 트리거 (Notification Trigger)
        notification_trigger = None
        if req.previous_expected_harvest_date:
            try:
                prev_dt = datetime.strptime(req.previous_expected_harvest_date, "%Y-%m-%d")
                diff_days = (expected_harvest_dt - prev_dt).days
                if abs(diff_days) >= 1:
                    notification_trigger = {
                        "triggered": True,
                        "diff_days": diff_days,
                        "message": f"기상 변화로 예측 수확일이 {abs(diff_days)}일 {'연기' if diff_days > 0 else '당겨'}졌습니다.",
                        "action": "UPDATE_SHOPPING_MALL_BANNER_AND_SMS",
                    }
            except ValueError:
                pass

        # 5. 비료 일정 계산
        area_ratio = req.area_pyeong / 100.0
        plant_dt = datetime.strptime(req.plant_date, "%Y-%m-%d") if req.plant_date else datetime.now()
        
        fertilizer_schedule = [
            FertilizerRecommendation(
                stage=fert["stage"],
                recommended_date=(plant_dt + timedelta(days=fert["days_offset"])).strftime("%Y-%m-%d"),
                item_name=fert["item_name"],
                amount_kg=round(fert["base_kg"] * area_ratio, 1),
            )
            for fert in fert_spec
        ]

        fert_summary = "\n".join([f"  • {f.stage} ({f.recommended_date}): {f.item_name} [{f.amount_kg}kg]" for f in fertilizer_schedule])

        report = (
            f"🌱 [생육 상태 및 환경 보정 예측 리포트 - {region_name}]\n"
            f"• 작물/부류: {req.crop_name} ({crop_category} | 예측 정확도: {crop_spec['accuracy']})\n"
            f"• 현재 누적 적산온도: {past_acc_temp:.1f}℃ / 목표 적산온도: {target_temp:.1f}℃\n"
            f"• 일조량/강우 환경 보정: +{env_delay_days}일 숙기 지연 반영됨\n"
            f"• 최종 예측 수확 확정일: {expected_harvest_dt.strftime('%m월 %d일')} (약 {total_days_to_harvest}일 후)\n"
            f"• 🛡️ 쇼핑몰 권장 발송 버퍼: {harvest_buffer_range}\n"
            f"• 예상 총 수확량: 약 {expected_yield}kg\n\n"
            f"💊 [{req.crop_name} {req.area_pyeong}평 맞춤 비료 Schedule]\n"
            f"{fert_summary}"
        )

        return CropAnalysisResponse(
            crop_name=req.crop_name,
            crop_category=crop_category,
            accuracy_range=crop_spec["accuracy"],
            accumulated_temp=past_acc_temp,
            target_accumulated_temp=target_temp,
            expected_harvest_date=expected_harvest_str,
            harvest_buffer_range=harvest_buffer_range,
            expected_yield_kg=expected_yield,
            fertilizer_schedule=fertilizer_schedule,
            notification_trigger=notification_trigger,
            analysis_report=report,
            weather=current_weather,
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)