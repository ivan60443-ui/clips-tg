"""Бизнес-логика ленты: пользователи, рейтинг, лайки, подписки, загрузка, оплаты."""
from __future__ import annotations

import time
from pathlib import Path

from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from . import config as C
from .db import Comment, Follow, Like, Payment, Report, User, Video, VideoView

MAX_CAPTION = 1024
MAX_COMMENT = 500


class AppError(Exception):
    pass


def now_ts() -> int:
    return int(time.time())


def display_name(u: User) -> str:
    name = f"{u.first_name or ''} {u.last_name or ''}".strip()
    return name or (f"@{u.username}" if u.username else f"id{u.id}")


def feed_score(v: Video, now: int) -> float:
    """Свежесть + лайки/просмотры. Буст сильно поднимает ролик."""
    age_h = max(0.0, (now - (v.created_at or 0)) / 3600)
    recency = 100.0 / (1.0 + age_h / 6.0)
    score = v.likes_count * 3.0 + v.comments_count * 2.0 + v.views * 0.15 + recency
    if (v.boosted_until or 0) > now:
        score += 5000.0
    return score


def parse_start_video(param: str | None) -> int | None:
    if not param:
        return None
    if param.startswith("v_"):
        try:
            return int(param[2:])
        except ValueError:
            return None
    return None


def share_link(video_id: int) -> str:
    if C.BOT_USERNAME and C.APP_SHORT_NAME:
        return f"https://t.me/{C.BOT_USERNAME}/{C.APP_SHORT_NAME}?startapp=v_{video_id}"
    if C.BOT_USERNAME:
        return f"https://t.me/{C.BOT_USERNAME}?start=v_{video_id}"
    return C.WEBAPP_URL or f"/?v={video_id}"


def bot_chat_url() -> str:
    if C.BOT_USERNAME:
        return f"https://t.me/{C.BOT_USERNAME}?start=upload"
    return "https://t.me"


def validate_upload(file_size: int | None, duration: int | None) -> str | None:
    """Вернуть текст ошибки или None, если ролик можно принять."""
    if file_size and file_size > C.MAX_VIDEO_BYTES:
        mb = C.MAX_VIDEO_BYTES // (1024 * 1024)
        size_mb = file_size / (1024 * 1024)
        return (f"Ролик слишком тяжёлый ({size_mb:.1f} МБ). "
                f"Telegram отдаёт файлы боту только до {mb} МБ — сожми видео и пришли ещё раз.")
    if duration and duration > C.MAX_DURATION_SEC:
        return f"Слишком длинный ролик ({duration} сек). Давай до {C.MAX_DURATION_SEC} секунд."
    return None


async def get_or_create(s: AsyncSession, tg: dict, now: int | None = None) -> User:
    now = now or now_ts()
    uid = int(tg["id"])
    u = await s.get(User, uid)
    first = (tg.get("first_name") or "")[:128]
    last = (tg.get("last_name") or "")[:128]
    uname = (tg.get("username") or "")[:64]
    photo = (tg.get("photo_url") or "")[:512]
    if u is None:
        u = User(id=uid, first_name=first, last_name=last, username=uname,
                 photo_url=photo, created_at=now)
        s.add(u)
        await s.flush()
        return u
    changed = False
    if first and u.first_name != first:
        u.first_name, changed = first, True
    if last and u.last_name != last:
        u.last_name, changed = last, True
    if uname and u.username != uname:
        u.username, changed = uname, True
    if photo and u.photo_url != photo:
        u.photo_url, changed = photo, True
    if changed:
        await s.flush()
    return u


async def counts_for(s: AsyncSession, user_id: int) -> dict:
    videos = await s.scalar(
        select(func.count()).select_from(Video).where(Video.author_id == user_id, Video.is_deleted == False)  # noqa: E712
    )
    followers = await s.scalar(
        select(func.count()).select_from(Follow).where(Follow.followee_id == user_id)
    )
    following = await s.scalar(
        select(func.count()).select_from(Follow).where(Follow.follower_id == user_id)
    )
    return {"videos": int(videos or 0), "followers": int(followers or 0), "following": int(following or 0)}


def ser_user(u: User, counts: dict | None = None, extra: dict | None = None) -> dict:
    d = {
        "id": u.id,
        "name": display_name(u),
        "first_name": u.first_name or "",
        "username": u.username or "",
        "photo": u.photo_url or (f"/api/avatar/{u.id}" if u.photo_file_id else ""),
        "fake": bool(u.is_fake),
    }
    if counts:
        d.update(counts)
    if extra:
        d.update(extra)
    return d


def ser_video(v: Video, author: User, now: int, liked: bool = False, followed: bool = False) -> dict:
    src = f"/api/video/{v.id}/stream"
    thumb = f"/api/video/{v.id}/thumb" if (v.thumb_file_id or v.local_path) else ""
    return {
        "id": v.id,
        "caption": v.caption or "",
        "duration": v.duration,
        "width": v.width,
        "height": v.height,
        "views": v.views,
        "likes": v.likes_count,
        "comments": v.comments_count,
        "gifts": v.gifts_count,
        "liked": liked,
        "boosted": (v.boosted_until or 0) > now,
        "boosted_until": v.boosted_until or 0,
        "created_at": v.created_at,
        "src": src,
        "thumb": thumb,
        "share": share_link(v.id),
        "author": ser_user(author, extra={"followed": followed}),
        "score": round(feed_score(v, now), 2),
    }


async def liked_set(s: AsyncSession, user_id: int, video_ids: list[int]) -> set[int]:
    if not video_ids:
        return set()
    rows = await s.execute(select(Like.video_id).where(Like.user_id == user_id, Like.video_id.in_(video_ids)))
    return set(rows.scalars())


async def followed_set(s: AsyncSession, follower_id: int, ids: list[int]) -> set[int]:
    if not ids:
        return set()
    rows = await s.execute(select(Follow.followee_id).where(
        Follow.follower_id == follower_id, Follow.followee_id.in_(ids)))
    return set(rows.scalars())


async def feed(s: AsyncSession, me: User, now: int, tab: str = "for_you", limit: int = 12,
               offset: int = 0, pin_id: int | None = None) -> list[dict]:
    q = select(Video).where(Video.is_deleted == False)  # noqa: E712
    if tab == "following":
        sub = select(Follow.followee_id).where(Follow.follower_id == me.id)
        q = q.where(Video.author_id.in_(sub))
    videos = list((await s.execute(q)).scalars())
    videos.sort(key=lambda v: (feed_score(v, now), v.created_at, v.id), reverse=True)
    if pin_id:
        pinned = [v for v in videos if v.id == pin_id]
        rest = [v for v in videos if v.id != pin_id]
        videos = pinned + rest
    page = videos[offset:offset + limit]
    authors = {}
    aids = {v.author_id for v in page}
    if aids:
        rows = await s.execute(select(User).where(User.id.in_(aids)))
        authors = {u.id: u for u in rows.scalars()}
    liked = await liked_set(s, me.id, [v.id for v in page])
    followed = await followed_set(s, me.id, list(aids))
    return [ser_video(v, authors[v.author_id], now, v.id in liked, v.author_id in followed)
            for v in page if v.author_id in authors]


async def toggle_like(s: AsyncSession, me: User, video_id: int, now: int) -> dict:
    v = await s.get(Video, video_id)
    if not v or v.is_deleted:
        raise AppError("Ролик не найден")
    existing = await s.get(Like, (me.id, video_id))
    if existing:
        await s.delete(existing)
        v.likes_count = max(0, v.likes_count - 1)
        liked = False
    else:
        s.add(Like(user_id=me.id, video_id=video_id, created_at=now))
        v.likes_count += 1
        liked = True
    await s.flush()
    return {"liked": liked, "likes": v.likes_count}


async def add_view(s: AsyncSession, me: User, video_id: int, now: int) -> dict:
    v = await s.get(Video, video_id)
    if not v or v.is_deleted:
        raise AppError("Ролик не найден")
    existing = await s.get(VideoView, (me.id, video_id))
    if not existing:
        s.add(VideoView(user_id=me.id, video_id=video_id, created_at=now))
        v.views += 1
        await s.flush()
    return {"views": v.views}


async def add_comment(s: AsyncSession, me: User, video_id: int, text: str, now: int) -> dict:
    v = await s.get(Video, video_id)
    if not v or v.is_deleted:
        raise AppError("Ролик не найден")
    text = (text or "").strip()
    if not text:
        raise AppError("Напиши комментарий")
    if len(text) > MAX_COMMENT:
        raise AppError(f"Слишком длинный комментарий (макс. {MAX_COMMENT})")
    c = Comment(user_id=me.id, video_id=video_id, text=text, created_at=now)
    s.add(c)
    v.comments_count += 1
    await s.flush()
    return {"id": c.id, "text": c.text, "created_at": c.created_at,
            "author": ser_user(me), "comments": v.comments_count}


async def list_comments(s: AsyncSession, video_id: int, limit: int = 50) -> list[dict]:
    v = await s.get(Video, video_id)
    if not v or v.is_deleted:
        raise AppError("Ролик не найден")
    rows = await s.execute(
        select(Comment, User).join(User, User.id == Comment.user_id)
        .where(Comment.video_id == video_id)
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .limit(limit)
    )
    out = []
    for c, u in rows.all():
        out.append({"id": c.id, "text": c.text, "created_at": c.created_at, "author": ser_user(u)})
    return out


async def toggle_follow(s: AsyncSession, me: User, target_id: int, now: int) -> dict:
    if me.id == target_id:
        raise AppError("Нельзя подписаться на себя")
    target = await s.get(User, target_id)
    if not target:
        raise AppError("Пользователь не найден")
    existing = await s.get(Follow, (me.id, target_id))
    if existing:
        await s.delete(existing)
        followed = False
    else:
        s.add(Follow(follower_id=me.id, followee_id=target_id, created_at=now))
        followed = True
    await s.flush()
    c = await counts_for(s, target_id)
    return {"followed": followed, "followers": c["followers"]}


async def report_video(s: AsyncSession, me: User, video_id: int, reason: str, now: int) -> dict:
    v = await s.get(Video, video_id)
    if not v or v.is_deleted:
        raise AppError("Ролик не найден")
    existing = await s.get(Report, (me.id, video_id))
    if existing:
        return {"ok": True, "already": True, "reports": v.reports_count}
    s.add(Report(user_id=me.id, video_id=video_id, reason=(reason or "")[:200], created_at=now))
    v.reports_count += 1
    await s.flush()
    return {"ok": True, "already": False, "reports": v.reports_count}


async def delete_video(s: AsyncSession, video_id: int, by: User) -> Video:
    v = await s.get(Video, video_id)
    if not v or v.is_deleted:
        raise AppError("Ролик не найден")
    if by.id != v.author_id and by.id not in C.ADMIN_IDS:
        raise AppError("Нельзя удалить чужой ролик")
    v.is_deleted = True
    await s.flush()
    return v


async def profile(s: AsyncSession, me: User, user_id: int, now: int) -> dict:
    u = await s.get(User, user_id)
    if not u:
        raise AppError("Пользователь не найден")
    c = await counts_for(s, user_id)
    followed = False
    if me.id != user_id:
        followed = (await s.get(Follow, (me.id, user_id))) is not None
    videos = list((await s.execute(
        select(Video).where(Video.author_id == user_id, Video.is_deleted == False)  # noqa: E712
        .order_by(Video.created_at.desc())
    )).scalars())
    liked = await liked_set(s, me.id, [v.id for v in videos])
    items = [ser_video(v, u, now, v.id in liked, followed) for v in videos]
    return {"user": ser_user(u, c, extra={"followed": followed, "is_me": me.id == user_id}), "videos": items}


async def publish_video(s: AsyncSession, author: User, now: int, *, file_id: str = "",
                        file_unique_id: str = "", thumb_file_id: str = "", local_path: str = "",
                        width: int = 0, height: int = 0, duration: int = 0, file_size: int = 0,
                        caption: str = "") -> Video:
    err = validate_upload(file_size, duration)
    if err:
        raise AppError(err)
    if not file_id and not local_path:
        raise AppError("Нет файла")
    v = Video(
        author_id=author.id, file_id=file_id, file_unique_id=file_unique_id,
        thumb_file_id=thumb_file_id, local_path=local_path, width=width, height=height,
        duration=duration, file_size=file_size, caption=(caption or "")[:MAX_CAPTION],
        created_at=now,
    )
    s.add(v)
    await s.flush()
    return v


def parse_payload(payload: str) -> dict | None:
    # boost:<video_id>:<uid>:<nonce>  or  gift:<gift_id>:<video_id>:<uid>:<nonce>
    parts = (payload or "").split(":")
    if len(parts) < 4:
        return None
    kind = parts[0]
    if kind == "boost":
        try:
            return {"kind": "boost", "video_id": int(parts[1]), "user_id": int(parts[2])}
        except ValueError:
            return None
    if kind == "gift":
        try:
            return {"kind": "gift", "gift_id": parts[1], "video_id": int(parts[2]), "user_id": int(parts[3])}
        except ValueError:
            return None
    return None


async def apply_payment(s: AsyncSession, *, user_id: int, payload: str, stars: int,
                        charge_id: str, now: int) -> dict:
    """Записать оплату. Повторный charge_id/payload не применяется дважды."""
    existing = (await s.execute(select(Payment).where(
        (Payment.payload == payload) | (Payment.telegram_charge_id == charge_id)
    ))).scalar_one_or_none()
    if existing and existing.telegram_charge_id:
        return {"ok": True, "duplicate": True, "kind": existing.kind}

    parsed = parse_payload(payload)
    if not parsed or parsed.get("user_id") != user_id:
        raise AppError("Некорректный платёж")

    v = await s.get(Video, parsed["video_id"])
    if not v or v.is_deleted:
        raise AppError("Ролик не найден")

    kind = parsed["kind"]
    gift_id = parsed.get("gift_id") or ""
    if kind == "boost":
        if stars != C.BOOST_STARS:
            raise AppError("Неверная сумма буста")
        v.boosted_until = max(v.boosted_until or 0, now) + C.BOOST_HOURS * 3600
        to_user = v.author_id
    elif kind == "gift":
        g = C.GIFTS.get(gift_id)
        if not g or stars != int(g["stars"]):
            raise AppError("Неверный подарок")
        v.gifts_count += 1
        to_user = v.author_id
        if to_user == user_id:
            raise AppError("Нельзя подарить себе")
    else:
        raise AppError("Неизвестный платёж")

    p = Payment(user_id=user_id, kind=kind, video_id=v.id, to_user_id=to_user, gift_id=gift_id,
                stars=stars, payload=payload, telegram_charge_id=charge_id or payload, created_at=now)
    s.add(p)
    await s.flush()
    return {"ok": True, "kind": kind, "video_id": v.id, "boosted_until": v.boosted_until,
            "gifts": v.gifts_count, "to_user_id": to_user, "gift_id": gift_id}


async def precheck_payment(s: AsyncSession, payload: str, user_id: int, stars: int, currency: str) -> bool:
    if currency != "XTR":
        return False
    parsed = parse_payload(payload)
    if not parsed or parsed.get("user_id") != user_id:
        return False
    v = await s.get(Video, parsed["video_id"])
    if not v or v.is_deleted:
        return False
    if parsed["kind"] == "boost":
        return stars == C.BOOST_STARS
    if parsed["kind"] == "gift":
        g = C.GIFTS.get(parsed.get("gift_id") or "")
        if not g or stars != int(g["stars"]):
            return False
        return v.author_id != user_id
    return False


def media_abs(local_path: str) -> Path | None:
    if not local_path:
        return None
    p = Path(local_path)
    if not p.is_absolute():
        p = C.ROOT / p
    try:
        p = p.resolve()
    except OSError:
        return None
    media = (C.ROOT / "media").resolve()
    if media not in p.parents and p.parent != media:
        return None
    return p if p.is_file() else None
