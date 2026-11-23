"""HTTP API для Mini App."""
from __future__ import annotations

import asyncio
import logging
import secrets
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import config as C
from .auth import AuthError, validate_init_data
from .db import User, Video
from . import service as S

log = logging.getLogger("clips.api")
router = APIRouter(prefix="/api")
public = APIRouter()
LOCK = asyncio.Lock()

# Кэш путей Telegram getFile: file_id -> (file_path, expires_ts)
_FILE_CACHE: dict[str, tuple[str, int]] = {}
_CACHE_TTL = 3000  # пути живут ~1 час, обновляем чуть раньше


class State:
    sessionmaker = None
    notifier = None
    make_invoice = None
    bot = None


class CommentIn(BaseModel):
    text: str = Field(default="", max_length=500)


class ReportIn(BaseModel):
    reason: str = Field(default="", max_length=200)


class GiftIn(BaseModel):
    gift_id: str = Field(default="fire")


async def current_user(request: Request, x_init_data: str = Header(default=""),
                       x_dev_user: str = Header(default="")):
    if x_init_data:
        try:
            data = validate_init_data(x_init_data, C.BOT_TOKEN)
        except AuthError as e:
            raise HTTPException(401, f"auth: {e}")
        tg, start = data["user"], data["start_param"]
    elif C.DEV_MODE and (x_dev_user or request.query_params.get("uid")):
        uid = int(x_dev_user or request.query_params.get("uid") or "643246726")
        names = {643246726: ("Ваня", "nikolavee")}
        first, uname = names.get(uid, ("Ваня", "vanya_dev"))
        tg, start = {"id": uid, "first_name": first, "username": uname}, request.query_params.get("startapp", "")
    else:
        raise HTTPException(401, "Открой приложение через Telegram")
    request.state.tg = tg
    request.state.start = start or ""
    return tg


async def run(request: Request, fn):
    async with LOCK:
        async with State.sessionmaker() as s:
            now = S.now_ts()
            me = await S.get_or_create(s, request.state.tg, now)
            try:
                result = await fn(s, me, now)
            except S.AppError as e:
                await s.rollback()
                return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
            notes = s.info.pop("notify", []) if hasattr(s, "info") else []
            await s.commit()
    if State.notifier and notes:
        for uid, text in notes:
            try:
                await State.notifier(uid, text)
            except Exception as e:  # noqa
                log.warning("notify failed: %s", e)
    return result


@router.get("/bootstrap")
async def bootstrap(request: Request, tg=Depends(current_user)):
    async def fn(s, me, now):
        pin = S.parse_start_video(request.state.start)
        items = await S.feed(s, me, now, tab="for_you", limit=12, pin_id=pin)
        c = await S.counts_for(s, me.id)
        return {
            "ok": True,
            "me": S.ser_user(me, c, extra={"is_me": True, "is_admin": me.id in C.ADMIN_IDS}),
            "feed": items,
            "prices": {"boost_stars": C.BOOST_STARS, "boost_hours": C.BOOST_HOURS,
                       "gifts": list(C.PRICES.get("gifts", []))},
            "bot": {"username": C.BOT_USERNAME, "upload_url": S.bot_chat_url(),
                    "app_name": C.APP_NAME, "tagline": C.APP_TAGLINE,
                    "short_name": C.APP_SHORT_NAME},
            "dev": C.DEV_MODE,
            "pin": pin,
        }
    return await run(request, fn)


@router.get("/feed")
async def get_feed(request: Request, tab: str = "for_you", offset: int = 0, limit: int = 12,
                   pin: int = 0, tg=Depends(current_user)):
    tab = "following" if tab == "following" else "for_you"
    limit = max(1, min(limit, 30))
    offset = max(0, offset)

    async def fn(s, me, now):
        items = await S.feed(s, me, now, tab=tab, limit=limit, offset=offset, pin_id=pin or None)
        return {"ok": True, "items": items, "tab": tab, "offset": offset}
    return await run(request, fn)


@router.post("/video/{video_id}/like")
async def like_video(video_id: int, request: Request, tg=Depends(current_user)):
    async def fn(s, me, now):
        r = await S.toggle_like(s, me, video_id, now)
        return {"ok": True, **r}
    return await run(request, fn)


@router.post("/video/{video_id}/view")
async def view_video(video_id: int, request: Request, tg=Depends(current_user)):
    async def fn(s, me, now):
        r = await S.add_view(s, me, video_id, now)
        return {"ok": True, **r}
    return await run(request, fn)


@router.get("/video/{video_id}/comments")
async def comments(video_id: int, request: Request, tg=Depends(current_user)):
    async def fn(s, me, now):
        items = await S.list_comments(s, video_id)
        return {"ok": True, "items": items}
    return await run(request, fn)


@router.post("/video/{video_id}/comments")
async def post_comment(video_id: int, body: CommentIn, request: Request, tg=Depends(current_user)):
    async def fn(s, me, now):
        r = await S.add_comment(s, me, video_id, body.text, now)
        return {"ok": True, **r}
    return await run(request, fn)


@router.post("/video/{video_id}/report")
async def report(video_id: int, body: ReportIn, request: Request, tg=Depends(current_user)):
    async def fn(s, me, now):
        r = await S.report_video(s, me, video_id, body.reason, now)
        return r
    return await run(request, fn)


@router.post("/video/{video_id}/delete")
async def delete_video(video_id: int, request: Request, tg=Depends(current_user)):
    async def fn(s, me, now):
        await S.delete_video(s, video_id, me)
        return {"ok": True}
    return await run(request, fn)


@router.post("/video/{video_id}/boost")
async def boost_video(video_id: int, request: Request, tg=Depends(current_user)):
    async def fn(s, me, now):
        v = await s.get(Video, video_id)
        if not v or v.is_deleted:
            raise S.AppError("Ролик не найден")
        if v.author_id != me.id:
            raise S.AppError("Бустить можно только свой ролик")
        payload = f"boost:{video_id}:{me.id}:{secrets.token_hex(4)}"
        title = f"Буст в рекомендации на {C.BOOST_HOURS} ч"
        if C.DEV_MODE and not State.make_invoice:
            r = await S.apply_payment(s, user_id=me.id, payload=payload, stars=C.BOOST_STARS,
                                      charge_id=f"dev-{payload}", now=now)
            return {"ok": True, "dev": True, **r}
        if not State.make_invoice:
            raise S.AppError("Оплата пока недоступна")
        url = await State.make_invoice(me.id, title, C.BOOST_STARS, payload)
        return {"ok": True, "invoice_url": url, "stars": C.BOOST_STARS}
    return await run(request, fn)


@router.post("/video/{video_id}/gift")
async def gift_video(video_id: int, body: GiftIn, request: Request, tg=Depends(current_user)):
    async def fn(s, me, now):
        g = C.GIFTS.get(body.gift_id)
        if not g:
            raise S.AppError("Нет такого подарка")
        v = await s.get(Video, video_id)
        if not v or v.is_deleted:
            raise S.AppError("Ролик не найден")
        if v.author_id == me.id:
            raise S.AppError("Нельзя подарить себе")
        payload = f"gift:{body.gift_id}:{video_id}:{me.id}:{secrets.token_hex(4)}"
        title = f"{g['emoji']} {g['title']} автору"
        if C.DEV_MODE and not State.make_invoice:
            r = await S.apply_payment(s, user_id=me.id, payload=payload, stars=int(g["stars"]),
                                      charge_id=f"dev-{payload}", now=now)
            return {"ok": True, "dev": True, **r}
        if not State.make_invoice:
            raise S.AppError("Оплата пока недоступна")
        url = await State.make_invoice(me.id, title, int(g["stars"]), payload)
        return {"ok": True, "invoice_url": url, "stars": int(g["stars"])}
    return await run(request, fn)


@router.get("/users/{user_id}")
async def get_profile(user_id: int, request: Request, tg=Depends(current_user)):
    async def fn(s, me, now):
        r = await S.profile(s, me, user_id, now)
        return {"ok": True, **r}
    return await run(request, fn)


@router.post("/users/{user_id}/follow")
async def follow_user(user_id: int, request: Request, tg=Depends(current_user)):
    async def fn(s, me, now):
        r = await S.toggle_follow(s, me, user_id, now)
        return {"ok": True, **r}
    return await run(request, fn)


@router.get("/me")
async def me_profile(request: Request, tg=Depends(current_user)):
    async def fn(s, me, now):
        r = await S.profile(s, me, me.id, now)
        return {"ok": True, **r}
    return await run(request, fn)


async def _tg_file_url(file_id: str) -> str:
    now = S.now_ts()
    cached = _FILE_CACHE.get(file_id)
    if cached and cached[1] > now:
        path = cached[0]
    else:
        if not State.bot or not C.BOT_TOKEN:
            raise HTTPException(404, "no file")
        try:
            f = await State.bot.get_file(file_id)
        except Exception as e:  # noqa
            log.warning("get_file failed: %s", e)
            raise HTTPException(404, "file unavailable")
        path = f.file_path
        _FILE_CACHE[file_id] = (path, now + _CACHE_TTL)
    return f"https://api.telegram.org/file/bot{C.BOT_TOKEN}/{path}"


async def _proxy_tg(file_id: str, media_type: str, filename: str):
    url = await _tg_file_url(file_id)
    client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)

    async def stream():
        try:
            async with client.stream("GET", url) as r:
                r.raise_for_status()
                async for chunk in r.aiter_bytes(64 * 1024):
                    yield chunk
        finally:
            await client.aclose()

    return StreamingResponse(stream(), media_type=media_type, headers={
        "Cache-Control": "private, max-age=300",
        "Content-Disposition": f'inline; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
    })


async def _load_video(video_id: int) -> Video:
    async with State.sessionmaker() as s:
        v = await s.get(Video, video_id)
        if not v or v.is_deleted:
            raise HTTPException(404, "not found")
        return v


@router.get("/video/{video_id}/stream")
async def stream_video(video_id: int):
    # Поток без initData, чтобы <video src> работал. Знающий id и так видит ролик в ленте.
    v = await _load_video(video_id)
    local = S.media_abs(v.local_path)
    if local:
        return FileResponse(local, media_type="video/mp4", filename=f"clip-{v.id}.mp4",
                            headers={"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=3600"})
    if not v.file_id:
        raise HTTPException(404, "no file")
    return await _proxy_tg(v.file_id, "video/mp4", f"clip-{v.id}.mp4")


@router.get("/video/{video_id}/thumb")
async def stream_thumb(video_id: int):
    v = await _load_video(video_id)
    if v.thumb_file_id and State.bot:
        return await _proxy_tg(v.thumb_file_id, "image/jpeg", f"thumb-{v.id}.jpg")
    # Для демо — первый кадр не храним, отдадим SVG-заглушку через публичный путь
    raise HTTPException(404, "no thumb")


@router.get("/avatar/{user_id}")
async def avatar(user_id: int):
    async with State.sessionmaker() as s:
        u = await s.get(User, user_id)
        if not u:
            raise HTTPException(404, "not found")
        if u.photo_url and u.photo_url.startswith("/media/"):
            p = S.media_abs(u.photo_url.lstrip("/"))
            if p:
                mt = "image/svg+xml" if p.suffix == ".svg" else "image/jpeg"
                return FileResponse(p, media_type=mt)
        if u.photo_file_id and State.bot:
            return await _proxy_tg(u.photo_file_id, "image/jpeg", f"ava-{u.id}.jpg")
    raise HTTPException(404, "no photo")


@public.get("/media/{name}")
async def public_media(name: str):
    if "/" in name or ".." in name:
        raise HTTPException(404)
    p = S.media_abs(f"media/{name}")
    if not p:
        raise HTTPException(404)
    mt = {".mp4": "video/mp4", ".svg": "image/svg+xml", ".jpg": "image/jpeg",
          ".png": "image/png", ".webp": "image/webp"}.get(p.suffix.lower(), "application/octet-stream")
    return FileResponse(p, media_type=mt, headers={"Cache-Control": "public, max-age=86400"})
