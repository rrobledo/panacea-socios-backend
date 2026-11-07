"""Reportes: filtro opcional por sucursal (`lugar`)."""
from datetime import timedelta

from sqlalchemy import text

from app.services.puntos import ahora_utc, hoy_local
from tests.conftest import auth
from tests.test_perfiles import cargar_perfil


def compra(db, socio, lugar, importe=1000, hace_dias=1):
    db.execute(text(
        "INSERT INTO registro_ventas (socio_id, fecha, lugar, importe) VALUES (:s, :f, :l, :i)"
    ), {"s": socio.id, "f": ahora_utc() - timedelta(days=hace_dias), "l": lugar, "i": importe})
    db.commit()


def cumple_hoy(db, socio):
    db.execute(text("UPDATE socios SET fecha_nacimiento = :f WHERE id = :id"),
               {"f": hoy_local().replace(year=1990), "id": socio.id})
    db.commit()


def test_ranking_filtra_compras_por_sucursal(client, admin, crear_socio, db):
    a, b = crear_socio(), crear_socio()
    compra(db, a, "Villa Allende", 5000)
    compra(db, a, "Villa Carlos Paz", 100)
    compra(db, b, "Villa Carlos Paz", 3000)

    todas = client.get("/reportes/ranking_compras", headers=auth(admin)).json()
    assert [(f["socio_id"], float(f["total_compras"])) for f in todas] == [(a.id, 5100), (b.id, 3000)]

    # Solo suma lo comprado en esa sucursal; sin distinguir mayúsculas ni espacios
    vcp = client.get("/reportes/ranking_compras", params={"lugar": " villa carlos paz "}, headers=auth(admin)).json()
    assert [(f["socio_id"], float(f["total_compras"]), f["cantidad_compras"]) for f in vcp] == [(b.id, 3000, 1), (a.id, 100, 1)]

    assert client.get("/reportes/ranking_compras", params={"lugar": ""}, headers=auth(admin)).json() == todas
    assert client.get("/reportes/ranking_compras", params={"lugar": "Villa General Belgrano"}, headers=auth(admin)).json() == []


def test_cumpleanios_por_sucursal_principal(client, admin, crear_socio, db):
    allende, vcp, sin_compras = crear_socio(), crear_socio(), crear_socio()
    for s in (allende, vcp, sin_compras):
        cumple_hoy(db, s)
    compra(db, allende, "Villa Allende")
    compra(db, allende, "Villa Allende")
    compra(db, allende, "Villa Carlos Paz")
    # Empate 1 a 1: gana la compra más reciente
    compra(db, vcp, "Villa Allende", hace_dias=5)
    compra(db, vcp, "Villa Carlos Paz", hace_dias=1)

    todas = client.get("/reportes/cumpleanios", headers=auth(admin)).json()
    assert {f["socio_id"]: f["lugar_principal"] for f in todas} == {
        allende.id: "Villa Allende", vcp.id: "Villa Carlos Paz", sin_compras.id: None,
    }
    filtrado = client.get("/reportes/cumpleanios", params={"lugar": "villa allende"}, headers=auth(admin)).json()
    assert [f["socio_id"] for f in filtrado] == [allende.id]


def test_preferencias_y_etiquetas_por_sucursal(client, admin, crear_socio, db):
    allende, vcp = crear_socio(), crear_socio()
    cargar_perfil(db, allende, etiquetas=["chocolate"])
    cargar_perfil(db, vcp, etiquetas=["chocolate", "sin tacc"])
    compra(db, allende, "Villa Allende")
    compra(db, vcp, "Villa Carlos Paz")

    todas = client.get("/reportes/preferencias", params={"q": "chocolate"}, headers=auth(admin)).json()
    assert {f["socio_id"]: f["lugar_principal"] for f in todas} == {allende.id: "Villa Allende", vcp.id: "Villa Carlos Paz"}

    filtrado = client.get("/reportes/preferencias", params={"q": "chocolate", "lugar": "Villa Carlos Paz"}, headers=auth(admin)).json()
    assert [f["socio_id"] for f in filtrado] == [vcp.id]

    etiquetas = client.get("/reportes/preferencias/etiquetas", params={"lugar": "Villa Allende"}, headers=auth(admin)).json()
    assert etiquetas == [{"etiqueta": "chocolate", "socios": 1}]
    assert len(client.get("/reportes/preferencias/etiquetas", headers=auth(admin)).json()) == 2
