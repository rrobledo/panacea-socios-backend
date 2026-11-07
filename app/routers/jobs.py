"""Procesos diarios del programa de puntos, invocados por Vercel Cron.

Vercel envía `Authorization: Bearer $CRON_SECRET` en cada invocación del cron.
"""
import logging

import anthropic

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.services import perfiles as perfiles_svc
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


def get_anthropic_client():
    """Cliente de Claude para el proceso de perfiles (se reemplaza en los tests)."""
    return perfiles_svc.crear_cliente()


@router.get("/perfiles", dependencies=[Depends(_check_cron_secret)])
def job_perfiles(db: Session = Depends(get_db), client=Depends(get_anthropic_client)):
    """Perfiles de preferencias con IA: procesa los lotes terminados y, si no queda ninguno
    pendiente, envía un lote nuevo con los socios que tienen compras nuevas. No espera a la IA."""
    activo, motivo = perfiles_svc.proceso_activo()
    if not activo:
        return {"activo": False, "motivo": motivo}

    resultado = perfiles_svc.procesar_lotes_pendientes(db, client)
    db.commit()

    lote_enviado = None
    if perfiles_svc.lotes_pendientes(db) == 0:
        try:
            lote = perfiles_svc.enviar_lote(db, client)
            db.commit()
        except anthropic.APIError as e:
            db.rollback()
            logger.exception("No se pudo enviar el lote de perfiles")
            resultado["error_envio"] = str(e)[:300]
            lote = None
        if lote is not None:
            lote_enviado = {"batch_id": lote.batch_id, "socios": lote.socios}
    resultado = {"activo": True, **resultado, "lote_enviado": lote_enviado}
    logger.info("Job de perfiles: %s", resultado)
    return resultado
