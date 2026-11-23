"""Telegram-бот: /start, приём роликов, Stars, админ-команды, инлайн-шеринг."""
from __future__ import annotations

import logging
import secrets

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BufferedInputFile,
    ChosenInlineResult,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultCachedVideo,
    InputTextMessageContent,
    LabeledPrice,
    MenuButtonWebApp,
    Message,
    PreCheckoutQuery,
    WebAppInfo,
)
from sqlalchemy import func, select

from . import config as C
from . import service as S
from .api import LOCK, State
from .db import Payment, User, Video

log = logging.getLogger("clips.bot")
router = Router()
PRIVATE = F.chat.type == "private"

UPLOAD_HINT = (
    "Чтобы выложить ролик, просто пришли мне <b>видео</b> в этот чат.\n"
    "Можно добавить подпись — она станет описанием.\n\n"
    f"Ограничения: до {C.MAX_VIDEO_BYTES // (1024 * 1024)} МБ и {C.MAX_DURATION_SEC} секунд "
    "(так устроен Bot API Telegram)."
)


def app_url(start: str = "") -> str:
    if C.BOT_USERNAME and C.APP_SHORT_NAME:
        base = f"https://t.me/{C.BOT_USERNAME}/{C.APP_SHORT_NAME}"
        return f"{base}?startapp={start}" if start else base
    if C.WEBAPP_URL:
        return f"{C.WEBAPP_URL}/?startapp={start}" if start else C.WEBAPP_URL
    if C.BOT_USERNAME:
        return f"https://t.me/{C.BOT_USERNAME}?start={start or 'app'}"
    return ""


def open_kb(text: str = "▶️ Открыть", start: str = "") -> InlineKeyboardMarkup:
    url = app_url(start)
    if C.WEBAPP_URL:
        btn = InlineKeyboardButton(text=text, web_app=WebAppInfo(url=C.WEBAPP_URL + (f"/?startapp={start}" if start else "")))
    elif url:
        btn = InlineKeyboardButton(text=text, url=url)
    else:
        btn = InlineKeyboardButton(text=text, callback_data="noop")
    return InlineKeyboardMarkup(inline_keyboard=[[btn]])


def build(token: str) -> tuple[Bot, Dispatcher]:
    bot = Bot(token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(router)
    return bot, dp


async def setup_menu(bot: Bot):
    if C.WEBAPP_URL:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Открыть", web_app=WebAppInfo(url=C.WEBAPP_URL)))
    try:
        await bot.set_my_name(C.APP_NAME)
    except Exception as e:  # noqa
        log.warning("set_my_name: %s", e)
    try:
        await bot.set_my_short_description("Короткие видео в Telegram. Свайпай ленту, выкладывай ролики, дари звёзды.")
        await bot.set_my_description(
            "Клипы — лента коротких видео прямо в Telegram.\n\n"
            "Свайпай рекомендации, подписывайся на авторов, оставляй комментарии и кидай подарки за Stars.\n"
            "Чтобы выложить ролик — просто пришли видео в этот чат (до 20 МБ и 90 секунд).\n\n"
            "Буст за 25 ⭐ поднимет ролик в рекомендации на 24 часа."
        )
    except Exception as e:  # noqa
        log.warning("set descriptions: %s", e)
    from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats
    cmds = [
        BotCommand(command="start", description="Открыть Клипы"),
        BotCommand(command="upload", description="Как выложить ролик"),
        BotCommand(command="help", description="Справка"),
    ]
    if C.ADMIN_IDS:
        cmds += [
            BotCommand(command="stats", description="Статистика (админ)"),
            BotCommand(command="delete", description="Удалить ролик: /delete ID"),
        ]
    try:
        await bot.set_my_commands(cmds, scope=BotCommandScopeAllPrivateChats())
    except Exception as e:  # noqa
        log.warning("set_my_commands: %s", e)


async def upsert_from_tg(s, u, now: int) -> User:
    photo_file_id = ""
    try:
        # фото подтянем отдельно, чтобы не тормозить /start
        pass
    except Exception:
        pass
    return await S.get_or_create(s, {
        "id": u.id, "first_name": u.first_name, "last_name": u.last_name or "",
        "username": u.username or "",
    }, now)


@router.message(PRIVATE, CommandStart())
async def cmd_start(m: Message, command: CommandObject):
    arg = (command.args or "").strip()
    now = S.now_ts()
    async with LOCK:
        async with State.sessionmaker() as s:
            await upsert_from_tg(s, m.from_user, now)
            await s.commit()
    if arg == "upload":
        await m.answer("Как выложить ролик 👇\n\n" + UPLOAD_HINT, reply_markup=open_kb("▶️ Открыть ленту"))
        return
    pin = S.parse_start_video(arg)
    start = arg if arg else ""
    text = (
        f"<b>{C.APP_NAME}</b> — {C.APP_TAGLINE}.\n\n"
        "Свайпай ленту, ставь лайки, пиши комментарии и выкладывай свои ролики.\n\n"
        + UPLOAD_HINT
    )
    if pin:
        text = "Тебе кинули ролик 👇 Нажми, чтобы открыть его в ленте."
        start = f"v_{pin}"
    await m.answer(text, reply_markup=open_kb("▶️ Открыть", start=start))


@router.message(PRIVATE, Command("help", "upload"))
async def cmd_help(m: Message):
    await m.answer(UPLOAD_HINT, reply_markup=open_kb())


@router.message(PRIVATE, Command("stats"))
async def cmd_stats(m: Message):
    if m.from_user.id not in C.ADMIN_IDS:
        return
    async with State.sessionmaker() as s:
        users = await s.scalar(select(func.count()).select_from(User))
        videos = await s.scalar(select(func.count()).select_from(Video).where(Video.is_deleted == False))  # noqa
        deleted = await s.scalar(select(func.count()).select_from(Video).where(Video.is_deleted == True))  # noqa
        pays = await s.scalar(select(func.count()).select_from(Payment))
        stars = await s.scalar(select(func.coalesce(func.sum(Payment.stars), 0)))
    await m.answer(
        f"👥 Пользователей: {users}\n"
        f"🎬 Роликов: {videos} (удалено {deleted})\n"
        f"⭐ Оплат: {pays} на {stars} Stars"
    )


@router.message(PRIVATE, Command("delete"))
async def cmd_delete(m: Message, command: CommandObject):
    if m.from_user.id not in C.ADMIN_IDS:
        return
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await m.answer("Напиши так: <code>/delete 12</code> — где 12 это id ролика.")
        return
    async with LOCK:
        async with State.sessionmaker() as s:
            me = await upsert_from_tg(s, m.from_user, S.now_ts())
            try:
                v = await S.delete_video(s, int(arg), me)
                await s.commit()
            except S.AppError as e:
                await s.rollback()
                await m.answer(str(e))
                return
    await m.answer(f"Ролик #{v.id} скрыт.")


def _video_meta(m: Message):
    if m.video:
        v = m.video
        return dict(file_id=v.file_id, file_unique_id=v.file_unique_id, file_size=v.file_size or 0,
                    width=v.width or 0, height=v.height or 0, duration=v.duration or 0,
                    thumb_file_id=(v.thumbnail.file_id if v.thumbnail else ""))
    if m.video_note:
        v = m.video_note
        return dict(file_id=v.file_id, file_unique_id=v.file_unique_id, file_size=v.file_size or 0,
                    width=v.length or 0, height=v.length or 0, duration=v.duration or 0,
                    thumb_file_id=(v.thumbnail.file_id if v.thumbnail else ""))
    if m.document and (m.document.mime_type or "").startswith("video/"):
        d = m.document
        return dict(file_id=d.file_id, file_unique_id=d.file_unique_id, file_size=d.file_size or 0,
                    width=0, height=0, duration=0,
                    thumb_file_id=(d.thumbnail.file_id if d.thumbnail else ""))
    return None


@router.message(PRIVATE, F.video | F.video_note | F.document)
async def on_video(m: Message):
    meta = _video_meta(m)
    if not meta:
        if m.document:
            await m.answer("Это не видео. Пришли ролик как видео, не как файл-архив.")
        return
    err = S.validate_upload(meta["file_size"], meta["duration"])
    if err:
        await m.answer(err)
        return
    caption = (m.caption or m.text or "").strip()
    now = S.now_ts()
    async with LOCK:
        async with State.sessionmaker() as s:
            me = await upsert_from_tg(s, m.from_user, now)
            v = await S.publish_video(s, me, now, caption=caption, **meta)
            await s.commit()
            vid = v.id
    await m.answer(
        f"Ролик #{vid} уже в ленте 🎬\n"
        + (f"<i>{caption}</i>\n" if caption else "")
        + "Открой приложение, чтобы посмотреть, как он выглядит, и забустить его в рекомендации.",
        reply_markup=open_kb("▶️ Смотреть в ленте", start=f"v_{vid}"),
    )


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    ok = False
    try:
        async with State.sessionmaker() as s:
            ok = await S.precheck_payment(s, q.invoice_payload, q.from_user.id, q.total_amount, q.currency)
    except Exception as e:  # noqa
        log.warning("precheckout: %s", e)
        ok = False
    await q.answer(ok=ok, error_message=None if ok else "Не получилось принять оплату, попробуй ещё раз.")


@router.message(F.successful_payment)
async def paid(m: Message):
    sp = m.successful_payment
    now = S.now_ts()
    async with LOCK:
        async with State.sessionmaker() as s:
            try:
                r = await S.apply_payment(
                    s, user_id=m.from_user.id, payload=sp.invoice_payload,
                    stars=sp.total_amount, charge_id=sp.telegram_payment_charge_id, now=now,
                )
                await s.commit()
            except S.AppError as e:
                await s.rollback()
                await m.answer(f"Оплата прошла, но применить не вышло: {e}. Напиши админу.")
                return
    if r.get("duplicate"):
        return
    if r.get("kind") == "boost":
        await m.answer(
            f"Буст включён на {C.BOOST_HOURS} ч 🚀 Ролик поднимется в рекомендациях.",
            reply_markup=open_kb("▶️ К ролику", start=f"v_{r['video_id']}"),
        )
    else:
        await m.answer("Подарок отправлен автору ✨", reply_markup=open_kb("▶️ К ролику", start=f"v_{r['video_id']}"))
        to_id = r.get("to_user_id")
        if to_id and State.notifier:
            g = C.GIFTS.get(r.get("gift_id") or "") or {}
            emoji = g.get("emoji") or "⭐"
            name = m.from_user.first_name or "Кто-то"
            try:
                await State.notifier(to_id, f"{name} отправил(а) тебе {emoji} за ролик #{r['video_id']}!")
            except Exception:
                pass


@router.inline_query()
async def inline_q(q: InlineQuery):
    # Карточки для «Поделиться» и @бота в чатах
    text = (q.query or "").strip()
    results = []
    async with State.sessionmaker() as s:
        me = await S.get_or_create(s, {
            "id": q.from_user.id, "first_name": q.from_user.first_name,
            "last_name": q.from_user.last_name or "", "username": q.from_user.username or "",
        }, S.now_ts())
        await s.commit()
        now = S.now_ts()
        items = []
        if text.isdigit():
            v = await s.get(Video, int(text))
            if v and not v.is_deleted:
                author = await s.get(User, v.author_id)
                if author:
                    items = [S.ser_video(v, author, now)]
        if not items:
            items = await S.feed(s, me, now, tab="for_you", limit=8)
    for it in items[:8]:
        link = it["share"]
        title = (it["caption"] or "Ролик").split("\n")[0][:64]
        desc = f"{it['author']['name']} · {it['likes']}❤ · {it['views']} просм."
        results.append(InlineQueryResultArticle(
            id=f"v{it['id']}",
            title=title,
            description=desc,
            input_message_content=InputTextMessageContent(
                message_text=f"🎬 {title}\n{desc}\n{link}"
            ),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="▶️ Смотреть в Клипах", url=link if link.startswith("https://t.me/") else app_url(f"v_{it['id']}"))
            ]]),
        ))
    await q.answer(results, cache_time=10, is_personal=True,
                   switch_pm_text="Открыть Клипы", switch_pm_parameter="app")


async def make_invoice(user_id: int, title: str, stars: int, payload: str) -> str:
    bot = State.bot
    if not bot:
        raise S.AppError("Бот не запущен")
    prices = [LabeledPrice(label=title[:32], amount=stars)]
    if hasattr(bot, "create_invoice_link"):
        return await bot.create_invoice_link(
            title=title[:32], description=title, payload=payload,
            currency="XTR", prices=prices, provider_token="",
        )
    # запасной путь — отправим инвойс в личку
    await bot.send_invoice(
        chat_id=user_id, title=title[:32], description=title, payload=payload,
        currency="XTR", prices=prices, provider_token="",
    )
    return ""


async def notify(user_id: int, text: str):
    bot = State.bot
    if not bot:
        return
    try:
        await bot.send_message(user_id, text, reply_markup=open_kb())
    except Exception as e:  # noqa
        log.info("notify skip %s: %s", user_id, e)
