"""Perfiles de preferencias con IA: relación venta→productos, ciclo del job y reportes.

La API de Claude se reemplaza por un cliente falso (no se hacen llamadas reales).
"""
import json
from datetime import timedelta
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from sqlalchemy import select, text

from app.config import settings
from app.main import app
from app.models.perfil import LotePerfiles, PerfilSocio
from app.routers import jobs
from app.services import detalle_ventas, perfiles
from app.services.puntos import ahora_utc
from tests.conftest import auth, engine

CRON = {"Authorization": "Bearer cron-test"}


# ── Tablas externas mínimas (en producción las llena otro sistema) ─────────────

@pytest.fixture(scope="module", autouse=True)
def tablas_externas():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS documentos (iddocumento integer, fechaentrada timestamp, valorapagar numeric);
            CREATE TABLE IF NOT EXISTS documentos_cp (iddocumento integer, fechaentrada timestamp, valorapagar numeric);
            CREATE TABLE IF NOT EXISTS panacea_sales_v2 (document_id bigint, category text, product text, subtotal numeric, count numeric);
        """))
    yield


@pytest.fixture(autouse=True)
def limpiar_externas(monkeypatch):
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE documentos, documentos_cp, panacea_sales_v2"))
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "perfiles_activo", True)
    monkeypatch.setattr(settings, "perfiles_max_por_lote", 500)
    yield
    app.dependency_overrides.pop(jobs.get_anthropic_client, None)


_doc = {"n": 0}


def venta(db, socio, productos, *, hace_dias=10, importe=1000, lugar="Villa Allende", con_documento=True):
    """Registra una venta y (opcional) su ticket con líneas. productos: [(categoria, producto, unidades)]."""
    fecha = ahora_utc().replace(microsecond=0) - timedelta(days=hace_dias)
    venta_id = db.execute(text(
        "INSERT INTO registro_ventas (socio_id, fecha, lugar, importe) VALUES (:s, :f, :l, :i) RETURNING id"
    ), {"s": socio.id, "f": fecha, "l": lugar, "i": importe}).scalar_one()
    if con_documento:
        _doc["n"] += 1
        doc = _doc["n"]
        tabla = "documentos" if lugar == "Villa Allende" else "documentos_cp"
        db.execute(text(f"INSERT INTO {tabla} VALUES (:d, :f, :i)"),
                   {"d": doc, "f": fecha - timedelta(hours=3) + timedelta(minutes=5), "i": importe})
        document_id = doc if lugar == "Villa Allende" else doc * 50000
        for categoria, producto, unidades in productos:
            db.execute(text("INSERT INTO panacea_sales_v2 VALUES (:d, :c, :p, 100, :u)"),
                       {"d": document_id, "c": categoria, "p": producto, "u": unidades})
    db.commit()
    return venta_id


# ── Cliente falso de la Message Batches API ────────────────────────────────────

def _texto(contenido: str):
    return SimpleNamespace(type="text", text=contenido)


def ok(perfil: dict, stop_reason="end_turn"):
    return SimpleNamespace(type="succeeded", message=SimpleNamespace(stop_reason=stop_reason, content=[_texto(json.dumps(perfil))]))


PERFIL_BASE = {
    "resumen": "Compra sobre todo alfajores de chocolate amargo y frutos secos.",
    "etiquetas": ["chocolate amargo", "frutos secos"],
    "categorias_favoritas": ["Alfajores"],
    "productos_favoritos": ["Alfajor chocolate amargo"],
}


class FakeBatches:
    def __init__(self):
        self.creados = []      # requests de cada lote
        self.estado = {}       # batch_id -> processing_status
        self.resultados = {}   # batch_id -> {socio_id: result}

    def create(self, requests):
        requests = list(requests)
        batch_id = f"msgbatch_{len(self.creados) + 1}"
        self.creados.append(requests)
        self.estado[batch_id] = "in_progress"
        return SimpleNamespace(id=batch_id)

    def retrieve(self, batch_id):
        if batch_id not in self.estado:
            raise anthropic.NotFoundError(
                "not found", response=httpx2.Response(404, request=httpx2.Request("GET", "https://api")), body=None
            )
        return SimpleNamespace(processing_status=self.estado[batch_id])

    def results(self, batch_id):
        return [SimpleNamespace(custom_id=f"socio-{sid}", result=r) for sid, r in self.resultados[batch_id].items()]

    def terminar(self, batch_id, resultados):
        self.estado[batch_id] = "ended"
        self.resultados[batch_id] = resultados


@pytest.fixture
def fake():
    batches = FakeBatches()
    app.dependency_overrides[jobs.get_anthropic_client] = lambda: SimpleNamespace(messages=SimpleNamespace(batches=batches))
    return batches


def correr(client):
    r = client.get("/jobs/perfiles", headers=CRON)
    assert r.status_code == 200, r.text
    return r.json()


def socios_del_lote(requests):
    return sorted(int(r["custom_id"].split("-")[1]) for r in requests)


def mensaje(request) -> str:
    return request["params"]["messages"][0]["content"]


# ── Relación y selección ───────────────────────────────────────────────────────

def test_solo_ventas_relacionables_generan_seleccion(client, crear_socio, db, fake):
    con_detalle = crear_socio()
    sin_documento = crear_socio()
    documento_sin_lineas = crear_socio()
    # Días distintos: la relación es por fecha e importe, y si coinciden un ticket se cruza con otra venta
    venta(db, con_detalle, [("Alfajores", "Alfajor chocolate amargo", 2)], hace_dias=10)
    venta(db, sin_documento, [], con_documento=False, hace_dias=11)
    venta(db, documento_sin_lineas, [], hace_dias=12)  # ticket sin líneas en panacea_sales_v2
    venta(db, crear_socio(), [("Panificados", "Pan de campo", 1)], lugar="Villa Carlos Paz", hace_dias=13)

    body = correr(client)
    assert body["lote_enviado"]["socios"] == 2
    ids = socios_del_lote(fake.creados[0])
    assert con_detalle.id in ids and sin_documento.id not in ids and documento_sin_lineas.id not in ids


def test_un_documento_por_venta_el_mas_cercano(crear_socio, db):
    socio = crear_socio()
    venta_id = venta(db, socio, [("Alfajores", "Alfajor chocolate amargo", 1)], importe=1000)
    fecha = db.execute(text("SELECT fecha FROM registro_ventas WHERE id = :v"), {"v": venta_id}).scalar_one()
    # Otro ticket parecido (importe dentro de ±100 pero más lejano) con otro producto
    db.execute(text("INSERT INTO documentos VALUES (9999, :f, 1080)"), {"f": fecha - timedelta(hours=3) + timedelta(minutes=40)})
    db.execute(text("INSERT INTO panacea_sales_v2 VALUES (9999, 'Bebidas', 'Gaseosa', 100, 1)"))
    db.commit()
    compras = detalle_ventas.compras_por_socio(db, [socio.id], ahora_utc() - timedelta(days=365), 100)[socio.id]
    assert [p.producto for p in compras.productos] == ["Alfajor chocolate amargo"]
    assert compras.ventas == 1


def test_agrupa_por_producto_y_no_envia_datos_personales(client, crear_socio, db, fake):
    socio = crear_socio(email="maria.perez@test.com")
    for unidades, dias in ((2, 30), (1, 20), (3, 5)):
        venta(db, socio, [("Alfajores", "Alfajor chocolate amargo", unidades)], hace_dias=dias)
    correr(client)
    texto = mensaje(fake.creados[0][0])
    ultima = (ahora_utc() - timedelta(days=5, hours=3)).date().isoformat()
    assert f"- Alfajores | Alfajor chocolate amargo | 6 | 3 | {ultima}" in texto
    assert "Compras analizadas: 3" in texto
    db.refresh(socio)
    pedido = json.dumps(fake.creados[0][0]["params"], default=str)
    for dato in (socio.nombre_apellido, socio.dni, socio.email):
        assert dato not in pedido
    params = fake.creados[0][0]["params"]
    assert params["output_config"]["effort"] == "low"
    assert params["output_config"]["format"]["type"] == "json_schema"
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_limite_por_lote_prioriza_compra_mas_reciente(client, crear_socio, db, fake, monkeypatch):
    monkeypatch.setattr(settings, "perfiles_max_por_lote", 1)
    viejo, reciente = crear_socio(), crear_socio()
    venta(db, viejo, [("A", "Producto A", 1)], hace_dias=40)
    venta(db, reciente, [("B", "Producto B", 1)], hace_dias=2)
    correr(client)
    assert socios_del_lote(fake.creados[0]) == [reciente.id]


# ── Ciclo del job ──────────────────────────────────────────────────────────────

def test_ciclo_completo_del_job(client, crear_socio, db, fake):
    socio = crear_socio()
    venta(db, socio, [("Alfajores", "Alfajor chocolate amargo", 2)])

    primera = correr(client)
    assert primera["lote_enviado"] == {"batch_id": "msgbatch_1", "socios": 1}

    # Lote en proceso: no se envía otro y el socio no se duplica
    venta(db, crear_socio(), [("X", "Producto X", 1)])
    segunda = correr(client)
    assert segunda["en_proceso"] == 1 and segunda["lote_enviado"] is None and len(fake.creados) == 1

    # Lote terminado: se guarda el perfil y se envía el siguiente (solo con el socio nuevo)
    fake.terminar("msgbatch_1", {socio.id: ok(PERFIL_BASE)})
    tercera = correr(client)
    assert tercera["procesados"] == 1 and tercera["perfiles_guardados"] == 1
    assert tercera["lote_enviado"]["socios"] == 1 and socio.id not in socios_del_lote(fake.creados[1])
    perfil = db.get(PerfilSocio, socio.id)
    assert perfil.etiquetas == ["chocolate amargo", "frutos secos"] and perfil.ventas_analizadas == 1
    assert perfil.modelo == settings.perfiles_modelo

    # Una compra nueva vuelve a seleccionar al socio
    fake.terminar("msgbatch_2", {})
    venta(db, socio, [("Alfajores", "Alfajor de maicena", 1)], hace_dias=1)
    correr(client)
    assert socio.id in socios_del_lote(fake.creados[2])
    assert "Alfajor de maicena" in mensaje(fake.creados[2][0])


def test_vocabulario_de_etiquetas_en_el_prompt(client, crear_socio, db, fake):
    socio = crear_socio()
    venta(db, socio, [("Alfajores", "Alfajor chocolate amargo", 2)])
    correr(client)
    assert "Etiquetas que ya usan otros socios" not in fake.creados[0][0]["params"]["system"][0]["text"]
    fake.terminar("msgbatch_1", {socio.id: ok(PERFIL_BASE)})
    venta(db, crear_socio(), [("X", "Producto X", 1)])
    correr(client)
    system = fake.creados[1][0]["params"]["system"][0]["text"]
    assert "Etiquetas que ya usan otros socios" in system and "chocolate amargo, frutos secos" in system


def test_job_desactivado_y_secreto(client, monkeypatch, fake):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert correr(client) == {"activo": False, "motivo": "Falta ANTHROPIC_API_KEY"}
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "perfiles_activo", False)
    assert correr(client)["activo"] is False
    assert fake.creados == []
    assert client.get("/jobs/perfiles").status_code == 401


# ── Resultados ─────────────────────────────────────────────────────────────────

def test_resultado_valido_se_normaliza(client, crear_socio, db, fake):
    socio = crear_socio()
    venta(db, socio, [("Alfajores", "Alfajor chocolate amargo", 2), ("Frutos secos", "Almendras", 1)])
    correr(client)
    fake.terminar("msgbatch_1", {socio.id: ok({
        "resumen": "Le gusta el chocolate. " * 60,
        "etiquetas": ["Chocolate  Amargo", "chocolate amargo", " Frutos secos. ", ""],
        "categorias_favoritas": ["Alfajores", "alfajores"],
        "productos_favoritos": ["alfajor chocolate amargo", "Producto inventado"],
    })})
    correr(client)
    perfil = db.get(PerfilSocio, socio.id)
    assert perfil.etiquetas == ["chocolate amargo", "frutos secos"]
    assert perfil.categorias_favoritas == ["Alfajores"]
    assert perfil.productos_favoritos == ["Alfajor chocolate amargo"]  # nombre canónico, sin el inventado
    assert len(perfil.resumen) <= 601 and perfil.resumen.endswith("…")


@pytest.mark.parametrize("resultado", [
    SimpleNamespace(type="errored", error=SimpleNamespace(error=SimpleNamespace(message="overloaded"))),
    SimpleNamespace(type="expired"),
    ok(PERFIL_BASE, stop_reason="refusal"),
    SimpleNamespace(type="succeeded", message=SimpleNamespace(stop_reason="end_turn", content=[_texto("no es json")])),
    ok({**PERFIL_BASE, "etiquetas": []}),
])
def test_resultado_con_error_no_cambia_el_perfil_y_reintenta(client, crear_socio, db, fake, resultado):
    socio = crear_socio()
    venta(db, socio, [("Alfajores", "Alfajor chocolate amargo", 2)], hace_dias=20)
    correr(client)
    fake.terminar("msgbatch_1", {socio.id: ok(PERFIL_BASE)})
    venta(db, socio, [("Alfajores", "Alfajor de maicena", 1)], hace_dias=1)
    correr(client)  # guarda el perfil y envía msgbatch_2 por la compra nueva
    anterior = db.get(PerfilSocio, socio.id).resumen

    fake.terminar("msgbatch_2", {socio.id: resultado})
    body = correr(client)
    assert body["errores"] == 1
    db.expire_all()
    assert db.get(PerfilSocio, socio.id).resumen == anterior
    error = db.execute(text("SELECT error FROM lote_perfil_items WHERE estado = 'ERROR'")).scalar_one()
    assert error
    assert socio.id in socios_del_lote(fake.creados[2])  # se reintenta en la corrida siguiente


def test_lote_vencido_o_inexistente(client, crear_socio, db, fake):
    socio = crear_socio()
    venta(db, socio, [("A", "Producto A", 1)])
    correr(client)
    db.execute(text("UPDATE lotes_perfiles SET creado_en = creado_en - INTERVAL '49 hours'"))
    db.commit()
    body = correr(client)
    assert body["con_error"] == 1 and body["lote_enviado"]["socios"] == 1  # el socio se reintenta

    del fake.estado["msgbatch_2"]  # la API ya no lo conoce
    assert correr(client)["con_error"] == 1
    estados = db.execute(select(LotePerfiles.estado).order_by(LotePerfiles.id)).scalars().all()
    assert estados[:2] == ["ERROR", "ERROR"]


# ── Endpoints ──────────────────────────────────────────────────────────────────

def cargar_perfil(db, socio, **campos):
    datos = {**PERFIL_BASE, **campos}
    db.add(PerfilSocio(
        socio_id=socio.id, resumen=datos["resumen"], etiquetas=datos["etiquetas"],
        categorias_favoritas=datos["categorias_favoritas"], productos_favoritos=datos["productos_favoritos"],
        ventas_analizadas=3, productos_analizados=5, periodo_desde=ahora_utc().date() - timedelta(days=90),
        periodo_hasta=ahora_utc().date(), ultima_venta_fecha=ahora_utc(), modelo="claude-opus-5-5",
        generado_en=ahora_utc(),
    ))
    db.commit()


def test_preferencias_del_socio(client, admin, crear_socio, db):
    socio = crear_socio()
    r = client.get(f"/socios/{socio.id}/preferencias", headers=auth(admin))
    assert r.status_code == 404 and r.json()["detail"]["code"] == "PERFIL_NO_DISPONIBLE"
    assert client.get("/socios/99999/preferencias", headers=auth(admin)).json()["detail"]["code"] == "SOCIO_NO_ENCONTRADO"

    cargar_perfil(db, socio)
    r = client.get(f"/socios/{socio.id}/preferencias", headers=auth(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["etiquetas"] == ["chocolate amargo", "frutos secos"] and body["ventas_analizadas"] == 3
    assert body["generado_en"].endswith("Z")


def test_reporte_por_preferencia(client, admin, crear_socio, db):
    por_etiqueta = crear_socio()
    cargar_perfil(db, por_etiqueta, etiquetas=["limón", "té"], productos_favoritos=["Té verde"], categorias_favoritas=["Infusiones"])
    por_categoria = crear_socio()
    cargar_perfil(db, por_categoria, etiquetas=["dulce"], productos_favoritos=["Alfajor"],
                  categorias_favoritas=["Limonadas"], resumen="Compra dulces.")
    por_resumen = crear_socio()
    cargar_perfil(db, por_resumen, etiquetas=["salado"], productos_favoritos=["Grisines"],
                  categorias_favoritas=["Snacks"], resumen="A veces lleva limones.")

    r = client.get("/reportes/preferencias", params={"q": "LIMON"}, headers=auth(admin))
    assert r.status_code == 200, r.text
    filas = r.json()
    assert [f["socio_id"] for f in filas] == [por_etiqueta.id, por_categoria.id]  # etiqueta antes que categoría
    assert filas[0]["coincidencias"] == [{"campo": "etiqueta", "valor": "limón"}]
    assert filas[0]["email"] and filas[0]["dni"]

    con_resumen = client.get("/reportes/preferencias", params={"q": "limon", "incluir_resumen": True}, headers=auth(admin)).json()
    assert [f["socio_id"] for f in con_resumen][-1] == por_resumen.id
    assert con_resumen[-1]["coincidencias"][0]["campo"] == "resumen"

    producto = client.get("/reportes/preferencias", params={"q": "té ver"}, headers=auth(admin)).json()
    assert producto[0]["coincidencias"][0] == {"campo": "producto", "valor": "Té verde"}

    pagina = client.get("/reportes/preferencias", params={"q": "limon", "skip": 1, "limit": 1}, headers=auth(admin)).json()
    assert [f["socio_id"] for f in pagina] == [por_categoria.id]

    assert client.get("/reportes/preferencias", params={"q": "l"}, headers=auth(admin)).status_code == 422
    assert client.get("/reportes/preferencias", params={"q": "zzz"}, headers=auth(admin)).json() == []
    assert client.get("/reportes/preferencias", params={"q": "50%"}, headers=auth(admin)).json() == []


def test_etiquetas_con_conteo(client, admin, crear_socio, db):
    for _ in range(3):
        cargar_perfil(db, crear_socio(), etiquetas=["chocolate"])
    cargar_perfil(db, crear_socio(), etiquetas=["sin tacc", "chocolate"])
    r = client.get("/reportes/preferencias/etiquetas", headers=auth(admin))
    assert r.json() == [{"etiqueta": "chocolate", "socios": 4}, {"etiqueta": "sin tacc", "socios": 1}]
