## Context

El programa de puntos ya tiene beneficios (descuentos porcentuales con tope opcional, stock, límite por socio y vigencia) y dos formas de obtenerlos, ambas desde la app del socio: el canje (`canjear_beneficio`, descuenta `costo_puntos` y emite un cupón `EMITIDO`) y la Máquina de Recompensas. En la venta el cupón se aplica con `cupon_codigo` (`aplicar_cupon` + marcado `USADO` en `create_venta`). Todo cambio de puntos pasa por `registrar_movimiento` con el socio bloqueado (`SELECT … FOR UPDATE`), y las funciones de servicio no hacen commit.

El registro de ventas lo usa el personal del mostrador desde un frontend que está en otro repositorio. `POST /ventas` solo exige un JWT válido (no rol admin).

## Goals / Non-Goals

**Goals:**
- Que el personal elija un beneficio en el registro de venta y que puntos, canje, descuento y venta queden consistentes en una sola transacción.
- Reutilizar las validaciones del canje desde la app para que ambos caminos apliquen exactamente las mismas reglas.
- Darle al frontend un endpoint para armar el selector con lo que el socio puede usar y el descuento estimado.
- Devolver los puntos si la venta se elimina.

**Non-Goals:**
- Beneficios que no sean descuentos sobre una compra (regalos, productos sin cargo).
- Cambiar el comportamiento de los cupones de la app o de la máquina al eliminar una venta.
- Implementar la pantalla del frontend (solo se define el contrato).
- Restringir por rol quién puede registrar ventas con beneficio (hoy cualquier usuario autenticado registra ventas; se mantiene).

## Decisions

### 1. Separar la validación del canje y agregar un origen `MOSTRADOR`
Se extrae de `canjear_beneficio` una función `_bloquear_y_validar_canje(db, socio_id, beneficio_id)` que lanza los mismos errores (`PROGRAMA_INACTIVO`, `SIN_STOCK`, `BENEFICIO_NO_DISPONIBLE`, `LIMITE_ALCANZADO`, `SALDO_INSUFICIENTE`), y otra `motivo_no_usable(...)` que devuelve el código sin lanzar, para el listado. Una función nueva `canjear_en_venta(db, socio_id, beneficio_id, monto) -> (Canje, descuento)` bloquea socio y beneficio, valida, emite el canje con `origen = MOSTRADOR` (reusando `_emitir_cupon`), registra el movimiento `CANJE` y calcula el descuento con `calcular_descuento`. `create_venta` marca el canje `USADO` igual que hoy hace con el cupón.

*Alternativa descartada:* llamar a `canjear_beneficio` y después `aplicar_cupon` con el código emitido. Funciona, pero deja el canje con origen `CANJE` (no se distingue en reportes ni en la devolución) y hace dos bloqueos y una búsqueda por código innecesarios.

El canje de mostrador conserva un `codigo` (la columna es obligatoria y única) para trazabilidad, y `expira_en` = momento del canje porque se usa en el acto.

### 2. El límite por socio cuenta `CANJE` y `MOSTRADOR`, sin cancelados
`canjes_por_beneficio` pasa a filtrar `origen IN (CANJE, MOSTRADOR)` y `estado <> CANCELADO`. Así un socio no puede esquivar el límite alternando app y mostrador, y una venta anulada no le consume el cupo.

### 3. Devolución con un tipo de movimiento nuevo `DEVOLUCION_CANJE`
Al eliminar la venta, para un canje `MOSTRADOR` asociado: estado `CANCELADO`, movimiento `DEVOLUCION_CANJE` por `+costo_puntos` con `canje_id`, y `stock += 1` si aplica. El índice único `ux_mov_canje_tipo (canje_id, tipo)` ya garantiza idempotencia. Hay que ejecutarlo **antes** de `db.delete(venta)`, porque la FK `canjes.venta_id` es `ON DELETE SET NULL` y después ya no se encuentra el canje por venta.

*Alternativa descartada:* usar `AJUSTE`. Mezclaría devoluciones automáticas con ajustes manuales en el historial del socio y en los reportes.

Los puntos devueltos son créditos nuevos a efectos del vencimiento FIFO (vencen a los N meses desde la devolución). Se acepta: es el comportamiento más favorable al socio y el caso es poco frecuente.

### 4. Exclusividad y requisitos como validación del schema (422)
`VentaCreate` valida con un `model_validator` que `beneficio_id` requiere `socio_id` y que no venga junto con `cupon_codigo`. Son errores de forma del pedido, no de negocio, y así no se llega a tocar la base.

### 5. Endpoint de listado bajo `/ventas`
`GET /ventas/beneficios-disponibles?socio_id=&importe=` con la misma autenticación que `POST /ventas`, porque lo consume la misma pantalla y el mismo usuario. `/recompensas/beneficios` no sirve: es del socio autenticado. `/admin/...` tampoco: exige rol admin y el cajero puede no tenerlo.

Respuesta:
```json
{
  "socio_id": 12,
  "saldo_puntos": 450,
  "beneficios": [
    {"id": 3, "nombre": "10% off", "descripcion": "…", "imagen_url": null,
     "costo_puntos": 300, "porcentaje_descuento": 10.0, "tope_descuento": null,
     "usable": true, "motivo": null, "descuento_estimado": 1000.00}
  ]
}
```

### 6. Respuesta de `POST /ventas`
`VentaCreateResponse` suma `puntos_canjeados` (0 si no hubo beneficio) y `saldo_puntos` (saldo final del socio, `null` si la venta no tiene socio), además de los `descuento` y `puntos_generados` existentes, para que el mostrador confirme el resultado sin otra consulta.

### Contrato para el frontend (pantalla de registro de venta)
- Al elegir el socio, llamar a `GET /ventas/beneficios-disponibles?socio_id=…`; al cambiar el importe, volver a llamar con `&importe=…` (o calcular localmente con `porcentaje_descuento`/`tope_descuento`).
- Mostrar un selector "Beneficio a usar" con la opción "Ninguno" por defecto. Cada opción muestra nombre, costo en puntos y descuento estimado. Las no usables aparecen deshabilitadas con el motivo en texto (`SALDO_INSUFICIENTE` → "Puntos insuficientes", `LIMITE_ALCANZADO` → "Ya usó este beneficio", `PROGRAMA_INACTIVO` → "Programa de puntos inactivo").
- Mostrar el saldo del socio y el total a cobrar con el descuento aplicado.
- Si se eligió un beneficio, deshabilitar el campo de código de cupón (y viceversa).
- Enviar `importe` como monto **antes** del descuento, igual que con `cupon_codigo`.
- Tras guardar, mostrar `descuento`, `puntos_canjeados`, `puntos_generados` y `saldo_puntos` de la respuesta. Ante un 409, mostrar `detail.message` y refrescar el listado (el saldo pudo cambiar).

## Risks / Trade-offs

- [Cualquier usuario autenticado puede registrar ventas con beneficio, incluso un socio para sí mismo] → Es el mismo riesgo que ya existe con el registro de ventas y los cupones; se deja documentado. Si hace falta, se restringe después con un rol de cajero, sin cambiar el contrato.
- [Editar el importe o el socio de una venta con beneficio dejaría el canje inconsistente] → `PUT /ventas/{id}` rechaza esos cambios con 409 `VENTA_CON_BENEFICIO`; para corregir, se elimina la venta (devuelve los puntos) y se registra de nuevo.
- [Interbloqueos entre canjes simultáneos] → Se mantiene el orden de bloqueo existente: primero socio, después beneficio, igual que `canjear_beneficio`.
- [Cupones de la app usados en una venta eliminada siguen perdiéndose] → Fuera de alcance; se anota como pregunta abierta para no cambiar dos comportamientos a la vez.

## Migration Plan

- Sin migración de base: `OrigenCanje.MOSTRADOR` (9 caracteres) y `TipoMovimiento.DEVOLUCION_CANJE` (16) entran en `canjes.origen String(10)` y `movimientos_puntos.tipo String(20)`.
- El backend se puede desplegar antes que el frontend: `beneficio_id` es opcional y el endpoint nuevo no afecta a los existentes.
- Rollback: revertir el despliegue. Los canjes `MOSTRADOR` ya creados siguen siendo filas válidas; el único efecto es que el límite por socio vuelve a ignorarlos.

## Open Questions

- ¿Confirmar que al eliminar una venta con beneficio de mostrador se devuelven los puntos? (Esta propuesta asume que sí.)
- ¿Los cupones de la app usados en una venta eliminada deberían volver a quedar `EMITIDO` para poder reusarse? Hoy se pierden; queda fuera de este cambio.
