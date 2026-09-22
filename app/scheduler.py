# scheduler.py
from datetime import datetime, timedelta
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy.orm import Session
from database import SessionLocal  # SQLAlchemy Session 생성기
from models import UserCropLog
from gdd_calculator import calculate_daily_gdd
from weather_service import fetch_daily_temperature

SERVICE_KEY = "YOUR_KMA_SERVICE_KEY"

def update_daily_gdd_job():
    session: Session = SessionLocal()
    yesterday = datetime.now().date() - timedelta(days=1)
    print(f"[{datetime.now()}] GDD 배치 작업 시작 (대상 일자: {yesterday})")

    try:
        active_logs = session.query(UserCropLog).all()

        for user_log in active_logs:
            crop = user_log.crop
            grid_x, grid_y = 55, 127  # 예시 사용자 좌표

            # 1. 기상청 API에서 어제 기온 조회
            temps = fetch_daily_temperature(SERVICE_KEY, yesterday, grid_x, grid_y)

            # 2. GDD 계산 (하한/상한 온도 반영)
            daily_gdd = calculate_daily_gdd(
                t_max=temps["t_max"],
                t_min=temps["t_min"],
                base_temp=crop.base_temp,
                upper_temp=crop.upper_temp
            )

            # 3. 누적 GDD 가산
            user_log.accumulated_gdd_since_event += daily_gdd

            # 4. 남은 GDD 기반 수확 예정일 보정
            if user_log.current_stage:
                target_gdd = user_log.current_stage.target_gdd
                remaining_gdd = target_gdd - user_log.accumulated_gdd_since_event

                if remaining_gdd > 0:
                    estimated_daily_gain = 15.0  # 평년 일일 average GDD 추정치
                    days_left = int(remaining_gdd // estimated_daily_gain) + 1
                    user_log.estimated_harvest_date = yesterday + timedelta(days=days_left)

            print(f"Log ID {user_log.id}: +{daily_gdd:.1f} GDD 누적 (총 {user_log.accumulated_gdd_since_event:.1f})")

        session.commit()
        print("GDD 배치 작업 성공적으로 완료되었습니다.")

    except Exception as e:
        session.rollback()
        print(f"GDD 배치 작업 중 오류 발생: {e}")
    finally:
        session.close()


if __name__ == "__main__":
    scheduler = BlockingScheduler()
    # 매일 새벽 3시 0분에 실행
    scheduler.add_job(update_daily_gdd_job, 'cron', hour=3, minute=0)
    
    print("GDD 배치 스케줄러가 시작되었습니다.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass