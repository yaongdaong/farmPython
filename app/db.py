from prisma import Prisma

# 앱 전체에서 공유할 Prisma 인스턴스
db = Prisma()

async def connect_db():
    if not db.is_connected():
        await db.connect()

async def disconnect_db():
    if db.is_connected():
        await db.disconnect()