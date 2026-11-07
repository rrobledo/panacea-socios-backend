"""Endpoints del socio autenticado: saldo, actividad, beneficios, canje, cupones y máquina."""
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import passport
from app.database import get_db
from app.models.puntos import Canje, EstadoCanje, MovimientoPuntos
from app.models.socio import Socio
from app.schemas.puntos import (
    BeneficioSocioResponse,
    CanjeResponse,
    CreditosResponse,
    CuponResponse,
    JugarResponse,
    MaquinaResponse,
    MovimientoResponse,
    ReglaVigenteResponse,
)
from app.services import puntos as svc

router = APIRouter(prefix="/recompensas", tags=["Recompensas"])

_STATUS_CUPON = {
    EstadoCanje.EMITIDO: "ACTIVE",
    EstadoCanje.USADO: "USED",
    EstadoCanje.EXPIRADO: "EXPIRED",
    EstadoCanje.CANCELADO: "EXPIRED",
}


def cupon_response(canje: Canje) -> CuponResponse:
    return CuponResponse(
        id=canje.id,
        codigo=canje.codigo,
        title=canje.titulo,
        porcentaje_descuento=float(canje.porcentaje_descuento),
        tope_descuento=float(canje.tope_descuento) if canje.tope_descuento is not None else None,
        status=_STATUS_CUPON[svc.estado_cupon(canje)],
        expires=canje.expira_en,
        origen=canje.origen,
    )


@router.get("/creditos", response_model=CreditosResponse, summary="Saldo de puntos")
def get_creditos(db: Session = Depends(get_db), socio: Socio = passport.authenticate("jwt")):
    saldo = socio.saldo_puntos or 0
    return CreditosResponse(
        saldo=saldo,
        por_vencer=svc.por_vencer(db, socio.id),
        proxima_recompensa=svc.proxima_recompensa(db, saldo),
    )


@router.get("/actividad", response_model=list[MovimientoResponse], summary="Movimientos de puntos")
def get_actividad(limit: int = 50, db: Session = Depends(get_db), socio: Socio = passport.authenticate("jwt")):
    movimientos = db.execute(
        select(MovimientoPuntos)
        .where(MovimientoPuntos.socio_id == socio.id)
        .order_by(MovimientoPuntos.creado_en.desc(), MovimientoPuntos.id.desc())
        .limit(min(max(limit, 1), 200))
    ).scalars().all()
    return [
        MovimientoResponse(id=m.id, tipo=m.tipo, puntos=m.puntos, descripcion=m.descripcion, fecha=m.creado_en)
        for m in movimientos
    ]


@router.get("/regla-vigente", response_model=ReglaVigenteResponse | None, summary="Regla de conversión vigente")
def get_regla_vigente(db: Session = Depends(get_db), _: Socio = passport.authenticate("jwt")):
    regla = svc.regla_vigente(db, svc.hoy_local())
    if regla is None:
        return None
    return ReglaVigenteResponse(
        monto_por_punto=float(regla.monto_por_punto),
        multiplicador=float(regla.multiplicador),
        tope_por_compra=regla.tope_por_compra,
        vigente_desde=regla.vigente_desde,
    )


@router.get("/beneficios", response_model=list[BeneficioSocioResponse], summary="Catálogo de beneficios")
def get_beneficios(db: Session = Depends(get_db), socio: Socio = passport.authenticate("jwt")):
    usados = svc.canjes_por_beneficio(db, socio.id)
    activo = svc.get_config(db).programa_activo
    saldo = socio.saldo_puntos or 0
    return [
        BeneficioSocioResponse(
            id=b.id,
            nombre=b.nombre,
            descripcion=b.descripcion,
            imagen_url=b.imagen_url,
            costo_puntos=b.costo_puntos,
            porcentaje_descuento=float(b.porcentaje_descuento),
            tope_descuento=float(b.tope_descuento) if b.tope_descuento is not None else None,
            dias_validez_cupon=b.dias_validez_cupon,
            canjeable=(
                activo
                and saldo >= b.costo_puntos
                and (b.limite_por_socio is None or usados.get(b.id, 0) < b.limite_por_socio)
            ),
        )
        for b in svc.beneficios_disponibles(db)
    ]


@router.post(
    "/beneficios/{beneficio_id}/canjear",
    response_model=CanjeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Canjear beneficio",
)
def canjear(beneficio_id: int, db: Session = Depends(get_db), socio: Socio = passport.authenticate("jwt")):
    """Descuenta los puntos y emite un cupón. Errores 409: SALDO_INSUFICIENTE, LIMITE_ALCANZADO, SIN_STOCK."""
    canje = svc.canjear_beneficio(db, socio.id, beneficio_id)
    db.commit()
    db.refresh(socio)
    return CanjeResponse(cupon=cupon_response(canje), saldo=socio.saldo_puntos)


@router.get("/cupones", response_model=list[CuponResponse], summary="Cupones del socio")
def get_cupones(db: Session = Depends(get_db), socio: Socio = passport.authenticate("jwt")):
    canjes = db.execute(
        select(Canje).where(Canje.socio_id == socio.id).order_by(Canje.creado_en.desc(), Canje.id.desc())
    ).scalars().all()
    cupones = [cupon_response(c) for c in canjes]
    orden = {"ACTIVE": 0, "USED": 1, "EXPIRED": 2}
    return sorted(cupones, key=lambda c: orden[c.status])  # sort estable: dentro de cada estado, más reciente primero


@router.get("/maquina", response_model=MaquinaResponse, summary="Estado de la Máquina de Recompensas")
def get_maquina(db: Session = Depends(get_db), _: Socio = passport.authenticate("jwt")):
    return svc.estado_maquina(db)


@router.post("/maquina/jugar", response_model=JugarResponse, summary="Jugar la Máquina de Recompensas")
def jugar(db: Session = Depends(get_db), socio: Socio = passport.authenticate("jwt")):
    canje = svc.jugar_maquina(db, socio.id)
    db.commit()
    db.refresh(socio)
    return JugarResponse(coupon=cupon_response(canje), saldo=socio.saldo_puntos)
