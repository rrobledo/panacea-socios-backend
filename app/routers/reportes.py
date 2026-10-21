from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import passport
from app.database import get_db
from app.models.socio import Socio
from app.schemas.reporte import CumpleanioResponse, RankingComprasResponse

router = APIRouter(prefix="/reportes", tags=["Reportes"])

_TZ = ZoneInfo("America/Argentina/Cordoba")


@router.get("/ranking_compras", response_model=list[RankingComprasResponse], summary="Socios ordenados por mayor compra")
def ranking_compras(
    desde: date | None = None,
    hasta: date | None = None,
    limit: int = 500,
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Total comprado por socio (suma de importes de registro_ventas), de mayor a menor. Filtrable por rango de fechas."""
    filters = ["r.socio_id IS NOT NULL"]
    params: dict = {"limit": limit}

    if desde is not None:
        filters.append("(r.fecha - INTERVAL '3 hours')::date >= :desde")
        params["desde"] = desde
    if hasta is not None:
        filters.append("(r.fecha - INTERVAL '3 hours')::date <= :hasta")
        params["hasta"] = hasta

    sql = text(f"""
        SELECT
            s.id AS socio_id,
            s.nombre_apellido,
            s.dni,
            s.telefono,
            s.email,
            COUNT(r.id) AS cantidad_compras,
            SUM(r.importe) AS total_compras,
            MAX(r.fecha - INTERVAL '3 hours') AS ultima_compra
        FROM registro_ventas r
            JOIN socios s ON s.id = r.socio_id
        WHERE {" AND ".join(filters)}
        GROUP BY s.id, s.nombre_apellido, s.dni, s.telefono, s.email
        ORDER BY total_compras DESC
        LIMIT :limit
    """)
    rows = db.execute(sql, params).mappings().all()
    return [RankingComprasResponse(**row) for row in rows]


@router.get("/cumpleanios", response_model=list[CumpleanioResponse], summary="Socios que cumplen años en un rango de días")
def cumpleanios(
    desde: date | None = None,
    hasta: date | None = None,
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Socios que cumplen años entre `desde` y `hasta` (ambos inclusive; por defecto, hoy en Argentina),
    ordenados por día de cumpleaños. Los nacidos el 29/02 se incluyen el 28/02 en años no bisiestos."""
    hoy = datetime.now(_TZ).date()
    desde = desde or hoy
    hasta = hasta or desde
    if hasta < desde:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="'hasta' debe ser igual o posterior a 'desde'")
    if (hasta - desde).days > 366:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El rango no puede superar un año")

    sql = text("""
        WITH dias AS (
            SELECT d::date AS dia
            FROM generate_series(CAST(:desde AS date), CAST(:hasta AS date), INTERVAL '1 day') AS d
        )
        SELECT dias.dia AS fecha_cumple, s.id AS socio_id, s.nombre_apellido, s.dni, s.telefono, s.email, s.fecha_nacimiento
        FROM dias
            JOIN socios s ON s.fecha_nacimiento IS NOT NULL AND (
                (EXTRACT(MONTH FROM s.fecha_nacimiento) = EXTRACT(MONTH FROM dias.dia)
                 AND EXTRACT(DAY FROM s.fecha_nacimiento) = EXTRACT(DAY FROM dias.dia))
                OR (EXTRACT(MONTH FROM s.fecha_nacimiento) = 2 AND EXTRACT(DAY FROM s.fecha_nacimiento) = 29
                    AND EXTRACT(MONTH FROM dias.dia) = 2 AND EXTRACT(DAY FROM dias.dia) = 28
                    AND EXTRACT(DAY FROM make_date(EXTRACT(YEAR FROM dias.dia)::int, 3, 1) - INTERVAL '1 day') = 28)
            )
        ORDER BY dias.dia, s.nombre_apellido
    """)
    rows = db.execute(sql, {"desde": desde, "hasta": hasta}).mappings().all()
    return [
        CumpleanioResponse(**row, edad=row["fecha_cumple"].year - row["fecha_nacimiento"].year)
        for row in rows
    ]
