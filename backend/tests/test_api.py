"""Backend API tests with mocked LLM calls."""

from __future__ import annotations


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "openai_configured" in payload
    assert "model" in payload


def test_create_and_get_session(client):
    create = client.post("/sessions", json={"title": "Q3 Margin Review"})
    assert create.status_code == 201
    session = create.json()
    assert session["title"] == "Q3 Margin Review"
    assert session["id"] > 0

    detail = client.get(f"/sessions/{session['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["title"] == "Q3 Margin Review"
    assert body["messages"] == []


def test_list_sessions(client):
    client.post("/sessions", json={"title": "Session A"})
    client.post("/sessions", json={"title": "Session B"})
    response = client.get("/sessions")
    assert response.status_code == 200
    assert len(response.json()) >= 2


def test_message_endpoint_mocked_board(client):
    created = client.post("/sessions", json={"title": "New Board Session"}).json()
    response = client.post(
        f"/sessions/{created['id']}/message",
        json={"question": "Our Q3 margins dropped by 4 points. What should we do?"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == created["id"]
    assert len(payload["discussion"]) == 8  # 4 executives x 2 rounds
    assert payload["synthesis"]["confidence"] == "Medium"
    assert payload["synthesis"]["recommendation"]

    messages = client.get(f"/sessions/{created['id']}/messages")
    assert messages.status_code == 200
    speakers = {m["role"] for m in messages.json()}
    assert "CEO" in speakers
    assert "CFO" in speakers
    assert "SYNTHESIS" in speakers


def test_csv_upload_validation(client):
    created = client.post("/sessions", json={"title": "Upload Test"}).json()
    session_id = created["id"]

    bad = client.post(
        f"/sessions/{session_id}/upload",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert bad.status_code == 400

    csv_bytes = (
        b"quarter,revenue,gross_margin\n"
        b"Q1,10000000,0.42\n"
        b"Q2,11000000,0.40\n"
        b"Q3,10800000,0.36\n"
    )
    good = client.post(
        f"/sessions/{session_id}/upload",
        files={"file": ("financials.csv", csv_bytes, "text/csv")},
    )
    assert good.status_code == 200
    body = good.json()
    assert body["summary"]["record_count"] == 3
    assert "gross_margin" in body["summary"]["fields"]


def test_json_upload(client):
    created = client.post("/sessions", json={"title": "JSON Upload"}).json()
    payload = b'{"revenue": 10800000, "gross_margin": 0.36, "market_share": 18.2}'
    response = client.post(
        f"/sessions/{created['id']}/upload",
        files={"file": ("company_data.json", payload, "application/json")},
    )
    assert response.status_code == 200
    assert response.json()["summary"]["format"] == "json"


def test_delete_session(client):
    created = client.post("/sessions", json={"title": "Temp"}).json()
    deleted = client.delete(f"/sessions/{created['id']}")
    assert deleted.status_code == 204
    missing = client.get(f"/sessions/{created['id']}")
    assert missing.status_code == 404
