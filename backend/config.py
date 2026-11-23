"""Настройки: .env + config/prices.json"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip().lstrip("@")
APP_SHORT_NAME = os.getenv("APP_SHORT_NAME", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip().rstrip("/")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
DB_URL = os.getenv("DB_URL", f"sqlite+aiosqlite:///{ROOT / 'clips.db'}")
DEV_MODE = os.getenv("DEV_MODE", "0") == "1"
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))
MAX_VIDEO_BYTES = int(os.getenv("MAX_VIDEO_BYTES", str(20 * 1024 * 1024)))
MAX_DURATION_SEC = int(os.getenv("MAX_DURATION_SEC", "90"))

PRICES = json.loads((ROOT / "config" / "prices.json").read_text(encoding="utf-8"))
BOOST_STARS = int(PRICES.get("boost_stars", 25))
BOOST_HOURS = int(PRICES.get("boost_hours", 24))
GIFTS = {g["id"]: g for g in PRICES.get("gifts", [])}

APP_NAME = "Клипы"
APP_TAGLINE = "Короткие видео в Telegram"
