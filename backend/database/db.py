from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from config import settings
import ssl

# Strip any ?ssl=disable from URL — asyncpg uses connect_args instead
db_url = settings.DATABASE_URL.split("?")[0]

connect_args = {}
if settings.DATABASE_URL.startswith("postgresql"):
    connect_args["ssl"] = False

engine_kwargs = {
    "echo": False,
    "pool_pre_ping": True,
    "connect_args": connect_args,
}
if not db_url.startswith("sqlite"):
    engine_kwargs["pool_size"] = 5
    engine_kwargs["max_overflow"] = 10

engine = create_async_engine(db_url, **engine_kwargs)
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

class Base(DeclarativeBase):
    pass

async def create_tables() -> bool:
    from config import settings
    is_postgres = settings.DATABASE_URL.startswith("postgresql")
    is_production = not settings.DEBUG and not settings.TESTING

    if is_production and is_postgres:
        print("ℹ️ Skipping create_all; use Alembic migrations.")
        return False

    print("ℹ️ Using create_all for development/testing.")
    from models.user import User
    from models.transaction import Transaction
    from models.audit_log import AuditLog
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return True

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
