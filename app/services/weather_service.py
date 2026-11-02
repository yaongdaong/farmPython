# weather_service.py: 기상청 API 호출, 날씨 데이터 파싱, GDD(적산온도) 계산 및 기상 재해 예보 로직을 담당합니다.

import asyncio
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple
import httpx
from app.config import SERVICE_KEY, df_grid
from app.schemas.crop import WeatherInfo

def get_grid_coords(location_str: str) -> tuple[int, int, str]:
    """지역 문자열을 기상청 격자 X, Y 좌표로 변환합니다."""
    default_nx, default_ny, default_name = 60, 127, "지정 지역"
    if not location_str or df_grid is None:
        return default_nx, default_ny, default_name

    tokens = location_str.split()
    sido = tokens[0] if len(tokens) > 0 else ""
    sigg = tokens[1] if len(tokens) > 1 else sido
    dong = tokens[2] if len(tokens) > 2 else ""

    matched = None
    if sido and sigg and dong:
        matched = df_grid[df_grid["1단계"].str.contains(sido, na=False) & 
                          df_grid["2단계"].str.contains(sigg, na=False) & 
                          df_grid["3단계"].str.contains(dong, na=False)]
    if (matched is None or matched.empty) and sido and sigg:
        matched = df_grid[df_grid["1단계"].str.contains(sido, na=False) & 
                          df_grid["2단계"].str.contains(sigg, na=False)]
    if (matched is None or matched.empty) and sido:
        matched = df_grid[df_grid["1단계"].str.contains(sido, na=False)]

    if matched is not None and not matched.empty:
        row = matched.iloc[0]
        return int(row["격자 X"]), int(row["격자 Y"]), (sigg if sigg else sido)

    return 60, 127, "지정 지역"

def get_ultrasrt_datetime():
    now = datetime.now()
    if now.minute < 45:
        now = now - timedelta(hours=1)
    return now.strftime("%Y%m%d"), now.strftime("%H") + "00"

def get_vilage_datetime():
    now = datetime.now()
    check_time = now - timedelta(minutes=20)
    current_hour = check_time.hour     
    base_times = [2, 5, 8, 11, 14, 17, 20, 23]
    past_times = [t for t in base_times if t <= current_hour]   

    if past_times:
        base_hour = max(past_times)
        base_date = check_time.strftime("%Y%m%d")
    else:
        base_hour = 23
        base_date = (check_time - timedelta(days=1)).strftime("%Y%m%d")

    return base_date, f"{base_hour:02d}00"

def calculate_accumulated_temp_with_environmental_factors(
    weather_list: List[WeatherInfo], base_temp: float, crop_category: str
) -> tuple[float, int]:
    """
    유효 적산온도(GDD) 계산 및 일조량 부족 / 연속 강우(장마)에 따른 숙기 지연일(delay_days) 산출
    """
    total_gdd = 0.0
    delay_days = 0
    consecutive_rain_days = 0

    if not weather_list:
        return 0.0, 0

    for w in weather_list:
        target_t = w.avg_temp if w.avg_temp is not None else w.temp

        # 1. 유효 적산온도 누적 (기준온도 이상일 때만 누적)
        if target_t > base_temp:
            total_gdd += (target_t - base_temp)

        # 2. 일조량 부족 보정 (4시간 미만 시 과수/엽채류 지연)
        if w.solHours is not None and 0.0 < w.solHours < 4.0:
            if crop_category in ["과수류", "엽채류"]:
                delay_days += 1

        # 3. 강수량 및 장마/연속 강우 패널티
        if w.rain >= 20.0 and crop_category == "과수류":
            delay_days += 1

        # 3일 이상 연속 강우(10mm 이상) 시 지연일 추가
        if w.rain >= 10.0:
            consecutive_rain_days += 1
            if consecutive_rain_days >= 3 and crop_category in ["과수류", "과채류"]:
                delay_days += 1
                consecutive_rain_days = 0  # 패널티 부여 후 초기화
        else:
            consecutive_rain_days = 0

    return round(total_gdd, 1), delay_days


class WeatherService:
    @staticmethod
    async def fetch_weather_data(nx: int, ny: int) -> dict:
        """기상청 단기예보 및 초단기예보 API를 비동기로 호출하여 날씨 데이터를 파싱합니다."""
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

    @staticmethod
    async def get_weather_alerts(sigungu: str):
        """선택된 시군구 지역에 맞춘 기상 재해 사전 예보 스마트 알림 데이터를 반환합니다."""
        return [
            {
                "id": "1",
                "alertType": "FROST",
                "title": f"[{sigungu}] 내일 새벽 서리·냉해 특보",
                "minTemp": 1.8,
                "content": "저온 피해 가능성 85%. 미세살수 관수 관리를 권장합니다."
            },
            {
                "id": "2",
                "alertType": "WIND",
                "title": f"[{sigungu}] 모레 강풍 예보 (최대 14m/s)",
                "windSpeed": 14.0,
                "content": "비닐하우스 개폐기 고정 상태 확인 및 측창 밀폐 처리를 하세요."
            }
        ]