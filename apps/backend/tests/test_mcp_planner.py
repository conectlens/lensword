from app.application.mcp.planner import CommandPlanner
from app.domain.entities import Group
from app.domain.value_objects import SupportedLanguage
from app.infrastructure.models import MCPGrantModel


def group(id=7, name="Spanish"):
    return Group(id=id, owner_id=1, name=name, target_language=SupportedLanguage.SPANISH)


def test_session_command_emits_a_confirmable_typed_preview():
    plan = CommandPlanner().plan("prepare a 15-minute session in Spanish", [group()])
    assert plan.executable and plan.requires_confirmation
    assert plan.steps[0].tool == "lensword.create_study_session"
    assert plan.steps[0].payload == {"limit": 30, "group_id": 7, "request_id": plan.steps[0].payload["request_id"]}


def test_extraction_resolves_group_source_and_cefr_without_unregistered_tools():
    plan = CommandPlanner().plan("extract unfamiliar B2+ words from this PDF in Spanish", [group()], source_text="hola mundo")
    assert plan.executable and plan.steps[0].tool == "lensword.extract_vocabulary"
    assert plan.steps[0].payload["target_language"] == "Spanish"
    assert any("CEFR threshold B2" in assumption for assumption in plan.assumptions)


def test_ambiguous_missing_and_unavailable_commands_fail_closed():
    groups = [group(1, "Spanish"), group(2, "Spanish travel")]
    assert not CommandPlanner().plan("prepare a session", groups).executable
    assert not CommandPlanner().plan("extract words", groups).executable
    assert not CommandPlanner(capabilities=[]).plan("prepare a 15-minute session in Spanish", [group()]).executable


def test_preview_requires_confirmation_and_can_be_cancelled(client, auth_headers):
    headers = auth_headers()
    created = client.post("/api/v1/groups", headers=headers, json={"name": "Spanish", "target_language": "Spanish"})
    assert created.status_code == 201
    preview = client.post("/api/v1/mcp/plans/preview", headers=headers, json={"command": "prepare a 15-minute session in Spanish", "requester": "planner", "workspace": "/approved"})
    assert preview.status_code == 200 and preview.json()["requires_confirmation"]
    plan_id = preview.json()["id"]
    assert client.post(f"/api/v1/mcp/plans/{plan_id}/execute", headers=headers, json={}).status_code == 409
    assert client.post(f"/api/v1/mcp/plans/{plan_id}/execute", headers=headers, json={"cancelled": True}).json() == {"status": "cancelled", "steps": []}


def test_execution_returns_per_step_denial_without_rolling_back_preview(client, auth_headers, db_session):
    headers = auth_headers()
    created = client.post("/api/v1/groups", headers=headers, json={"name": "Spanish", "target_language": "Spanish"})
    assert created.status_code == 201
    assert client.post(f"/api/v1/groups/{created.json()['id']}/words", headers=headers, json={"term": "hola", "target_language": "Spanish", "translations": ["hello"]}).status_code == 201
    preview = client.post("/api/v1/mcp/plans/preview", headers=headers, json={"command": "prepare a 15-minute session in Spanish", "requester": "planner", "workspace": "/approved"}).json()
    denied = client.post(f"/api/v1/mcp/plans/{preview['id']}/execute", headers=headers, json={"confirmed": True})
    assert denied.status_code == 200 and denied.json()["status"] == "partial_failure"
    db_session.add(MCPGrantModel(requester="planner", server="lensword", tool="lensword.create_study_session", access="write", workspace="/approved", mode="always")); db_session.flush()
    retry = client.post("/api/v1/mcp/plans/preview", headers=headers, json={"command": "prepare a 15-minute session in Spanish", "requester": "planner", "workspace": "/approved"}).json()
    assert client.post(f"/api/v1/mcp/plans/{retry['id']}/execute", headers=headers, json={"confirmed": True}).json()["status"] == "completed"
