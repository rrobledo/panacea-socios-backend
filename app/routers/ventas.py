from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.venta import DetalleRegistroVenta, RegistroVenta
from app.schemas.venta import VentaCreate, VentaResponse, VentaUpdate

router = APIRouter(prefix="/ventas", tags=["Registro de Ventas"])


def _get_or_404(venta_id: int, db: Session) -> RegistroVenta:
    venta = db.get(RegistroVenta, venta_id)
    if not venta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venta no encontrada")
    return venta


@router.get("/", response_model=list[VentaResponse], summary="Listar ventas")
def list_ventas(
    socio_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """Retorna ventas con sus detalles. Filtrable por socio_id."""
    q = db.query(RegistroVenta)
    if socio_id is not None:
        q = q.filter(RegistroVenta.socio_id == socio_id)
    return q.offset(skip).limit(limit).all()


@router.post("/", response_model=VentaResponse, status_code=status.HTTP_201_CREATED, summary="Registrar venta")
def create_venta(body: VentaCreate, db: Session = Depends(get_db)):
    """Crea un registro de venta con sus líneas de detalle."""
    detalles_data = body.detalles
    venta_data = body.model_dump(exclude={"detalles"})
    venta = RegistroVenta(**venta_data)
    db.add(venta)
    db.flush()

    for d in detalles_data:
        detalle = DetalleRegistroVenta(registro_venta_id=venta.id, **d.model_dump())
        db.add(detalle)

    db.commit()
    db.refresh(venta)
    return venta


@router.get("/{venta_id}", response_model=VentaResponse, summary="Obtener venta")
def get_venta(venta_id: int, db: Session = Depends(get_db)):
    """Retorna una venta con sus detalles por ID."""
    return _get_or_404(venta_id, db)


@router.put("/{venta_id}", response_model=VentaResponse, summary="Actualizar cabecera de venta")
def update_venta(venta_id: int, body: VentaUpdate, db: Session = Depends(get_db)):
    """Actualiza los campos de cabecera de una venta (no los detalles)."""
    venta = _get_or_404(venta_id, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(venta, field, value)
    db.commit()
    db.refresh(venta)
    return venta


@router.delete("/{venta_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Eliminar venta")
def delete_venta(venta_id: int, db: Session = Depends(get_db)):
    """Elimina una venta y todos sus detalles (cascade)."""
    venta = _get_or_404(venta_id, db)
    db.delete(venta)
    db.commit()
