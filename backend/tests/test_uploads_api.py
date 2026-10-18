import io
import time

import httpx

from app.services import uploads as uploads_service
from tests.test_transfers import bind, install, register
from tests.test_uploads_service import FakeAdapter


def wait_upload(client, task_id: int, *, timeout: float = 3.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = client.get("/api/uploads").json()
        row = next((item for item in rows if item["id"] == task_id), None)
        if row and row["status"] != "running":
            return row
        time.sleep(0.05)
    rows = client.get("/api/uploads").json()
    return next(item for item in rows if item["id"] == task_id)


def test_upload_file_creates_task(client, monkeypatch):
    register(client)
    account_id = bind(client)
    fake = FakeAdapter()
    monkeypatch.setattr(uploads_service, "adapter_for", lambda provider, client: fake)

    def handler(request: httpx.Request) -> httpx.Response:
        if "gettemplatevariable" in str(request.url):
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        raise AssertionError(str(request.url))

    install(client, handler)
    response = client.post(
        f"/api/accounts/{account_id}/files/upload",
        data={"dest": "/测试", "relative_paths": "folder/a.txt"},
        files=[("files", ("a.txt", io.BytesIO(b"hello"), "application/octet-stream"))],
    )
    assert response.status_code == 201, response.text
    task_id = response.json()["id"]
    task = wait_upload(client, task_id)
    assert task["status"] == "done"
    assert task["dest_path"] == "/测试"
    assert task["bytes_done"] == 5
    assert fake.files[0][1] == "a.txt"
    assert fake.files[0][2] == b"hello"
    listed = client.get("/api/uploads")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == task_id


def test_upload_rejects_empty_list(client):
    register(client)
    account_id = bind(client)
    response = client.post(
        f"/api/accounts/{account_id}/files/upload",
        data={"dest": "/"},
        files=[],
    )
    assert response.status_code == 422
