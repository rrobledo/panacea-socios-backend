## ADDED Requirements

### Requirement: Listar beneficios usables por un socio
El sistema SHALL exponer `GET /ventas/beneficios-disponibles?socio_id=<id>[&importe=<monto>]`, con la misma autenticación que el registro de ventas, que devuelva los beneficios activos, vigentes hoy (fecha local) y con stock, ordenados por costo en puntos. Cada beneficio MUST indicar `usable` (booleano), `motivo` (código de por qué no es usable, o `null`) y, si se informó `importe`, `descuento_estimado` calculado con el porcentaje y el tope del beneficio. La respuesta MUST incluir el `saldo_puntos` actual del socio.

#### Scenario: Socio con saldo suficiente
- **WHEN** se consulta con un socio de 500 puntos y existe un beneficio activo de 300 puntos
- **THEN** el beneficio aparece con `usable = true` y `motivo = null`

#### Scenario: Saldo insuficiente
- **WHEN** se consulta con un socio de 100 puntos y el beneficio cuesta 300 puntos
- **THEN** el beneficio aparece con `usable = false` y `motivo = "SALDO_INSUFICIENTE"`

#### Scenario: Límite por socio alcanzado
- **WHEN** el beneficio tiene `limite_por_socio = 1` y el socio ya lo usó una vez (desde la app o en el mostrador)
- **THEN** el beneficio aparece con `usable = false` y `motivo = "LIMITE_ALCANZADO"`

#### Scenario: Programa inactivo
- **WHEN** el programa de puntos está desactivado
- **THEN** todos los beneficios aparecen con `usable = false` y `motivo = "PROGRAMA_INACTIVO"`

#### Scenario: Descuento estimado
- **WHEN** se consulta con `importe = 10000` y el beneficio es de 20% con tope de 1500
- **THEN** el beneficio informa `descuento_estimado = 1500.00`

#### Scenario: Socio inexistente
- **WHEN** se consulta con un `socio_id` que no existe
- **THEN** el sistema responde 404 con código `SOCIO_NO_ENCONTRADO`

### Requirement: Usar un beneficio al registrar una venta
`POST /ventas` SHALL aceptar un `beneficio_id` opcional. Cuando viene, en la misma transacción que la venta el sistema MUST: validar el beneficio para el socio con las mismas reglas que el canje desde la app (programa activo, vigencia, stock, límite por socio, saldo), descontar `costo_puntos` del saldo del socio con un movimiento `CANJE`, descontar una unidad de stock si el beneficio tiene stock, crear un canje con origen `MOSTRADOR` en estado `USADO` asociado a la venta con el snapshot del beneficio, registrar como importe de la venta el monto neto (`importe` enviado menos el descuento) y generar los puntos de la compra sobre ese neto. La respuesta MUST informar `descuento`, `puntos_canjeados`, `puntos_generados` y el `saldo_puntos` final del socio.

#### Scenario: Venta con beneficio
- **WHEN** se registra una venta de 10000 para un socio con 500 puntos usando un beneficio de 300 puntos, 10% de descuento y sin tope, con regla de 100 pesos por punto
- **THEN** la venta queda con importe 9000, el socio pierde 300 puntos y gana 90, `saldo_puntos` es 290 y existe un canje `MOSTRADOR` en estado `USADO` asociado a la venta con `monto_descontado = 1000.00`

#### Scenario: Validación fallida no registra la venta
- **WHEN** se registra una venta con un beneficio que el socio no puede usar (por ejemplo, saldo insuficiente)
- **THEN** el sistema responde 409 con el código correspondiente (`SALDO_INSUFICIENTE`, `LIMITE_ALCANZADO`, `SIN_STOCK`, `BENEFICIO_NO_DISPONIBLE`, `PROGRAMA_INACTIVO`) o 404 `BENEFICIO_NO_ENCONTRADO`, y no se registra la venta, ni el canje, ni ningún movimiento de puntos

#### Scenario: Beneficio sin socio
- **WHEN** se registra una venta con `beneficio_id` y sin `socio_id`
- **THEN** el sistema responde 422 y no registra la venta

#### Scenario: Beneficio y cupón juntos
- **WHEN** se registra una venta con `beneficio_id` y `cupon_codigo` a la vez
- **THEN** el sistema responde 422 (un solo beneficio por compra) y no registra la venta

#### Scenario: Canjes simultáneos
- **WHEN** se registran en paralelo dos ventas del mismo socio usando beneficios cuyo costo total supera su saldo
- **THEN** solo una se registra con el beneficio y la otra responde 409 `SALDO_INSUFICIENTE`

#### Scenario: Venta sin beneficio no cambia
- **WHEN** se registra una venta sin `beneficio_id`
- **THEN** el comportamiento es el mismo que antes del cambio (incluido el uso de `cupon_codigo`) y `puntos_canjeados` es 0

### Requirement: Límite por socio incluye canjes de mostrador
El control de `limite_por_socio` de un beneficio SHALL contar tanto los canjes hechos desde la app como los hechos en el mostrador, sin contar los canjes anulados. Los cupones obtenidos con la Máquina de Recompensas MUST seguir sin contar.

#### Scenario: Límite alcanzado en el mostrador
- **WHEN** un beneficio tiene `limite_por_socio = 1`, el socio lo usó en el mostrador y después intenta canjearlo desde la app
- **THEN** el canje desde la app responde 409 `LIMITE_ALCANZADO`

#### Scenario: Canje anulado libera el límite
- **WHEN** el socio usó el beneficio en una venta que luego se eliminó
- **THEN** puede volver a usar ese beneficio

### Requirement: Devolver puntos al eliminar una venta con beneficio de mostrador
Al eliminar una venta que tiene asociado un canje de origen `MOSTRADOR`, el sistema SHALL, en la misma transacción: pasar el canje a estado `CANCELADO`, registrar un movimiento `DEVOLUCION_CANJE` por `+costo_puntos` asociado al canje, sumar una unidad al stock del beneficio si lo controla, y revertir los puntos generados por la compra como hasta ahora. La devolución MUST ser idempotente (como máximo un movimiento `DEVOLUCION_CANJE` por canje). Los cupones emitidos desde la app o la máquina y usados en la venta MUST mantener el comportamiento actual.

#### Scenario: Eliminar venta con beneficio
- **WHEN** se elimina la venta del escenario "Venta con beneficio"
- **THEN** el socio recupera los 300 puntos del canje y pierde los 90 generados, quedando en 500, y el canje queda `CANCELADO`

#### Scenario: Stock devuelto
- **WHEN** se elimina una venta que usó un beneficio con stock 4 (antes 5)
- **THEN** el stock del beneficio vuelve a 5

### Requirement: Proteger ventas con beneficio de mostrador al editarlas
`PUT /ventas/{id}` SHALL rechazar con 409 `VENTA_CON_BENEFICIO` el cambio de `socio_id` o de `importe` en una venta con un canje de origen `MOSTRADOR`, porque el canje y el descuento quedarían inconsistentes. Los demás campos MUST poder editarse.

#### Scenario: Cambiar socio de una venta con beneficio
- **WHEN** se intenta cambiar el `socio_id` de una venta que usó un beneficio de mostrador
- **THEN** el sistema responde 409 `VENTA_CON_BENEFICIO` y la venta no cambia

#### Scenario: Cambiar lugar de una venta con beneficio
- **WHEN** se cambia solo el `lugar` de esa venta
- **THEN** la actualización se aplica normalmente
