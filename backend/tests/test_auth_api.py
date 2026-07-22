def test_register_creates_account_and_returns_token(client):
    resp = client.post(
        "/api/v1/auth/register",
        json={"username": "alex", "email": "alex@example.com", "password": "supersecret1"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["user"]["username"] == "alex"
    assert body["user"]["email"] == "alex@example.com"
    assert body["user"]["role"] == "user"
    assert body["token"]["access_token"]


def test_register_rejects_duplicate_email(client):
    payload = {"username": "alex", "email": "alex@example.com", "password": "supersecret1"}
    client.post("/api/v1/auth/register", json=payload)
    resp = client.post("/api/v1/auth/register", json={**payload, "username": "alex2"})
    assert resp.status_code == 409


def test_register_rejects_duplicate_username(client):
    client.post(
        "/api/v1/auth/register", json={"username": "alex", "email": "a@example.com", "password": "supersecret1"}
    )
    resp = client.post(
        "/api/v1/auth/register", json={"username": "alex", "email": "b@example.com", "password": "supersecret1"}
    )
    assert resp.status_code == 409


def test_register_rejects_short_password(client):
    resp = client.post(
        "/api/v1/auth/register", json={"username": "alex", "email": "a@example.com", "password": "short"}
    )
    assert resp.status_code == 422


def test_login_succeeds_with_correct_credentials(client):
    client.post(
        "/api/v1/auth/register", json={"username": "alex", "email": "alex@example.com", "password": "supersecret1"}
    )
    resp = client.post("/api/v1/auth/login", json={"email": "alex@example.com", "password": "supersecret1"})
    assert resp.status_code == 200
    assert resp.json()["token"]["access_token"]


def test_login_rejects_wrong_password(client):
    client.post(
        "/api/v1/auth/register", json={"username": "alex", "email": "alex@example.com", "password": "supersecret1"}
    )
    resp = client.post("/api/v1/auth/login", json={"email": "alex@example.com", "password": "wrongpassword"})
    assert resp.status_code == 401


def test_login_rejects_unknown_email(client):
    resp = client.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "supersecret1"})
    assert resp.status_code == 401


def test_me_requires_authentication(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_me_returns_current_user_with_valid_token(client, auth_headers):
    headers = auth_headers()
    resp = client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == "alex"


def test_me_rejects_garbage_token(client):
    resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401
