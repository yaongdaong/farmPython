# sms_service.py: 문자(SMS)나 알림톡을 실제로 발송하는 외부 연동 로직을 담당합니다.

import os
import logging
from typing import Dict, Any, Optional
from dotenv import load_dotenv

logger = logging.getLogger("sms_service")
load_dotenv()

# Solapi / CoolSMS 환경 변수
SOLAPI_API_KEY = os.getenv("SOLAPI_API_KEY", "")
SOLAPI_SECRET_KEY = os.getenv("SOLAPI_SECRET_KEY", "")
SENDER_PHONE_NUMBER = os.getenv("SENDER_PHONE_NUMBER", "")  # 발신번호 (등록된 번호만 가능)

try:
    from sdk.api.message import Message
    from sdk.exceptions import CoolsmsException
    COOLSMS_AVAILABLE = True
except ImportError:
    COOLSMS_AVAILABLE = False


def send_harvest_notice_sms(
    receiver_phone: str,
    crop_name: str,
    expected_harvest_date: str,
    expected_yield_kg: float,
    d_day: int
) -> Dict[str, Any]:
    """
    수확 사전 예약 및 안내 문자(LMS/SMS) 발송 함수
    """
    # 문자 내용 구성
    message_text = (
        f"[농사하나로] 📢 {crop_name} 수확 사전 예약 안내\n\n"
        f"안녕하세요! {crop_name} 수확이 약 {d_day}일 앞으로 다가왔습니다.\n\n"
        f"• 예상 수확일: {expected_harvest_date}\n"
        f"• 예상 수확량: 약 {expected_yield_kg}kg\n\n"
        f"싱싱한 직배송 작물을 미리 예약하시려면 아래 링크에서 신청해 주세요!\n"
        f"👉 예약 페이지: https://your-farm-mall.com/pre-order"
    )

    # API 키가 없거나 SDK 미설치 시 테스트 모드(Console 출력)로 동작
    if not COOLSMS_AVAILABLE or not SOLAPI_API_KEY or not SOLAPI_SECRET_KEY:
        logger.info(f"📱 [SMS Mock 발송] 수신자: {receiver_phone}\n{message_text}")
        return {
            "status": "success",
            "mode": "mock",
            "message": "테스트 모드로 실제 문자는 발송되지 않았습니다.",
            "content": message_text
        }

    # 실제 Solapi SDK 발송 로직
    params = {
        'type': 'LMS',  # 긴 문자(LMS)
        'to': receiver_phone.replace("-", ""),  # 하이픈 제거
        'from': SENDER_PHONE_NUMBER,
        'text': message_text,
        'subject': f'[{crop_name}] 수확 D-{d_day}일 전 사전 예약 안내'
    }

    try:
        cool = Message(SOLAPI_API_KEY, SOLAPI_SECRET_KEY)
        response = cool.send(params)
        logger.info(f"✅ SMS 발송 성공: {response}")
        return {"status": "success", "mode": "real", "response": response}
    except CoolsmsException as e:
        logger.error(f"❌ SMS 발송 실패 (Code: {e.code}): {e.msg}")
        return {"status": "error", "code": e.code, "message": e.msg}