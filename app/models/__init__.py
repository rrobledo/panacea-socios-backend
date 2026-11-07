from app.models.socio import Socio
from app.models.pregunta import PreguntaPorSocio, ClavePregunta
from app.models.venta import RegistroVenta, DetalleRegistroVenta
from app.models.puntos import Beneficio, Canje, ConfigPrograma, MovimientoPuntos, ReglaPuntos
from app.models.perfil import LotePerfilItem, LotePerfiles, PerfilSocio

__all__ = [
    "Socio",
    "PreguntaPorSocio",
    "ClavePregunta",
    "RegistroVenta",
    "DetalleRegistroVenta",
    "ReglaPuntos",
    "MovimientoPuntos",
    "Beneficio",
    "Canje",
    "ConfigPrograma",
    "PerfilSocio",
    "LotePerfiles",
    "LotePerfilItem",
]
