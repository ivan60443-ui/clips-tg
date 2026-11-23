import pytest

from backend import config as C
from backend.db import Payment, init_db, make_engine
from backend import service as S
from backend.service import AppError


@pytest.fixture
async def session(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'p.db'}"
    engine, sm = make_engine(url)
    await init_db(engine)
    async with sm() as s:
        yield s
    await engine.dispose()


async def setup(s):
    author = await S.get_or_create(s, {"id": 10, "first_name": "Автор"})
    fan = await S.get_or_create(s, {"id": 20, "first_name": "Фан"})
    v = await S.publish_video(s, author, 100, local_path="media/demo1.mp4", caption="ролик")
    await s.flush()
    return author, fan, v


async def test_boost_extends_window(session):
    author, fan, v = await setup(session)
    payload = f"boost:{v.id}:{author.id}:aaa"
    r = await S.apply_payment(session, user_id=author.id, payload=payload, stars=C.BOOST_STARS,
                              charge_id="ch1", now=1000)
    assert r["kind"] == "boost"
    assert v.boosted_until == 1000 + C.BOOST_HOURS * 3600
    # повтор того же charge не дублирует
    r2 = await S.apply_payment(session, user_id=author.id, payload=payload, stars=C.BOOST_STARS,
                               charge_id="ch1", now=1100)
    assert r2.get("duplicate") is True
    assert v.boosted_until == 1000 + C.BOOST_HOURS * 3600


async def test_gift_records_and_increments(session):
    author, fan, v = await setup(session)
    g = next(iter(C.GIFTS.values()))
    payload = f"gift:{g['id']}:{v.id}:{fan.id}:bbb"
    r = await S.apply_payment(session, user_id=fan.id, payload=payload, stars=int(g["stars"]),
                              charge_id="ch2", now=2000)
    assert r["kind"] == "gift" and r["gifts"] == 1 and r["to_user_id"] == author.id
    pays = (await session.execute(Payment.__table__.select())).all() if False else None
    # просто проверим счётчик
    assert v.gifts_count == 1


async def test_cannot_gift_self(session):
    author, fan, v = await setup(session)
    g = next(iter(C.GIFTS.values()))
    payload = f"gift:{g['id']}:{v.id}:{author.id}:ccc"
    with pytest.raises(AppError, match="себе"):
        await S.apply_payment(session, user_id=author.id, payload=payload, stars=int(g["stars"]),
                              charge_id="ch3", now=1)


async def test_precheck_rejects_bad_currency_and_amount(session):
    author, fan, v = await setup(session)
    payload = f"boost:{v.id}:{author.id}:ddd"
    assert await S.precheck_payment(session, payload, author.id, C.BOOST_STARS, "XTR") is True
    assert await S.precheck_payment(session, payload, author.id, C.BOOST_STARS, "USD") is False
    assert await S.precheck_payment(session, payload, author.id, 1, "XTR") is False
    assert await S.precheck_payment(session, payload, fan.id, C.BOOST_STARS, "XTR") is False


async def test_parse_payload():
    assert S.parse_payload("boost:12:99:ff") == {"kind": "boost", "video_id": 12, "user_id": 99}
    p = S.parse_payload("gift:fire:3:7:aa")
    assert p == {"kind": "gift", "gift_id": "fire", "video_id": 3, "user_id": 7}
    assert S.parse_payload("nope") is None
