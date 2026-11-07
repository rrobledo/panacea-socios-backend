"""Relación entre las ventas registradas y el detalle de productos de los tickets de cada local.

`registro_ventas` no guarda productos: el detalle se obtiene cruzando cada venta con el
documento de su local (`documentos` para Villa Allende, `documentos_cp` para Villa Carlos Paz,
cuyo id se multiplica por 50000) por fecha e importe, y el documento con `panacea_sales_v2`.

A diferencia de las consultas de `routers/ventas.py`, acá se elige UN documento por venta
(el más cercano por importe y hora) para no sumar productos de dos tickets parecidos.
"""
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

# Ventas con socio, desde :desde (UTC naive), relacionadas con un documento que tiene líneas de venta.
# Las fechas se pasan a hora local restando 3 horas, igual que el resto de los reportes.
_VENTAS_REL_CTE = """
    candidatos AS (
      SELECT r.id AS venta_id, r.socio_id, r.fecha, d.iddocumento::bigint AS document_id,
             abs(trunc(r.importe)::integer - trunc(d.valorapagar)::integer) AS dif_importe,
             abs(extract(epoch FROM (r.fecha - INTERVAL '3 hours') - d.fechaentrada)) AS dif_tiempo
      FROM registro_ventas r
          JOIN documentos d
          ON (r.fecha - INTERVAL '3 hours')::date = d.fechaentrada::date
         AND r.fecha - INTERVAL '3 hours' BETWEEN d.fechaentrada - INTERVAL '30 minutes' AND d.fechaentrada + INTERVAL '2 hour'
         AND trunc(r.importe)::integer BETWEEN trunc(d.valorapagar)::integer - 100 AND trunc(d.valorapagar)::integer + 100
      WHERE r.lugar = 'Villa Allende' AND r.socio_id IS NOT NULL AND r.fecha >= :desde {filtro}
      UNION ALL
      SELECT r.id, r.socio_id, r.fecha, d.iddocumento::bigint * 50000,
             abs(trunc(r.importe)::integer - trunc(d.valorapagar)::integer),
             abs(extract(epoch FROM (r.fecha - INTERVAL '3 hours') - d.fechaentrada))
      FROM registro_ventas r
          JOIN documentos_cp d
          ON (r.fecha - INTERVAL '3 hours')::date = d.fechaentrada::date
         AND r.fecha - INTERVAL '3 hours' BETWEEN d.fechaentrada - INTERVAL '30 minutes' AND d.fechaentrada + INTERVAL '2 hour'
         AND trunc(r.importe)::integer BETWEEN trunc(d.valorapagar)::integer - 100 AND trunc(d.valorapagar)::integer + 100
      WHERE r.lugar = 'Villa Carlos Paz' AND r.socio_id IS NOT NULL AND r.fecha >= :desde {filtro}
    ),
    ventas_doc AS (
      SELECT DISTINCT ON (venta_id) venta_id, socio_id, fecha, document_id
      FROM candidatos
      ORDER BY venta_id, dif_importe, dif_tiempo, document_id
    ),
    ventas_rel AS (
      SELECT v.* FROM ventas_doc v
      WHERE EXISTS (SELECT 1 FROM panacea_sales_v2 s WHERE s.document_id = v.document_id)
    )
"""


def _cte(filtrar_socios: bool) -> str:
    return _VENTAS_REL_CTE.format(filtro="AND r.socio_id = ANY(:socio_ids)" if filtrar_socios else "")


@dataclass
class ProductoComprado:
    categoria: str | None
    producto: str
    cantidad: float
    compras: int
    ultima_compra: date


@dataclass
class ComprasSocio:
    socio_id: int
    ventas: int
    periodo_desde: date
    periodo_hasta: date
    ultima_venta_fecha: datetime  # UTC naive
    productos: list[ProductoComprado] = field(default_factory=list)


def socios_a_perfilar(db: Session, desde: datetime, limite: int) -> list[int]:
    """Socios con ventas relacionables posteriores a la última considerada en su perfil (o sin
    perfil), que no estén en un lote pendiente. Primero los de compra más reciente."""
    sql = text(f"""
        WITH {_cte(False)}
        SELECT v.socio_id
        FROM ventas_rel v
            LEFT JOIN perfiles_socio p ON p.socio_id = v.socio_id
        WHERE NOT EXISTS (
            SELECT 1 FROM lote_perfil_items i JOIN lotes_perfiles l ON l.id = i.lote_id
            WHERE i.socio_id = v.socio_id AND l.estado = 'ENVIADO'
        )
        GROUP BY v.socio_id, p.ultima_venta_fecha
        HAVING p.ultima_venta_fecha IS NULL OR max(v.fecha) > p.ultima_venta_fecha
        ORDER BY max(v.fecha) DESC, v.socio_id
        LIMIT :limite
    """)
    return list(db.execute(sql, {"desde": desde, "limite": limite}).scalars())


def compras_por_socio(db: Session, socio_ids: list[int], desde: datetime, max_productos: int) -> dict[int, ComprasSocio]:
    """Productos de las ventas relacionables de cada socio, agrupados por producto.

    Deja los `max_productos` más comprados (por cantidad de compras y después por unidades).
    """
    if not socio_ids:
        return {}
    params = {"desde": desde, "socio_ids": list(socio_ids)}
    resumen = db.execute(text(f"""
        WITH {_cte(True)}
        SELECT socio_id, count(*) AS ventas,
               min((fecha - INTERVAL '3 hours')::date) AS desde,
               max((fecha - INTERVAL '3 hours')::date) AS hasta,
               max(fecha) AS ultima
        FROM ventas_rel GROUP BY socio_id
    """), params).mappings().all()
    resultado = {
        r["socio_id"]: ComprasSocio(
            socio_id=r["socio_id"], ventas=r["ventas"], periodo_desde=r["desde"],
            periodo_hasta=r["hasta"], ultima_venta_fecha=r["ultima"],
        )
        for r in resumen
    }
    filas = db.execute(text(f"""
        WITH {_cte(True)}
        SELECT v.socio_id, s.category AS categoria, s.product AS producto,
               COALESCE(sum(s.count), 0) AS cantidad,
               count(DISTINCT v.venta_id) AS compras,
               max((v.fecha - INTERVAL '3 hours')::date) AS ultima_compra
        FROM ventas_rel v
            JOIN panacea_sales_v2 s ON s.document_id = v.document_id
        WHERE s.product IS NOT NULL AND btrim(s.product) <> ''
        GROUP BY v.socio_id, s.category, s.product
    """), params).mappings().all()
    for f in filas:
        compras = resultado.get(f["socio_id"])
        if compras is not None:
            compras.productos.append(ProductoComprado(
                categoria=f["categoria"], producto=f["producto"].strip(), cantidad=float(f["cantidad"]),
                compras=f["compras"], ultima_compra=f["ultima_compra"],
            ))
    for compras in resultado.values():
        compras.productos.sort(key=lambda p: (-p.compras, -p.cantidad, p.producto))
        del compras.productos[max_productos:]
    return resultado
