import json
import time

import pytest

from backend.auth import AuthError, sign_init_data, validate_init_data

TOKEN = "123456:TESTTOKEN-clips"


def test_sign_and_validate_ok():
    user = {"id": 643246726, "first_name": "Ваня", "username": "nikolavee"}
    raw = sign_init_data({
        "user": json.dumps(user, ensure_ascii=False, separators=(",", ":")),
        "auth_date": str(int(time.time())),
        "query_id": "AAE",
    }, TOKEN)
    data = validate_init_data(raw, TOKEN)
    assert data["user"]["id"] == 643246726
    assert data["user"]["first_name"] == "Ваня"


def test_bad_hash_rejected():
    user = {"id": 1, "first_name": "X"}
    raw = sign_init_data({
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(int(time.time())),
    }, TOKEN)
    with pytest.raises(AuthError, match="bad hash"):
        validate_init_data(raw + "ff", TOKEN)


def test_expired_rejected():
    user = {"id": 1, "first_name": "X"}
    raw = sign_init_data({
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(int(time.time()) - 100000),
    }, TOKEN)
    with pytest.raises(AuthError, match="expired"):
        validate_init_data(raw, TOKEN, max_age=60)


def test_no_user_rejected():
    raw = sign_init_data({"auth_date": str(int(time.time())), "user": "{}"}, TOKEN)
    with pytest.raises(AuthError, match="no user"):
        validate_init_data(raw, TOKEN)


def test_missing_init_data():
    with pytest.raises(AuthError):
        validate_init_data("", TOKEN)
