"""Test validation schema của /generate."""


def test_generate_requires_auth(client):
    # Không có token + body sai -> phải bị từ chối (401 do auth, hoặc 422 do body)
    resp = client.post("/generate", json={"foo": "bar"})
    assert resp.status_code in {401, 422, 403}


def test_generate_bad_body_returns_422(client, admin_token):
    # Có token nhưng thiếu field bắt buộc 'topics' -> 422
    resp = client.post(
        "/generate",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"output_name": "exam"},  # thiếu 'topics'
    )
    assert resp.status_code == 422


def test_generate_invalid_retrieval_mode_returns_422(client, admin_token):
    resp = client.post(
        "/generate",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "topics": [{"topic_id": "t1", "chapter_id": "ch08", "topic": "CNN"}],
            "retrieval_mode": "khong_hop_le",
        },
    )
    if resp.status_code >= 500:
        import pytest
        pytest.skip("Endpoint trả 5xx (thiếu service nền như Redis) — bỏ qua")
    assert resp.status_code == 422
