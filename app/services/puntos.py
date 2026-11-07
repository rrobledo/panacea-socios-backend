"""Lógica de negocio del sistema de puntos.

Reglas clave:
- Todo cambio de puntos es un `MovimientoPuntos` (ledger inmutable) y actualiza
  `socios.saldo_puntos` en la misma transacción, con la fila del socio bloqueada.
- Los puntos de una compra se calculan UNA vez, con la regla vigente a la fecha
  (local) de la compra, y nunca se recalculan.
- Los puntos se descuentan al canjear (no al usar el cupón). Cupones vencidos se pierden.
- Un cupón por compra.

Las funciones no hacen commit: el llamador controla la transacción.
"""
import logging
import math
import random
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.puntos import (
    Beneficio,
    Canje,
    ConfigPrograma,
    EstadoCanje,
    MovimientoPuntos,
    OrigenCanje,
    ReglaPuntos,
    TipoMovimiento,
)
from app.models.socio import Socio
from app.models.venta import RegistroVenta

logger = logging.getLogger(__name__)

TZ = ZoneInfo("America/Argentina/Cordoba")
DIAS_AVISO_VENCIMIENTO = 30
_ALFABETO_CODIGO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # sin 0/O, 1/I/L


# ── Errores de negocio ─────────────────────────────────────────────────────────

def error(code: str, message: str, http_status: int = status.HTTP_409_CONFLICT) -> HTTPException:
    """HTTPException con `detail = {code, message}` (lo interpreta el frontend)."""
    return HTTPException(status_code=http_status, detail={"code": code, "message": message})


# ── Fechas ─────────────────────────────────────────────────────────────────────

def ahora_utc() -> datetime:
    """Timestamp UTC naive (mismo criterio que registro_ventas.fecha)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hoy_local() -> date:
    return datetime.now(TZ).date()


def a_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def fecha_local(dt_utc_naive: datetime) -> date:
    return dt_utc_naive.replace(tzinfo=timezone.utc).astimezone(TZ).date()


def restar_meses(dt: datetime, meses: int) -> datetime:
    total = dt.year * 12 + (dt.month - 1) - meses
    year, month = divmod(total, 12)
    month += 1
    # último día válido del mes destino
    siguiente = date(year + (month // 12), (month % 12) + 1, 1)
    ultimo_dia = (siguiente - timedelta(days=1)).day
    return dt.replace(year=year, month=month, day=min(dt.day, ultimo_dia))


def sumar_meses(dt: datetime, meses: int) -> datetime:
    return restar_meses(dt, -meses)


# ── Configuración y bloqueos ───────────────────────────────────────────────────

def get_config(db: Session) -> ConfigPrograma:
    config = db.get(ConfigPrograma, 1)
    if config is None:
        config = ConfigPrograma(id=1, meses_expiracion_puntos=12, costo_juego_maquina=100, programa_activo=True)
        db.add(config)
        db.flush()
    return config


def bloquear_socio(db: Session, socio_id: int) -> Socio:
    """SELECT … FOR UPDATE sobre el socio (serializa operaciones sobre su saldo)."""
    socio = db.execute(
        select(Socio).where(Socio.id == socio_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if socio is None:
        raise error("SOCIO_NO_ENCONTRADO", "Socio no encontrado", status.HTTP_404_NOT_FOUND)
    return socio


def registrar_movimiento(
    db: Session,
    socio: Socio,
    tipo: str,
    puntos: int,
    *,
    descripcion: str | None = None,
    venta_id: int | None = None,
    canje_id: int | None = None,
    regla_id: int | None = None,
    monto_base: Decimal | None = None,
    creado_por: str | None = None,
) -> MovimientoPuntos:
    """Inserta un movimiento y actualiza el saldo cacheado. El socio debe estar bloqueado."""
    mov = MovimientoPuntos(
        socio_id=socio.id,
        tipo=tipo,
        puntos=puntos,
        descripcion=descripcion,
        venta_id=venta_id,
        canje_id=canje_id,
        regla_id=regla_id,
        monto_base=monto_base,
        creado_por=creado_por,
        creado_en=ahora_utc(),
    )
    db.add(mov)
    socio.saldo_puntos = (socio.saldo_puntos or 0) + puntos
    db.flush()
    return mov


# ── Reglas de conversión ───────────────────────────────────────────────────────

def regla_vigente(db: Session, dia: date) -> ReglaPuntos | None:
    return db.execute(
        select(ReglaPuntos)
        .where(ReglaPuntos.vigente_desde <= dia)
        .where((ReglaPuntos.vigente_hasta.is_(None)) | (ReglaPuntos.vigente_hasta > dia))
        .order_by(ReglaPuntos.vigente_desde.desc())
        .limit(1)
    ).scalar_one_or_none()


def calcular_puntos(monto: Decimal, regla: ReglaPuntos) -> int:
    if monto is None or monto <= 0:
        return 0
    puntos = math.floor(Decimal(monto) / regla.monto_por_punto * (regla.multiplicador or Decimal("1")))
    if regla.tope_por_compra:
        puntos = min(puntos, regla.tope_por_compra)
    return max(puntos, 0)


def acumular_por_venta(db: Session, venta: RegistroVenta) -> int:
    """Genera los puntos de una compra registrada. Idempotente. Devuelve los puntos generados."""
    if venta.socio_id is None:
        return 0
    existente = db.execute(
        select(MovimientoPuntos).where(
            MovimientoPuntos.venta_id == venta.id, MovimientoPuntos.tipo == TipoMovimiento.ACUMULACION
        )
    ).scalar_one_or_none()
    if existente:
        return existente.puntos
    if not get_config(db).programa_activo:
        return 0

    dia = fecha_local(a_utc_naive(venta.fecha))
    regla = regla_vigente(db, dia)
    if regla is None:
        logger.warning("Sin regla de puntos vigente para %s: la venta %s no genera puntos", dia, venta.id)
        return 0

    puntos = calcular_puntos(venta.importe, regla)
    if puntos <= 0:
        return 0

    socio = bloquear_socio(db, venta.socio_id)
    registrar_movimiento(
        db, socio, TipoMovimiento.ACUMULACION, puntos,
        descripcion=f"Compra en {venta.lugar}" if venta.lugar else f"Compra #{venta.id}",
        venta_id=venta.id, regla_id=regla.id, monto_base=venta.importe,
    )
    return puntos


def reversar_venta(db: Session, venta: RegistroVenta) -> int:
    """Revierte los puntos de una compra anulada (el saldo puede quedar negativo). Idempotente."""
    acumulacion = db.execute(
        select(MovimientoPuntos).where(
            MovimientoPuntos.venta_id == venta.id, MovimientoPuntos.tipo == TipoMovimiento.ACUMULACION
        )
    ).scalar_one_or_none()
    if acumulacion is None:
        return 0
    ya_reversado = db.execute(
        select(MovimientoPuntos.id).where(
            MovimientoPuntos.venta_id == venta.id, MovimientoPuntos.tipo == TipoMovimiento.REVERSO_COMPRA
        )
    ).first()
    if ya_reversado:
        return 0
    socio = bloquear_socio(db, acumulacion.socio_id)
    registrar_movimiento(
        db, socio, TipoMovimiento.REVERSO_COMPRA, -acumulacion.puntos,
        descripcion=f"Anulación de compra #{venta.id}", venta_id=venta.id,
    )
    return acumulacion.puntos


# ── Beneficios y canjes ────────────────────────────────────────────────────────

def beneficio_disponible(b: Beneficio, dia: date) -> bool:
    return (
        b.activo
        and b.vigente_desde <= dia
        and (b.vigente_hasta is None or dia <= b.vigente_hasta)
        and (b.stock is None or b.stock > 0)
    )


def beneficios_disponibles(db: Session) -> list[Beneficio]:
    dia = hoy_local()
    beneficios = db.execute(
        select(Beneficio).where(Beneficio.activo.is_(True)).order_by(Beneficio.costo_puntos, Beneficio.id)
    ).scalars().all()
    return [b for b in beneficios if beneficio_disponible(b, dia)]


def canjes_por_beneficio(db: Session, socio_id: int) -> dict[int, int]:
    rows = db.execute(
        select(Canje.beneficio_id, func.count())
        .where(Canje.socio_id == socio_id, Canje.origen == OrigenCanje.CANJE)
        .group_by(Canje.beneficio_id)
    ).all()
    return {beneficio_id: n for beneficio_id, n in rows}


def _generar_codigo(db: Session) -> str:
    for _ in range(10):
        codigo = "".join(secrets.choice(_ALFABETO_CODIGO) for _ in range(8))
        if not db.execute(select(Canje.id).where(Canje.codigo == codigo)).first():
            return codigo
    raise RuntimeError("No se pudo generar un código de cupón único")


def _emitir_cupon(db: Session, socio: Socio, beneficio: Beneficio, origen: str, costo: int) -> Canje:
    canje = Canje(
        socio_id=socio.id,
        beneficio_id=beneficio.id,
        codigo=_generar_codigo(db),
        origen=origen,
        titulo=beneficio.nombre,
        costo_puntos=costo,
        porcentaje_descuento=beneficio.porcentaje_descuento,
        tope_descuento=beneficio.tope_descuento,
        estado=EstadoCanje.EMITIDO,
        expira_en=ahora_utc() + timedelta(days=beneficio.dias_validez_cupon),
        creado_en=ahora_utc(),
    )
    db.add(canje)
    if beneficio.stock is not None:
        beneficio.stock -= 1
    db.flush()
    return canje


def canjear_beneficio(db: Session, socio_id: int, beneficio_id: int) -> Canje:
    if not get_config(db).programa_activo:
        raise error("PROGRAMA_INACTIVO", "El programa de puntos no está activo")

    socio = bloquear_socio(db, socio_id)
    beneficio = db.execute(
        select(Beneficio).where(Beneficio.id == beneficio_id).with_for_update()
    ).scalar_one_or_none()
    if beneficio is None:
        raise error("BENEFICIO_NO_ENCONTRADO", "Beneficio no encontrado", status.HTTP_404_NOT_FOUND)

    dia = hoy_local()
    if beneficio.stock is not None and beneficio.stock <= 0:
        raise error("SIN_STOCK", "El beneficio no tiene stock")
    if not beneficio_disponible(beneficio, dia):
        raise error("BENEFICIO_NO_DISPONIBLE", "El beneficio no está disponible")
    if beneficio.limite_por_socio is not None:
        usados = canjes_por_beneficio(db, socio.id).get(beneficio.id, 0)
        if usados >= beneficio.limite_por_socio:
            raise error("LIMITE_ALCANZADO", "Alcanzaste el límite de canjes de este beneficio")
    if socio.saldo_puntos < beneficio.costo_puntos:
        raise error("SALDO_INSUFICIENTE", "Saldo de puntos insuficiente")

    canje = _emitir_cupon(db, socio, beneficio, OrigenCanje.CANJE, beneficio.costo_puntos)
    registrar_movimiento(
        db, socio, TipoMovimiento.CANJE, -beneficio.costo_puntos,
        descripcion=f"Canje: {beneficio.nombre}", canje_id=canje.id,
    )
    return canje


def estado_maquina(db: Session) -> dict:
    config = get_config(db)
    enabled = config.programa_activo and bool(beneficios_disponibles(db))
    return {"cost": config.costo_juego_maquina, "enabled": enabled}


def jugar_maquina(db: Session, socio_id: int) -> Canje:
    """Descuenta el costo del juego y emite un cupón de un beneficio disponible al azar."""
    config = get_config(db)
    if not config.programa_activo:
        raise error("PROGRAMA_INACTIVO", "El programa de puntos no está activo")
    socio = bloquear_socio(db, socio_id)
    costo = config.costo_juego_maquina
    if socio.saldo_puntos < costo or socio.saldo_puntos <= 0:
        raise error("SALDO_INSUFICIENTE", "Saldo de puntos insuficiente")
    premios = beneficios_disponibles(db)
    if not premios:
        raise error("SIN_PREMIOS", "No hay premios disponibles en este momento")

    beneficio = db.execute(
        select(Beneficio).where(Beneficio.id == random.choice(premios).id).with_for_update()
    ).scalar_one()
    canje = _emitir_cupon(db, socio, beneficio, OrigenCanje.MAQUINA, 0)
    if costo > 0:
        registrar_movimiento(
            db, socio, TipoMovimiento.JUEGO, -costo,
            descripcion=f"Ganó: {beneficio.nombre}", canje_id=canje.id,
        )
    return canje


def estado_cupon(canje: Canje, ahora: datetime | None = None) -> str:
    """Estado efectivo (un EMITIDO vencido se informa como EXPIRADO aunque el job no haya corrido)."""
    if canje.estado == EstadoCanje.EMITIDO and canje.expira_en <= (ahora or ahora_utc()):
        return EstadoCanje.EXPIRADO
    return canje.estado


def calcular_descuento(canje: Canje, monto: Decimal) -> Decimal:
    descuento = Decimal(monto) * canje.porcentaje_descuento / Decimal(100)
    if canje.tope_descuento is not None:
        descuento = min(descuento, canje.tope_descuento)
    return descuento.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def evaluar_cupon(db: Session, codigo: str, socio_id: int | None, *, bloquear: bool = False) -> tuple[Canje | None, str | None]:
    """Devuelve (canje, None) si es aplicable, o (canje|None, motivo) si no."""
    q = select(Canje).where(Canje.codigo == codigo.strip().upper())
    if bloquear:
        q = q.with_for_update()
    canje = db.execute(q).scalar_one_or_none()
    if canje is None:
        return None, "El cupón no existe"
    if socio_id is None or canje.socio_id != socio_id:
        return canje, "El cupón no pertenece a este socio"
    estado = estado_cupon(canje)
    if estado == EstadoCanje.USADO:
        return canje, "El cupón ya fue usado"
    if estado != EstadoCanje.EMITIDO:
        return canje, "El cupón está vencido"
    return canje, None


def aplicar_cupon(db: Session, codigo: str, socio_id: int | None, monto: Decimal) -> tuple[Canje, Decimal]:
    canje, motivo = evaluar_cupon(db, codigo, socio_id, bloquear=True)
    if motivo:
        raise error("CUPON_INVALIDO", motivo)
    return canje, calcular_descuento(canje, monto)


# ── Ajustes ────────────────────────────────────────────────────────────────────

def ajustar_puntos(db: Session, socio_id: int, puntos: int, motivo: str, admin_email: str) -> MovimientoPuntos:
    socio = bloquear_socio(db, socio_id)
    if puntos < 0 and socio.saldo_puntos + puntos < 0:
        raise error("SALDO_INSUFICIENTE", "El ajuste dejaría el saldo en negativo")
    return registrar_movimiento(
        db, socio, TipoMovimiento.AJUSTE, puntos, descripcion=motivo, creado_por=admin_email,
    )


# ── Saldo y vencimientos ───────────────────────────────────────────────────────

def _creditos_y_consumo(db: Session, socio_id: int) -> tuple[list[tuple[datetime, int]], int]:
    rows = db.execute(
        select(MovimientoPuntos.creado_en, MovimientoPuntos.puntos)
        .where(MovimientoPuntos.socio_id == socio_id)
        .order_by(MovimientoPuntos.creado_en, MovimientoPuntos.id)
    ).all()
    creditos = [(c, p) for c, p in rows if p > 0]
    consumido = sum(-p for _, p in rows if p < 0)
    return creditos, consumido


def por_vencer(db: Session, socio_id: int, dias: int = DIAS_AVISO_VENCIMIENTO) -> dict | None:
    """Puntos (FIFO) que vencen en los próximos `dias` días y la fecha más próxima."""
    meses = get_config(db).meses_expiracion_puntos
    if not meses:
        return None
    creditos, consumido = _creditos_y_consumo(db, socio_id)
    limite = ahora_utc() + timedelta(days=dias)
    total, fecha = 0, None
    for creado_en, puntos in creditos:
        restante = puntos - min(puntos, consumido)
        consumido = max(0, consumido - puntos)
        if restante <= 0:
            continue
        vence = sumar_meses(creado_en, meses)
        if vence > limite:
            break
        total += restante
        fecha = fecha or vence
    if total <= 0:
        return None
    return {"puntos": total, "fecha": fecha.replace(tzinfo=timezone.utc)}


def proxima_recompensa(db: Session, saldo: int) -> int | None:
    costos = sorted({b.costo_puntos for b in beneficios_disponibles(db)})
    if not costos:
        return None
    pendientes = [c for c in costos if c > saldo]
    return pendientes[0] if pendientes else costos[0]


# ── Jobs ───────────────────────────────────────────────────────────────────────

def vencer_cupones(db: Session) -> int:
    result = db.execute(
        text("UPDATE canjes SET estado = :expirado WHERE estado = :emitido AND expira_en <= :ahora"),
        {"expirado": EstadoCanje.EXPIRADO, "emitido": EstadoCanje.EMITIDO, "ahora": ahora_utc()},
    )
    return result.rowcount or 0


def expirar_puntos(db: Session) -> int:
    """Registra EXPIRACION por los créditos vencidos no consumidos (FIFO). Devuelve socios afectados."""
    meses = get_config(db).meses_expiracion_puntos
    if not meses:
        return 0
    corte = restar_meses(ahora_utc(), meses)
    candidatos = db.execute(
        text("""
            SELECT socio_id
            FROM movimientos_puntos
            GROUP BY socio_id
            HAVING SUM(CASE WHEN puntos > 0 AND creado_en <= :corte THEN puntos ELSE 0 END)
                 > SUM(CASE WHEN puntos < 0 THEN -puntos ELSE 0 END)
        """),
        {"corte": corte},
    ).scalars().all()

    afectados = 0
    for socio_id in candidatos:
        socio = bloquear_socio(db, socio_id)
        creditos, consumido = _creditos_y_consumo(db, socio_id)
        vencidos = sum(p for c, p in creditos if c <= corte)
        a_expirar = vencidos - consumido
        if a_expirar > 0:
            registrar_movimiento(
                db, socio, TipoMovimiento.EXPIRACION, -a_expirar,
                descripcion=f"Vencimiento de puntos ({meses} meses)",
            )
            afectados += 1
    return afectados


def conciliar_saldos(db: Session) -> int:
    """Corrige socios.saldo_puntos contra la suma del ledger. Devuelve la cantidad corregida."""
    rows = db.execute(text("""
        SELECT s.id, s.saldo_puntos, COALESCE(SUM(m.puntos), 0) AS ledger
        FROM socios s
        LEFT JOIN movimientos_puntos m ON m.socio_id = s.id
        GROUP BY s.id, s.saldo_puntos
        HAVING s.saldo_puntos <> COALESCE(SUM(m.puntos), 0)
    """)).all()
    for socio_id, cacheado, ledger in rows:
        logger.error("Saldo desincronizado socio=%s cache=%s ledger=%s: se corrige", socio_id, cacheado, ledger)
        socio = bloquear_socio(db, socio_id)
        socio.saldo_puntos = int(ledger)
    return len(rows)
