from __future__ import annotations

import io
import os
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


os.environ.setdefault("DATABASE_URL", "sqlite:///./test_invoice_recon.db")
os.environ.setdefault("AUTO_CREATE_SCHEMA", "false")

from app.db.base import Base
from app.db.session import get_db
from app.main import create_application


@pytest.fixture()
def client():
    runtime_dir = BACKEND_ROOT / ".test_runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    db_path = runtime_dir / "test.db"
    if db_path.exists():
        db_path.unlink()
    engine = create_engine(
        f"sqlite:///{db_path}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    app = create_application()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    if db_path.exists():
        db_path.unlink()
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir, ignore_errors=True)


@pytest.fixture()
def fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "sample_data" / "fixtures"


@pytest.fixture()
def upload_payloads():
    return {
        "invoice": ("Invoice_598527_Account_64876_Division_MRPI_Full_unlocked.pdf", io.BytesIO(b"pdf"), "application/pdf"),
        "delivery_docket": ("Delivery Docket.jpeg", io.BytesIO(b"jpeg"), "image/jpeg"),
    }
