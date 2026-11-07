## 1. Base y configuración

- [x] 1.1 Agregar `anthropic` a `requirements.txt` e instalarlo en el entorno local
- [x] 1.2 Agregar a `Settings` las variables `anthropic_api_key`, `perfiles_activo`, `perfiles_modelo`, `perfiles_meses_historia`, `perfiles_max_por_lote` y `perfiles_max_productos`
- [x] 1.3 Crear los modelos `PerfilSocio`, `LotePerfiles` y `LotePerfilItem` en `app/models/perfil.py` y registrarlos
- [x] 1.4 Migración Alembic `0005` con las tres tablas, las FK y el único `(lote_id, socio_id)`, con su downgrade

## 2. Relación venta→productos

- [x] 2.1 Crear `app/services/detalle_ventas.py` con la consulta de ventas relacionables que elige un documento por venta (`DISTINCT ON`, el más cercano por importe y hora)
- [x] 2.2 Función `compras_por_socio(db, socio_ids, desde, max_productos)` que devuelve, por socio, los productos agrupados (categoría, cantidad, compras, última compra), las ventas analizadas, el período y la última venta, limitada a `perfiles_max_productos`
- [x] 2.3 Función `socios_a_perfilar(db, limite)`: socios con ventas relacionables nuevas respecto de su perfil, sin ítems en lotes `ENVIADO`, ordenados por compra más reciente

## 3. Servicio de perfiles

- [x] 3.1 Modelo Pydantic `PerfilIA` con los límites del esquema y su JSON Schema (`additionalProperties: false`)
- [x] 3.2 System prompt fijo, más el vocabulario con las hasta 200 etiquetas más usadas, con `cache_control`
- [x] 3.3 Armar el mensaje del usuario por socio sin datos personales, y los `Request` del lote con `custom_id = socio-<id>`, `output_config` (effort `low` y formato JSON) y `max_tokens`
- [x] 3.4 `enviar_lote(db, client)`: selecciona socios, crea el lote en la API y guarda `LotePerfiles` e ítems con la base enviada
- [x] 3.5 `procesar_lotes_pendientes(db, client)`: consulta el estado y, si terminó, procesa los resultados por `custom_id`, valida, normaliza etiquetas, filtra productos inventados y hace upsert del perfil; registra los errores (errored, expired, canceled, refusal, max_tokens, JSON inválido); marca `ERROR` los lotes de más de 48 h o inexistentes
- [x] 3.6 Cliente de Anthropic inyectable (construido desde `Settings`) para poder reemplazarlo en los tests

## 4. Endpoints y cron

- [x] 4.1 `GET /jobs/perfiles` con `CRON_SECRET`: procesa los pendientes, envía un lote nuevo si no queda ninguno, responde con un resumen y se desactiva si falta la API key o `perfiles_activo` es falso
- [x] 4.2 Agregar el cron `/jobs/perfiles` a `vercel.json`
- [x] 4.3 `GET /socios/{id}/preferencias` con 404 `PERFIL_NO_DISPONIBLE` / `SOCIO_NO_ENCONTRADO`
- [x] 4.4 `GET /reportes/preferencias` (q de 2 caracteres o más, `incluir_resumen`, `skip`, `limit` hasta 500) con `unaccent`, relevancia y coincidencias
- [x] 4.5 `GET /reportes/preferencias/etiquetas` con el conteo de socios por etiqueta
- [x] 4.6 Schemas de respuesta y docstrings para `/docs`

## 5. Tests

- [x] 5.1 Fixture que crea tablas mínimas `documentos`, `documentos_cp` y `panacea_sales_v2` en la base de prueba, y helpers para cargar ventas con detalle
- [x] 5.2 Relación y selección: venta relacionable o no, un documento por venta, socio sin compras nuevas excluido, límite por lote, socio en lote pendiente excluido
- [x] 5.3 Input a la IA: agrupación por producto y ausencia de datos personales
- [x] 5.4 Ciclo del job con cliente falso: envía el lote; lote en proceso no envía otro; lote terminado guarda perfiles y envía el siguiente; job desactivado; 401 sin secreto
- [x] 5.5 Resultados: válido (con normalización y filtro de productos inventados), errored, refusal, JSON inválido (el perfil anterior no cambia y el socio se reintenta), lote vencido de más de 48 h
- [x] 5.6 Endpoints: perfil de socio (con y sin perfil), reporte (sin acentos, por producto, orden por relevancia, resumen opcional, q corto 422, paginación) y conteo de etiquetas
- [x] 5.7 Correr la suite completa

## 6. Documentación

- [x] 6.1 README: proceso de perfiles, variables de entorno, costo estimado, ejecución manual del job y endpoints nuevos

## 7. Frontend (repositorio `panacea-socios`)

- [x] 7.1 Funciones de API: `getPreferenciasSocio`, `buscarSociosPorPreferencia` y `getEtiquetasPreferencias`
- [x] 7.2 Bloque "Gustos y preferencias" en la ficha del socio (`SocioResumen`), con el estado "sin perfil"
- [x] 7.3 Página "Socios por preferencia" en el menú Reportes: buscador, chips de etiquetas, casilla de resumen, tabla paginada, enlace a la ficha y exportación CSV
- [x] 7.4 Verificar el build con Node 22
