from datetime import datetime, timedelta, timezone


def register(client, email: str):
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password-123"},
    )
    assert response.status_code == 201
    return response.json()


def test_user_cannot_list_or_change_plans(client):
    register(client, "user@example.com")
    assert client.get("/api/admin/users").status_code == 403
    assert client.patch(
        "/api/admin/users/1",
        json={"plan": "paid", "plan_expires_at": "2026-10-01T00:00:00Z"},
    ).status_code == 403


def test_admin_sets_paid_until_expiry(client):
    user = register(client, "user@example.com")
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "admin-pass-123"},
    )
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    updated = client.patch(
        f"/api/admin/users/{user['id']}",
        json={"plan": "paid", "plan_expires_at": future},
    )
    assert updated.status_code == 200
    assert updated.json()["plan"] == "paid"
    assert updated.json()["effective_plan"] == "paid"
    assert updated.json()["paid_features"] is True

    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "user@example.com", "password": "password-123"})
    me = client.get("/api/auth/me")
    assert me.json()["effective_plan"] == "paid"
    assert me.json()["paid_features"] is True


def test_expired_paid_user_is_free(client):
    user = register(client, "user@example.com")
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "admin-pass-123"},
    )
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    updated = client.patch(
        f"/api/admin/users/{user['id']}",
        json={"plan": "paid", "plan_expires_at": past},
    )
    assert updated.status_code == 200
    assert updated.json()["plan"] == "paid"
    assert updated.json()["effective_plan"] == "free"
    assert updated.json()["paid_features"] is False


def test_paid_without_expiry_is_rejected(client):
    user = register(client, "user@example.com")
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "admin-pass-123"},
    )
    response = client.patch(f"/api/admin/users/{user['id']}", json={"plan": "paid"})
    assert response.status_code == 422


def test_setting_free_clears_expiry(client):
    user = register(client, "user@example.com")
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "admin-pass-123"},
    )
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    client.patch(
        f"/api/admin/users/{user['id']}",
        json={"plan": "paid", "plan_expires_at": future},
    )
    cleared = client.patch(
        f"/api/admin/users/{user['id']}",
        json={"plan": "free", "plan_expires_at": future},
    )
    assert cleared.status_code == 200
    assert cleared.json()["plan"] == "free"
    assert cleared.json()["plan_expires_at"] is None
    assert cleared.json()["effective_plan"] == "free"


def test_unauthenticated_admin_route_is_rejected(client):
    assert client.get("/api/admin/users").status_code == 401
