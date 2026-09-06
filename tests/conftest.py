"""Fixtures pytest — base SQLite dédiée aux tests (jamais la base de dev)."""
import os

os.environ["DATABASE_URL"] = "sqlite:///./sika_test.db"
os.environ["SIKA_SECRET_KEY"] = "cle-de-test"
os.environ["SIKA_SEED_PIN"] = "1234"

import pytest
from fastapi.testclient import TestClient

import app.models  # noqa: F401 — enregistre les tables
from app.core.db import Base, SessionLocal, engine
from app.main import app


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(engine)


@pytest.fixture()
def compte(db):
    from app.services.comptes import creer_compte

    c = creer_compte(db, prenom="Aïcha", telephone="+22890000000", langue="fr", pin="1234")
    db.commit()
    return c


@pytest.fixture()
def compte_b(db):
    from app.services.comptes import creer_compte

    c = creer_compte(db, prenom="Bénédicte", telephone="+22890000001", langue="fr", pin="1234")
    db.commit()
    return c


def token_de(compte_id: str) -> str:
    from app.core.security import new_access_token

    return new_access_token(compte_id, ttl=3600)
