# database.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# PostgreSQL 접속 정보 (Next.js에서 사용하는 DB 주소와 동일하게 세팅)
# 형식: postgresql://USER:PASSWORD@HOST:PORT/DB_NAME
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://postgres:1234@localhost:5432/postgres"
)

engine = create_engine(
    DATABASE_URL,
    pool_size=10,        # 기본 커넥션 풀 크기
    max_overflow=20,     # 초과 요청 시 추가 생성할 커넥션 수
    pool_pre_ping=True   # 끊어진 DB 커넥션 자동 재연결 확인
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# DB 세션 생성
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()