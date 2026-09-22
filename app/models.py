# models.py
from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from database import Base

class Crop(Base):
    __tablename__ = "crops"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)        # 작물명 (예: 토마토, 고추)
    base_temp = Column(Float, nullable=False, default=10.0)      # 생육 하한 온도 (Base Temp)
    upper_temp = Column(Float, nullable=False, default=30.0)     # 생육 상한 온도 (Upper Temp)

    stages = relationship("CropStageGdd", back_populates="crop", cascade="all, delete-orphan")
    logs = relationship("UserCropLog", back_populates="crop")

class CropStageGdd(Base):
    __tablename__ = "crop_stage_gdds"

    id = Column(Integer, primary_key=True, index=True)
    crop_id = Column(Integer, ForeignKey("crops.id"), nullable=False)
    stage_name = Column(String(50), nullable=False)              # 생육 단계 (예: 정식~수확, 발아~개화)
    target_gdd = Column(Float, nullable=False)                   # 해당 단계 목표 누적 GDD

    crop = relationship("Crop", back_populates="stages")

class UserCropLog(Base):
    __tablename__ = "user_crop_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, default=1)
    crop_id = Column(Integer, ForeignKey("crops.id"), nullable=False)
    
    last_event_type = Column(String(50), default="PLANTED")       # 이벤트 유형 (PLANTED, HARVESTED 등)
    last_event_date = Column(Date, nullable=False)                # 파종/정식일
    accumulated_gdd_since_event = Column(Float, default=0.0)     # 누적 GDD
    estimated_harvest_date = Column(Date, nullable=True)          # 예상 수확일
    
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    crop = relationship("Crop", back_populates="logs")