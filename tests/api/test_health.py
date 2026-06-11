"""Test endpoint /health."""


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    # status có thể là 'ok' hoặc 'degraded' (vd thiếu Redis trong CI) — cả 2 đều hợp lệ
    assert body.get("status") in {"ok", "degraded"}
    assert body.get("service") == "MCQGen API"
    assert body.get("version") == "2.0"
    assert "components" in body
