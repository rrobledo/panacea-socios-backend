from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import passport
from app.auth.utils import hash_password
from app.database import get_db
from app.models.socio import Socio
from app.schemas.socio import SocioCreate, SocioResponse, SocioUpdate

router = APIRouter(prefix="/socios", tags=["Socios"])


def _get_or_404(socio_id: int, db: Session) -> Socio:
    socio = db.get(Socio, socio_id)
    if not socio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Socio no encontrado")
    return socio


@router.get("/", response_model=list[SocioResponse], summary="Listar socios")
def list_socios(
    skip: int = 0,
    limit: int = 100,
    dni: str | None = None,
    name: str | None = None,
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Retorna la lista paginada de socios. Requiere autenticación."""
    q = db.query(Socio)
    if dni is not None:
        q = q.filter(Socio.dni == dni)
    if name is not None:
        pattern = func.concat('%', func.unaccent(name), '%')
        q = q.filter(func.unaccent(Socio.nombre_apellido).ilike(pattern))
    return q.offset(skip).limit(limit).all()


@router.post("/", response_model=SocioResponse, status_code=status.HTTP_201_CREATED, summary="Crear socio")
def create_socio(
    body: SocioCreate,
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Crea un nuevo socio. Requiere autenticación. DNI y email deben ser únicos."""
    socio = Socio(**body.model_dump())
    db.add(socio)
    try:
        db.commit()
        db.refresh(socio)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="DNI o email ya registrado")
    return socio


@router.get("/me", response_model=SocioResponse, summary="Obtener perfil propio")
def get_me(current_socio: Socio = passport.authenticate("jwt")):
    """Retorna el perfil del socio autenticado."""
    return current_socio


@router.get("/{socio_id}", response_model=SocioResponse, summary="Obtener socio")
def get_socio(
    socio_id: int,
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Retorna los datos de un socio por su ID. Requiere autenticación."""
    return _get_or_404(socio_id, db)


@router.put("/{socio_id}", response_model=SocioResponse, summary="Actualizar socio")
def update_socio(
    socio_id: int,
    body: SocioUpdate,
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Actualiza parcialmente los datos de un socio. Requiere autenticación."""
    socio = _get_or_404(socio_id, db)
    data = body.model_dump(exclude_unset=True)
    if "password" in data:
        socio.password_hash = hash_password(data.pop("password"))
    for field, value in data.items():
        setattr(socio, field, value)
    try:
        db.commit()
        db.refresh(socio)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="DNI o email ya registrado")
    return socio


@router.delete("/{socio_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Eliminar socio")
def delete_socio(
    socio_id: int,
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Elimina un socio y sus preguntas asociadas. Requiere autenticación."""
    socio = _get_or_404(socio_id, db)
    db.delete(socio)
    db.commit()
