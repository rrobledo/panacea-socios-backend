"""Administración del programa de puntos (pantallas "Maestro").

Por ahora beneficios, reglas y configuración están abiertos a cualquier usuario autenticado
(`require_maestro`). Saldos y ajustes manuales siguen requiriendo rol admin.
Para volver a restringir el maestro, hacer que `require_maestro` delegue en `require_admin`.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import passport
from app.auth.dependencies import require_admin
from app.database import get_db
from app.models.puntos import Beneficio, Canje, ReglaPuntos
from app.models.socio import Socio
from app.schemas.puntos import (
    AjusteCreate,
    BeneficioAdminResponse,
    BeneficioCreate,
    BeneficioUpdate,
    ConfigProgramaSchema,
    MovimientoResponse,
    ReglaCreate,
    ReglaResponse,
    SaldoSocioResponse,
)
from app.services import puntos as svc

router = APIRouter(prefix="/admin", tags=["Admin · Puntos"])


def require_maestro(current_socio: Socio = passport.authenticate("jwt")) -> Socio:
    """Acceso a las pantallas Maestro: cualquier usuario autenticado (temporal)."""
    return current_socio


# ── Beneficios ─────────────────────────────────────────────────────────────────

def _beneficio_response(db: Session, b: Beneficio) -> BeneficioAdminResponse:
    canjes = db.execute(select(func.count()).select_from(Canje).where(Canje.beneficio_id == b.id)).scalar_one()
    resp = BeneficioAdminResponse.model_validate(b)
    resp.canjes_realizados = canjes
    return resp


@router.get("/beneficios", response_model=list[BeneficioAdminResponse], summary="Listar beneficios")
def list_beneficios(db: Session = Depends(get_db), _: Socio = Depends(require_maestro)):
    conteos = dict(db.execute(select(Canje.beneficio_id, func.count()).group_by(Canje.beneficio_id)).all())
    beneficios = db.execute(select(Beneficio).order_by(Beneficio.activo.desc(), Beneficio.costo_puntos)).scalars().all()
    result = []
    for b in beneficios:
        resp = BeneficioAdminResponse.model_validate(b)
        resp.canjes_realizados = conteos.get(b.id, 0)
        result.append(resp)
    return result


@router.post("/beneficios", response_model=BeneficioAdminResponse, status_code=status.HTTP_201_CREATED, summary="Crear beneficio")
def create_beneficio(body: BeneficioCreate, db: Session = Depends(get_db), _: Socio = Depends(require_maestro)):
    beneficio = Beneficio(**body.model_dump())
    db.add(beneficio)
    db.commit()
    db.refresh(beneficio)
    return _beneficio_response(db, beneficio)


@router.put("/beneficios/{beneficio_id}", response_model=BeneficioAdminResponse, summary="Actualizar beneficio")
def update_beneficio(
    beneficio_id: int, body: BeneficioUpdate, db: Session = Depends(get_db), _: Socio = Depends(require_maestro)
):
    """Actualización parcial (incluye activar/desactivar). Los cupones emitidos conservan su snapshot."""
    beneficio = db.get(Beneficio, beneficio_id)
    if beneficio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Beneficio no encontrado")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(beneficio, field, value)
    if beneficio.vigente_hasta and beneficio.vigente_hasta < beneficio.vigente_desde:
        raise svc.error("VIGENCIA_INVALIDA", "vigente_hasta debe ser posterior a vigente_desde", 422)
    db.commit()
    db.refresh(beneficio)
    return _beneficio_response(db, beneficio)


# ── Reglas de conversión ───────────────────────────────────────────────────────

@router.get("/reglas-puntos", response_model=list[ReglaResponse], summary="Historial de reglas de conversión")
def list_reglas(db: Session = Depends(get_db), _: Socio = Depends(require_maestro)):
    return db.execute(select(ReglaPuntos).order_by(ReglaPuntos.vigente_desde.desc())).scalars().all()


@router.post("/reglas-puntos", response_model=ReglaResponse, status_code=status.HTTP_201_CREATED, summary="Crear regla de conversión")
def create_regla(body: ReglaCreate, db: Session = Depends(get_db), admin: Socio = Depends(require_maestro)):
    """Cierra la regla abierta y abre la nueva desde `vigente_desde` (>= hoy). No hay edición retroactiva."""
    if body.vigente_desde < svc.hoy_local():
        raise svc.error("VIGENCIA_RETROACTIVA", "La fecha de inicio no puede ser anterior a hoy", 422)
    # Serializa altas concurrentes de reglas
    reglas = db.execute(select(ReglaPuntos).with_for_update()).scalars().all()
    if any(r.vigente_desde >= body.vigente_desde for r in reglas):
        raise svc.error(
            "CONFLICTO_VIGENCIA",
            "Ya existe una regla que empieza en esa fecha o después. Eliminá la regla programada primero.",
        )
    for r in reglas:
        if r.vigente_hasta is None:
            r.vigente_hasta = body.vigente_desde
    regla = ReglaPuntos(**body.model_dump(), creado_por=admin.email)
    db.add(regla)
    db.commit()
    db.refresh(regla)
    return regla


@router.delete("/reglas-puntos/{regla_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Eliminar regla programada")
def delete_regla(regla_id: int, db: Session = Depends(get_db), _: Socio = Depends(require_maestro)):
    """Solo reglas que todavía no empezaron. La regla anterior vuelve a quedar abierta."""
    regla = db.get(ReglaPuntos, regla_id)
    if regla is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regla no encontrada")
    if regla.vigente_desde <= svc.hoy_local():
        raise svc.error("REGLA_EN_USO", "Solo se pueden eliminar reglas programadas a futuro")
    anterior = db.execute(
        select(ReglaPuntos).where(ReglaPuntos.vigente_hasta == regla.vigente_desde)
    ).scalar_one_or_none()
    if anterior:
        anterior.vigente_hasta = regla.vigente_hasta
    db.delete(regla)
    db.commit()


# ── Configuración ──────────────────────────────────────────────────────────────

@router.get("/configuracion", response_model=ConfigProgramaSchema, summary="Configuración del programa")
def get_configuracion(db: Session = Depends(get_db), _: Socio = Depends(require_maestro)):
    config = svc.get_config(db)
    db.commit()
    return config


@router.put("/configuracion", response_model=ConfigProgramaSchema, summary="Actualizar configuración")
def update_configuracion(body: ConfigProgramaSchema, db: Session = Depends(get_db), _: Socio = Depends(require_maestro)):
    config = svc.get_config(db)
    for field, value in body.model_dump().items():
        setattr(config, field, value)
    db.commit()
    db.refresh(config)
    return config


# ── Saldos y ajustes ───────────────────────────────────────────────────────────

@router.get("/socios/{socio_id}/puntos", response_model=SaldoSocioResponse, summary="Saldo de un socio")
def get_saldo_socio(socio_id: int, db: Session = Depends(get_db), _: Socio = Depends(require_admin)):
    socio = db.get(Socio, socio_id)
    if socio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Socio no encontrado")
    return SaldoSocioResponse(socio_id=socio.id, saldo=socio.saldo_puntos or 0)


@router.post("/ajustes-puntos", response_model=MovimientoResponse, status_code=status.HTTP_201_CREATED, summary="Ajuste manual de puntos")
def create_ajuste(body: AjusteCreate, db: Session = Depends(get_db), admin: Socio = Depends(require_admin)):
    mov = svc.ajustar_puntos(db, body.socio_id, body.puntos, body.motivo, admin.email)
    db.commit()
    return MovimientoResponse(id=mov.id, tipo=mov.tipo, puntos=mov.puntos, descripcion=mov.descripcion, fecha=mov.creado_en)
