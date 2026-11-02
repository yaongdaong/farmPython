# sms_router.py: 수확 알림 SMS 발송 및 기상 재해 알림톡 구독 DB 연동 처리를 담당하는 라우터입니다.

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

from app.database import get_db
from app.models import NotificationSubscriptionModel
from app.schemas.crop import NotificationRequest
from app.services.sms_service import send_harvest_notice_sms

router = APIRouter(tags=["SMS & Notifications"])

# ==========================================
# 1. 기상 재해 알림톡 구독 관리 API (DB 연동 완료)
# ==========================================
@router.post("/api/notifications/subscribe")
async def subscribe_notification(payload: NotificationRequest, db: Session = Depends(get_db)):
    """
    특정 지역(시군구)의 기상 재해 사전 예보 알림톡 수신을 위해 전화번호를 DB에 저장합니다.
    """
    try:
        # 동일한 번호와 지역으로 이미 등록된 내역이 있는지 확인
        existing = db.query(NotificationSubscriptionModel).filter(
            NotificationSubscriptionModel.phoneNumber == payload.phoneNumber,
            NotificationSubscriptionModel.sigungu == payload.sigungu
        ).first()

        if existing:
            existing.isSubscribed = True
            db.commit()
            db.refresh(existing)
            return {
                "success": True,
                "message": f"[{payload.sigungu}] 번호 {payload.phoneNumber} 재해 알림톡 구독 정보가 갱신되었습니다.",
                "data": {
                    "id": existing.id,
                    "phoneNumber": existing.phoneNumber,
                    "sigungu": existing.sigungu,
                    "isSubscribed": existing.isSubscribed
                }
            }

        # 새로운 구독 정보 DB 객체 생성
        db_subscription = NotificationSubscriptionModel(
            phoneNumber=payload.phoneNumber,
            sigungu=payload.sigungu,
            isSubscribed=True
        )

        # 데이터베이스에 저장
        db.add(db_subscription)
        db.commit()
        db.refresh(db_subscription)

        return {
            "success": True,
            "message": f"[{payload.sigungu}] 번호 {payload.phoneNumber} 재해 알림톡 서비스가 성공적으로 등록되었습니다.",
            "data": {
                "id": db_subscription.id,
                "phoneNumber": db_subscription.phoneNumber,
                "sigungu": db_subscription.sigungu,
                "isSubscribed": db_subscription.isSubscribed
            }
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"알림톡 구독 DB 저장 중 오류 발생: {str(e)}"
        )


# ==========================================
# 2. 수확 D-7 알림 및 SMS 발송 관련 스키마 및 라우터
# ==========================================
class CustomerInfo(BaseModel):
    id: int
    name: str
    phone: str
    order_status: str  # 예: "사전예약 완료", "알림 신청"

class BulkSMSRequest(BaseModel):
    crop_name: str
    expected_harvest_date: str
    expected_yield_kg: float
    d_day: int
    customers: List[CustomerInfo]

class SMSNoticeRequest(BaseModel):
    receiver_phone: str = Field(..., description="수신인 전화번호 (예: 01012345678)")
    crop_name: str = Field(..., description="작물명")
    expected_harvest_date: str = Field(..., description="예상 수확일 (YYYY-MM-DD)")
    expected_yield_kg: float = Field(..., description="예상 수확량")
    d_day: int = Field(7, description="수확 D-day (기본 7일 전)")


@router.get("/api/sms/customers/pre-order-target")
async def get_pre_order_customers(crop_name: Optional[str] = None):
    """
    쇼핑몰 DB에서 수확 알림 수신 동의 및 사전예약 신청 고객 리스트를 조회합니다.
    """
    mock_customers = [
        {"id": 1, "name": "김철수", "phone": "01012345678", "order_status": "사전예약 완료"},
        {"id": 2, "name": "이영희", "phone": "01098765432", "order_status": "알림 신청"},
        {"id": 3, "name": "박민수", "phone": "01055556666", "order_status": "알림 신청"},
    ]
    return {
        "status": "success",
        "crop_name": crop_name or "전체",
        "total_count": len(mock_customers),
        "customers": mock_customers
    }


@router.post("/api/sms/send-bulk-harvest-notice")
async def send_bulk_harvest_sms(req: BulkSMSRequest):
    """
    선택된 쇼핑몰 고객들에게 수확 사전 알림 문자(D-Day / D-7 등)를 일괄 전송합니다.
    """
    results = []
    success_count = 0
    fail_count = 0

    for customer in req.customers:
        res = send_harvest_notice_sms(
            receiver_phone=customer.phone,
            crop_name=req.crop_name,
            expected_harvest_date=req.expected_harvest_date,
            expected_yield_kg=req.expected_yield_kg,
            d_day=req.d_day
        )
        
        if res.get("status") == "success":
            success_count += 1
        else:
            fail_count += 1

        results.append({
            "customer_name": customer.name,
            "phone": customer.phone,
            "result": res
        })

    return {
        "status": "completed",
        "total": len(req.customers),
        "success_count": success_count,
        "fail_count": fail_count,
        "details": results
    }


@router.post("/api/sms/send-harvest-notice")
async def send_harvest_sms(req: SMSNoticeRequest):
    """
    수확 7일 전 또는 D-Day에 구매 고객을 대상으로 개별 예약 문자를 발송합니다.
    """
    try:
        result = send_harvest_notice_sms(
            receiver_phone=req.receiver_phone,
            crop_name=req.crop_name,
            expected_harvest_date=req.expected_harvest_date,
            expected_yield_kg=req.expected_yield_kg,
            d_day=req.d_day
        )

        if result.get("status") == "error":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"SMS 발송 중 오류가 발생했습니다: {result.get('message')}"
            )

        return {
            "status": "success",
            "message": f"[{req.crop_name}] D-{req.d_day}일 사전 예약 문자가 정상 전송되었습니다.",
            "data": result
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"서버 내부 오류: {str(e)}"
        )