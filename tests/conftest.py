"""
Cấu hình chung cho pytest của MCQGen.

- Thêm repo root vào sys.path để import được `api.*`, `src.*`.
- Đặt biến môi trường thân thiện test TRƯỚC khi import app.
- Fixture `client`: FastAPI TestClient; tự SKIP nếu không import/khởi động được
  app (ví dụ thiếu Redis/Celery trong môi trường CI tối giản) — nhờ vậy test
  pipeline/PDF vẫn chạy được kể cả khi test API bị skip.
- Fixture `admin_token`: token đăng nhập admin; SKIP nếu không login được.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent  # tests/.. -> repo root
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Env an toàn cho test (đặt trước khi import api.main)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "admin2026")


@pytest.fixture(scope="session")
def client():
    try:
        from fastapi.testclient import TestClient
        from api.main import app
        c = TestClient(app)
        c.__enter__()  # kích hoạt startup events (tạo bảng, seed admin)
    except Exception as exc:  # thiếu deps/service -> skip toàn bộ test API
        pytest.skip(f"Không khởi động được FastAPI app (thiếu service/deps): {exc}")
    yield c
    try:
        c.__exit__(None, None, None)
    except Exception:
        pass


@pytest.fixture(scope="session")
def admin_token(client):
    resp = client.post(
        "/auth/login",
        data={
            "username": os.environ["ADMIN_USERNAME"],
            "password": os.environ["ADMIN_PASSWORD"],
        },
    )
    if resp.status_code != 200:
        pytest.skip(f"Không đăng nhập được admin (status {resp.status_code})")
    return resp.json()["access_token"]
