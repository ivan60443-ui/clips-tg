import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api import State, public, router
from backend.db import init_db, make_engine
from backend.service import get_or_create, now_ts, publish_video
from backend import config as C

C.DEV_MODE = True


def build_app():
    app = FastAPI()
    app.include_router(router)
    app.include_router(public)

    @app.get("/health")
    async def health():
        return {"ok": True, "app": "Клипы"}

    return app


@pytest.fixture
async def client(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'api.db'}"
    engine, sm = make_engine(url)
    await init_db(engine)
    State.sessionmaker = sm
    async with sm() as s:
        await get_or_create(s, {"id": 643246726, "first_name": "Ваня", "username": "nikolavee"})
        author = await get_or_create(s, {"id": 900001, "first_name": "Маша", "username": "masha_clips"})
        await publish_video(s, author, now_ts(), local_path="media/demo1.mp4", caption="демо")
        await s.commit()
    transport = ASGITransport(app=build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await engine.dispose()


def h(uid=643246726):
    return {"X-Dev-User": str(uid)}


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200 and r.json()["ok"] is True


async def test_bootstrap_like_view_comment(client):
    r = await client.get("/api/bootstrap", headers=h())
    assert r.status_code == 200
    data = r.json()
    assert data["me"]["id"] == 643246726
    assert data["feed"] and data["feed"][0]["caption"] == "демо"
    vid = data["feed"][0]["id"]
    like = await client.post(f"/api/video/{vid}/like", headers=h())
    assert like.json()["liked"] is True and like.json()["likes"] == 1
    view = await client.post(f"/api/video/{vid}/view", headers=h())
    assert view.json()["views"] >= 1
    c = await client.post(f"/api/video/{vid}/comments", headers=h(), json={"text": "огонь"})
    assert c.json()["text"] == "огонь"
    listed = await client.get(f"/api/video/{vid}/comments", headers=h())
    assert listed.json()["items"][0]["text"] == "огонь"


async def test_follow_profile_and_unauthorized(client):
    r = await client.post("/api/users/900001/follow", headers=h())
    assert r.json()["followed"] is True
    p = await client.get("/api/users/900001", headers=h())
    assert p.json()["user"]["followed"] is True
    assert p.json()["user"]["followers"] == 1
    noauth = await client.get("/api/bootstrap")
    assert noauth.status_code == 401
