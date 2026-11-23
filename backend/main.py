"""Точка входа: FastAPI (API + статика Mini App) + aiogram-бот в одном процессе."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config as C
from .api import State, public, router
from .db import init_db, make_engine
from .seed import seed_demo
from .service import now_ts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("clips")
WEB = C.ROOT / "webapp"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
BOTREF: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine, sm = make_engine(C.DB_URL)
    await init_db(engine)
    State.sessionmaker = sm
    if C.DEV_MODE or os.getenv("SEED_DEMO", "1") == "1":
        async with sm() as s:
            n = await seed_demo(s, now=now_ts())
            await s.commit()
            if n:
                log.info("Seeded %s demo videos", n)
    task = None
    if C.BOT_TOKEN and os.getenv("RUN_BOT", "1") == "1":
        from .bot import build, make_invoice, notify, setup_menu
        bot, dp = build(C.BOT_TOKEN)
        BOTREF["bot"], BOTREF["dp"] = bot, dp
        State.bot = bot
        State.notifier = notify
        State.make_invoice = make_invoice
        try:
            me = await bot.get_me()
            if not C.BOT_USERNAME:
                C.BOT_USERNAME = me.username or C.BOT_USERNAME
            await setup_menu(bot)
            log.info("Bot @%s started, webapp %s", me.username, C.WEBAPP_URL)
        except Exception as e:  # noqa
            log.error("Bot setup failed: %s", e)
        if WEBHOOK_SECRET and C.WEBAPP_URL.startswith("https://"):
            try:
                await bot.set_webhook(
                    f"{C.WEBAPP_URL}/tg/{WEBHOOK_SECRET}",
                    secret_token=WEBHOOK_SECRET,
                    allowed_updates=dp.resolve_used_update_types(),
                    drop_pending_updates=False,
                )
                log.info("Webhook mode")
            except Exception as e:  # noqa
                log.error("set_webhook failed: %s", e)
        else:
            try:
                await bot.delete_webhook(drop_pending_updates=False)
            except Exception as e:  # noqa
                log.warning("delete_webhook: %s", e)
            task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
    else:
        log.warning("BOT_TOKEN не задан — бот не запущен (только API/веб)")
    yield
    if task:
        task.cancel()
        try:
            await task
        except Exception:
            pass
    await engine.dispose()


app = FastAPI(title="Клипы", lifespan=lifespan)
app.include_router(router)
app.include_router(public)


@app.post("/tg/{secret}")
async def tg_webhook(secret: str, request: Request):
    if not WEBHOOK_SECRET or secret != WEBHOOK_SECRET or \
            request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET or not BOTREF:
        return JSONResponse({"ok": False}, status_code=403)
    from aiogram.types import Update
    upd = Update.model_validate(await request.json(), context={"bot": BOTREF["bot"]})
    await BOTREF["dp"].feed_update(BOTREF["bot"], upd)
    return {"ok": True}


@app.get("/health")
async def health():
    return {"ok": True, "app": C.APP_NAME}


@app.get("/")
async def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/", StaticFiles(directory=WEB), name="web")


if __name__ == "__main__":
    uvicorn.run("backend.main:app", host=C.HOST, port=int(os.getenv("PORT", C.PORT)),
                proxy_headers=True, forwarded_allow_ips="*")
