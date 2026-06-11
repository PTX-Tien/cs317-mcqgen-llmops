"""Test luồng đăng nhập /auth/login."""


def test_login_missing_password_returns_422(client):
    resp = client.post("/auth/login", data={"username": "admin", "password": ""})
    assert resp.status_code == 422


def test_login_unknown_user_returns_401(client):
    resp = client.post(
        "/auth/login",
        data={"username": "khong_ton_tai_xyz", "password": "whatever"},
    )
    assert resp.status_code == 401


def test_login_admin_success(client, admin_token):
    # admin_token fixture đã login thành công (nếu không sẽ skip)
    assert isinstance(admin_token, str) and len(admin_token) > 10


def test_me_requires_token(client):
    resp = client.get("/auth/me")  # không kèm Bearer token
    assert resp.status_code in {401, 403}
