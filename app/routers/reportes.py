from datetime import date, datetime
from zoneinfo import ZoneInfo

import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import passport
from app.database import get_db
from app.models.socio import Socio
from app.schemas.perfil import Coincidencia, EtiquetaConteoResponse, SocioPorPreferenciaResponse
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


# ── Socios por preferencia (perfiles generados con IA) ─────────────────────────

def _normalizar(texto: str) -> str:
    """Minúsculas y sin acentos (mismo criterio que unaccent(lower(...)) en la base)."""
    sin_acentos = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sin_acentos if not unicodedata.combining(c)).lower()


def _fragmento(texto: str, q: str, ancho: int = 60) -> str:
    i = _normalizar(texto).find(q)
    if i < 0:
        return texto[:ancho * 2]
    inicio, fin = max(0, i - ancho), min(len(texto), i + len(q) + ancho)
    return ("…" if inicio else "") + texto[inicio:fin].strip() + ("…" if fin < len(texto) else "")


def _coincidencias(fila, q: str, incluir_resumen: bool) -> list[Coincidencia]:
    salida = []
    for campo, valores in (("etiqueta", fila["etiquetas"]), ("producto", fila["productos_favoritos"]),
                           ("categoria", fila["categorias_favoritas"])):
        salida += [Coincidencia(campo=campo, valor=v) for v in valores or [] if q in _normalizar(v)]
    if incluir_resumen and q in _normalizar(fila["resumen"]):
        salida.append(Coincidencia(campo="resumen", valor=_fragmento(fila["resumen"], q)))
    return salida


_COINCIDE = "EXISTS (SELECT 1 FROM jsonb_array_elements_text(p.{col}) x WHERE unaccent(lower(x)) LIKE :patron)"

_SOCIOS_POR_PREFERENCIA_SQL = text(f"""
    SELECT * FROM (
        SELECT s.id AS socio_id, s.nombre_apellido, s.dni, s.telefono, s.email,
               p.etiquetas, p.productos_favoritos, p.categorias_favoritas, p.resumen,
               p.generado_en AS perfil_generado_en,
               GREATEST(
                   CASE WHEN {_COINCIDE.format(col="etiquetas")} THEN 4 ELSE 0 END,
                   CASE WHEN {_COINCIDE.format(col="productos_favoritos")} THEN 3 ELSE 0 END,
                   CASE WHEN {_COINCIDE.format(col="categorias_favoritas")} THEN 2 ELSE 0 END,
                   CASE WHEN :incluir_resumen AND unaccent(lower(p.resumen)) LIKE :patron THEN 1 ELSE 0 END
               ) AS relevancia
        FROM perfiles_socio p
            JOIN socios s ON s.id = p.socio_id
    ) t
    WHERE relevancia > 0
    ORDER BY relevancia DESC, nombre_apellido, socio_id
    OFFSET :skip LIMIT :limit
""")


@router.get("/preferencias", response_model=list[SocioPorPreferenciaResponse], summary="Socios por producto o preferencia")
def socios_por_preferencia(
    q: str = Query(..., min_length=2, max_length=100, description="Producto, categoría o preferencia (sin distinguir acentos)"),
    incluir_resumen: bool = False,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Socios cuyo perfil de preferencias (generado con IA) coincide con `q` en etiquetas,
    productos favoritos o categorías favoritas, y en el resumen si `incluir_resumen=true`.

    Coincidencia parcial sin distinguir mayúsculas ni acentos. Orden por relevancia
    (etiqueta > producto > categoría > resumen) y después por nombre.
    """
    qn = _normalizar(q.strip())
    if len(qn) < 2:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="q debe tener al menos 2 caracteres")
    patron = "%" + qn.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    filas = db.execute(_SOCIOS_POR_PREFERENCIA_SQL, {
        "patron": patron, "incluir_resumen": incluir_resumen, "skip": skip, "limit": limit,
    }).mappings().all()
    return [
        SocioPorPreferenciaResponse(
            socio_id=f["socio_id"], nombre_apellido=f["nombre_apellido"], dni=f["dni"], telefono=f["telefono"],
            email=f["email"], relevancia=f["relevancia"], perfil_generado_en=f["perfil_generado_en"],
            coincidencias=_coincidencias(f, qn, incluir_resumen),
        )
        for f in filas
    ]


@router.get("/preferencias/etiquetas", response_model=list[EtiquetaConteoResponse], summary="Etiquetas de preferencia y cantidad de socios")
def etiquetas_preferencias(
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Todas las etiquetas presentes en los perfiles, con cuántos socios tiene cada una."""
    filas = db.execute(text("""
        SELECT e AS etiqueta, count(DISTINCT p.socio_id) AS socios
        FROM perfiles_socio p, jsonb_array_elements_text(p.etiquetas) e
        GROUP BY e ORDER BY socios DESC, e
    """)).mappings().all()
    return [EtiquetaConteoResponse(**f) for f in filas]
