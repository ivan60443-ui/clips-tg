"""Проверка initData Telegram Mini App."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl, urlencode


class AuthError(Exception):
    pass


def validate_init_data(init_data: str, bot_token: str, max_age: int = 86400) -> dict:
    if not init_data or not bot_token:
        raise AuthError("no init data")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise AuthError("no hash")
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received_hash):
        raise AuthError("bad hash")
    auth_date = int(pairs.get("auth_date", "0") or 0)
    if max_age and time.time() - auth_date > max_age:
        raise AuthError("init data expired")
    user = json.loads(pairs.get("user", "{}") or "{}")
    if not user.get("id"):
        raise AuthError("no user")
    return {"user": user, "start_param": pairs.get("start_param", ""), "auth_date": auth_date}


def sign_init_data(fields: dict, bot_token: str) -> str:
    """Для тестов: собрать валидную initData."""
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret_key, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": h})
