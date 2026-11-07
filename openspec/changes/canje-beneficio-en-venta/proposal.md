## Why

Hoy un beneficio solo se puede usar si el socio lo canjea antes desde la app (eso descuenta los puntos y le emite un cupón) y después el cajero ingresa el código en la venta. En el mostrador no hay forma de que el personal elija el beneficio que el socio quiere usar y descuente los puntos en el momento, así que socios sin la app (o sin el cupón a mano) no pueden usar sus puntos.

## What Changes

- Al registrar una venta (`POST /ventas`) se puede indicar un `beneficio_id` opcional. En la misma transacción se valida el beneficio para el socio, se descuentan los puntos, se crea el canje ya usado y asociado a la venta, se aplica el descuento al importe y los puntos de la compra se calculan sobre el neto.
- `beneficio_id` y `cupon_codigo` son excluyentes (se mantiene un beneficio por compra) y `beneficio_id` requiere que la venta tenga socio.
- Nuevo endpoint `GET /ventas/beneficios-disponibles?socio_id=…[&importe=…]` para alimentar el selector del mostrador: devuelve los beneficios vigentes indicando si el socio puede usarlo, el motivo si no puede y el descuento estimado para el importe.
- Al eliminar una venta que usó un beneficio de mostrador, se anula el canje y se le devuelven los puntos al socio (y el stock al beneficio).
- Los canjes de mostrador cuentan para el `limite_por_socio` del beneficio igual que los canjes desde la app.
- Sin cambios incompatibles: `cupon_codigo` y el canje desde la app siguen funcionando igual.

## Capabilities

### New Capabilities
- `canje-beneficio-en-venta`: uso de un beneficio elegido por el personal al registrar una venta, listado de beneficios usables por socio y devolución de puntos al anular la venta.

### Modified Capabilities
<!-- No hay specs existentes en openspec/specs/. -->

## Impact

- **API**: `POST /ventas` (campo nuevo `beneficio_id`, respuesta con `puntos_canjeados` y `saldo_puntos`), nuevo `GET /ventas/beneficios-disponibles`, `DELETE /ventas/{id}` (devolución de puntos).
- **Código**: `app/services/puntos.py` (extraer validación de canje, canje de mostrador, devolución), `app/routers/ventas.py`, `app/schemas/venta.py`, `app/schemas/puntos.py`, `app/models/puntos.py` (nuevos valores `OrigenCanje.MOSTRADOR` y `TipoMovimiento.DEVOLUCION_CANJE`).
- **Base de datos**: sin migración; los valores nuevos entran en las columnas `String` existentes.
- **Frontend** (otro repositorio): selector "Beneficio a usar" en la pantalla de registro de venta, descripto en `design.md`.
- **Tests**: `tests/test_puntos.py`.
