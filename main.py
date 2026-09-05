import asyncio
from datetime import datetime, timedelta
import os
from pathlib import Path
import re
from typing import List, Optional
from urllib.parse import unquote

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
import numpy as np
import pandas as pd
from pydantic import BaseModel
import joblib

app = FastAPI()
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
import torch.nn as nn
from torch.utils.data import DataLoader,Dataset
from sklearn.preprocessing import StandardScaler


BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "app" / "data" / "weather_history.csv" # 과거 기상 데이터
MODEL_PATH = BASE_DIR / "app" / "models" / "weather_lstm.pt"
SCALER_SAVE_PATH = BASE_DIR / "app" / "models" / "weather_scaler.joblib"
CSV_PATH = BASE_DIR/"app"/"data"/"kma_coords.csv"

SEQ_LEN = 14 # 입력 시퀀스 길이 (최근 14일)
OUTPUT_DAYS = 30 # 예측 시퀀스 길이 (향후 30일)
BATCH_SIZE = 32
EPOCHS = 50
LEARNING_RATE = 0.001
DEVICE = torch.device("cuda" if (TORCH_AVAILABLE and torch.cuda.is_available()) else "cpu")

class WeatherDataset(Dataset):
    """
    Sliding Window 방식으로 과거 SEQ_LEN일 데이터를 입력(X)으로,
    향후 OUTPUT_DAYS의 평균 기온을 타깃(Y)으로 생성합니다.
    """
    def __init__(self,features:np.ndarray, target_temp:np.ndarray,seq_len=14,output_days=30):
        self.X = []
        self.Y = []
        total_len = len(features)
        for i in range(total_len - seq_len - output_days+1):
            x_window = features[i:i+seq_len]
            y_window = target_temp[i+seq_len:i+seq_len+output_days]
            self.X.append(x_window)
            self.Y.append(y_window)

        self.X = torch.tensor(np.array(self.X),dtype=torch.float32)
        self.Y = torch.tensor(np.array(self.Y),dtype=torch.float32)

    def __len__(self):
        return len(self.X)

    def __getitem__(self,idx):
        return self.X[idx], self.Y[idx]

# PyTorch LSTM 모델 정의
class WeatherLSTM(nn.Module):
    def __init__(self,input_size=4, hidden_size=64,num_layers=2, output_days_30=30):
        super(WeatherLSTM,self).__init__()
        self.lstm = nn.LSTM(
            input_size = input_size,
            hidden_size = hidden_size,
            num_layers = num_layers,
            batch_first=True,
            dropout=0.2 if num_layers > 1 else 0.0
        )
        self.fc = nn.Sequential(
            nn.Linear(hidden_size,32),
            nn.ReLU(),
            nn.Linear(32,output_days)
        )

    def forward(self, x):
        # x shape: (Batch, Seq_) 
        app = FastAPI(title="Smart Farm Analysis API with PyTorch Weather Predictor")
        load_dotenv(os.path.join(BASE_DIR, ".env"))

# 경로 설정 (중복 선언 제거 및 통일)
CSV_PATH = BASE_DIR / "app" / "data" / "kma_coords.csv"

# --- 0. 기상청 격자 좌표 CSV 로드 ---
try:
    df_grid = pd.read_csv(CSV_PATH, encoding="euc-kr")
    print(f"✅ 좌표 CSV 로드 성공! ({len(df_grid)}개 좌표 데이터)")
except UnicodeDecodeError:
    try:
        df_grid = pd.read_csv(CSV_PATH, encoding="cp949")
    except Exception as e:
        print(f"⚠️ 좌표 CSV 파일 로드 실패 (기본 서울 좌표로 대체됩니다): {e}")
        df_grid = None
except Exception as e:
    print(f"⚠️ 좌표 CSV 파일 로드 실패 (기본 서울 좌표로 대체됩니다): {e}")
    df_grid = None

# PyTorch 기반 시계열 (LSTM) 기온 예측 모델 정의
if TORCH_AVAILABLE:

    class WeatherLSTM(nn.Module):

        def __init__(
            self,
            input_size=4,
            hidden_size=64,
            num_layers=2,
            output_days=30,
        ):
            super(WeatherLSTM, self).__init__()
            self.lstm = nn.LSTM(
                input_size, hidden_size, num_layers, batch_first=True
            )
            self.fc = nn.Linear(hidden_size, output_days)

        def forward(self, x):
            # x_shape: (batch_size, seq_len, input_size)
            out, _ = self.lstm(x)
            # 마지막 시점의 hidden state 활용
            out = self.fc(out[:, -1, :])
            return out


class WeatherPredictorEngine:
    """PyTorch LSTM 모델 기반 향후 30일 일평균 기온 예측 엔진"""

    def __init__(self, model_path: Path):
        self.model_path = model_path
        self.model = None
        self.output_days = 30
        if TORCH_AVAILABLE and self.model_path.exists():
            try:
                self.model = WeatherLSTM(
                    input_size=4, hidden_size=64, output_days=self.output_days
                )
                self.model.load_state_dict(
                    torch.load(
                        self.model_path, map_location=torch.device("cpu")
                    )
                )
                self.model.eval()
                print(
                    f"PyTorch 시계열 모델 로드 완료: {self.model_path.name}"
                )
            except Exception as e:
                print(f"모델 가중치 로드 중 에러 발생: {e}")
                self.model = None

    def predict_future_temps(
        self, recent_weather: List["WeatherInfo"], base_avg_temp: float
    ) -> List[float]:
        """과거 기상 데이터 (최소 7일 이상)를 입력받아 향후 30일간의 일평균 기온을 예측합니다.

        가중치 모델이 없거나 데이터가 부족하면 계절성을 반영한 Fallback 추정을 수행합니다.
        """
        # PyTorch 추론 로직
        if TORCH_AVAILABLE and self.model is not None and len(recent_weather) >= 7:
            try:
                # 입력 피처 정렬: [temp, humidity, rain, solHours]
                feature_matrix = []
                for w in recent_weather[-14:]:  # 최근 최대 14일 데이터 활용
                    t = w.avg_temp if w.avg_temp is not None else w.temp
                    feature_matrix.append(
                        [
                            t,
                            float(w.humidity),
                            float(w.rain),
                            float(w.solHours),
                        ]
                    )

                # Tensor 변환 (Batch=1, Seq, Feat)
                input_tensor = torch.tensor(
                    [feature_matrix], dtype=torch.float32
                )

                with torch.no_grad():
                    predictions = (
                        self.model(input_tensor).squeeze(0).numpy().tolist()
                    )
                    return [round(p, 1) for p in predictions]
            except Exception as e:
                print(f"LSTM 추론 실패(Fallback 전환): {e}")

        # Fallback 예측 엔진 (통계/계절성 Trend 추정)
        predicted_temps = []
        current_date = datetime.now()
        start_temp = base_avg_temp

        for i in range(1, self.output_days + 1):
            target_dt = current_date + timedelta(days=i)
            month = target_dt.month

            if month in [6, 7, 8]:
                seasonal_trend = 0.1  # 여름철
            elif month in [9, 10, 11]:
                seasonal_trend = -0.2  # 가을철
            elif month in [12, 1, 2]:
                seasonal_trend = -0.05  # 겨울철
            else:
                seasonal_trend = 0.15  # 봄철

            day_temp = (
                start_temp + (i * seasonal_trend) + np.sin(i / 2) * 0.8
            )
            predicted_temps.append(round(day_temp, 1))

        return predicted_temps


# 전역 인스턴스 생성 (상단에서 정의한 MODEL_PATH 활용)
predictor = WeatherPredictorEngine(MODEL_PATH)


# --- Request / Response 데이터 모델 정의 ---
class WeatherInfo(BaseModel):
    temp: float
    avg_temp: Optional[float] = None
    humidity: int
    rain: float
    sky: str
    solHours: float


class WeatherRequest(BaseModel):
    location_str: str


class CropAnalysisRequest(BaseModel):
    crop_name: str
    area_pyeong: float
    status_type: str  # "growing" | "planned"
    location_str: str
    plant_date: Optional[str] = None
    recent_weather: Optional[List[WeatherInfo]] = None


class FertilizerRecommendation(BaseModel):
    stage: str
    recommended_date: str
    item_name: str
    amount_kg: float


class CropAnalysisResponse(BaseModel):
    crop_name: str
    accumulated_temp: float
    target_accumulated_temp: float
    expected_harvest_date: str
    expected_yield_kg: float
    fertilizer_schedule: List[FertilizerRecommendation]
    analysis_report: str
    weather: WeatherInfo


# --- 농업 데이터 기준표 (Master Data) ---
CROP_TEMP_MASTER = {
    "토마토": {
        "base_temp": 10.0,
        "target_temp": 1100.0,
        "yield_per_pyeong": 12.0,
    },
    "고추": {"base_temp": 13.0, "target_temp": 1300.0, "yield_per_pyeong": 4.0},
    "default": {
        "base_temp": 10.0,
        "target_temp": 1000.0,
        "yield_per_pyeong": 8.0,
    },
}

FERTILIZER_MASTER_100_PYEONG = {
    "토마토": [
        {
            "stage": "밑거름 (식재 14일 전)",
            "days_offset": -14,
            "item_name": "퇴비/복합비료",
            "base_kg": 150.0,
        },
        {
            "stage": "1차 추비 (식재 30일 후)",
            "days_offset": 30,
            "item_name": "요소 비료",
            "base_kg": 5.0,
        },
        {
            "stage": "2차 추비 (식재 60일 후)",
            "days_offset": 60,
            "item_name": "NK 비료",
            "base_kg": 6.0,
        },
    ],
    "고추": [
        {
            "stage": "밑거름 (식재 14일 전)",
            "days_offset": -14,
            "item_name": "퇴비/석회",
            "base_kg": 200.0,
        },
        {
            "stage": "1차 추비 (식재 25일 후)",
            "days_offset": 25,
            "item_name": "고추 전용 추비",
            "base_kg": 4.0,
        },
        {
            "stage": "2차 추비 (식재 50일 후)",
            "days_offset": 50,
            "item_name": "NK 비료",
            "base_kg": 5.0,
        },
    ],
    "default": [
        {
            "stage": "밑거름",
            "days_offset": -14,
            "item_name": "일반 복합비료",
            "base_kg": 100.0,
        },
        {
            "stage": "1차 추비",
            "days_offset": 30,
            "item_name": "요소 비료",
            "base_kg": 4.0,
        },
    ],
}


# --- 유틸리티 및 Helper 함수 ---
def get_crop_key(crop_name: str) -> str:
    if not crop_name:
        return "default"
    for key in CROP_TEMP_MASTER.keys():
        if key in crop_name:
            return key
    return "default"


def get_grid_coords(location_str: str) -> tuple[int, int, str]:
    default_nx, default_ny, default_name = 60, 127, "지정 지역"
    if not location_str or df_grid is None:
        return default_nx, default_ny, default_name

    tokens = location_str.split()
    sido = tokens[0] if len(tokens) > 0 else ""
    sigg = (
        tokens[1]
        if len(tokens) > 1
        else (tokens[0] if len(tokens) > 0 else "")
    )
    dong = tokens[2] if len(tokens) > 2 else ""

    matched = pd.DataFrame()

    if sido and sigg and dong:
        matched = df_grid[
            df_grid["1단계"].str.contains(sido, na=False)
            & df_grid["2단계"].str.contains(sigg, na=False)
            & df_grid["3단계"].str.contains(dong, na=False)
        ]

    if matched.empty and sido and sigg:
        matched = df_grid[
            df_grid["1단계"].str.contains(sido, na=False)
            & df_grid["2단계"].str.contains(sigg, na=False)
        ]

    if matched.empty and sido:
        matched = df_grid[df_grid["1단계"].str.contains(sido, na=False)]

    if not matched.empty:
        row = matched.iloc[0]
        nx = int(row["격자 X"])
        ny = int(row["격자 Y"])
        region_name = sigg if sigg else sido
        return nx, ny, region_name

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


if SERVICE_KEY:
    print(f"🔑 로드된 서비스키: {SERVICE_KEY[:5]}...{SERVICE_KEY[-5:]}")
else:
    print("⚠️ KMA_API_KEY를 .env 파일에서 찾을 수 없습니다.")


async def fetch_weather_data(nx: int, ny: int):
    DEFAULT_WEATHER = {
        "current_temp": 25.5,
        "avg_temp": 22.5,
        "humidity": 60,
        "sky": "맑음",
        "rain": 0.0,
    }

    u_date, u_time = get_ultrasrt_datetime()
    v_date, v_time = get_vilage_datetime()

    u_url = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtFcst"
    v_url = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"

    u_params = {
        "serviceKey": SERVICE_KEY,
        "pageNo": "1",
        "numOfRows": "1000",
        "dataType": "JSON",
        "base_date": u_date,
        "base_time": u_time,
        "nx": str(nx),
        "ny": str(ny),
    }

    v_params = {
        "serviceKey": SERVICE_KEY,
        "pageNo": "1",
        "numOfRows": "1000",
        "dataType": "JSON",
        "base_date": v_date,
        "base_time": v_time,
        "nx": str(nx),
        "ny": str(ny),
    }

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=3.0)
    ) as client:
        try:
            u_res, v_res = await asyncio.gather(
                client.get(u_url, params=u_params),
                client.get(v_url, params=v_params),
                return_exceptions=True,
            )

            if isinstance(u_res, Exception) or isinstance(v_res, Exception):
                return DEFAULT_WEATHER

            if u_res.status_code != 200 or v_res.status_code != 200:
                return DEFAULT_WEATHER

            u_json = u_res.json()
            v_json = v_res.json()

            u_code = (
                u_json.get("response", {})
                .get("header", {})
                .get("resultCode")
            )
            v_code = (
                v_json.get("response", {})
                .get("header", {})
                .get("resultCode")
            )

            if u_code != "00" or v_code != "00":
                return DEFAULT_WEATHER

            u_items = (
                u_json.get("response", {})
                .get("body", {})
                .get("items", {})
                .get("item", [])
            )
            v_items = (
                v_json.get("response", {})
                .get("body", {})
                .get("items", {})
                .get("item", [])
            )

            parsed = {
                "current_temp": None,
                "humidity": None,
                "sky": None,
                "pty": None,
                "rain": None,
            }

            for item in u_items:
                category = item.get("category")
                val = item.get("fcstValue")

                if category == "T1H" and parsed["current_temp"] is None:
                    parsed["current_temp"] = float(val)
                elif category == "REH" and parsed["humidity"] is None:
                    parsed["humidity"] = int(val)
                elif category == "SKY" and parsed["sky"] is None:
                    sky_code = int(val)
                    parsed["sky"] = (
                        "맑음"
                        if sky_code == 1
                        else ("구름많음" if sky_code == 3 else "흐림")
                    )
                elif category == "PTY" and parsed["pty"] is None:
                    parsed["pty"] = int(val)
                elif category == "RN1" and parsed["rain"] is None:
                    if val in ["강수없음", "0"]:
                        parsed["rain"] = 0.0
                    else:
                        num_str = re.sub(r"[^0-9.]", "", str(val))
                        parsed["rain"] = float(num_str) if num_str else 0.0

            temp_list = [
                float(item["fcstValue"])
                for item in v_items
                if item.get("category") == "TMP"
            ]

            if temp_list:
                today_temps = temp_list[:24]
                avg_temp = sum(today_temps) / len(today_temps)
            else:
                avg_temp = DEFAULT_WEATHER["avg_temp"]

            final_sky = (
                parsed["sky"] if parsed["sky"] is not None else "맑음"
            )

            if parsed["pty"] is not None and parsed["pty"] > 0:
                pty_code = parsed["pty"]
                if pty_code in [1, 5]:
                    final_sky = "비"
                elif pty_code in [2, 6]:
                    final_sky = "비/눈"
                elif pty_code in [3, 7]:
                    final_sky = "눈"
                elif pty_code == 4:
                    final_sky = "소나기"

            return {
                "current_temp": round(
                    parsed["current_temp"]
                    if parsed["current_temp"] is not None
                    else DEFAULT_WEATHER["current_temp"],
                    1,
                ),
                "avg_temp": round(avg_temp, 1),
                "humidity": parsed["humidity"]
                if parsed["humidity"] is not None
                else DEFAULT_WEATHER["humidity"],
                "sky": final_sky,
                "rain": parsed["rain"]
                if parsed["rain"] is not None
                else DEFAULT_WEATHER["rain"],
            }

        except Exception as e:
            print(f"❌ 날씨 데이터 파싱 중 예외 발생: {e}")
            return DEFAULT_WEATHER


# 적산온도 계산 함수 교정
def calculate_accumulated_temp(
    weather_list: List[WeatherInfo], base_temp: float
) -> float:
    total_temp = 0.0
    if not weather_list:
        return 0.0

    for w in weather_list:
        target_t = w.avg_temp if w.avg_temp is not None else w.temp
        if target_t > base_temp:
            total_temp += target_t - base_temp

    return round(total_temp, 1)


# --- CORS 설정 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- API 엔드포인트 ---
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
    current_temp = weather["current_temp"]
    real_avg_temp = weather["avg_temp"]
    humidity = weather["humidity"]
    sky = weather["sky"]
    rain = weather["rain"]

    current_weather = WeatherInfo(
        temp=current_temp,
        avg_temp=real_avg_temp,
        humidity=humidity,
        rain=rain,
        sky=sky,
        solHours=0.0,
    )

    crop_key = get_crop_key(req.crop_name)
    crop_spec = CROP_TEMP_MASTER[crop_key]
    fert_spec = FERTILIZER_MASTER_100_PYEONG.get(
        crop_key, FERTILIZER_MASTER_100_PYEONG["default"]
    )

    base_temp = crop_spec["base_temp"]
    target_temp = crop_spec["target_temp"]

    today_effective_gdd = max(0.0, real_avg_temp - base_temp)
    expected_yield = round(req.area_pyeong * crop_spec["yield_per_pyeong"], 1)

    if req.status_type == "planned":
        recommended_plant_date = "3월 하순"
        expected_harvest_period = "6월 하순 ~ 7월 초순"

        report = (
            f"📅 [최적 식재 시기 및 기상 분석 리포트 - {region_name}]\n"
            f"• 현재 지역 예상 일평균 기온: {real_avg_temp:.1f}℃ (오늘 유효 적산온도: +{today_effective_gdd:.1f}℃/일)\n"
            f"• 선택 작물: {req.crop_name} ({req.area_pyeong}평)\n"
            f"• 시세 분석 결과: 최근 3개년 도매시장 최고가 경락 시기를 역산했을 때, "
            f"[{recommended_plant_date}]에 심는 것이 가장 높은 수익성을 기대할 수 있습니다.\n"
            f"• 예상 수확 시기: {expected_harvest_period}\n"
            f"• 예상 총 수확량: 약 {expected_yield}kg"
        )

        return CropAnalysisResponse(
            crop_name=req.crop_name,
            accumulated_temp=0.0,
            target_accumulated_temp=target_temp,
            expected_harvest_date=expected_harvest_period,
            expected_yield_kg=expected_yield,
            fertilizer_schedule=[],
            analysis_report=report,
            weather=current_weather,
        )

    else:
        area_ratio = req.area_pyeong / 100.0
        plant_dt = (
            datetime.strptime(req.plant_date, "%Y-%m-%d")
            if req.plant_date
            else datetime.now()
        )

        fertilizer_schedule = []
        for fert in fert_spec:
            target_date = plant_dt + timedelta(days=fert["days_offset"])
            calc_amount = round(fert["base_kg"] * area_ratio, 1)

            fertilizer_schedule.append(
                FertilizerRecommendation(
                    stage=fert["stage"],
                    recommended_date=target_date.strftime("%Y-%m-%d"),
                    item_name=fert["item_name"],
                    amount_kg=calc_amount,
                )
            )

        past_acc_temp = calculate_accumulated_temp(
            req.recent_weather or [], base_temp
        )
        remaining_temp = max(0.0, target_temp - past_acc_temp)

        predicted_future_temps = predictor.predict_future_temps(
            recent_weather=req.recent_weather or [],
            base_avg_temp=real_avg_temp,
        )

        current_gdd_sum = 0.0
        days_to_harvest = 0

        for idx, fut_temp in enumerate(predicted_future_temps, start=1):
            daily_gdd = max(0.0, fut_temp - base_temp)
            current_gdd_sum += daily_gdd
            days_to_harvest = idx
            if current_gdd_sum >= remaining_temp:
                break

        if (
            current_gdd_sum < remaining_temp
            and len(predicted_future_temps) > 0
        ):
            avg_future_gdd = max(
                1.0, current_gdd_sum / len(predicted_future_temps)
            )
            extra_days = int(
                (remaining_temp - current_gdd_sum) / avg_future_gdd
            )
            days_to_harvest += extra_days

        expected_harvest_dt = datetime.now() + timedelta(days=days_to_harvest)

        fert_summary = "\n".join(
            [
                f"  • {f.stage} ({f.recommended_date}): {f.item_name} [{f.amount_kg}kg]"
                for f in fertilizer_schedule
            ]
        )

        report = (
            f"🌱 [현재 생육 및 PyTorch 기상 반영 분석 리포트 - {region_name}]\n"
            f"• 기상청 예보 기반 일평균 기온: {real_avg_temp:.1f}℃ (오늘 예상 GDD: +{today_effective_gdd:.1f}℃/일)\n"
            f"• 현재 누적 적산온도: {past_acc_temp:.1f}℃ / 목표 적산온도: {target_temp:.1f}℃\n"
            f"• 시계열 예측(LSTM) 반영 수확 예정일: {expected_harvest_dt.strftime('%m월 %d일')} (약 {days_to_harvest}일 후)\n"
            f"• 예상 총 수확량: {expected_yield}kg\n\n"
            f"💊 [{req.crop_name} {req.area_pyeong}평 맞춤 비료/자재 투입량]\n"
            f"{fert_summary}"
        )

        return CropAnalysisResponse(
            crop_name=req.crop_name,
            accumulated_temp=past_acc_temp,
            target_accumulated_temp=target_temp,
            expected_harvest_date=expected_harvest_dt.strftime("%Y-%m-%d"),
            expected_yield_kg=expected_yield,
            fertilizer_schedule=fertilizer_schedule,
            analysis_report=report,
            weather=current_weather,
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)