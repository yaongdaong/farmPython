from datetime import date, timedelta
from sqlalchemy.orm import Session
import models, schemas
from gdd_calculator import calculate_daily_gdd
from weather_service import fetch_daily_temperature

SERVICE_KEY = "YOUR_KMA_SERVICE_KEY"

def process_user_event_recalculation(
    db: Session, 
    request: schemas.EventRegisterRequest
) -> models.UserCropLog:
    
    # 1. DB에서 재배 기록 조회
    user_log = db.query(models.UserCropLog).filter(
        models.UserCropLog.id == request.user_crop_log_id
    ).first()

    if not user_log:
        raise ValueError("해당 재배 기록을 찾을 수 없습니다.")

    crop = user_log.crop

    # 2. 다음 생육 단계(CropStageGdd) 매핑 및 현재 단계 갱신
    next_stage = db.query(models.CropStageGdd).filter(
        models.CropStageGdd.crop_id == crop.id,
        models.CropStageGdd.stage_name == request.event_type.value
    ).first()

    user_log.last_event_type = request.event_type.value
    user_log.last_event_date = request.event_date
    user_log.current_stage = next_stage
    
    # 3. GDD 리셋 (이벤트 발생일 기준 0.0부터 시작)
    accumulated_gdd = 0.0
    
    # 4. 이벤트 입력일 ~ 오늘(또는 어제)까지 일별 GDD 재계산
    current_date = request.event_date
    today = date.today()
    grid_x, grid_y = 55, 127  # 사용자 농장 좌표

    while current_date < today:
        # 일별 기온 조회 (API 또는 로컬 기상 DB 캐시 조회)
        temps = fetch_daily_temperature(SERVICE_KEY, current_date, grid_x, grid_y)
        
        daily_gdd = calculate_daily_gdd(
            t_max=temps["t_max"],
            t_min=temps["t_min"],
            base_temp=crop.base_temp,
            upper_temp=crop.upper_temp
        )
        accumulated_gdd += daily_gdd
        current_date += timedelta(days=1)

    user_log.accumulated_gdd_since_event = accumulated_gdd

    # 5. 남은 Target GDD 기반 수확 예정일 보정
    if next_stage:
        remaining_gdd = next_stage.target_gdd - accumulated_gdd
        if remaining_gdd > 0:
            estimated_daily_gain = 15.0  # 평년 하루 평균 GDD 가상치
            days_left = int(remaining_gdd // estimated_daily_gain) + 1
            user_log.estimated_harvest_date = today + timedelta(days=days_left)
        else:
            user_log.estimated_harvest_date = today

    db.commit()
    db.refresh(user_log)
    return user_log