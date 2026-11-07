from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import passport
from app.database import get_db
from app.models.socio import Socio
from app.models.venta import DetalleRegistroVenta, RegistroVenta
from app.models.puntos import EstadoCanje
from app.schemas.puntos import BeneficiosDisponiblesResponse, BeneficioUsableResponse
from app.schemas.venta import ComprasPorCategoriaResponse, ComprasSemanalResponse, VentaCreate, VentaCreateResponse, VentaDetailResponse, VentaResponse, VentaUpdate
from app.services import puntos as puntos_svc

router = APIRouter(prefix="/ventas", tags=["Registro de Ventas"])


def _get_or_404(venta_id: int, db: Session) -> RegistroVenta:
    venta = db.get(RegistroVenta, venta_id)
    if not venta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venta no encontrada")
    return venta


@router.get("/", response_model=list[VentaResponse], summary="Listar ventas")
def list_ventas(
    socio_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Retorna ventas con sus detalles. Filtrable por socio_id. Requiere autenticación."""
    q = db.query(RegistroVenta)
    if socio_id is not None:
        q = q.filter(RegistroVenta.socio_id == socio_id)
    return q.offset(skip).limit(limit).all()


@router.post("/", response_model=VentaCreateResponse, status_code=status.HTTP_201_CREATED, summary="Registrar venta")
def create_venta(
    body: VentaCreate,
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Crea un registro de venta con sus líneas de detalle. Requiere autenticación.

    - `cupon_codigo` (opcional, uno solo): aplica el descuento del cupón; `importe` se
      interpreta como monto antes del descuento y se registra el neto. 409 `CUPON_INVALIDO`.
    - `beneficio_id` (opcional, excluyente con `cupon_codigo`, requiere `socio_id`): beneficio
      elegido en el mostrador. En la misma operación descuenta sus puntos, registra el canje
      como usado en esta venta y aplica el descuento (`importe` = monto antes del descuento).
      409 `SALDO_INSUFICIENTE`, `LIMITE_ALCANZADO`, `SIN_STOCK`, `BENEFICIO_NO_DISPONIBLE`,
      `PROGRAMA_INACTIVO`; 404 `BENEFICIO_NO_ENCONTRADO`. Si falla, no se registra la venta.
    - Si la venta tiene socio, genera los puntos sobre el neto con la regla vigente a la fecha.
    """
    detalles_data = body.detalles
    venta_data = body.model_dump(exclude={"detalles", "cupon_codigo", "beneficio_id"})
    venta_data["fecha"] = puntos_svc.a_utc_naive(venta_data["fecha"])

    canje, descuento = None, Decimal("0")
    if body.cupon_codigo:
        canje, descuento = puntos_svc.aplicar_cupon(db, body.cupon_codigo, body.socio_id, body.importe)
    elif body.beneficio_id is not None:
        canje, descuento = puntos_svc.canjear_en_venta(db, body.socio_id, body.beneficio_id, body.importe)
    if canje is not None:
        venta_data["importe"] = body.importe - descuento

    venta = RegistroVenta(**venta_data)
    db.add(venta)
    db.flush()

    for d in detalles_data:
        detalle = DetalleRegistroVenta(registro_venta_id=venta.id, **d.model_dump())
        db.add(detalle)

    if canje is not None:
        canje.estado = EstadoCanje.USADO
        canje.venta_id = venta.id
        canje.monto_descontado = descuento
        canje.usado_en = puntos_svc.ahora_utc()

    puntos = puntos_svc.acumular_por_venta(db, venta)

    db.commit()
    db.refresh(venta)
    resp = VentaCreateResponse.model_validate(venta)
    resp.descuento = descuento
    resp.puntos_generados = puntos
    if body.beneficio_id is not None and canje is not None:
        resp.puntos_canjeados = canje.costo_puntos
    if venta.socio_id is not None:
        resp.saldo_puntos = db.get(Socio, venta.socio_id).saldo_puntos
    return resp


@router.get(
    "/beneficios-disponibles",
    response_model=BeneficiosDisponiblesResponse,
    summary="Beneficios que un socio puede usar en una venta",
)
def beneficios_disponibles(
    socio_id: int,
    importe: Decimal | None = None,
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Beneficios vigentes para el selector del mostrador, ordenados por costo en puntos.

    Cada uno indica si el socio puede usarlo (`usable`) y, si no, el `motivo`
    (`SALDO_INSUFICIENTE`, `LIMITE_ALCANZADO`, `PROGRAMA_INACTIVO`, …). Con `importe`
    (monto antes del descuento) informa además el `descuento_estimado`. 404 `SOCIO_NO_ENCONTRADO`.
    """
    socio = db.get(Socio, socio_id)
    if socio is None:
        raise puntos_svc.error("SOCIO_NO_ENCONTRADO", "Socio no encontrado", status.HTTP_404_NOT_FOUND)
    activo = puntos_svc.get_config(db).programa_activo
    usados = puntos_svc.canjes_por_beneficio(db, socio.id)
    saldo = socio.saldo_puntos or 0
    dia = puntos_svc.hoy_local()
    beneficios = []
    for b in puntos_svc.beneficios_disponibles(db):
        motivo = puntos_svc.motivo_no_usable(b, saldo, usados, programa_activo=activo, dia=dia)
        descuento = None
        if importe is not None and importe > 0:
            descuento = float(puntos_svc.calcular_descuento(b, importe))
        beneficios.append(BeneficioUsableResponse(
            id=b.id,
            nombre=b.nombre,
            descripcion=b.descripcion,
            imagen_url=b.imagen_url,
            costo_puntos=b.costo_puntos,
            porcentaje_descuento=float(b.porcentaje_descuento),
            tope_descuento=float(b.tope_descuento) if b.tope_descuento is not None else None,
            usable=motivo is None,
            motivo=motivo,
            descuento_estimado=descuento,
        ))
    return BeneficiosDisponiblesResponse(socio_id=socio.id, saldo_puntos=saldo, beneficios=beneficios)


@router.get("/estadisticas/compras_semanales", response_model=list[ComprasSemanalResponse], summary="Compras semanales")
def compras_semanales(
    socio_id: int | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Revenue semanal agregado (lunes de cada semana como fecha). Filtrable por socio_id y rango de fechas."""
    filters = []
    params: dict = {}

    if socio_id is not None:
        filters.append("socio_id = :socio_id")
        params["socio_id"] = socio_id
    if desde is not None:
        filters.append("(fecha - INTERVAL '3 hours')::date >= :desde")
        params["desde"] = desde
    if hasta is not None:
        filters.append("(fecha - INTERVAL '3 hours')::date <= :hasta")
        params["hasta"] = hasta

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    sql = text(f"""
        SELECT
            date_trunc('week', fecha - INTERVAL '3 hours')::date AS fecha,
            SUM(importe) AS total
        FROM registro_ventas
        {where}
        GROUP BY 1
        ORDER BY 1
    """)
    rows = db.execute(sql, params).mappings().all()
    return [ComprasSemanalResponse(**row) for row in rows]


_COMPRAS_POR_CATEGORIA_SQL = """
    WITH ventas_rel AS (
      SELECT (r.fecha - INTERVAL '3 hours') AS fecha, r.socio_id, r.lugar, r.importe, d.iddocumento::bigint AS document_id
      FROM registro_ventas r
          LEFT OUTER JOIN documentos d
          ON (r.fecha - INTERVAL '3 hours')::date = d.fechaentrada::date
         AND r.fecha - INTERVAL '3 hours' BETWEEN d.fechaentrada - INTERVAL '30 minutes' AND d.fechaentrada + INTERVAL '2 hour'
         AND trunc(r.importe)::integer BETWEEN trunc(d.valorapagar)::integer - 100 AND trunc(d.valorapagar)::integer + 100
      WHERE r.lugar = 'Villa Allende'
      UNION
      SELECT (r.fecha - INTERVAL '3 hours') AS fecha, r.socio_id, r.lugar, r.importe, d.iddocumento::bigint * 50000 AS document_id
      FROM registro_ventas r
          LEFT OUTER JOIN documentos_cp d
          ON (r.fecha - INTERVAL '3 hours')::date = d.fechaentrada::date
         AND r.fecha - INTERVAL '3 hours' BETWEEN d.fechaentrada - INTERVAL '30 minutes' AND d.fechaentrada + INTERVAL '2 hour'
         AND trunc(r.importe)::integer BETWEEN trunc(d.valorapagar)::integer - 100 AND trunc(d.valorapagar)::integer + 100
      WHERE r.lugar = 'Villa Carlos Paz'
    )
    SELECT
        product AS name,
        ROUND((SUM(subtotal) * 100.0 / SUM(SUM(subtotal)) OVER ())::numeric)::int AS value
    FROM ventas_rel r
        LEFT OUTER JOIN panacea_sales_v2 s ON r.document_id = s.document_id
    {where}
    GROUP BY product
"""


@router.get("/estadisticas/compras_por_categoria", response_model=list[ComprasPorCategoriaResponse], summary="Compras por categoría (DonutChart)")
def compras_por_categoria(
    socio_id: int | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Suma de subtotal agrupada por producto. Retorna {name, value} listo para DonutChart."""
    filters = []
    params: dict = {}

    if socio_id is not None:
        filters.append("r.socio_id = :socio_id")
        params["socio_id"] = socio_id
    if desde is not None:
        filters.append("r.fecha::date >= :desde")
        params["desde"] = desde
    if hasta is not None:
        filters.append("r.fecha::date <= :hasta")
        params["hasta"] = hasta

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    sql = text(_COMPRAS_POR_CATEGORIA_SQL.format(where=where))
    rows = db.execute(sql, params).mappings().all()
    return [ComprasPorCategoriaResponse(**row) for row in rows]


@router.get("/{venta_id}", response_model=VentaResponse, summary="Obtener venta")
def get_venta(
    venta_id: int,
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Retorna una venta con sus detalles por ID. Requiere autenticación."""
    return _get_or_404(venta_id, db)


@router.put("/{venta_id}", response_model=VentaResponse, summary="Actualizar cabecera de venta")
def update_venta(
    venta_id: int,
    body: VentaUpdate,
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Actualiza los campos de cabecera de una venta. Requiere autenticación.

    Si la venta usó un beneficio en el mostrador, no se puede cambiar `socio_id` ni `importe`
    (409 `VENTA_CON_BENEFICIO`): para corregirla, eliminarla (devuelve los puntos) y registrarla de nuevo.
    """
    venta = _get_or_404(venta_id, db)
    cambios = body.model_dump(exclude_unset=True)
    if (
        ("socio_id" in cambios and cambios["socio_id"] != venta.socio_id)
        or ("importe" in cambios and cambios["importe"] != venta.importe)
    ) and puntos_svc.canje_mostrador_de_venta(db, venta.id) is not None:
        raise puntos_svc.error(
            "VENTA_CON_BENEFICIO",
            "La venta usó un beneficio: no se puede cambiar el socio ni el importe. Eliminala y registrala de nuevo.",
        )
    for field, value in cambios.items():
        setattr(venta, field, value)
    db.commit()
    db.refresh(venta)
    return venta


@router.delete("/{venta_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Eliminar venta")
def delete_venta(
    venta_id: int,
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Elimina una venta y todos sus detalles (cascade). Requiere autenticación.

    Revierte los puntos que generó y, si usó un beneficio en el mostrador, anula el canje y
    le devuelve al socio los puntos y al beneficio el stock.
    """
    venta = _get_or_404(venta_id, db)
    puntos_svc.devolver_canje_de_venta(db, venta)  # antes del delete: canjes.venta_id es ON DELETE SET NULL
    puntos_svc.reversar_venta(db, venta)
    db.delete(venta)
    db.commit()


_DETAIL_SQL = text("""
with ventas_rel as (
  select (r.fecha - INTERVAL '3 hours') as fecha, r.socio_id, r.lugar, r.importe, d.iddocumento::bigint as document_id
  FROM registro_ventas r
      left outer join documentos d
      on (r.fecha - INTERVAL '3 hours')::date =  d.fechaentrada::date
     and r.fecha - INTERVAL '3 hours' between d.fechaentrada - INTERVAL '30 minutes' and d.fechaentrada + INTERVAL '2 hour'
     and trunc(r.importe)::integer between trunc(d.valorapagar)::integer - 100 and trunc(d.valorapagar)::integer + 100
  where r.lugar = 'Villa Allende'
    and r.id = :venta_id
  union
  select (r.fecha - INTERVAL '3 hours') as fecha, r.socio_id, r.lugar, r.importe, d.iddocumento::bigint * 50000 as document_id
  FROM registro_ventas r
      left outer join documentos_cp d
      on (r.fecha - INTERVAL '3 hours')::date =  d.fechaentrada::date
     and r.fecha - INTERVAL '3 hours' between d.fechaentrada - INTERVAL '30 minutes' and d.fechaentrada + INTERVAL '2 hour'
     and trunc(r.importe)::integer between trunc(d.valorapagar)::integer - 100 and trunc(d.valorapagar)::integer + 100
  where r.lugar = 'Villa Carlos Paz'
    and r.id = :venta_id
)
select category as categoria, product as producto, subtotal, count as cantidad
  from ventas_rel r
      left outer join panacea_sales_v2 s
        on r.document_id = s.document_id
""")


@router.get("/{venta_id}/detail", response_model=list[VentaDetailResponse], summary="Detalle de venta desde documentos")
def get_venta_detail(
    venta_id: int,
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Retorna el detalle de productos de una venta cruzando con documentos y panacea_sales_v2."""
    _get_or_404(venta_id, db)
    rows = db.execute(_DETAIL_SQL, {"venta_id": venta_id}).mappings().all()
    return [VentaDetailResponse(**row) for row in rows]
