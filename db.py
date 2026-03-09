from __future__ import annotations

import datetime as dt
from typing import Optional, List

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base, relationship

from config import get_settings


settings = get_settings()

engine = create_async_engine(settings.db_url, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)

    requests = relationship("ImageRequest", back_populates="user")


class ImageRequest(Base):
    __tablename__ = "image_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    prompt = Column(Text, nullable=False)
    input_images = Column(Text, nullable=True)  # Список URL через запятую
    generated_url = Column(Text, nullable=True)
    model = Column(String(255), nullable=False, default="nano-banana-pro")
    status = Column(String(32), nullable=False, default="pending")  # pending/success/fail
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow, nullable=False
    )

    user = relationship("User", back_populates="requests")


async def init_db() -> None:
    """Создание таблиц (простая авто-миграция для старта)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
) -> User:
    result = await session.execute(
        User.__table__.select().where(User.telegram_id == telegram_id)
    )
    row = result.first()
    if row:
        return User(**row._mapping)

    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
    )
    session.add(user)
    await session.flush()
    return user


async def create_image_request(
    session: AsyncSession,
    user: User,
    prompt: str,
    image_urls: Optional[List[str]],
    status: str = "pending",
    generated_url: Optional[str] = None,
    error_message: Optional[str] = None,
    model: str = "nano-banana-pro",
) -> ImageRequest:
    input_images_str = ",".join(image_urls) if image_urls else None
    req = ImageRequest(
        user_id=user.id,
        prompt=prompt,
        input_images=input_images_str,
        generated_url=generated_url,
        status=status,
        error_message=error_message,
        model=model,
    )
    session.add(req)
    await session.flush()
    return req


async def update_image_request_status(
    session: AsyncSession,
    request_id: int,
    status: str,
    generated_url: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    result = await session.execute(
        ImageRequest.__table__.update()
        .where(ImageRequest.id == request_id)
        .values(
            status=status,
            generated_url=generated_url,
            error_message=error_message,
        )
    )

