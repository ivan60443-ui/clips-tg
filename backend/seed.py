"""Демо-данные для DEV_MODE: оригинальные короткие ролики из media/."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import config as C
from .db import Comment, Follow, User, Video
from .service import now_ts

AUTHORS = {
    900001: {"first_name": "Маша", "username": "masha_clips", "photo_url": "/media/ava_masha.svg"},
    900002: {"first_name": "Артём", "username": "artem_night", "photo_url": "/media/ava_artem.svg"},
    900003: {"first_name": "Лена", "username": "lena_rain", "photo_url": "/media/ava_lena.svg"},
    900004: {"first_name": "Кирилл", "username": "kir_neon", "photo_url": "/media/ava_kirill.svg"},
}

DEMOS = [
    {
        "file": "demo1.mp4",
        "caption": "Закат на набережной. Кто ещё здесь гуляет по вечерам?",
        "author_id": 900001, "likes": 128, "views": 1840, "hours_ago": 3,
        "comments": [
            (900002, "Красота, сам там вчера был", 3600),
            (900003, "Куда это снято??", 1800),
        ],
    },
    {
        "file": "demo2.mp4",
        "caption": "Город ночью — только свет и шум.",
        "author_id": 900002, "likes": 86, "views": 990, "hours_ago": 8,
        "comments": [(900001, "Как ты это снял? 🔥", 5000)],
    },
    {
        "file": "demo3.mp4",
        "caption": "Кофе и дождь. Идеальный вайб на понедельник ☕",
        "author_id": 900003, "likes": 210, "views": 3200, "hours_ago": 20,
        "comments": [],
    },
    {
        "file": "demo4.mp4",
        "caption": "Неоновый вечер. Включи звук 🔊",
        "author_id": 900004, "likes": 54, "views": 640, "hours_ago": 30,
        "comments": [],
    },
]

DEV_VIEWER_ID = 643246726


async def _ensure_user(s: AsyncSession, uid: int, now: int, **extra) -> User:
    u = await s.get(User, uid)
    if u is None:
        meta = AUTHORS.get(uid, {})
        u = User(
            id=uid,
            first_name=extra.get("first_name") or meta.get("first_name") or "Пользователь",
            username=extra.get("username") or meta.get("username") or "",
            photo_url=extra.get("photo_url") or meta.get("photo_url") or "",
            is_fake=uid in AUTHORS,
            created_at=now - 86400 * 7,
        )
        s.add(u)
        await s.flush()
    return u


async def seed_demo(s: AsyncSession, now: int | None = None) -> int:
    """Создаёт демо-ролики, если их ещё нет и файлы лежат в media/."""
    now = now or now_ts()
    existing = await s.scalar(select(func.count()).select_from(Video).where(Video.local_path != ""))
    if existing:
        return int(existing)

    for uid in AUTHORS:
        await _ensure_user(s, uid, now)
    await _ensure_user(s, DEV_VIEWER_ID, now, first_name="Ваня", username="nikolavee", photo_url="")

    created = 0
    for d in DEMOS:
        path = Path("media") / d["file"]
        if not (C.ROOT / path).is_file():
            continue
        comments = d.get("comments") or []
        v = Video(
            author_id=d["author_id"],
            local_path=str(path),
            width=720, height=1280, duration=4,
            caption=d["caption"],
            likes_count=d["likes"],
            views=d["views"],
            comments_count=len(comments),
            created_at=now - d["hours_ago"] * 3600,
        )
        s.add(v)
        await s.flush()
        for uid, text, ago in comments:
            s.add(Comment(user_id=uid, video_id=v.id, text=text, created_at=now - ago))
        created += 1

    if created and await s.get(Follow, (DEV_VIEWER_ID, 900001)) is None:
        s.add(Follow(follower_id=DEV_VIEWER_ID, followee_id=900001, created_at=now))

    await s.flush()
    return created
