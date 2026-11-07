"""Validación de cupones en caja (sin consumirlos)."""
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import passport
from app.database import get_db
from app.models.socio import Socio
from app.schemas.puntos import ValidarCuponResponse
from app.services import puntos as svc

router = APIRouter(prefix="/canjes", tags=["Canjes"])


@router.get("/{codigo}", response_model=ValidarCuponResponse, summary="Validar cupón")
def validar_cupon(
    codigo: str,
    socio_id: int = Query(...),
    monto: Decimal = Query(..., gt=0),
    db: Session = Depends(get_db),
    _: Socio = passport.authenticate("jwt"),
):
    """Indica si el cupón puede aplicarse a una compra de `monto` del socio y el descuento resultante."""
    canje, motivo = svc.evaluar_cupon(db, codigo, socio_id)
    if motivo:
        return ValidarCuponResponse(valido=False, motivo=motivo)
    return ValidarCuponResponse(
        valido=True,
        descuento=float(svc.calcular_descuento(canje, monto)),
        porcentaje_descuento=float(canje.porcentaje_descuento),
    )
