from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import passport
from app.database import get_db
from app.models.socio import Socio
from app.models.venta import DetalleRegistroVenta, RegistroVenta
from app.schemas.venta import ComprasPorCategoriaResponse, ComprasSemanalResponse, VentaCreate, VentaDetailResponse, VentaResponse, VentaUpdate

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


@router.post("/", response_model=VentaResponse, status_code=status.HTTP_201_CREATED, summary="Registrar venta")
def create_venta(
    body: VentaCreate,
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Crea un registro de venta con sus líneas de detalle. Requiere autenticación."""
    detalles_data = body.detalles
    venta_data = body.model_dump(exclude={"detalles"})
    venta = RegistroVenta(**venta_data)
    db.add(venta)
    db.flush()

    for d in detalles_data:
        detalle = DetalleRegistroVenta(registro_venta_id=venta.id, **d.model_dump())
        db.add(detalle)

    db.commit()
    db.refresh(venta)
    return venta


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
    """Actualiza los campos de cabecera de una venta. Requiere autenticación."""
    venta = _get_or_404(venta_id, db)
    for field, value in body.model_dump(exclude_unset=True).items():
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
    """Elimina una venta y todos sus detalles (cascade). Requiere autenticación."""
    venta = _get_or_404(venta_id, db)
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
