from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.database import Base, get_db
from src.middleware.size_limit import BodySizeLimitMiddleware
from src.routes import alerts_router, audio_router, auth_router, patients_router, push_tokens_router

# Import models so Base.metadata contains every table.
from src.models.alert import Alert  # noqa: F401
from src.models.journal import JournalEntry  # noqa: F401
from src.models.patient import Patient, PatientContext  # noqa: F401
from src.models.push_token import PushToken  # noqa: F401
from src.models.transcript import Transcript  # noqa: F401
from src.models.user import User  # noqa: F401


def _test_database_url() -> URL:
    db_name = os.getenv("TEST_DB_NAME", "tfg_demencia_test")
    if not db_name.endswith("_test"):
        raise RuntimeError(
            f"Refusing to run tests against non-test database {db_name!r}. "
            "Set TEST_DB_NAME to a database ending in '_test'."
        )

    return URL.create(
        "mysql+pymysql",
        username=os.getenv("TEST_DB_USER", "tfg_app"),
        password=os.getenv("TEST_DB_PASSWORD", "tfg_pass_2024"),
        host=os.getenv("TEST_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("TEST_DB_PORT", "3306")),
        database=db_name,
        query={"charset": "utf8mb4"},
    )


@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine(_test_database_url(), pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(
            "MariaDB test database is not available. Run backend/init_test_db.sql "
            "or set TEST_DB_* variables. Original error: " + str(exc),
            allow_module_level=False,
        )

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def clean_database(db_engine):
    with db_engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f"TRUNCATE TABLE {table.name}"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))


@pytest.fixture
def db_session(db_engine, clean_database):
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def app(db_engine, clean_database):
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    test_app = FastAPI(title="TFG-DEMENCIA Test API")
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    test_app.add_middleware(BodySizeLimitMiddleware)
    test_app.include_router(auth_router)
    test_app.include_router(patients_router)
    test_app.include_router(audio_router)
    test_app.include_router(alerts_router)
    test_app.include_router(push_tokens_router)

    @test_app.get("/health")
    async def health():
        return {"status": "ok", "llm_available": True}

    test_app.dependency_overrides[get_db] = override_get_db
    return test_app


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def register_caregiver():
    def _register(client: TestClient, email: str = "care@example.com", password: str = "secret123"):
        response = client.post(
            "/auth/register",
            json={
                "role": "caregiver",
                "email": email,
                "password": password,
                "full_name": "Cuidador Test",
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    return _register


@pytest.fixture
def register_patient():
    def _register(
        client: TestClient,
        username: str = "paciente_test",
        caregiver_email: str = "care@example.com",
        password: str = "secret123",
    ):
        caregiver_login = client.post(
            "/auth/login",
            json={"identifier": caregiver_email, "password": "secret123", "role": "caregiver"},
        )
        assert caregiver_login.status_code == 200, caregiver_login.text
        created = client.post(
            "/patients/",
            headers=auth_headers(caregiver_login.json()["access_token"]),
            json={
                "username": username,
                "password": password,
                "full_name": "Paciente Test",
            },
        )
        assert created.status_code == 200, created.text
        response = client.post(
            "/auth/login",
            json={"identifier": username, "password": password, "role": "patient"},
        )
        assert response.status_code == 200, response.text
        return response.json()

    return _register
