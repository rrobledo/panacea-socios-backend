import threading
from datetime import timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select, text

from tests.conftest import SessionLocal
from app.models.puntos import Canje, MovimientoPuntos
from app.models.venta import RegistroVenta
from app.services import puntos as svc
from tests.conftest import auth


def crear_regla(client, admin, monto_por_punto=100, desde=None, **extra):
    body = {
        "monto_por_punto": monto_por_punto,
        "vigente_desde": str(desde or svc.hoy_local()),
        "motivo": "Regla de prueba",
        **extra,
    }
    return client.post("/admin/reglas-puntos", json=body, headers=auth(admin))


def crear_beneficio(client, admin, **extra):
    body = {
        "nombre": "15% en farmacia",
        "costo_puntos": 500,
        "porcentaje_descuento": 15,
        "tope_descuento": 1000,
        "dias_validez_cupon": 30,
        "vigente_desde": str(svc.hoy_local()),
        **extra,
    }
    r = client.post("/admin/beneficios", json=body, headers=auth(admin))
    assert r.status_code == 201, r.text
    return r.json()


def registrar_venta(client, operador, socio, importe, **extra):
    body = {"socio_id": socio.id, "fecha": "2026-11-06T15:00:00Z", "lugar": "Villa Allende", "importe": importe, **extra}
    body["fecha"] = svc.ahora_utc().isoformat() + "Z"
    return client.post("/ventas/", json=body, headers=auth(operador))


def saldo(client, socio):
    return client.get("/recompensas/creditos", headers=auth(socio)).json()["saldo"]


# ── Rol ────────────────────────────────────────────────────────────────────────

def test_me_expone_es_admin(client, admin, crear_socio):
    socio = crear_socio()
    assert client.get("/socios/me", headers=auth(admin)).json()["es_admin"] is True
    assert client.get("/socios/me", headers=auth(socio)).json()["es_admin"] is False


def test_maestro_abierto_a_usuarios_autenticados(client, crear_socio):
    socio = crear_socio()
    for url in ["/admin/beneficios", "/admin/reglas-puntos", "/admin/configuracion"]:
        assert client.get(url, headers=auth(socio)).status_code == 200
        assert client.get(url).status_code == 401


def test_ajustes_y_saldos_requieren_rol_admin(client, crear_socio):
    socio = crear_socio()
    assert client.get(f"/admin/socios/{socio.id}/puntos", headers=auth(socio)).status_code == 403
    r = client.post("/admin/ajustes-puntos", json={"socio_id": socio.id, "puntos": 10, "motivo": "test"}, headers=auth(socio))
    assert r.status_code == 403


# ── Reglas de conversión ───────────────────────────────────────────────────────

def test_regla_retroactiva_rechazada(client, admin):
    r = crear_regla(client, admin, desde=svc.hoy_local() - timedelta(days=1))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "VIGENCIA_RETROACTIVA"


def test_nueva_regla_cierra_la_anterior_y_se_puede_eliminar_si_es_futura(client, admin):
    hoy = svc.hoy_local()
    assert crear_regla(client, admin, 100, hoy).status_code == 201
    futura = crear_regla(client, admin, 150, hoy + timedelta(days=10))
    assert futura.status_code == 201

    reglas = client.get("/admin/reglas-puntos", headers=auth(admin)).json()
    assert reglas[0]["monto_por_punto"] == 150 and reglas[0]["vigente_hasta"] is None
    assert reglas[1]["vigente_hasta"] == str(hoy + timedelta(days=10))

    # Superposición
    r = crear_regla(client, admin, 120, hoy + timedelta(days=5))
    assert r.json()["detail"]["code"] == "CONFLICTO_VIGENCIA"

    # Eliminar la programada reabre la anterior
    assert client.delete(f"/admin/reglas-puntos/{futura.json()['id']}", headers=auth(admin)).status_code == 204
    reglas = client.get("/admin/reglas-puntos", headers=auth(admin)).json()
    assert len(reglas) == 1 and reglas[0]["vigente_hasta"] is None

    # La vigente no se puede eliminar
    r = client.delete(f"/admin/reglas-puntos/{reglas[0]['id']}", headers=auth(admin))
    assert r.json()["detail"]["code"] == "REGLA_EN_USO"


# ── Acumulación ────────────────────────────────────────────────────────────────

def test_compra_genera_puntos_con_regla_vigente(client, admin, crear_socio):
    crear_regla(client, admin, 100)
    socio = crear_socio()
    r = registrar_venta(client, admin, socio, 2550)
    assert r.status_code == 201, r.text
    assert r.json()["puntos_generados"] == 25
    assert saldo(client, socio) == 25
    actividad = client.get("/recompensas/actividad", headers=auth(socio)).json()
    assert actividad[0]["tipo"] == "ACUMULACION" and actividad[0]["puntos"] == 25
    # El saldo se expone en el socio para mostrarlo al registrar compras
    assert client.get(f"/socios/{socio.id}", headers=auth(admin)).json()["saldo_puntos"] == 25


def test_tope_por_compra_y_monto_menor(client, admin, crear_socio):
    crear_regla(client, admin, 100, tope_por_compra=500)
    socio = crear_socio()
    assert registrar_venta(client, admin, socio, 80000).json()["puntos_generados"] == 500
    assert registrar_venta(client, admin, socio, 50).json()["puntos_generados"] == 0
    assert saldo(client, socio) == 500


def test_sin_regla_la_compra_se_registra_sin_puntos(client, admin, crear_socio):
    socio = crear_socio()
    r = registrar_venta(client, admin, socio, 5000)
    assert r.status_code == 201 and r.json()["puntos_generados"] == 0


def test_cambio_de_regla_no_recalcula(client, admin, crear_socio, db):
    crear_regla(client, admin, 100)
    socio = crear_socio()
    registrar_venta(client, admin, socio, 1000)
    # La regla vigente pasa a $1000 por punto mañana: lo ya acumulado no cambia
    crear_regla(client, admin, 1000, svc.hoy_local() + timedelta(days=1))
    assert saldo(client, socio) == 10


def test_acumulacion_idempotente(client, admin, crear_socio, db):
    crear_regla(client, admin, 100)
    socio = crear_socio()
    venta_id = registrar_venta(client, admin, socio, 1000).json()["id"]
    venta = db.get(RegistroVenta, venta_id)
    assert svc.acumular_por_venta(db, venta) == 10
    db.commit()
    movs = db.execute(select(MovimientoPuntos).where(MovimientoPuntos.venta_id == venta_id)).scalars().all()
    assert len(movs) == 1
    assert saldo(client, socio) == 10


def test_anular_compra_revierte_puntos(client, admin, crear_socio):
    crear_regla(client, admin, 100)
    socio = crear_socio()
    venta_id = registrar_venta(client, admin, socio, 12000).json()["id"]
    assert client.delete(f"/ventas/{venta_id}", headers=auth(admin)).status_code == 204
    assert saldo(client, socio) == 0
    tipos = [m["tipo"] for m in client.get("/recompensas/actividad", headers=auth(socio)).json()]
    assert "REVERSO_COMPRA" in tipos


# ── Canje ──────────────────────────────────────────────────────────────────────

def test_canje_exitoso_descuenta_puntos_y_emite_cupon(client, admin, crear_socio):
    b = crear_beneficio(client, admin)
    socio = crear_socio(saldo=600)
    r = client.post(f"/recompensas/beneficios/{b['id']}/canjear", headers=auth(socio))
    assert r.status_code == 201, r.text
    assert r.json()["saldo"] == 100
    cupon = r.json()["cupon"]
    assert cupon["status"] == "ACTIVE" and cupon["porcentaje_descuento"] == 15 and len(cupon["codigo"]) == 8
    cupones = client.get("/recompensas/cupones", headers=auth(socio)).json()
    assert cupones[0]["codigo"] == cupon["codigo"]


def test_canje_errores(client, admin, crear_socio):
    b = crear_beneficio(client, admin, limite_por_socio=1, stock=1)
    pobre = crear_socio(saldo=100)
    r = client.post(f"/recompensas/beneficios/{b['id']}/canjear", headers=auth(pobre))
    assert r.json()["detail"]["code"] == "SALDO_INSUFICIENTE"

    rico = crear_socio(saldo=5000)
    assert client.post(f"/recompensas/beneficios/{b['id']}/canjear", headers=auth(rico)).status_code == 201
    r = client.post(f"/recompensas/beneficios/{b['id']}/canjear", headers=auth(rico))
    assert r.json()["detail"]["code"] in {"LIMITE_ALCANZADO", "SIN_STOCK"}

    otro = crear_socio(saldo=5000)
    r = client.post(f"/recompensas/beneficios/{b['id']}/canjear", headers=auth(otro))
    assert r.json()["detail"]["code"] == "SIN_STOCK"
    assert saldo(client, otro) == 5000


def test_beneficios_marcan_canjeable_segun_saldo(client, admin, crear_socio):
    crear_beneficio(client, admin, costo_puntos=500)
    crear_beneficio(client, admin, nombre="Inactivo", activo=False)
    socio = crear_socio(saldo=300)
    lista = client.get("/recompensas/beneficios", headers=auth(socio)).json()
    assert len(lista) == 1 and lista[0]["canjeable"] is False
    assert client.get("/recompensas/creditos", headers=auth(socio)).json()["proxima_recompensa"] == 500


def test_snapshot_no_cambia_si_se_edita_el_beneficio(client, admin, crear_socio):
    b = crear_beneficio(client, admin)
    socio = crear_socio(saldo=500)
    client.post(f"/recompensas/beneficios/{b['id']}/canjear", headers=auth(socio))
    client.put(f"/admin/beneficios/{b['id']}", json={"porcentaje_descuento": 50, "costo_puntos": 900}, headers=auth(admin))
    cupon = client.get("/recompensas/cupones", headers=auth(socio)).json()[0]
    assert cupon["porcentaje_descuento"] == 15
    admin_list = client.get("/admin/beneficios", headers=auth(admin)).json()
    assert admin_list[0]["canjes_realizados"] == 1


def test_canjes_concurrentes_no_gastan_dos_veces(client, admin, crear_socio):
    b = crear_beneficio(client, admin)
    socio = crear_socio(saldo=700)  # alcanza para uno solo
    resultados = []
    barrera = threading.Barrier(2)

    def canjear():
        s = SessionLocal()
        try:
            barrera.wait()
            svc.canjear_beneficio(s, socio.id, b["id"])
            s.commit()
            resultados.append("ok")
        except HTTPException as e:
            s.rollback()
            resultados.append(e.detail["code"])
        finally:
            s.close()

    hilos = [threading.Thread(target=canjear) for _ in range(2)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert sorted(resultados) == ["SALDO_INSUFICIENTE", "ok"]
    assert saldo(client, socio) == 200


# ── Cupón en la compra ─────────────────────────────────────────────────────────

def test_aplicar_cupon_en_compra(client, admin, crear_socio):
    crear_regla(client, admin, 100)
    b = crear_beneficio(client, admin)
    socio = crear_socio(saldo=500)
    codigo = client.post(f"/recompensas/beneficios/{b['id']}/canjear", headers=auth(socio)).json()["cupon"]["codigo"]

    v = client.get(f"/canjes/{codigo}", params={"socio_id": socio.id, "monto": 10000}, headers=auth(admin)).json()
    assert v == {"valido": True, "descuento": 1000.0, "porcentaje_descuento": 15.0, "motivo": None}

    r = registrar_venta(client, admin, socio, 10000, cupon_codigo=codigo.lower())
    assert r.status_code == 201, r.text
    body = r.json()
    assert Decimal(body["importe"]) == Decimal("9000") and Decimal(body["descuento"]) == Decimal("1000")
    assert body["puntos_generados"] == 90  # puntos sobre el neto
    cupon = client.get("/recompensas/cupones", headers=auth(socio)).json()[0]
    assert cupon["status"] == "USED"

    # Reutilizar el cupón
    r = registrar_venta(client, admin, socio, 5000, cupon_codigo=codigo)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CUPON_INVALIDO"


def test_cupon_de_otro_socio_rechazado_y_venta_no_registrada(client, admin, crear_socio, db):
    b = crear_beneficio(client, admin)
    duenio = crear_socio(saldo=500)
    otro = crear_socio()
    codigo = client.post(f"/recompensas/beneficios/{b['id']}/canjear", headers=auth(duenio)).json()["cupon"]["codigo"]
    r = registrar_venta(client, admin, otro, 1000, cupon_codigo=codigo)
    assert r.json()["detail"]["code"] == "CUPON_INVALIDO"
    assert db.execute(text("SELECT count(*) FROM registro_ventas")).scalar() == 0


def test_mas_de_un_cupon_no_se_acepta(client, admin, crear_socio):
    socio = crear_socio()
    r = registrar_venta(client, admin, socio, 1000, cupon_codigo=["A", "B"])
    assert r.status_code == 422


# ── Jobs ───────────────────────────────────────────────────────────────────────

def test_job_requiere_secreto(client):
    assert client.get("/jobs/diario").status_code == 401
    assert client.get("/jobs/diario", headers={"Authorization": "Bearer cron-test"}).status_code == 200


def test_cupon_vencido_se_pierde(client, admin, crear_socio, db):
    b = crear_beneficio(client, admin)
    socio = crear_socio(saldo=500)
    client.post(f"/recompensas/beneficios/{b['id']}/canjear", headers=auth(socio))
    db.execute(text("UPDATE canjes SET expira_en = now() - interval '1 day'"))
    db.commit()
    r = client.get("/jobs/diario", headers={"Authorization": "Bearer cron-test"}).json()
    assert r["cupones_vencidos"] == 1
    assert client.get("/recompensas/cupones", headers=auth(socio)).json()[0]["status"] == "EXPIRED"
    assert saldo(client, socio) == 0  # sin devolución


def test_expiracion_de_puntos_fifo(client, admin, crear_socio, db):
    socio = crear_socio(saldo=100)                      # crédito viejo de 100
    db.execute(text("UPDATE movimientos_puntos SET creado_en = now() - interval '13 months'"))
    db.commit()
    s = svc.bloquear_socio(db, socio.id)
    svc.registrar_movimiento(db, s, "AJUSTE", 50, descripcion="crédito nuevo")
    svc.registrar_movimiento(db, s, "AJUSTE", -30, descripcion="consumo")
    db.commit()

    client.get("/jobs/diario", headers={"Authorization": "Bearer cron-test"})
    # De los 100 viejos se consumieron 30 (FIFO) → vencen 70; quedan los 50 nuevos
    assert saldo(client, socio) == 50
    exp = db.execute(select(MovimientoPuntos).where(MovimientoPuntos.tipo == "EXPIRACION")).scalar_one()
    assert exp.puntos == -70
    # Segunda corrida: no vuelve a expirar
    client.get("/jobs/diario", headers={"Authorization": "Bearer cron-test"})
    assert saldo(client, socio) == 50


def test_por_vencer(client, crear_socio, db):
    socio = crear_socio(saldo=80)
    db.execute(text("UPDATE movimientos_puntos SET creado_en = now() - interval '12 months' + interval '10 days'"))
    db.commit()
    pv = client.get("/recompensas/creditos", headers=auth(socio)).json()["por_vencer"]
    assert pv["puntos"] == 80


def test_conciliacion_corrige_saldo(client, crear_socio, db):
    socio = crear_socio(saldo=40)
    db.execute(text("UPDATE socios SET saldo_puntos = 999"))
    db.commit()
    r = client.get("/jobs/diario", headers={"Authorization": "Bearer cron-test"}).json()
    assert r["saldos_corregidos"] == 1
    assert saldo(client, socio) == 40


# ── Ajustes, configuración y máquina ───────────────────────────────────────────

def test_ajuste_manual(client, admin, crear_socio):
    socio = crear_socio()
    r = client.post("/admin/ajustes-puntos", json={"socio_id": socio.id, "puntos": 200, "motivo": "Compensación reclamo"}, headers=auth(admin))
    assert r.status_code == 201
    assert client.get(f"/admin/socios/{socio.id}/puntos", headers=auth(admin)).json()["saldo"] == 200
    r = client.post("/admin/ajustes-puntos", json={"socio_id": socio.id, "puntos": -500, "motivo": "Error"}, headers=auth(admin))
    assert r.json()["detail"]["code"] == "SALDO_INSUFICIENTE"


def test_configuracion_y_programa_inactivo(client, admin, crear_socio):
    crear_regla(client, admin, 100)
    b = crear_beneficio(client, admin)
    r = client.put("/admin/configuracion", json={"meses_expiracion_puntos": 6, "costo_juego_maquina": 50, "programa_activo": False}, headers=auth(admin))
    assert r.status_code == 200 and r.json()["meses_expiracion_puntos"] == 6
    socio = crear_socio(saldo=1000)
    assert registrar_venta(client, admin, socio, 5000).json()["puntos_generados"] == 0
    r = client.post(f"/recompensas/beneficios/{b['id']}/canjear", headers=auth(socio))
    assert r.json()["detail"]["code"] == "PROGRAMA_INACTIVO"


def test_maquina_descuenta_costo_y_emite_cupon(client, admin, crear_socio):
    crear_beneficio(client, admin, nombre="Premio")
    socio = crear_socio(saldo=150)
    estado = client.get("/recompensas/maquina", headers=auth(socio)).json()
    assert estado == {"cost": 100, "enabled": True}
    r = client.post("/recompensas/maquina/jugar", headers=auth(socio))
    assert r.status_code == 200, r.text
    assert r.json()["saldo"] == 50 and r.json()["coupon"]["title"] == "Premio"
    r = client.post("/recompensas/maquina/jugar", headers=auth(socio))
    assert r.json()["detail"]["code"] == "SALDO_INSUFICIENTE"


# ── Beneficio en el mostrador ──────────────────────────────────────────────────

def beneficio_10(client, admin, **extra):
    """300 puntos, 10% sin tope (el escenario de la spec)."""
    return crear_beneficio(client, admin, nombre="10% off", costo_puntos=300, porcentaje_descuento=10,
                           tope_descuento=None, **extra)


def disponibles(client, operador, socio_id, **params):
    return client.get("/ventas/beneficios-disponibles", params={"socio_id": socio_id, **params}, headers=auth(operador))


def test_listado_de_beneficios_usables(client, admin, crear_socio):
    barato = beneficio_10(client, admin)
    caro = crear_beneficio(client, admin, nombre="Caro", costo_puntos=900, porcentaje_descuento=20, tope_descuento=1500)
    crear_beneficio(client, admin, nombre="Inactivo", activo=False)
    socio = crear_socio(saldo=500)

    r = disponibles(client, admin, socio.id, importe=10000)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["socio_id"] == socio.id and body["saldo_puntos"] == 500
    por_id = {b["id"]: b for b in body["beneficios"]}
    assert set(por_id) == {barato["id"], caro["id"]}
    assert [b["id"] for b in body["beneficios"]] == [barato["id"], caro["id"]]  # por costo
    assert por_id[barato["id"]]["usable"] is True and por_id[barato["id"]]["motivo"] is None
    assert por_id[barato["id"]]["descuento_estimado"] == 1000.0
    assert por_id[caro["id"]]["usable"] is False and por_id[caro["id"]]["motivo"] == "SALDO_INSUFICIENTE"
    assert por_id[caro["id"]]["descuento_estimado"] == 1500.0  # tope

    sin_importe = disponibles(client, admin, socio.id).json()["beneficios"]
    assert all(b["descuento_estimado"] is None for b in sin_importe)

    r = disponibles(client, admin, 99999)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "SOCIO_NO_ENCONTRADO"


def test_listado_limite_y_programa_inactivo(client, admin, crear_socio):
    b = beneficio_10(client, admin, limite_por_socio=1)
    socio = crear_socio(saldo=5000)
    assert registrar_venta(client, admin, socio, 1000, beneficio_id=b["id"]).status_code == 201
    item = disponibles(client, admin, socio.id).json()["beneficios"][0]
    assert item["usable"] is False and item["motivo"] == "LIMITE_ALCANZADO"

    r = client.put("/admin/configuracion", json={"meses_expiracion_puntos": 12, "costo_juego_maquina": 100, "programa_activo": False}, headers=auth(admin))
    assert r.status_code == 200, r.text
    otro = crear_socio(saldo=5000)
    item = disponibles(client, admin, otro.id).json()["beneficios"][0]
    assert item["usable"] is False and item["motivo"] == "PROGRAMA_INACTIVO"


def test_venta_con_beneficio(client, admin, crear_socio, db):
    crear_regla(client, admin, 100)
    b = beneficio_10(client, admin, stock=5)
    socio = crear_socio(saldo=500)

    r = registrar_venta(client, admin, socio, 10000, beneficio_id=b["id"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert Decimal(body["importe"]) == Decimal("9000") and Decimal(body["descuento"]) == Decimal("1000")
    assert body["puntos_canjeados"] == 300 and body["puntos_generados"] == 90 and body["saldo_puntos"] == 290
    assert saldo(client, socio) == 290

    canje = db.execute(select(Canje).where(Canje.venta_id == body["id"])).scalar_one()
    assert (canje.origen, canje.estado, canje.monto_descontado, canje.costo_puntos) == ("MOSTRADOR", "USADO", Decimal("1000.00"), 300)
    assert canje.usado_en is not None
    stock = client.get("/admin/beneficios", headers=auth(admin)).json()[0]["stock"]
    assert stock == 4


def test_venta_sin_beneficio_informa_cero_canjeados(client, admin, crear_socio):
    socio = crear_socio(saldo=50)
    body = registrar_venta(client, admin, socio, 1000).json()
    assert body["puntos_canjeados"] == 0 and body["saldo_puntos"] == 50


def test_venta_con_beneficio_errores_no_registran_nada(client, admin, crear_socio, db):
    b = beneficio_10(client, admin)
    pobre = crear_socio(saldo=100)
    r = registrar_venta(client, admin, pobre, 10000, beneficio_id=b["id"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SALDO_INSUFICIENTE"

    r = registrar_venta(client, admin, pobre, 10000, beneficio_id=99999)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "BENEFICIO_NO_ENCONTRADO"

    sin_socio = {"fecha": svc.ahora_utc().isoformat() + "Z", "importe": 1000, "beneficio_id": b["id"]}
    assert client.post("/ventas/", json=sin_socio, headers=auth(admin)).status_code == 422

    r = registrar_venta(client, admin, pobre, 1000, beneficio_id=b["id"], cupon_codigo="ABCDEFGH")
    assert r.status_code == 422

    assert db.execute(text("SELECT count(*) FROM registro_ventas")).scalar() == 0
    assert db.execute(text("SELECT count(*) FROM canjes")).scalar() == 0
    assert saldo(client, pobre) == 100


def test_limite_compartido_entre_app_y_mostrador(client, admin, crear_socio):
    b = beneficio_10(client, admin, limite_por_socio=1)
    socio = crear_socio(saldo=5000)
    venta = registrar_venta(client, admin, socio, 1000, beneficio_id=b["id"]).json()

    r = client.post(f"/recompensas/beneficios/{b['id']}/canjear", headers=auth(socio))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "LIMITE_ALCANZADO"
    assert client.get("/recompensas/beneficios", headers=auth(socio)).json()[0]["canjeable"] is False

    # Anular la venta libera el límite
    assert client.delete(f"/ventas/{venta['id']}", headers=auth(admin)).status_code == 204
    assert registrar_venta(client, admin, socio, 1000, beneficio_id=b["id"]).status_code == 201


def test_eliminar_venta_con_beneficio_devuelve_puntos_y_stock(client, admin, crear_socio, db):
    crear_regla(client, admin, 100)
    b = beneficio_10(client, admin, stock=5)
    socio = crear_socio(saldo=500)
    venta = registrar_venta(client, admin, socio, 10000, beneficio_id=b["id"]).json()
    canje_id = db.execute(select(Canje.id).where(Canje.venta_id == venta["id"])).scalar_one()

    assert client.delete(f"/ventas/{venta['id']}", headers=auth(admin)).status_code == 204
    assert saldo(client, socio) == 500
    db.expire_all()
    canje = db.get(Canje, canje_id)
    assert canje.estado == "CANCELADO"
    assert client.get("/admin/beneficios", headers=auth(admin)).json()[0]["stock"] == 5
    tipos = [m["tipo"] for m in client.get("/recompensas/actividad", headers=auth(socio)).json()]
    assert "DEVOLUCION_CANJE" in tipos and "REVERSO_COMPRA" in tipos

    # Idempotente: una segunda llamada no devuelve de nuevo
    assert svc.devolver_canje_de_venta(db, RegistroVenta(id=venta["id"])) == 0
    devoluciones = db.execute(
        select(MovimientoPuntos).where(MovimientoPuntos.canje_id == canje_id, MovimientoPuntos.tipo == "DEVOLUCION_CANJE")
    ).scalars().all()
    assert len(devoluciones) == 1


def test_editar_venta_con_beneficio(client, admin, crear_socio):
    b = beneficio_10(client, admin)
    socio = crear_socio(saldo=500)
    otro = crear_socio()
    venta = registrar_venta(client, admin, socio, 10000, beneficio_id=b["id"]).json()

    for cambio in ({"socio_id": otro.id}, {"importe": "5000.00"}):
        r = client.put(f"/ventas/{venta['id']}", json=cambio, headers=auth(admin))
        assert r.status_code == 409 and r.json()["detail"]["code"] == "VENTA_CON_BENEFICIO"

    r = client.put(f"/ventas/{venta['id']}", json={"lugar": "Villa Carlos Paz", "socio_id": socio.id}, headers=auth(admin))
    assert r.status_code == 200 and r.json()["lugar"] == "Villa Carlos Paz"


def test_ventas_con_beneficio_concurrentes(client, admin, crear_socio):
    b = beneficio_10(client, admin)
    socio = crear_socio(saldo=400)  # alcanza para un solo canje de 300
    resultados = []
    barrera = threading.Barrier(2)

    def vender():
        barrera.wait()
        r = registrar_venta(client, admin, socio, 1000, beneficio_id=b["id"])
        resultados.append(r.status_code if r.status_code == 201 else r.json()["detail"]["code"])

    hilos = [threading.Thread(target=vender) for _ in range(2)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert sorted(map(str, resultados)) == ["201", "SALDO_INSUFICIENTE"]
    assert saldo(client, socio) == 100
