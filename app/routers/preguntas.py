from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.pregunta import ClavePregunta, PreguntaPorSocio
from app.models.socio import Socio
from app.schemas.pregunta import PreguntaCreate, PreguntaResponse, PreguntaUpdate

router = APIRouter(prefix="/socios/{socio_id}/preguntas", tags=["Preguntas por Socio"])


def _get_socio_or_404(socio_id: int, db: Session) -> Socio:
    socio = db.get(Socio, socio_id)
    if not socio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Socio no encontrado")
    return socio


@router.get("/", response_model=list[PreguntaResponse], summary="Listar preferencias del socio")
def list_preguntas(socio_id: int, db: Session = Depends(get_db)):
    """Retorna todas las preferencias registradas para un socio."""
    _get_socio_or_404(socio_id, db)
    return db.query(PreguntaPorSocio).filter(PreguntaPorSocio.socio_id == socio_id).all()


@router.post("/", response_model=PreguntaResponse, status_code=status.HTTP_201_CREATED, summary="Agregar o actualizar preferencia")
def upsert_pregunta(socio_id: int, body: PreguntaCreate, db: Session = Depends(get_db)):
    """Crea o actualiza una preferencia (clave única por socio)."""
    _get_socio_or_404(socio_id, db)
    existing = (
        db.query(PreguntaPorSocio)
        .filter(PreguntaPorSocio.socio_id == socio_id, PreguntaPorSocio.clave == body.clave)
        .first()
    )
    if existing:
        existing.valor = body.valor
        db.commit()
        db.refresh(existing)
        return existing

    pregunta = PreguntaPorSocio(socio_id=socio_id, clave=body.clave, valor=body.valor)
    db.add(pregunta)
    db.commit()
    db.refresh(pregunta)
    return pregunta


@router.get("/{clave}", response_model=PreguntaResponse, summary="Obtener una preferencia por clave")
def get_pregunta(socio_id: int, clave: ClavePregunta, db: Session = Depends(get_db)):
    """Retorna la respuesta a una clave específica para un socio."""
    _get_socio_or_404(socio_id, db)
    pregunta = (
        db.query(PreguntaPorSocio)
        .filter(PreguntaPorSocio.socio_id == socio_id, PreguntaPorSocio.clave == clave)
        .first()
    )
    if not pregunta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preferencia no encontrada")
    return pregunta


@router.put("/{clave}", response_model=PreguntaResponse, summary="Actualizar una preferencia")
def update_pregunta(socio_id: int, clave: ClavePregunta, body: PreguntaUpdate, db: Session = Depends(get_db)):
    """Actualiza el valor de una preferencia existente."""
    _get_socio_or_404(socio_id, db)
    pregunta = (
        db.query(PreguntaPorSocio)
        .filter(PreguntaPorSocio.socio_id == socio_id, PreguntaPorSocio.clave == clave)
        .first()
    )
    if not pregunta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preferencia no encontrada")
    pregunta.valor = body.valor
    db.commit()
    db.refresh(pregunta)
    return pregunta


@router.delete("/{clave}", status_code=status.HTTP_204_NO_CONTENT, summary="Eliminar una preferencia")
def delete_pregunta(socio_id: int, clave: ClavePregunta, db: Session = Depends(get_db)):
    """Elimina la respuesta a una clave específica para un socio."""
    _get_socio_or_404(socio_id, db)
    pregunta = (
        db.query(PreguntaPorSocio)
        .filter(PreguntaPorSocio.socio_id == socio_id, PreguntaPorSocio.clave == clave)
        .first()
    )
    if not pregunta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preferencia no encontrada")
    db.delete(pregunta)
    db.commit()
