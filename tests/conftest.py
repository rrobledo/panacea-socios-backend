"""Pruebas de integración del sistema de puntos.

Requieren un PostgreSQL de PRUEBA (nunca el de producción) en TEST_DATABASE_URL, p. ej.:
    docker run -d --name puntos-test-pg -e POSTGRES_PASSWORD=test -e POSTGRES_DB=puntos -p 55432:5432 postgres:16-alpine
    TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/puntos pytest
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL")
if not TEST_DB:
    pytest.skip("TEST_DATABASE_URL no definido", allow_module_level=True)
if "localhost" not in TEST_DB and "127.0.0.1" not in TEST_DB:
    # Las pruebas borran el esquema completo: solo se permiten bases locales.
    raise RuntimeError("TEST_DATABASE_URL debe apuntar a una base local de prueba")

os.environ["DATABASE_URL"] = TEST_DB
os.environ["ADMIN_EMAILS"] = "admin@test.com"
os.environ["CRON_SECRET"] = "cron-test"

ROOT = Path(__file__).resolve().parent.parent

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.auth.utils import create_token  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

import app.database as database  # noqa: E402

# La app usa pool_size=1 (serverless). En pruebas la sesión del test y la del request
# conviven, así que se usa un engine con más conexiones.
database.engine.dispose()
engine = create_engine(TEST_DB, pool_size=5, max_overflow=5)
database.SessionLocal.configure(bind=engine)
SessionLocal = database.SessionLocal
from app.main import app  # noqa: E402
from app.models.socio import Socio  # noqa: E402

TABLAS = "movimientos_puntos, canjes, beneficios, reglas_puntos, detalle_registro_ventas, registro_ventas, socios"


@pytest.fixture(scope="session", autouse=True)
def migrar():
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True, env=os.environ.copy())
    yield


@pytest.fixture(autouse=True)
def limpiar():
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLAS} RESTART IDENTITY CASCADE"))
        conn.execute(text(
            "UPDATE config_programa SET meses_expiracion_puntos = 12, costo_juego_maquina = 100, programa_activo = true"
        ))
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client():
    return TestClient(app)


_contador = {"n": 0}


@pytest.fixture
def crear_socio(db):
    def _crear(email=None, saldo=0):
        _contador["n"] += 1
        n = _contador["n"]
        socio = Socio(nombre_apellido=f"Socio {n}", email=email or f"socio{n}@test.com", dni=f"{30000000 + n}")
        db.add(socio)
        db.commit()
        if saldo:
            from app.services import puntos as svc
            s = svc.bloquear_socio(db, socio.id)
            svc.registrar_movimiento(db, s, "MIGRACION", saldo, descripcion="Saldo inicial de prueba")
            db.commit()
        db.refresh(socio)
        return socio
    return _crear


def auth(socio) -> dict:
    return {"Authorization": f"Bearer {create_token(socio.id, socio.email)}"}


@pytest.fixture
def admin(crear_socio):
    return crear_socio(email="admin@test.com")
