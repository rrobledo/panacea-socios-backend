"""Migración única de compras históricas al sistema de puntos.

Por defecto corre en modo simulación (no escribe nada). Usar --aplicar para confirmar.

Modos:
  historico  Genera ACUMULACION para cada venta con socio que todavía no tenga puntos,
             usando la regla vigente a la fecha de esa venta. Las reglas de períodos
             pasados se cargan desde un CSV (--reglas) con columnas:
                 vigente_desde,monto_por_punto[,multiplicador,tope_por_compra]
             ordenadas por fecha; cada una se cierra donde empieza la siguiente y la
             última se cierra donde empieza la primera regla ya cargada en la base.
  bono       Registra un movimiento MIGRACION de --puntos para cada socio con al menos
             una compra registrada.

Los movimientos se registran con fecha de HOY para que no venzan de inmediato.

Ejemplos:
  python -m scripts.migrar_puntos_historicos historico --reglas reglas_2024_2026.csv
  python -m scripts.migrar_puntos_historicos historico --reglas reglas.csv --aplicar
  python -m scripts.migrar_puntos_historicos bono --puntos 200 --aplicar
"""
import argparse
import csv
import sys
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.database import SessionLocal
from app.models.puntos import MovimientoPuntos, ReglaPuntos, TipoMovimiento
from app.models.venta import RegistroVenta
from app.services import puntos as svc

MOTIVO = "Migración histórica"


def cargar_reglas(db, path: str) -> int:
    with open(path, newline="", encoding="utf-8") as f:
        filas = sorted(csv.DictReader(f), key=lambda r: r["vigente_desde"])
    if not filas:
        return 0
    primera_existente = db.execute(
        select(ReglaPuntos.vigente_desde).order_by(ReglaPuntos.vigente_desde).limit(1)
    ).scalar_one_or_none()
    desdes = [date.fromisoformat(r["vigente_desde"]) for r in filas]
    hastas = desdes[1:] + [primera_existente]
    if primera_existente and desdes[-1] >= primera_existente:
        sys.exit(f"Las reglas del CSV deben empezar antes de {primera_existente} (primera regla existente)")
    for fila, desde, hasta in zip(filas, desdes, hastas):
        db.add(ReglaPuntos(
            monto_por_punto=Decimal(fila["monto_por_punto"]),
            multiplicador=Decimal(fila.get("multiplicador") or "1"),
            tope_por_compra=int(fila["tope_por_compra"]) if fila.get("tope_por_compra") else None,
            vigente_desde=desde,
            vigente_hasta=hasta,
            motivo=MOTIVO,
            creado_por="script",
        ))
    db.flush()
    return len(filas)


def migrar_historico(db, reglas_csv: str | None) -> tuple[int, int]:
    if reglas_csv:
        print(f"Reglas históricas cargadas: {cargar_reglas(db, reglas_csv)}")
    con_puntos = select(MovimientoPuntos.venta_id).where(
        MovimientoPuntos.tipo == TipoMovimiento.ACUMULACION, MovimientoPuntos.venta_id.is_not(None)
    )
    ventas = db.execute(
        select(RegistroVenta)
        .where(RegistroVenta.socio_id.is_not(None), RegistroVenta.id.not_in(con_puntos))
        .order_by(RegistroVenta.fecha)
    ).scalars().all()
    total_puntos, sin_regla = 0, 0
    for venta in ventas:
        if svc.regla_vigente(db, svc.fecha_local(venta.fecha)) is None:
            sin_regla += 1
            continue
        total_puntos += svc.acumular_por_venta(db, venta)
    print(f"Ventas procesadas: {len(ventas)} · sin regla para su fecha: {sin_regla} · puntos generados: {total_puntos}")
    return len(ventas), total_puntos


def migrar_bono(db, puntos: int) -> int:
    socios = db.execute(
        select(RegistroVenta.socio_id).where(RegistroVenta.socio_id.is_not(None)).distinct()
    ).scalars().all()
    ya_migrados = set(db.execute(
        select(MovimientoPuntos.socio_id).where(MovimientoPuntos.tipo == TipoMovimiento.MIGRACION)
    ).scalars().all())
    nuevos = [s for s in socios if s not in ya_migrados]
    for socio_id in nuevos:
        socio = svc.bloquear_socio(db, socio_id)
        svc.registrar_movimiento(db, socio, TipoMovimiento.MIGRACION, puntos, descripcion="Bono de bienvenida al programa de puntos")
    print(f"Socios con bono: {len(nuevos)} (ya migrados antes: {len(socios) - len(nuevos)}) · puntos: {len(nuevos) * puntos}")
    return len(nuevos)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("modo", choices=["historico", "bono"])
    parser.add_argument("--reglas", help="CSV de reglas históricas (modo historico)")
    parser.add_argument("--puntos", type=int, help="Puntos por socio (modo bono)")
    parser.add_argument("--aplicar", action="store_true", help="Confirma los cambios (por defecto solo simula)")
    args = parser.parse_args()

    if args.modo == "bono" and not (args.puntos and args.puntos > 0):
        parser.error("--puntos debe ser mayor a 0 en modo bono")

    db = SessionLocal()
    try:
        if args.modo == "historico":
            migrar_historico(db, args.reglas)
        else:
            migrar_bono(db, args.puntos)
        if args.aplicar:
            db.commit()
            print("Cambios APLICADOS.")
        else:
            db.rollback()
            print("Simulación: no se guardó nada. Usar --aplicar para confirmar.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
