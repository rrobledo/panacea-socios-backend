"""Perfiles de gustos y preferencias de los socios generados con Claude (Message Batches API).

Flujo (lo dispara /jobs/perfiles una vez por día):
1. `procesar_lotes_pendientes`: para cada lote ENVIADO que ya terminó, guarda los perfiles.
2. `enviar_lote`: si no queda ninguno pendiente, elige socios con compras nuevas y envía un lote.

A Claude solo se le envían productos, categorías, cantidades y fechas: nunca datos personales.
El socio viaja únicamente como `custom_id` (`socio-<id>`).
Las funciones no hacen commit: el llamador controla la transacción.
"""
import json
import logging
import re
from datetime import datetime, timedelta

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.models.perfil import EstadoItem, EstadoLote, LotePerfilItem, LotePerfiles, PerfilSocio
from app.services import detalle_ventas
from app.services.puntos import ahora_utc, restar_meses

logger = logging.getLogger(__name__)

MAX_RESUMEN = 600
MAX_ETIQUETAS = 15
MAX_CATEGORIAS = 5
MAX_PRODUCTOS_FAVORITOS = 10
MAX_VOCABULARIO = 200
HORAS_VENCIMIENTO_LOTE = 48
_PREFIJO_ID = "socio-"

SYSTEM_PROMPT = """Analizás las compras de un socio del club de clientes de Panacea, un comercio de alimentos de Córdoba, Argentina, para describir sus gustos y preferencias de consumo. El personal usa este perfil para conocer a cada socio y para encontrar socios a quienes ofrecer productos.

Vas a recibir la lista de productos que compró en el período indicado, agrupados por producto, con su categoría, las unidades, la cantidad de compras en las que aparece y la fecha de la última compra. No recibís datos personales del socio.

Devolvé:
- resumen: 2 a 4 oraciones en español rioplatense neutro que describan qué compra y qué parece preferir (sabores, tipos de producto, frecuencia, cambios recientes). Basate solo en los datos; si hay pocas compras, decilo.
- etiquetas: entre 1 y 15 preferencias cortas en minúsculas y en singular cuando sea natural (por ejemplo "chocolate amargo", "frutos secos", "sin tacc", "panificados", "compra frecuente"). Sirven para buscar socios, así que usá términos concretos y reutilizables.
- categorias_favoritas: hasta 5 categorías que más compra, escritas como aparecen en los datos.
- productos_favoritos: hasta 10 productos que más compra, copiados exactamente como aparecen en los datos.

No infieras ni menciones datos sensibles de la persona (salud, enfermedades, embarazo, religión, ideas políticas, situación económica). Podés usar etiquetas que describan lo que compra (por ejemplo "sin tacc" o "sin azúcar") pero no conclusiones sobre la persona ("celíaco", "diabético")."""

# Esquema para output_config.format: solo tipos y obligatoriedad. Los límites de longitud y
# cantidad se aplican al normalizar (ver `normalizar_perfil`).
_LISTA_TEXTO = {"type": "array", "items": {"type": "string"}}
PERFIL_SCHEMA = {
    "type": "object",
    "properties": {
        "resumen": {"type": "string"},
        "etiquetas": _LISTA_TEXTO,
        "categorias_favoritas": _LISTA_TEXTO,
        "productos_favoritos": _LISTA_TEXTO,
    },
    "required": ["resumen", "etiquetas", "categorias_favoritas", "productos_favoritos"],
    "additionalProperties": False,
}


class PerfilIA(BaseModel):
    """Lo que devuelve Claude (ya validado contra el esquema)."""
    model_config = ConfigDict(extra="forbid")

    resumen: str
    etiquetas: list[str]
    categorias_favoritas: list[str]
    productos_favoritos: list[str]


class PerfilInvalido(Exception):
    pass


def crear_cliente() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def proceso_activo() -> tuple[bool, str | None]:
    if not settings.perfiles_activo:
        return False, "PERFILES_ACTIVO está desactivado"
    if not settings.anthropic_api_key:
        return False, "Falta ANTHROPIC_API_KEY"
    return True, None


# ── Armado del pedido ──────────────────────────────────────────────────────────

def vocabulario(db: Session, limite: int = MAX_VOCABULARIO) -> list[str]:
    """Etiquetas más usadas en los perfiles existentes, para que la IA las reutilice."""
    return list(db.execute(text("""
        SELECT e FROM perfiles_socio p, jsonb_array_elements_text(p.etiquetas) e
        GROUP BY e ORDER BY count(*) DESC, e LIMIT :limite
    """), {"limite": limite}).scalars())


def system_prompt(etiquetas_existentes: list[str]) -> str:
    if not etiquetas_existentes:
        return SYSTEM_PROMPT
    return (
        SYSTEM_PROMPT
        + "\n\nEtiquetas que ya usan otros socios. Si alguna describe bien una preferencia, usala tal cual "
        "en lugar de inventar una variante; agregá etiquetas nuevas solo cuando ninguna sirva:\n"
        + ", ".join(etiquetas_existentes)
    )


def mensaje_usuario(compras: detalle_ventas.ComprasSocio) -> str:
    """Solo productos, categorías, cantidades y fechas. Nunca datos personales del socio."""
    lineas = [
        f"Período: {compras.periodo_desde.isoformat()} a {compras.periodo_hasta.isoformat()}",
        f"Compras analizadas: {compras.ventas}",
        "",
        "Productos (categoría | producto | unidades | compras | última compra):",
    ]
    for p in compras.productos:
        unidades = int(p.cantidad) if float(p.cantidad).is_integer() else round(p.cantidad, 2)
        lineas.append(
            f"- {p.categoria or 'Sin categoría'} | {p.producto} | {unidades} | {p.compras} | {p.ultima_compra.isoformat()}"
        )
    return "\n".join(lineas)


def armar_pedido(compras: detalle_ventas.ComprasSocio, system: str, modelo: str) -> Request:
    return Request(
        custom_id=f"{_PREFIJO_ID}{compras.socio_id}",
        params=MessageCreateParamsNonStreaming(
            model=modelo,
            max_tokens=16000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": mensaje_usuario(compras)}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": PERFIL_SCHEMA}},
        ),
    )


def inicio_ventana() -> datetime:
    return restar_meses(ahora_utc(), settings.perfiles_meses_historia)


def enviar_lote(db: Session, client: anthropic.Anthropic) -> LotePerfiles | None:
    """Elige socios con compras nuevas y envía un lote. None si no hay a quién perfilar."""
    desde = inicio_ventana()
    socio_ids = detalle_ventas.socios_a_perfilar(db, desde, settings.perfiles_max_por_lote)
    compras = detalle_ventas.compras_por_socio(db, socio_ids, desde, settings.perfiles_max_productos)
    compras = {sid: c for sid, c in compras.items() if c.productos}
    if not compras:
        return None

    modelo = settings.perfiles_modelo
    system = system_prompt(vocabulario(db))
    pedidos = [armar_pedido(compras[sid], system, modelo) for sid in socio_ids if sid in compras]
    batch = client.messages.batches.create(requests=pedidos)
    logger.info("Lote de perfiles enviado: %s (%d socios)", batch.id, len(pedidos))

    lote = LotePerfiles(
        batch_id=batch.id, estado=EstadoLote.ENVIADO, modelo=modelo, socios=len(pedidos), creado_en=ahora_utc()
    )
    db.add(lote)
    db.flush()
    for sid in socio_ids:
        c = compras.get(sid)
        if c is None:
            continue
        db.add(LotePerfilItem(
            lote_id=lote.id, socio_id=sid, ultima_venta_fecha=c.ultima_venta_fecha,
            ventas_analizadas=c.ventas, productos_analizados=len(c.productos),
            periodo_desde=c.periodo_desde, periodo_hasta=c.periodo_hasta,
            productos_enviados=[p.producto for p in c.productos], estado=EstadoItem.PENDIENTE,
        ))
    db.flush()
    return lote


# ── Procesamiento de resultados ────────────────────────────────────────────────

def _limpiar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto or "").strip()


def _unicos(valores, clave=lambda v: v.lower()) -> list[str]:
    vistos, salida = set(), []
    for v in valores:
        if v and clave(v) not in vistos:
            vistos.add(clave(v))
            salida.append(v)
    return salida


def _recortar(texto: str, limite: int) -> str:
    if len(texto) <= limite:
        return texto
    corte = texto[:limite].rsplit(" ", 1)[0]
    return corte.rstrip(" ,;:") + "…"


def normalizar_perfil(perfil: PerfilIA, productos_enviados: list[str]) -> PerfilIA:
    """Aplica límites, normaliza etiquetas y descarta productos que no estaban en el input."""
    resumen = _recortar(_limpiar(perfil.resumen), MAX_RESUMEN)
    etiquetas = _unicos(
        [_limpiar(e).lower().strip(" .,;:-") for e in perfil.etiquetas if len(_limpiar(e)) <= 60]
    )[:MAX_ETIQUETAS]
    categorias = _unicos([_limpiar(c) for c in perfil.categorias_favoritas])[:MAX_CATEGORIAS]
    canonicos = {_limpiar(p).lower(): p for p in productos_enviados}
    productos = _unicos(
        [canonicos[_limpiar(p).lower()] for p in perfil.productos_favoritos if _limpiar(p).lower() in canonicos]
    )[:MAX_PRODUCTOS_FAVORITOS]
    if not resumen:
        raise PerfilInvalido("Resumen vacío")
    if not etiquetas:
        raise PerfilInvalido("Sin etiquetas")
    return PerfilIA(resumen=resumen, etiquetas=etiquetas, categorias_favoritas=categorias, productos_favoritos=productos)


def interpretar_resultado(result) -> PerfilIA:
    """Convierte un resultado del lote en PerfilIA o lanza PerfilInvalido con el motivo."""
    tipo = result.type
    if tipo != "succeeded":
        detalle = ""
        if tipo == "errored":
            detalle = f": {getattr(getattr(result.error, 'error', None), 'message', '') or result.error}"
        raise PerfilInvalido(f"Resultado {tipo}{detalle}")
    message = result.message
    if message.stop_reason in ("refusal", "max_tokens"):
        raise PerfilInvalido(f"stop_reason {message.stop_reason}")
    texto = next((b.text for b in message.content if b.type == "text"), None)
    if not texto:
        raise PerfilInvalido("Respuesta sin texto")
    try:
        return PerfilIA.model_validate(json.loads(texto))
    except (json.JSONDecodeError, ValidationError) as e:
        raise PerfilInvalido(f"JSON inválido: {e}") from e


def _guardar_perfil(db: Session, item: LotePerfilItem, perfil: PerfilIA, modelo: str) -> None:
    registro = db.get(PerfilSocio, item.socio_id) or PerfilSocio(socio_id=item.socio_id)
    registro.resumen = perfil.resumen
    registro.etiquetas = perfil.etiquetas
    registro.categorias_favoritas = perfil.categorias_favoritas
    registro.productos_favoritos = perfil.productos_favoritos
    registro.ventas_analizadas = item.ventas_analizadas
    registro.productos_analizados = item.productos_analizados
    registro.periodo_desde = item.periodo_desde
    registro.periodo_hasta = item.periodo_hasta
    registro.ultima_venta_fecha = item.ultima_venta_fecha
    registro.modelo = modelo
    registro.generado_en = ahora_utc()
    db.add(registro)


def _marcar_error_pendientes(db: Session, lote: LotePerfiles, motivo: str) -> None:
    db.flush()  # la sesión no hace autoflush: sin esto se cuentan ítems ya resueltos en memoria
    items = db.execute(
        select(LotePerfilItem).where(LotePerfilItem.lote_id == lote.id, LotePerfilItem.estado == EstadoItem.PENDIENTE)
    ).scalars().all()
    for item in items:
        item.estado, item.error = EstadoItem.ERROR, motivo[:300]
    lote.errores += len(items)


def _procesar_resultados(db: Session, client: anthropic.Anthropic, lote: LotePerfiles) -> None:
    items = {
        i.socio_id: i
        for i in db.execute(select(LotePerfilItem).where(LotePerfilItem.lote_id == lote.id)).scalars()
    }
    for resultado in client.messages.batches.results(lote.batch_id):
        if not resultado.custom_id.startswith(_PREFIJO_ID):
            continue
        item = items.get(int(resultado.custom_id[len(_PREFIJO_ID):]))
        if item is None or item.estado != EstadoItem.PENDIENTE:
            continue  # socio eliminado o resultado repetido
        try:
            perfil = normalizar_perfil(interpretar_resultado(resultado.result), item.productos_enviados)
        except PerfilInvalido as e:
            item.estado, item.error = EstadoItem.ERROR, str(e)[:300]
            lote.errores += 1
            logger.warning("Perfil del socio %s no generado (lote %s): %s", item.socio_id, lote.batch_id, e)
            continue
        _guardar_perfil(db, item, perfil, lote.modelo)
        item.estado = EstadoItem.OK
        lote.exitosos += 1
    _marcar_error_pendientes(db, lote, "Sin resultado en el lote")


def procesar_lotes_pendientes(db: Session, client: anthropic.Anthropic) -> dict:
    """Procesa los lotes ENVIADO que terminaron. Marca ERROR los inexistentes o demasiado viejos."""
    resumen = {"procesados": 0, "en_proceso": 0, "con_error": 0, "perfiles_guardados": 0, "errores": 0}
    lotes = db.execute(
        select(LotePerfiles).where(LotePerfiles.estado == EstadoLote.ENVIADO).order_by(LotePerfiles.id)
    ).scalars().all()
    for lote in lotes:
        try:
            batch = client.messages.batches.retrieve(lote.batch_id)
        except anthropic.NotFoundError:
            batch = None
        if batch is not None and batch.processing_status == "ended":
            _procesar_resultados(db, client, lote)
            lote.estado, lote.procesado_en = EstadoLote.PROCESADO, ahora_utc()
            resumen["procesados"] += 1
            resumen["perfiles_guardados"] += lote.exitosos
            resumen["errores"] += lote.errores
        elif batch is None or ahora_utc() - lote.creado_en > timedelta(hours=HORAS_VENCIMIENTO_LOTE):
            _marcar_error_pendientes(db, lote, "Lote inexistente" if batch is None else "Lote vencido")
            lote.estado, lote.procesado_en = EstadoLote.ERROR, ahora_utc()
            resumen["con_error"] += 1
            logger.warning("Lote de perfiles %s marcado con error", lote.batch_id)
        else:
            resumen["en_proceso"] += 1
        db.flush()
    return resumen


def lotes_pendientes(db: Session) -> int:
    return db.execute(
        select(func.count()).select_from(LotePerfiles).where(LotePerfiles.estado == EstadoLote.ENVIADO)
    ).scalar_one()
