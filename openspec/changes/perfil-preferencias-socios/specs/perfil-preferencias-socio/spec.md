## ADDED Requirements

### Requirement: Selección diaria de socios a perfilar
Cada día el sistema SHALL seleccionar los socios que necesitan un perfil nuevo o actualizado: los que tienen al menos una venta relacionable con su detalle de productos y que, o bien no tienen perfil, o bien tienen una venta relacionable posterior a la última venta considerada en su perfil. Una venta es relacionable cuando se la puede cruzar con un documento de su local (`documentos` para Villa Allende, `documentos_cp` para Villa Carlos Paz) y ese documento tiene líneas en `panacea_sales_v2`. Las ventas que no se pueden relacionar MUST ignorarse. La cantidad de socios por corrida MUST estar limitada por configuración (`PERFILES_MAX_POR_LOTE`); los que no entran quedan para el día siguiente, empezando por los que tienen la compra más reciente.

#### Scenario: Socio sin perfil con compras relacionables
- **WHEN** un socio tiene ventas relacionables y todavía no tiene perfil
- **THEN** se incluye en el lote del día

#### Scenario: Socio sin compras nuevas
- **WHEN** la última venta relacionable de un socio es la misma que la que se usó en su perfil
- **THEN** no se incluye en el lote

#### Scenario: Socio con ventas no relacionables
- **WHEN** ninguna venta del socio se puede cruzar con un documento con productos
- **THEN** no se incluye en el lote y no se genera perfil

#### Scenario: Límite por lote
- **WHEN** hay 800 socios para perfilar y `PERFILES_MAX_POR_LOTE` es 500
- **THEN** se envían los 500 con la compra más reciente y los otros 300 quedan para la corrida siguiente

#### Scenario: Socio ya en un lote pendiente
- **WHEN** un socio ya está en un lote enviado que todavía no terminó
- **THEN** no se lo vuelve a enviar en otro lote

### Requirement: Datos enviados a la IA
Para cada socio seleccionado el sistema SHALL armar un resumen de sus compras relacionables de los últimos `PERFILES_MESES_HISTORIA` meses (por defecto 12), agrupado por producto con categoría, cantidad total, cantidad de compras y fecha de la última compra, limitado a los `PERFILES_MAX_PRODUCTOS` productos más comprados (por defecto 100). Lo que se envía a Claude MUST contener solo datos de productos, categorías, cantidades y fechas, y MUST NOT incluir nombre, DNI, email, teléfono ni fecha de nacimiento del socio. El identificador del socio solo MUST viajar como `custom_id` del pedido del lote.

#### Scenario: Agrupación por producto
- **WHEN** un socio compró 3 veces "Alfajor chocolate amargo" (2, 1 y 3 unidades)
- **THEN** el input contiene una sola línea para ese producto con cantidad 6, 3 compras y la fecha de la última

#### Scenario: Sin datos personales
- **WHEN** se arma el pedido para cualquier socio
- **THEN** el contenido del mensaje no contiene su nombre, DNI, email, teléfono ni fecha de nacimiento

### Requirement: Generación asíncrona por lotes
El proceso SHALL ejecutarse en `GET /jobs/perfiles`, protegido con `CRON_SECRET` igual que `/jobs/diario`. En cada ejecución MUST, en este orden: (1) para cada lote pendiente, consultar su estado y, si terminó, procesar sus resultados; (2) si no queda ningún lote pendiente, seleccionar socios y enviar un lote nuevo a la Message Batches API. El proceso MUST NOT quedarse esperando a que un lote termine. Si `ANTHROPIC_API_KEY` no está configurada o `PERFILES_ACTIVO` es falso, MUST responder sin hacer nada e informarlo.

#### Scenario: Primera corrida
- **WHEN** se ejecuta el job y no hay lotes pendientes
- **THEN** se crea un lote con los socios seleccionados, se guarda su identificador y el job responde sin esperar resultados

#### Scenario: Lote terminado
- **WHEN** se ejecuta el job y el lote del día anterior terminó
- **THEN** se procesan sus resultados, se guardan los perfiles y se envía un lote nuevo

#### Scenario: Lote todavía en proceso
- **WHEN** se ejecuta el job y el lote pendiente sigue procesándose
- **THEN** no se envía un lote nuevo y el job lo informa

#### Scenario: Proceso desactivado
- **WHEN** `PERFILES_ACTIVO` es falso o falta `ANTHROPIC_API_KEY`
- **THEN** el job responde indicando que está desactivado y no llama a la API

#### Scenario: Secreto inválido
- **WHEN** se llama al job sin el `CRON_SECRET` correcto
- **THEN** responde 401

### Requirement: Contenido y validación del perfil
Cada resultado exitoso SHALL ser un JSON que cumpla el esquema del perfil: `resumen` (texto en español, hasta 600 caracteres), `etiquetas` (de 1 a 15 preferencias en minúsculas, por ejemplo "chocolate amargo" o "sin tacc"), `categorias_favoritas` (hasta 5) y `productos_favoritos` (hasta 10, solo productos que aparecen en el input). El sistema MUST normalizar las etiquetas (minúsculas, sin espacios repetidos, sin duplicados) y descartar productos favoritos que no estén en el input. Un resultado con error, vencido, cancelado, rechazado (`stop_reason` `refusal`), cortado (`max_tokens`) o que no cumpla el esquema MUST NOT modificar el perfil existente; se registra el error en el ítem del lote y el socio vuelve a quedar seleccionable al día siguiente.

#### Scenario: Resultado válido
- **WHEN** el resultado de un socio es un JSON válido
- **THEN** su perfil se crea o reemplaza con el resumen, las etiquetas normalizadas, las categorías y productos favoritos, la cantidad de ventas y productos analizados, el período, el modelo y la fecha de generación

#### Scenario: Producto inventado
- **WHEN** el resultado incluye en `productos_favoritos` un producto que no estaba en el input
- **THEN** ese producto se descarta y el resto del perfil se guarda

#### Scenario: Resultado inválido o con error
- **WHEN** el resultado de un socio es un error, un rechazo o un JSON que no cumple el esquema
- **THEN** su perfil anterior (si existe) no cambia, el ítem del lote queda con el error y el socio se vuelve a seleccionar en la corrida siguiente

### Requirement: Consultar el perfil de un socio
`GET /socios/{id}/preferencias` SHALL devolver el perfil del socio con el resumen, las etiquetas, las categorías y productos favoritos, la base del análisis y la fecha de generación. Requiere un usuario autenticado. Si el socio no tiene perfil MUST responder 404 con código `PERFIL_NO_DISPONIBLE`; si el socio no existe, 404 `SOCIO_NO_ENCONTRADO`.

#### Scenario: Socio con perfil
- **WHEN** se consulta un socio que tiene perfil
- **THEN** se devuelve su perfil completo

#### Scenario: Socio sin perfil
- **WHEN** se consulta un socio sin perfil
- **THEN** responde 404 con código `PERFIL_NO_DISPONIBLE`
