## Context

- **Relación venta→productos.** `registro_ventas` no guarda productos. El detalle se obtiene cruzando cada venta con el documento de su local (`documentos` para Villa Allende, `documentos_cp` para Villa Carlos Paz, cuyo id se multiplica por 50000) por fecha (−3 h a hora local, del mismo día, entre 30 min antes y 2 h después) e importe (±100), y el documento con `panacea_sales_v2` (`category`, `product`, `count`, `subtotal`). Esa lógica está copiada en dos lugares de `app/routers/ventas.py` (`_DETAIL_SQL` y `_COMPRAS_POR_CATEGORIA_SQL`). Esas tablas viven en la base de producción pero no las crea Alembic.
- **Ejecución.** La app corre en Vercel (funciones serverless con tiempo máximo de ejecución) y ya tiene un cron diario `/jobs/diario` protegido con `CRON_SECRET`.
- **IA.** El proyecto no usa ningún proveedor de IA todavía; se usará Claude con el SDK oficial `anthropic` para Python.
- **Búsqueda.** La base ya tiene la extensión `unaccent` (migración `0002`).

## Goals / Non-Goals

**Goals:**
- Un perfil de gustos por socio, actualizado a diario solo para quienes tienen compras nuevas.
- Que el cron no dependa del tiempo de respuesta de la IA.
- Un reporte que encuentre socios por producto o preferencia sin depender de cómo se escribió (acentos, mayúsculas, plural).
- Costo acotado y configurable.
- No enviar datos personales a la IA.

**Non-Goals:**
- Búsqueda en lenguaje natural ("socios que prefieren lo dulce pero no el chocolate") resuelta con IA en el momento: se puede agregar después sobre los mismos perfiles.
- Recomendaciones automáticas de productos o campañas.
- Corregir la heurística de relación en los endpoints existentes (`/ventas/{id}/detail` y compras por categoría).
- Regenerar perfiles a pedido desde la UI.

## Decisions

### 1. Message Batches API en dos fases dentro de un cron diario
`GET /jobs/perfiles` (cron propio en `vercel.json`, separado de `/jobs/diario` para que un problema de la IA no frene los procesos de puntos) hace en cada corrida: (1) por cada lote `ENVIADO`, `client.messages.batches.retrieve(batch_id)`; si `processing_status == "ended"`, recorre `client.messages.batches.results(batch_id)` y guarda perfiles por `custom_id`; (2) si no quedó ningún lote pendiente, selecciona socios y crea uno nuevo con `client.messages.batches.create(...)`.

- **Por qué:** las llamadas síncronas a cientos de socios no entran en el tiempo máximo de una función de Vercel, y el lote cuesta 50% menos. La mayoría termina en menos de 1 h (máximo 24 h), así que con un cron diario los perfiles se actualizan con un día de demora, aceptable para este uso.
- **Alternativa descartada:** llamadas síncronas en paralelo desde el cron. Son más caras y no escalan con la cantidad de socios.
- Un lote `ENVIADO` hace más de 48 h, o cuyo `retrieve` devuelve 404, se marca `ERROR` para no bloquear los siguientes; sus ítems quedan como error y esos socios se reintentan.
- Los resultados llegan en cualquier orden: siempre se busca el socio por `custom_id` (`socio-<id>`), nunca por posición.

### 2. Modelo, effort y salida estructurada
- **Modelo** `claude-opus-5-5` (configurable con `PERFILES_MODELO`) y `output_config.effort = "low"`, porque es una tarea de resumen y clasificación. En este modelo el thinking no se puede desactivar: `low` es el control de costo.
- **Salida:** `output_config.format = {"type": "json_schema", "schema": …}` con `additionalProperties: false` en todos los objetos. En lotes no se usa `messages.parse()`: se toma el bloque de texto, se hace `json.loads` y se valida con un modelo Pydantic (`PerfilIA`). Así se garantiza la forma, y además se validan los límites y se aplica la normalización.
- `max_tokens = 16000`: no hay timeout HTTP en lotes y solo se cobra lo generado. Se descarta el resultado si `stop_reason` es `max_tokens` o `refusal`.
- **Sin `fallbacks`:** la Batches API no acepta el parámetro de fallback del servidor. Un rechazo se trata como error del ítem y el socio se reintenta al día siguiente.

### 3. Prompt y vocabulario de etiquetas
- **System prompt fijo** (en español, en el código): explica que el input son compras de un almacén o dietética de Córdoba, que el resumen debe basarse solo en esos datos, sin inferir salud, religión ni otros datos sensibles, y que las etiquetas deben ser cortas y en minúsculas.
- **Vocabulario:** al final del system prompt se agregan las hasta 200 etiquetas más usadas en los perfiles existentes, con la instrucción de reutilizarlas cuando apliquen. Sin esto, la IA inventaría variantes ("dulces", "dulce", "golosinas") y el reporte se fragmentaría.
- **Cache:** el system prompt lleva `cache_control: {"type": "ephemeral"}`. Es idéntico para todo el lote, así que los pedidos pueden reusar el prefijo. Si no alcanza el tamaño mínimo cacheable, no se cachea y no pasa nada.
- **Mensaje del usuario:** solo la tabla de productos agrupados (categoría, producto, cantidad, compras, última compra), el período y la cantidad de ventas. Ningún dato personal.

### 4. Selección incremental y relación más precisa para este proceso
Se extrae la relación venta→documento a `app/services/detalle_ventas.py` y, solo para este proceso, se elige **un** documento por venta (`DISTINCT ON (venta.id)` ordenado por diferencia de importe y de hora). Así una venta no suma productos de dos tickets parecidos. Los endpoints existentes no cambian (fuera de alcance).

- **Selección:** socios con `max(fecha)` de ventas relacionables en la ventana mayor que `perfiles_socio.ultima_venta_fecha` (o sin perfil), que no estén en un lote `ENVIADO`, ordenados por esa fecha descendente, hasta `PERFILES_MAX_POR_LOTE` (por defecto 500).
- Cada ítem del lote guarda la `ultima_venta_fecha` y la lista de productos enviados. Al procesar el resultado se usa esa fecha (no la actual) y la lista sirve para descartar productos favoritos inventados.

### 5. Almacenamiento (migración `0005`)
- **`perfiles_socio`** (1 a 1 con el socio, `ON DELETE CASCADE`): `resumen` (text), `etiquetas`, `categorias_favoritas`, `productos_favoritos` (JSONB, listas de strings), `ventas_analizadas`, `productos_analizados`, `periodo_desde`, `periodo_hasta`, `ultima_venta_fecha`, `modelo`, `generado_en`.
- **`lotes_perfiles`:** `batch_id` (único), `estado` (`ENVIADO`, `PROCESADO`, `ERROR`), `modelo`, `socios`, `exitosos`, `errores`, `creado_en`, `procesado_en`.
- **`lote_perfil_items`:** `lote_id`, `socio_id`, `ultima_venta_fecha`, `ventas_analizadas`, `productos_analizados`, `periodo_desde`, `periodo_hasta`, `productos_enviados` (JSONB), `estado` (`PENDIENTE`, `OK`, `ERROR`), `error`. Único `(lote_id, socio_id)`.
- Se usa una tabla separada de `socios` y no columnas nuevas, porque el perfil se reemplaza entero, tiene su propio ciclo de vida y no conviene cargarlo en cada consulta de socios.

### 6. Búsqueda del reporte en SQL con `unaccent`
`EXISTS (SELECT 1 FROM jsonb_array_elements_text(p.etiquetas) e WHERE unaccent(lower(e)) LIKE '%' || unaccent(lower(:q)) || '%')`, igual para productos y categorías, más el resumen opcional. La relevancia es un `CASE` (etiqueta 4, producto 3, categoría 2, resumen 1) y las coincidencias se devuelven armadas desde Python sobre las filas paginadas. Sin índices: con miles de perfiles un escaneo secuencial alcanza. Si crece, se puede agregar `pg_trgm`.
- **Alternativa descartada:** búsqueda semántica con embeddings, que agrega otra dependencia y otro costo. El vocabulario de etiquetas compartido cubre lo principal.

### 7. Configuración
Variables nuevas en `Settings`:

| Variable | Valor por defecto |
|---|---|
| `anthropic_api_key` | vacío = desactivado |
| `perfiles_activo` | `true` |
| `perfiles_modelo` | `claude-opus-5-5` |
| `perfiles_meses_historia` | 12 |
| `perfiles_max_por_lote` | 500 |
| `perfiles_max_productos` | 100 |

El cliente de Anthropic se construye en el servicio y se puede inyectar, para poder reemplazarlo en los tests.

### Estimación de costo
Por socio: unos 3.000–6.000 tokens de entrada (system prompt + vocabulario + hasta 100 productos) y unos 1.000–1.500 de salida (thinking a effort `low` + JSON). Con precios de lote (50% de descuento):

| Modelo | Entrada / salida por MTok (lote) | Por socio | 1.000 socios |
|---|---|---|---|
| `claude-opus-5-5` (por defecto) | $2 / $10 | ~$0,02–0,03 | ~$20–30 |
| `claude-sonnet-5-5` | $1 / $5 | ~$0,01–0,015 | ~$10–15 |
| `claude-haiku-5-5` | $0,05 / $0,25 | ~$0,001 | ~$1 |

La primera corrida perfila a todos los socios con compras relacionables (costo único). Después, solo a los que compraron desde su último perfil. El modelo se cambia con `PERFILES_MODELO` sin tocar código; conviene medir la calidad con un lote chico antes de bajar de modelo.

### Contrato para el frontend (`panacea-socios`)
- **Ficha del socio:** bloque "Gustos y preferencias" con `GET /socios/{id}/preferencias`. Muestra el resumen, las etiquetas como chips, las categorías y productos favoritos, y "Actualizado el …, basado en N compras". Con 404 `PERFIL_NO_DISPONIBLE` muestra "Todavía no hay perfil para este socio".
- **Reporte "Socios por preferencia"** (menú Reportes):
  - buscador de texto (mínimo 2 caracteres) con sugerencias de `GET /reportes/preferencias/etiquetas` (chips clicables con su conteo);
  - casilla "Buscar también en el resumen";
  - tabla con nombre, DNI, teléfono, email, coincidencias y fecha del perfil;
  - enlace a la ficha del socio, paginación y exportación a CSV de la página actual.

## Risks / Trade-offs

- [La relación venta→documento es heurística y puede asignar un ticket equivocado] → Se elige el documento más cercano por importe y hora, y la IA ve un agregado de 12 meses, así que un error aislado pesa poco.
- [La IA puede inventar o exagerar gustos] → Las instrucciones exigen basarse solo en el input, los productos favoritos se filtran contra lo enviado y el perfil muestra la base ("basado en N compras").
- [Datos personales enviados a un tercero] → Solo se envían productos, categorías, cantidades y fechas; el socio viaja como `custom_id`. Conviene igual mencionarlo en la política de privacidad del club.
- [Inferencias sensibles (salud, dieta por religión)] → El prompt prohíbe inferirlas. Etiquetas descriptivas de producto como "sin tacc" se aceptan porque describen lo comprado, no a la persona.
- [Costo inesperado en la primera corrida] → `PERFILES_MAX_POR_LOTE` limita cuántos socios se procesan por día; la carga inicial se reparte sola en varios días.
- [Vocabulario que crece sin control] → Se le pasan a la IA las etiquetas existentes para que las reutilice, y el endpoint de etiquetas permite ver la fragmentación.
- [Las tablas `documentos*` y `panacea_sales_v2` no están en Alembic] → Los tests crean versiones mínimas en una fixture; en producción ya existen.

## Migration Plan

1. Agregar `anthropic` a `requirements.txt` y aplicar la migración `0005` (`alembic upgrade head`).
2. Configurar `ANTHROPIC_API_KEY` en Vercel. Para la primera semana, conviene un `PERFILES_MAX_POR_LOTE` chico (por ejemplo 50) para revisar la calidad y el costo.
3. Desplegar con el cron nuevo `/jobs/perfiles`. Se puede disparar a mano con `curl -H "Authorization: Bearer $CRON_SECRET" …/jobs/perfiles`; una segunda llamada al rato recoge el lote.
4. Revisar perfiles y costo, subir `PERFILES_MAX_POR_LOTE` y desplegar el frontend.
5. **Rollback:** `PERFILES_ACTIVO=false` detiene el proceso sin desplegar. Las tablas nuevas no afectan a nada existente y se pueden borrar con el downgrade de la migración.

## Open Questions

- ¿Qué modelo usar? Esta propuesta usa `claude-opus-5-5` por defecto; Sonnet 5.5 o Haiku 5.5 bajan el costo y se pueden elegir por variable de entorno.
- ¿El plan de Vercel permite más de una ejecución diaria del cron? Con dos (por ejemplo 06:00 y 08:00) los perfiles estarían listos el mismo día.
- ¿Hace falta avisar a los socios en la política de privacidad que sus compras se analizan con IA?
