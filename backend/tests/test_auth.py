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
