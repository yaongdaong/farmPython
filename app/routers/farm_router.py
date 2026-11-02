# farm_router.py: 농장 정보, 경작 면적, 작물 관리 및 비료/수확 예약 DB 연동 API

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.models import Farm, FarmLog, HarvestReservationModel
from app.schemas.crop import FertilizerRequest, HarvestScheduleRequest

router = APIRouter(prefix="/api", tags=["Farm"])

# ==========================================
# 1. 농장 및 영농 정보 조회 API
# ==========================================
@router.get("/farm-list")
async def get_farm_list(db: Session = Depends(get_db)):
    """등록된 농장 목록과 최신 영농 생장 단계를 조인하여 반환합니다."""
    latest_journal = (
        db.query(
            FarmLog.farmId,
            FarmLog.growthStage,
            FarmLog.createdAt
        )
        .order_by(FarmLog.farmId, FarmLog.createdAt.desc())
        .subquery()
    )

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
            "id": str(farm.id),
            "name": farm.name,
            "address": farm.address,
            "actualArea": farm.actualArea,
            "totalArea": farm.totalArea,
            "plantDate": farm.plantDate.isoformat() if farm.plantDate else "",
            "bloomDate": farm.bloomDate.isoformat() if farm.bloomDate else None,
            "statusType": farm.statusType,
            "growthStatus": growthStage if growthStage else farm.growthStatus or "영농생장기",
            "accumulatedTemp": farm.accumulatedTemp,
            "targetTemp": farm.targetTemp,
            "baseTemp": farm.baseTemp,
            "targetGdd": farm.targetGdd,
            "facilityType": farm.facilityType,
        }
        for farm, growthStage in farms
    ]


# ==========================================
# 2. 맞춤 처방 비료·관수 계산 API
# ==========================================
@router.post("/crops/calculator")
async def calculate_fertilizer(payload: FertilizerRequest):
    """경작 면적(평)에 따른 추천 복합비료 투입량과 관수량을 자동 산출합니다."""
    area = payload.area
    
    fertilizer_kg = round((area / 1000) * 24)
    fertilizer_bags = round((area / 1000) * 1.2, 1)
    irrigation_liters = round((area / 1000) * 5000)

    return {
        "success": True,
        "data": {
            "area": area,
            "fertilizerKg": fertilizer_kg,
            "fertilizerBags": fertilizer_bags,
            "irrigationLiters": irrigation_liters,
        }
    }


# ==========================================
# 3. 수확 D-7 예약 및 쇼핑몰 팝업 연동 API (DB 저장 구현 완료)
# ==========================================
@router.post("/harvest/schedule")
async def harvest_schedule(payload: HarvestScheduleRequest, db: Session = Depends(get_db)):
    """수확 D-7 단골 예약 SMS 발송 및 직거래 쇼핑몰 메인 팝업 노출 정보를 DB에 저장합니다."""
    try:
        # 날짜 문자열을 datetime 객체로 변환
        parsed_harvest_date = datetime.strptime(payload.harvestDate, "%Y-%m-%d")

        # DB 모델 객체 생성
        db_reservation = HarvestReservationModel(
            farmId=payload.farmId,
            cropName=payload.cropName,
            harvestDate=parsed_harvest_date,
            expectedKg=payload.expectedKg,
            expectedRevenue=payload.expectedRevenue,
            popupLinked=True,
            smsSent=True
        )

        # 데이터베이스에 저장
        db.add(db_reservation)
        db.commit()
        db.refresh(db_reservation)

        return {
            "success": True,
            "message": "수확 D-7 단골 예약 SMS 발송 및 직거래 쇼핑몰 메인 팝업 노출이 DB에 성공적으로 등록되었습니다.",
            "data": payload.model_dump()
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"수확 예약 저장 중 오류 발생: {str(e)}")