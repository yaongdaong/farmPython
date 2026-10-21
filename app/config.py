import os
from pathlib import Path
from dotenv import load_dotenv
from urllib.parse import unquote
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "app" / "data" / "weather_history.csv"
MODEL_PATH = BASE_DIR / "app" / "models" / "weather_lstm.pt"
SCALER_SAVE_PATH = BASE_DIR / "app" / "models" / "weather_scaler.joblib"
CSV_PATH = BASE_DIR / "app" / "data" / "kma_coords.csv"

load_dotenv(BASE_DIR / ".env")

RAW_KEY = os.getenv("KMA_API_KEY", "")
SERVICE_KEY = unquote(RAW_KEY)

# 기상청 격자 좌표 CSV 로드
try:
    df_grid = pd.read_csv(CSV_PATH, encoding="euc-kr")
except UnicodeDecodeError:
    try:
        df_grid = pd.read_csv(CSV_PATH, encoding="cp949")
    except Exception:
        df_grid = None
except Exception:
    df_grid = None

# 작물 마스터 데이터
CROP_TEMP_MASTER = {
    "토마토": {"category": "과채류", "base_temp": 10.0, "target_temp": 1100.0, "yield_per_pyeong": 12.0, "accuracy": "90~95%", "buffer_days": 1},
    "딸기": {"category": "과채류", "base_temp": 5.0, "target_temp": 900.0, "yield_per_pyeong": 8.0, "accuracy": "90~95%", "buffer_days": 1},
    "고추": {"category": "과채류", "base_temp": 13.0, "target_temp": 1300.0, "yield_per_pyeong": 4.0, "accuracy": "90~95%", "buffer_days": 1},
    "수박": {"category": "과채류", "base_temp": 12.0, "target_temp": 1000.0, "yield_per_pyeong": 15.0, "accuracy": "90~95%", "buffer_days": 1},
    "사과": {"category": "과수류", "base_temp": 7.0, "target_temp": 1400.0, "yield_per_pyeong": 10.0, "accuracy": "85~90%", "buffer_days": 2},
    "배": {"category": "과수류", "base_temp": 7.5, "target_temp": 1350.0, "yield_per_pyeong": 11.0, "accuracy": "85~90%", "buffer_days": 2},
    "포도": {"category": "과수류", "base_temp": 10.0, "target_temp": 1200.0, "yield_per_pyeong": 7.0, "accuracy": "85~90%", "buffer_days": 2},
    "배추": {"category": "엽채류", "base_temp": 5.0, "target_temp": 750.0, "yield_per_pyeong": 15.0, "accuracy": "80~85%", "buffer_days": 3},
    "상추": {"category": "엽채류", "base_temp": 4.0, "target_temp": 500.0, "yield_per_pyeong": 6.0, "accuracy": "80~85%", "buffer_days": 3},
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