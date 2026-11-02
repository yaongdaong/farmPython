# models.py: 데이터베이스 테이블 구조를 정의하는 ORM 모델 파일입니다.

from datetime import datetime
from app.database import Base
from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, Boolean
from sqlalchemy.orm import relationship


class Crop(Base):
    __tablename__ = "crop"

    id = Column(Integer, primary_key=True, index=True)
    farmId = Column("farmId", Integer, ForeignKey("farm.id"), nullable=False)
    name = Column("name", String, nullable=False)
    status = Column("status", String, nullable=False)
    baseTemp = Column("baseTemp", Float, default=10.0, nullable=False)
    upperTemp = Column("upperTemp", Float, default=30.0, nullable=False)
    targetGdd = Column("targetGdd", Float, default=1500.0, nullable=False)
    expectedYield = Column("expectedYield", Float, nullable=True)
    plantingDate = Column("plantingDate", DateTime(timezone=True), nullable=True)
    bloomDate = Column("bloomDate", DateTime(timezone=True), nullable=True)
    harvestDate = Column("harvestDate", DateTime(timezone=True), nullable=True)
    createdAt = Column("createdAt", DateTime(timezone=True), default=datetime.utcnow)

    farm = relationship("Farm", back_populates="crops")
    stages = relationship(
        "CropStageGdd", back_populates="crop", cascade="all, delete-orphan"
    )
    logs = relationship(
        "UserCropLog", back_populates="crop", cascade="all, delete-orphan"
    )
    farmLogs = relationship(
        "FarmLog", back_populates="crop", cascade="all, delete-orphan"
    )


class CropStageGdd(Base):
    __tablename__ = "crop_stage_gdds"

    id = Column(Integer, primary_key=True, index=True)
    cropId = Column("cropId", Integer, ForeignKey("crop.id"), nullable=False)
    stageName = Column("stageName", String, nullable=False)
    targetGdd = Column("targetGdd", Float, nullable=False)

    crop = relationship("Crop", back_populates="stages")


class UserCropLog(Base):
    __tablename__ = "user_crop_logs"

    id = Column(Integer, primary_key=True, index=True)
    userId = Column("userId", Integer, nullable=False, default=1)
    cropId = Column("cropId", Integer, ForeignKey("crop.id"), nullable=False)
    lastEventType = Column("lastEventType", String, default="PLANTED")
    lastEventDate = Column("lastEventDate", Date, nullable=False)
    accumulatedGddSinceEvent = Column(
        "accumulatedGddSinceEvent", Float, default=0.0
    )
    estimatedHarvestDate = Column("estimatedHarvestDate", Date, nullable=True)
    updatedAt = Column("updatedAt", DateTime(timezone=True), default=datetime.utcnow)

    crop = relationship("Crop", back_populates="logs")


class Farm(Base):
    __tablename__ = "farm"

    id = Column(Integer, primary_key=True, index=True)
    name = Column("name", String, nullable=False)
    address = Column("address", String, nullable=False)
    actualArea = Column("actualArea", Float, nullable=False)
    totalArea = Column("totalArea", Float, nullable=False)
    gridX = Column("gridX", Integer, nullable=False)
    gridY = Column("gridY", Integer, nullable=False)
    plantDate = Column("plantDate", Date, nullable=True)
    bloomDate = Column("bloomDate", Date, nullable=True)
    statusType = Column("statusType", String, default="PLANNED")
    growthStatus = Column("growthStatus", String, default="영농생장기")
    accumulatedTemp = Column("accumulatedTemp", Float, default=0.0)
    targetTemp = Column("targetTemp", Float, nullable=True)
    baseTemp = Column("baseTemp", Float, nullable=True)
    targetGdd = Column("targetGdd", Float, nullable=True)
    facilityType = Column("facilityType", String, nullable=True)
    createdAt = Column("createdAt", DateTime(timezone=True), default=datetime.utcnow)

    crops = relationship(
        "Crop", back_populates="farm", cascade="all, delete-orphan"
    )
    farmLogs = relationship(
        "FarmLog", back_populates="farm", cascade="all, delete-orphan"
    )
    predictions = relationship(
        "Prediction", back_populates="farm", cascade="all, delete-orphan"
    )
    harvests = relationship(
        "Harvest", back_populates="farm", cascade="all, delete-orphan"
    )


class FarmLog(Base):
    __tablename__ = "farmLog"

    id = Column(Integer, primary_key=True, index=True)
    farmId = Column("farmId", Integer, ForeignKey("farm.id"), nullable=True)
    cropId = Column("cropId", Integer, ForeignKey("crop.id"), nullable=True)
    date = Column("date", DateTime(timezone=True), nullable=False)
    growthStage = Column("growthStage", String, nullable=False)
    workType = Column("workType", String, nullable=False)
    avgTemp = Column("avgTemp", Float, nullable=True)
    memo = Column("memo", Text, nullable=False)
    createdAt = Column("createdAt", DateTime(timezone=True), default=datetime.utcnow)

    farm = relationship("Farm", back_populates="farmLogs")
    crop = relationship("Crop", back_populates="farmLogs")


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    farmId = Column("farmId", Integer, ForeignKey("farm.id"), nullable=False)
    predictedHarvestDate = Column("predictedHarvestDate", Date, nullable=True)
    predictedYield = Column("predictedYield", Float, nullable=True)
    predictedGdd = Column("predictedGdd", Float, nullable=True)
    predictionDate = Column(
        "predictionDate", DateTime(timezone=True), default=datetime.utcnow
    )

    farm = relationship("Farm", back_populates="predictions")


class Harvest(Base):
    __tablename__ = "harvests"

    id = Column(Integer, primary_key=True, index=True)
    farmId = Column("farmId", Integer, ForeignKey("farm.id"), nullable=False)
    actualHarvestDate = Column("actualHarvestDate", Date, nullable=False)
    actualYield = Column("actualYield", Float, nullable=False)
    memo = Column("memo", Text, nullable=True)
    createdAt = Column("createdAt", DateTime(timezone=True), default=datetime.utcnow)

    farm = relationship("Farm", back_populates="harvests")

class HarvestReservationModel(Base):
    __tablename__ = "harvest_reservations"

    id = Column(String, primary_key=True, default=lambda: str(datetime.utcnow().timestamp()))
    farmId = Column(String, nullable=False, default="default-farm-id")
    cropName = Column(String, nullable=False)
    harvestDate = Column(DateTime, nullable=False)
    expectedKg = Column(Float, nullable=False)
    expectedRevenue = Column(Float, nullable=False)
    popupLinked = Column(Boolean, default=True)
    smsSent = Column(Boolean, default=True)
    createdAt = Column(DateTime, default=datetime.utcnow)

class NotificationSubscriptionModel(Base):
    __tablename__ = "notification_subscriptions"

    id = Column(String, primary_key=True, default=lambda: str(datetime.utcnow().timestamp()))
    phoneNumber = Column(String, nullable=False)
    sigungu = Column(String, nullable=False)
    isSubscribed = Column(Boolean, default=True)
    createdAt = Column(DateTime, default=datetime.utcnow)