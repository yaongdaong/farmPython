# init_db.py
from database import engine, Base, SessionLocal
from models import Crop, CropStageGdd

# 초기 기본 작물 마스터 데이터 정의
SEED_CROPS = [
    {
        "name": "토마토",
        "base_temp": 10.0,
        "upper_temp": 30.0,
        "stages": [
            {"stage_name": "정식~첫 수확", "target_gdd": 1000.0}
        ]
    },
    {
        "name": "고추",
        "base_temp": 10.0,
        "upper_temp": 32.0,
        "stages": [
            {"stage_name": "정식~첫 수확", "target_gdd": 1200.0}
        ]
    },
    {
        "name": "상추",
        "base_temp": 4.0,
        "upper_temp": 24.0,
        "stages": [
            {"stage_name": "파종~수확", "target_gdd": 600.0}
        ]
    },
    {
        "name": "옥수수",
        "base_temp": 10.0,
        "upper_temp": 30.0,
        "stages": [
            {"stage_name": "파종~수확", "target_gdd": 1400.0}
        ]
    }
]

def init_database():
    print("1. DB 테이블 생성 중...")
    # Base에 정의된 모든 모델을 기반으로 DB 테이블을 생성합니다.
    Base.metadata.create_all(bind=engine)
    print("   -> 테이블 생성 완료.")

    db = SessionLocal()
    try:
        print("2. 초기 시드 데이터 삽입 확인 중...")
        for data in SEED_CROPS:
            # 이미 존재하는 작물인지 확인 (중복 삽입 방지)
            existing_crop = db.query(Crop).filter(Crop.name == data["name"]).first()
            if not existing_crop:
                crop = Crop(
                    name=data["name"],
                    base_temp=data["base_temp"],
                    upper_temp=data["upper_temp"]
                )
                db.add(crop)
                db.flush()  # crop.id를 할당받기 위해 flush

                # 단계별 GDD 데이터 추가
                for stage_info in data["stages"]:
                    stage = CropStageGdd(
                        crop_id=crop.id,
                        stage_name=stage_info["stage_name"],
                        target_gdd=stage_info["target_gdd"]
                    )
                    db.add(stage)
                
                print(f"   [+] '{data['name']}' 작물 데이터 추가 완료")
            else:
                print(f"   [-] '{data['name']}' 이미 존재함 (건너뜀)")

        db.commit()
        print("\n초기 DB 세팅이 완료되었습니다!")

    except Exception as e:
        db.rollback()
        print(f"오류 발생: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    init_database()