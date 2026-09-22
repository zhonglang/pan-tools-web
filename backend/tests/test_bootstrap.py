def test_startup_creates_admin(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "admin-pass-123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "admin"
    assert body["paid_features"] is True
    assert "password" not in body
