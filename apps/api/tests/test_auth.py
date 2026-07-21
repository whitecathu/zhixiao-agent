"""tests/test_auth.py
认证核心接口单测 - 注册 / 登录 / me
"""
import pytest


@pytest.mark.asyncio
async def test_register_and_login(client):
    # 注册
    resp = await client.post("/api/v1/auth/register", json={
        "username": "alice",
        "email": "alice@example.com",
        "password": "Str0ngPwd!",
        "nickname": "Alice",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["username"] == "alice"

    # 登录
    resp = await client.post("/api/v1/auth/login", json={
        "username": "alice", "password": "Str0ngPwd!",
    })
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["user"]["email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post("/api/v1/auth/register", json={
        "username": "bob", "email": "bob@example.com",
        "password": "AnotherPwd1",
    })
    for _ in range(2):
        resp = await client.post("/api/v1/auth/login", json={
            "username": "bob", "password": "wrong",
        })
        assert resp.json()["code"] == 100006  # AUTH_LOGIN_FAIL


@pytest.mark.asyncio
async def test_me_requires_token(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_register_duplicate_username(client):
    payload = {
        "username": "carol", "email": "carol@example.com",
        "password": "Str0ngPwd!",
    }
    r = await client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 200
    r = await client.post("/api/v1/auth/register", json={
        "username": "carol", "email": "carol2@example.com",
        "password": "Str0ngPwd!",
    })
    assert r.json()["code"] == 110001  # USER_EXISTS