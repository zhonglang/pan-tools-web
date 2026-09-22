def test_register_sets_httponly_cookie_and_hides_password(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "User@Example.com", "password": "password-123"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "user@example.com"
    assert body["role"] == "user"
    assert body["plan"] == "free"
    assert body["effective_plan"] == "free"
    assert body["paid_features"] is False
    assert "password" not in body
    assert "password_hash" not in body
    cookie = response.headers["set-cookie"]
    assert "access_token=" in cookie
    assert "HttpOnly" in cookie


def test_register_rejects_short_password(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "user@example.com", "password": "short"},
    )
    assert response.status_code == 422


def test_register_rejects_duplicate_email(client):
    payload = {"email": "user@example.com", "password": "password-123"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    again = client.post("/api/auth/register", json=payload)
    assert again.status_code == 409
    assert again.json()["detail"] == "邮箱已注册"


def test_logout_clears_session_cookie_with_matching_attributes(client):
    client.post(
        "/api/auth/register",
        json={"email": "user@example.com", "password": "password-123"},
    )
    client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "password-123"},
    )
    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    cookie = logout.headers.get("set-cookie", "")
    assert "access_token=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" not in cookie


def test_login_and_me(client):
    client.post("/api/auth/register", json={"email": "user@example.com", "password": "password-123"})
    client.post("/api/auth/logout")
    denied = client.get("/api/auth/me")
    assert denied.status_code == 401

    logged_in = client.post(
        "/api/auth/login",
        json={"email": "USER@example.com", "password": "password-123"},
    )
    assert logged_in.status_code == 200
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "user@example.com"


def test_login_rejects_bad_password(client):
    client.post("/api/auth/register", json={"email": "user@example.com", "password": "password-123"})
    response = client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "wrong-pass-123"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "邮箱或密码错误"


def test_login_rejects_unknown_email(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "missing@example.com", "password": "password-123"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "邮箱或密码错误"
