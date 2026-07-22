def _make_admin(client, db_session):
    """Register a normal user then promote them to admin directly via the
    repository, since there is no public signup path for admins (by design)."""
    resp = client.post(
        "/api/v1/auth/register", json={"username": "root", "email": "root@example.com", "password": "supersecret1"}
    )
    user_id = resp.json()["user"]["id"]
    token = resp.json()["token"]["access_token"]

    from app.infrastructure.models import UserModel

    db_user = db_session.get(UserModel, user_id)
    db_user.role = "admin"
    db_session.commit()

    return {"Authorization": f"Bearer {token}"}


def test_non_admin_cannot_access_admin_routes(client, auth_headers):
    headers = auth_headers()
    resp = client.get("/api/v1/admin/stats", headers=headers)
    assert resp.status_code == 403


def test_admin_can_view_stats(client, db_session):
    admin_headers = _make_admin(client, db_session)
    resp = client.get("/api/v1/admin/stats", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_users"] == 1


def test_admin_can_list_and_search_users(client, db_session, auth_headers):
    admin_headers = _make_admin(client, db_session)
    auth_headers(username="alex", email="alex@example.com")
    auth_headers(username="sam", email="sam@example.com")

    resp = client.get("/api/v1/admin/users", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 3

    resp = client.get("/api/v1/admin/users", params={"search": "alex"}, headers=admin_headers)
    usernames = {u["username"] for u in resp.json()["users"]}
    assert usernames == {"alex"}


def test_admin_can_suspend_and_reactivate_a_user(client, db_session, auth_headers):
    admin_headers = _make_admin(client, db_session)
    user_headers = auth_headers(username="alex", email="alex@example.com")

    me = client.get("/api/v1/auth/me", headers=user_headers).json()

    resp = client.post(f"/api/v1/admin/users/{me['id']}/suspend", headers=admin_headers)
    assert resp.status_code == 204

    # A suspended user's existing token should no longer authenticate
    resp = client.get("/api/v1/auth/me", headers=user_headers)
    assert resp.status_code == 401

    resp = client.post(f"/api/v1/admin/users/{me['id']}/reactivate", headers=admin_headers)
    assert resp.status_code == 204

    resp = client.get("/api/v1/auth/me", headers=user_headers)
    assert resp.status_code == 200


def test_admin_can_delete_a_user_and_their_data_cascades(client, db_session, auth_headers):
    admin_headers = _make_admin(client, db_session)
    user_headers = auth_headers(username="alex", email="alex@example.com")
    me = client.get("/api/v1/auth/me", headers=user_headers).json()

    client.post(
        "/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=user_headers
    )

    resp = client.delete(f"/api/v1/admin/users/{me['id']}", headers=admin_headers)
    assert resp.status_code == 204

    resp = client.get("/api/v1/auth/me", headers=user_headers)
    assert resp.status_code == 401

    from app.infrastructure.models import GroupModel

    remaining_groups = db_session.query(GroupModel).filter_by(owner_id=me["id"]).all()
    assert remaining_groups == []
