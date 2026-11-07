"""Procesos diarios del programa de puntos, invocados por Vercel Cron.

Vercel envía `Authorization: Bearer $CRON_SECRET` en cada invocación del cron.
"""
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.services import puntos as svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["Jobs"], include_in_schema=False)


def _check_cron_secret(authorization: str | None = Header(None)) -> None:
    if not settings.cron_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="CRON_SECRET no configurado")
    if authorization != f"Bearer {settings.cron_secret}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")


@router.get("/diario", dependencies=[Depends(_check_cron_secret)])
def job_diario(db: Session = Depends(get_db)):
    """Vence cupones (sin devolver puntos), expira puntos (FIFO) y concilia saldos."""
    cupones = svc.vencer_cupones(db)
    db.commit()
    socios_expirados = svc.expirar_puntos(db)
    db.commit()
    saldos_corregidos = svc.conciliar_saldos(db)
    db.commit()
    result = {
        "cupones_vencidos": cupones,
        "socios_con_puntos_expirados": socios_expirados,
        "saldos_corregidos": saldos_corregidos,
    }
    logger.info("Job diario de puntos: %s", result)
    return result
