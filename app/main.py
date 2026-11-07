import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.routers import admin_puntos, canjes, jobs, preguntas, recompensas, reportes, socios, ventas

# Los logs de la app (logger "app.*") van a stdout para que aparezcan en Vercel.
# Sin esto, Python descarta todo lo que esté por debajo de WARNING.
_app_logger = logging.getLogger("app")
if not _app_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    _app_logger.addHandler(_handler)
    _app_logger.setLevel(logging.INFO)

app = FastAPI(
    title="Panacea Socios API",
    description=(
        "API para gestión de socios, sus preferencias y registro de ventas de Panacea. "
        "Permite registrar clientes, capturar sus respuestas a preguntas clave y "
        "llevar un historial de compras para futuras promociones y regalos."
    ),
    version="2.0.0",
    contact={"name": "Panacea", "email": "info@panacea.com"},
    license_info={"name": "Proprietary"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(socios.router)
app.include_router(preguntas.router)
app.include_router(ventas.router)
app.include_router(reportes.router)
app.include_router(recompensas.router)
app.include_router(canjes.router)
app.include_router(admin_puntos.router)
app.include_router(jobs.router)


@app.get("/", tags=["Health"], summary="Health check")
def root():
    """Verifica que el servicio está en línea."""
    return {"status": "ok", "service": "panacea-socios-api"}
