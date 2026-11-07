## Why

Hoy sabemos cuánto compra cada socio, pero no qué le gusta. El detalle de productos existe (se cruza cada venta con `documentos` / `documentos_cp` y `panacea_sales_v2`), pero nadie lo puede leer socio por socio. Un perfil de gustos generado con IA, actualizado a diario, permite saber qué le gusta a cada socio y armar listas de socios para acciones puntuales ("a quién le ofrezco el nuevo alfajor de chocolate amargo").

## What Changes

- Nuevo proceso diario que, para cada socio con compras nuevas que se puedan relacionar con su detalle de productos, junta los productos de los últimos 12 meses y le pide a Claude un resumen estructurado de gustos y preferencias.
- El resultado se guarda como perfil del socio: resumen en texto, etiquetas de preferencia normalizadas, categorías y productos favoritos, y la base usada (ventas y productos analizados, período, modelo, fecha).
- Las llamadas a Claude se envían por la Message Batches API (asíncrona, 50% del costo): cada corrida diaria recoge los resultados del lote anterior y envía el siguiente. Así el cron de Vercel no queda esperando a la IA.
- A Claude solo se le envían productos, categorías, cantidades y fechas: nunca nombre, DNI, email ni teléfono.
- Nuevo endpoint para ver el perfil de un socio: `GET /socios/{id}/preferencias`.
- Nuevo reporte para buscar socios por producto o preferencia: `GET /reportes/preferencias?q=…`, sin distinguir mayúsculas ni acentos y ordenado por relevancia, más `GET /reportes/preferencias/etiquetas` con las etiquetas existentes y cuántos socios tiene cada una.
- Frontend (`panacea-socios`): pantalla de reporte "Socios por preferencia" y bloque "Gustos y preferencias" en la ficha del socio.
- Nueva dependencia `anthropic` y nuevas variables de entorno (`ANTHROPIC_API_KEY`, configuración del proceso). Sin cambios incompatibles.

## Capabilities

### New Capabilities
- `perfil-preferencias-socio`: generación diaria con IA del perfil de gustos de cada socio a partir del detalle de sus compras, y su almacenamiento y consulta.
- `reporte-socios-por-preferencia`: búsqueda de socios por producto, categoría o preferencia sobre los perfiles generados.

### Modified Capabilities
<!-- No hay specs existentes en openspec/specs/. -->

## Impact

- **Código**: nuevo `app/services/perfiles.py` (armado del input, lote y parseo), `app/services/detalle_ventas.py` (relación venta→productos extraída de `ventas.py` para reusarla), modelos y migración Alembic `0005`, `app/routers/jobs.py` (nuevo `/jobs/perfiles`), `app/routers/socios.py`, `app/routers/reportes.py`, schemas.
- **Base de datos**: tablas nuevas `perfiles_socio`, `lotes_perfiles` y `lote_perfil_items`.
- **Infraestructura**: cron nuevo en `vercel.json`; `ANTHROPIC_API_KEY` en las variables de Vercel.
- **Costo**: se paga por uso de la API de Claude; ver la estimación en `design.md`.
- **Dependencias**: `anthropic` en `requirements.txt`.
- **Frontend** (`panacea-socios`): pantalla de reporte y bloque en la ficha del socio.
