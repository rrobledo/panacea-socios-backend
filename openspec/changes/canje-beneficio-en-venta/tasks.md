## 1. Modelo y servicio de puntos

- [x] 1.1 Agregar `OrigenCanje.MOSTRADOR` y `TipoMovimiento.DEVOLUCION_CANJE` en `app/models/puntos.py`
- [x] 1.2 Extraer de `canjear_beneficio` las funciones `_bloquear_y_validar_canje` (lanza los errores existentes) y `motivo_no_usable` (devuelve el código o `None`), sin cambiar el comportamiento del canje desde la app
- [x] 1.3 Cambiar `canjes_por_beneficio` para contar origen `CANJE` y `MOSTRADOR` y excluir canjes `CANCELADO`
- [x] 1.4 Hacer que `_emitir_cupon` acepte `expira_en` opcional para el canje de mostrador
- [x] 1.5 Implementar `canjear_en_venta(db, socio_id, beneficio_id, monto) -> (Canje, descuento)`: bloquea socio y beneficio (en ese orden), valida, emite el canje `MOSTRADOR`, registra el movimiento `CANJE` y calcula el descuento
- [x] 1.6 Implementar `devolver_canje_de_venta(db, venta)`: canje `MOSTRADOR` → `CANCELADO`, movimiento `DEVOLUCION_CANJE` idempotente y `stock += 1`

## 2. Schemas

- [x] 2.1 Agregar `beneficio_id` a `VentaCreate` con un `model_validator` (requiere `socio_id` y excluye `cupon_codigo`)
- [x] 2.2 Agregar `puntos_canjeados` y `saldo_puntos` a `VentaCreateResponse`
- [x] 2.3 Crear `BeneficioUsableResponse` y `BeneficiosDisponiblesResponse` en `app/schemas/puntos.py`

## 3. Endpoints de ventas

- [x] 3.1 `GET /ventas/beneficios-disponibles` con `socio_id` obligatorio e `importe` opcional (declararlo antes de `GET /ventas/{venta_id}` para que no lo capture la ruta con parámetro)
- [x] 3.2 `POST /ventas`: si viene `beneficio_id`, llamar a `canjear_en_venta`, registrar el neto, marcar el canje `USADO` con `venta_id`, `monto_descontado` y `usado_en`, y completar la respuesta nueva
- [x] 3.3 `DELETE /ventas/{id}`: llamar a `devolver_canje_de_venta` antes de `db.delete(venta)`
- [x] 3.4 `PUT /ventas/{id}`: rechazar con 409 `VENTA_CON_BENEFICIO` los cambios de `socio_id` o `importe` si la venta tiene un canje `MOSTRADOR`
- [x] 3.5 Actualizar los docstrings de los endpoints (se ven en `/docs`)

## 4. Tests (`tests/test_puntos.py`)

- [x] 4.1 Listado: usable, `SALDO_INSUFICIENTE`, `LIMITE_ALCANZADO`, `PROGRAMA_INACTIVO`, `descuento_estimado` con tope y socio inexistente (404)
- [x] 4.2 Venta con beneficio: importe neto, puntos descontados y generados sobre el neto, canje `MOSTRADOR` `USADO`, stock y respuesta
- [x] 4.3 Errores: saldo insuficiente no registra venta ni movimientos; sin socio y con cupón a la vez responden 422
- [x] 4.4 Límite compartido entre app y mostrador, y canje cancelado que libera el límite
- [x] 4.5 Eliminar venta con beneficio: devuelve puntos y stock, cancela el canje y revierte la acumulación
- [x] 4.6 `PUT` sobre venta con beneficio: rechaza socio e importe y acepta lugar
- [x] 4.7 Concurrencia: dos ventas simultáneas que superan el saldo, solo una se registra
- [x] 4.8 Correr toda la suite y verificar que los tests existentes (cupón, canje desde la app, máquina) siguen pasando

## 5. Documentación

- [x] 5.1 Documentar en el README el flujo de beneficio en mostrador y el contrato para el frontend (resumen de `design.md`)
