"""Модели и подключение к SQLite (SQLAlchemy 2 + aiosqlite)."""
from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(128), default="")
    last_name: Mapped[str] = mapped_column(String(128), default="")
    username: Mapped[str] = mapped_column(String(64), default="")
    photo_file_id: Mapped[str] = mapped_column(String(256), default="")
    photo_url: Mapped[str] = mapped_column(String(512), default="")
    is_fake: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[int] = mapped_column(Integer, default=0)

    videos: Mapped[list["Video"]] = relationship(back_populates="author")


class Video(Base):
    __tablename__ = "videos"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    author_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    file_id: Mapped[str] = mapped_column(String(256), default="")
    file_unique_id: Mapped[str] = mapped_column(String(128), default="")
    thumb_file_id: Mapped[str] = mapped_column(String(256), default="")
    local_path: Mapped[str] = mapped_column(String(512), default="")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[int] = mapped_column(Integer, default=0)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    caption: Mapped[str] = mapped_column(String(1024), default="")
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes_count: Mapped[int] = mapped_column(Integer, default=0)
    comments_count: Mapped[int] = mapped_column(Integer, default=0)
    reports_count: Mapped[int] = mapped_column(Integer, default=0)
    gifts_count: Mapped[int] = mapped_column(Integer, default=0)
    boosted_until: Mapped[int] = mapped_column(Integer, default=0)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[int] = mapped_column(Integer, index=True, default=0)

    author: Mapped[User] = relationship(back_populates="videos")


class Like(Base):
    __tablename__ = "likes"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    video_id: Mapped[int] = mapped_column(Integer, ForeignKey("videos.id"), primary_key=True, index=True)
    created_at: Mapped[int] = mapped_column(Integer, default=0)


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    video_id: Mapped[int] = mapped_column(Integer, ForeignKey("videos.id"), index=True)
    text: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[int] = mapped_column(Integer, default=0)


class Follow(Base):
    __tablename__ = "follows"
    follower_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    followee_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    created_at: Mapped[int] = mapped_column(Integer, default=0)


class VideoView(Base):
    __tablename__ = "video_views"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    video_id: Mapped[int] = mapped_column(Integer, ForeignKey("videos.id"), primary_key=True, index=True)
    created_at: Mapped[int] = mapped_column(Integer, default=0)


class Report(Base):
    __tablename__ = "reports"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    video_id: Mapped[int] = mapped_column(Integer, ForeignKey("videos.id"), primary_key=True, index=True)
    reason: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[int] = mapped_column(Integer, default=0)


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(String(32), default="")  # boost | gift
    video_id: Mapped[int] = mapped_column(Integer, default=0)
    to_user_id: Mapped[int] = mapped_column(BigInteger, default=0)
    gift_id: Mapped[str] = mapped_column(String(32), default="")
    stars: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[str] = mapped_column(String(128), default="")
    telegram_charge_id: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("payload", name="uq_payment_payload"),)


def make_engine(url: str):
    kwargs = dict(echo=False, future=True)
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"timeout": 30}
    engine = create_async_engine(url, **kwargs)

    if url.startswith("sqlite"):
        @event.listens_for(engine.sync_engine, "connect")
        def _on_connect(dbapi_conn, _rec):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

    sm = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, sm


def _migrate(conn):
    """Простые ALTER для новых колонок (SQLite)."""
    tables = {
        "users": {
            "photo_file_id": ("VARCHAR(256)", ""),
            "photo_url": ("VARCHAR(512)", ""),
            "is_fake": ("BOOLEAN", 0),
        },
        "videos": {
            "gifts_count": ("INTEGER", 0),
        },
    }
    for table, cols in tables.items():
        existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
        for name, (typ, default) in cols.items():
            if name in existing:
                continue
            ddl = f"ALTER TABLE {table} ADD COLUMN {name} {typ}"
            if default is not None and default != "":
                ddl += " DEFAULT " + (f"'{default}'" if isinstance(default, str) else str(int(default)))
            conn.execute(text(ddl))


async def init_db(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate)
