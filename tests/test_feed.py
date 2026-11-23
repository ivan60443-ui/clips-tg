import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import Like, User, Video, init_db, make_engine
from backend import service as S
from backend.service import AppError


@pytest.fixture
async def session(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 't.db'}"
    engine, sm = make_engine(url)
    await init_db(engine)
    async with sm() as s:
        yield s
    await engine.dispose()


async def mk(s, uid=1, name="Анна"):
    u = await S.get_or_create(s, {"id": uid, "first_name": name})
    await s.flush()
    return u


async def clip(s, author, caption="привет", likes=0, views=0, ago=0, boosted=0):
    now = 1_700_000_000
    v = await S.publish_video(s, author, now - ago, local_path="media/demo1.mp4",
                              caption=caption, width=720, height=1280, duration=4)
    v.likes_count = likes
    v.views = views
    v.boosted_until = boosted
    await s.flush()
    return v


async def test_get_or_create_updates_name(session):
    u = await S.get_or_create(session, {"id": 10, "first_name": "Иван"})
    assert u.first_name == "Иван"
    u2 = await S.get_or_create(session, {"id": 10, "first_name": "Ваня", "username": "nikolavee"})
    assert u2.id == 10
    assert u2.first_name == "Ваня"
    assert u2.username == "nikolavee"


async def test_validate_upload_size_and_duration():
    assert S.validate_upload(1024, 10) is None
    err = S.validate_upload(21 * 1024 * 1024, 10)
    assert err and "МБ" in err
    err2 = S.validate_upload(1000, 200)
    assert err2 and "длинный" in err2


async def test_publish_rejects_too_big(session):
    u = await mk(session)
    with pytest.raises(AppError, match="тяжёл"):
        await S.publish_video(session, u, S.now_ts(), file_id="x", file_size=30 * 1024 * 1024, duration=5)


async def test_toggle_like_and_counts(session):
    a = await mk(session, 1, "А")
    me = await mk(session, 2, "Б")
    v = await clip(session, a)
    r = await S.toggle_like(session, me, v.id, 10)
    assert r["liked"] is True and r["likes"] == 1
    r = await S.toggle_like(session, me, v.id, 11)
    assert r["liked"] is False and r["likes"] == 0


async def test_views_count_once(session):
    a = await mk(session, 1)
    me = await mk(session, 2)
    v = await clip(session, a)
    assert (await S.add_view(session, me, v.id, 1))["views"] == 1
    assert (await S.add_view(session, me, v.id, 2))["views"] == 1  # тот же зритель
    other = await mk(session, 3)
    assert (await S.add_view(session, other, v.id, 3))["views"] == 2


async def test_comments(session):
    a = await mk(session, 1)
    me = await mk(session, 2, "Ваня")
    v = await clip(session, a)
    c = await S.add_comment(session, me, v.id, "огонь", 5)
    assert c["text"] == "огонь" and c["comments"] == 1
    items = await S.list_comments(session, v.id)
    assert len(items) == 1 and items[0]["author"]["name"] == "Ваня"
    with pytest.raises(AppError):
        await S.add_comment(session, me, v.id, "   ", 6)


async def test_follow_and_following_feed(session):
    a = await mk(session, 1, "Маша")
    me = await mk(session, 2, "Ваня")
    v = await clip(session, a, "её ролик")
    await clip(session, me, "мой")
    empty = await S.feed(session, me, 1_700_000_000, tab="following")
    assert empty == []
    r = await S.toggle_follow(session, me, a.id, 1)
    assert r["followed"] is True and r["followers"] == 1
    items = await S.feed(session, me, 1_700_000_000, tab="following")
    assert len(items) == 1 and items[0]["id"] == v.id
    await S.toggle_follow(session, me, a.id, 2)
    assert await S.feed(session, me, 1_700_000_000, tab="following") == []
    with pytest.raises(AppError):
        await S.toggle_follow(session, me, me.id, 3)


async def test_ranking_prefers_likes_and_boost(session):
    now = 1_700_000_000
    a = await mk(session, 1)
    me = await mk(session, 9)
    old_hot = await clip(session, a, "старый хит", likes=50, views=100, ago=20 * 3600)
    fresh = await clip(session, a, "свежий", likes=1, views=5, ago=600)
    boosted = await clip(session, a, "буст", likes=0, views=0, ago=3600, boosted=now + 1000)
    items = await S.feed(session, me, now, tab="for_you")
    ids = [i["id"] for i in items]
    assert ids[0] == boosted.id
    # хит с кучей лайков обгоняет почти пустой свежий
    assert ids.index(old_hot.id) < ids.index(fresh.id)


async def test_pin_video_goes_first(session):
    a = await mk(session, 1)
    me = await mk(session, 2)
    v1 = await clip(session, a, "один", likes=10)
    v2 = await clip(session, a, "два", likes=1)
    items = await S.feed(session, me, 1_700_000_000, pin_id=v2.id)
    assert items[0]["id"] == v2.id
    assert {i["id"] for i in items} == {v1.id, v2.id}


async def test_report_and_delete(session):
    from backend import config as C
    a = await mk(session, 1)
    me = await mk(session, 2)
    admin = await mk(session, 643246726)
    C.ADMIN_IDS.add(643246726)
    v = await clip(session, a)
    r = await S.report_video(session, me, v.id, "спам", 1)
    assert r["reports"] == 1 and r["already"] is False
    r2 = await S.report_video(session, me, v.id, "ещё раз", 2)
    assert r2["already"] is True and r2["reports"] == 1
    with pytest.raises(AppError):
        await S.delete_video(session, v.id, me)
    await S.delete_video(session, v.id, admin)
    items = await S.feed(session, me, 1_700_000_000)
    assert items == []


async def test_profile_grid(session):
    a = await mk(session, 1, "Маша")
    me = await mk(session, 2)
    await clip(session, a, "1")
    await clip(session, a, "2")
    p = await S.profile(session, me, a.id, 1_700_000_000)
    assert p["user"]["videos"] == 2
    assert p["user"]["is_me"] is False
    assert len(p["videos"]) == 2


async def test_parse_start_and_share_link():
    assert S.parse_start_video("v_42") == 42
    assert S.parse_start_video("ref_1") is None
    from backend import config as C
    C.BOT_USERNAME = "Districtt13bot"
    C.APP_SHORT_NAME = "clips"
    assert S.share_link(7) == "https://t.me/Districtt13bot/clips?startapp=v_7"


async def test_feed_score_monotonic():
    now = 1000
    v = Video(likes_count=0, comments_count=0, views=0, created_at=now, boosted_until=0)
    base = S.feed_score(v, now)
    v.likes_count = 10
    assert S.feed_score(v, now) > base
    v.boosted_until = now + 10
    assert S.feed_score(v, now) > 5000
