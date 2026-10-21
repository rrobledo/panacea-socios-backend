from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
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


@router.get("/cumpleanios", response_model=list[CumpleanioResponse], summary="Socios que cumplen años en un día")
def cumpleanios(
    fecha: date | None = None,
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Socios cuyo día y mes de nacimiento coinciden con `fecha` (por defecto, hoy en Argentina).
    Los nacidos el 29/02 se incluyen el 28/02 en años no bisiestos."""
    fecha = fecha or datetime.now(_TZ).date()
    es_bisiesto = fecha.year % 4 == 0 and (fecha.year % 100 != 0 or fecha.year % 400 == 0)
    incluir_29_feb = fecha.month == 2 and fecha.day == 28 and not es_bisiesto

    sql = text("""
        SELECT id AS socio_id, nombre_apellido, dni, telefono, email, fecha_nacimiento
        FROM socios
        WHERE fecha_nacimiento IS NOT NULL
          AND (
            (EXTRACT(MONTH FROM fecha_nacimiento) = :mes AND EXTRACT(DAY FROM fecha_nacimiento) = :dia)
            OR (:incluir_29_feb AND EXTRACT(MONTH FROM fecha_nacimiento) = 2 AND EXTRACT(DAY FROM fecha_nacimiento) = 29)
          )
        ORDER BY nombre_apellido
    """)
    rows = db.execute(sql, {"mes": fecha.month, "dia": fecha.day, "incluir_29_feb": incluir_29_feb}).mappings().all()
    return [CumpleanioResponse(**row, edad=fecha.year - row["fecha_nacimiento"].year) for row in rows]
