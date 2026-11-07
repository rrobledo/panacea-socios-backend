# Panacea Socios Backend

REST API para gestión de socios, preferencias y ventas de Panacea.  
Construida con **FastAPI + SQLAlchemy + PostgreSQL**, desplegable en **Vercel**.

---

## Stack

| Capa | Tecnología |
|------|-----------|
| Framework | FastAPI 0.115 |
| ORM | SQLAlchemy 2.0 |
| Migraciones | Alembic |
| DB | PostgreSQL |
| Validación | Pydantic v2 |
| Deploy | Vercel (serverless Python) |

---

## Estructura del proyecto

```
api/
  index.py                  ← Entrypoint de Vercel
app/
  main.py                   ← App FastAPI + middleware
  config.py                 ← Settings (DATABASE_URL, claves OAuth)
  database.py               ← Engine + sesión SQLAlchemy
  auth/
    passport.py             ← Singleton tipo Passport.js
    router.py               ← Endpoints /auth/*
    dependencies.py         ← require_admin guard
    state.py                ← Generación/verificación de state CSRF
    utils.py                ← hash_password, verify_password, create_token
    strategies/
      local.py              ← Email + contraseña
      register.py           ← Registro de nuevo socio
      jwt.py                ← Verificación de Bearer token
      google.py             ← OAuth2 Google
      facebook.py           ← OAuth2 Facebook
      apple.py              ← Sign In with Apple
  models/
    socio.py                ← Tabla socios
    pregunta.py             ← Tabla preguntas_por_socios
    venta.py                ← Tablas registro_ventas + detalle
  schemas/
    auth.py                 ← RegisterRequest, TokenResponse
    socio.py                ← Pydantic schemas socios
    pregunta.py             ← Pydantic schemas preguntas
    venta.py                ← Pydantic schemas ventas
  routers/
    socios.py               ← CRUD /socios
    preguntas.py            ← CRUD /socios/{id}/preguntas
    ventas.py               ← CRUD /ventas
alembic/
  versions/
    0001_initial_schema.py  ← Migración inicial
vercel.json
requirements.txt
```

---

## Instalación local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Editar .env con tu DATABASE_URL real
```

## Migraciones

```bash
# Aplicar migraciones
alembic upgrade head

# Revertir última migración
alembic downgrade -1
```

## Desarrollo local

```bash
uvicorn app.main:app --reload
```

- Swagger UI: http://localhost:8000/docs  
- ReDoc:      http://localhost:8000/redoc

---

## Despliegue en Vercel

1. Conectar el repositorio en [vercel.com](https://vercel.com)
2. Agregar variable de entorno `DATABASE_URL` en el panel de Vercel  
   (Recomendado: [Neon](https://neon.tech) o [Supabase](https://supabase.com) para Postgres gestionado)
3. Ejecutar `alembic upgrade head` una vez desde local apuntando a la DB de producción
4. `vercel deploy --prod`

---

## API — Recursos y endpoints

### Socios (`/socios`)

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/socios/` | Listar socios (paginado) |
| POST | `/socios/` | Crear socio |
| GET | `/socios/{id}` | Obtener socio |
| PUT | `/socios/{id}` | Actualizar socio |
| DELETE | `/socios/{id}` | Eliminar socio |

#### Parámetros de consulta — `GET /socios/`

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `skip` | int | Registros a omitir (paginación, default `0`) |
| `limit` | int | Máximo de registros a retornar (default `100`) |
| `dni` | string | Filtra por DNI exacto |
| `name` | string | Filtra por nombre (parcial, sin distinción de mayúsculas) |

Ejemplos:
```
GET /socios/?dni=12345678
GET /socios/?name=garcia
GET /socios/?name=garcia&skip=0&limit=20
```

### Preguntas por socio (`/socios/{id}/preguntas`)

Claves válidas:
- `que_producto_te_gustaria_que_sumemos`
- `que_parte_de_panacea_es_tu_favorita`
- `de_donde_son`

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/socios/{id}/preguntas/` | Listar preferencias |
| POST | `/socios/{id}/preguntas/` | Agregar / actualizar preferencia |
| GET | `/socios/{id}/preguntas/{clave}` | Obtener preferencia |
| PUT | `/socios/{id}/preguntas/{clave}` | Actualizar preferencia |
| DELETE | `/socios/{id}/preguntas/{clave}` | Eliminar preferencia |

### Ventas (`/ventas`)

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/ventas/` | Listar ventas (filtro: `?socio_id=`) |
| POST | `/ventas/` | Registrar venta con detalles (opcional: `cupon_codigo` o `beneficio_id`) |
| GET | `/ventas/beneficios-disponibles` | Beneficios que un socio puede usar (`?socio_id=&importe=`) |
| GET | `/ventas/{id}` | Obtener venta con detalles |
| PUT | `/ventas/{id}` | Actualizar cabecera de venta |
| DELETE | `/ventas/{id}` | Eliminar venta y detalles (revierte puntos y devuelve el beneficio usado) |

---

## Autenticación

El sistema usa un patrón tipo **Passport.js**: cada método de login es una _estrategia_ intercambiable. Todos retornan el mismo `TokenResponse`:

```json
{
  "access_token": "<JWT>",
  "token_type": "bearer",
  "socio_id": 42
}
```

El JWT se firma con `HS256` usando `SECRET_KEY` y expira a los `ACCESS_TOKEN_EXPIRE_DAYS` días (default 7). Payload: `{ sub: "<socio_id>", email, exp }`.

Para rutas protegidas, enviar el token en el header:

```
Authorization: Bearer <access_token>
```

---

### Método 1 — Email y contraseña (Local)

Flujo directo: las credenciales se validan contra la base de datos. Las contraseñas se hashean con **bcrypt**.

#### Registro

```
POST /auth/register
Content-Type: application/json

{
  "nombre_apellido": "Juan Pérez",
  "email": "juan@example.com",
  "password": "s3cr3tPass!",
  "dni": "30123456",
  "telefono": "+54911...",      ← opcional
  "fecha_nacimiento": "1990-05-20"  ← opcional
}
```

Crea un nuevo `Socio` con `email_verified = false`. Retorna `201 Created` con `TokenResponse`.  
Error `409 Conflict` si el email o DNI ya existe.

#### Login

```
POST /auth/token
Content-Type: application/x-www-form-urlencoded

username=juan@example.com&password=s3cr3tPass!
```

Formato estándar **OAuth2 Password Grant** (compatible con el botón _Authorize_ del Swagger UI).  
Error `401 Unauthorized` si las credenciales son incorrectas o el usuario no tiene contraseña configurada.

---

### Método 2 — Google OAuth2 (Authorization Code Flow)

Flujo completo de redirecciones. Google autentica al usuario y devuelve un código que el backend intercambia por un JWT propio.

#### Variables de entorno requeridas

```
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
BASE_URL=https://tu-dominio.com        ← base para construir el redirect_uri
FRONTEND_URLS=https://app.tu-dominio.com,https://admin.tu-dominio.com  ← whitelist de destinos
```

#### Flujo paso a paso

```
1. Cliente  →  GET /auth/google?redirect_uri=https://app.tu-dominio.com
               ↓
2. Backend  →  valida redirect_uri contra FRONTEND_URLS
            →  302 → https://accounts.google.com/o/oauth2/v2/auth
                     ?client_id=...&redirect_uri=BASE_URL/auth/google/callback
                     &response_type=code&scope=openid email profile
                     &state=<JWT firmado con redirect_uri embebida>
               ↓  (usuario aprueba en Google)
3. Google   →  302 → BASE_URL/auth/google/callback?code=...&state=...
               ↓
4. Backend  →  verifica state (CSRF) y extrae redirect_uri del JWT
            →  POST https://oauth2.googleapis.com/token  (intercambia code → access_token)
            →  GET  https://www.googleapis.com/oauth2/v3/userinfo
            →  busca Socio por email en la DB
            →  emite JWT propio
               ↓
5. Respuesta:
   - Si redirect_uri fue pasada y es válida → 302 → redirect_uri?token=...&socio_id=...
   - Si no se pasó redirect_uri             → 302 → primera URL de FRONTEND_URLS
   - Si FRONTEND_URLS está vacío            → 200 JSON con TokenResponse
```

> **Nota**: Google solo autentica; no crea cuentas nuevas. El socio debe existir previamente en la DB con ese email. Si no existe, responde `404 Not Found`.

#### Soporte para múltiples frontends

`FRONTEND_URLS` es una lista separada por comas. Cada frontend pasa su propia URL al iniciar el login:

```
# App principal
GET /auth/google?redirect_uri=https://app.panacea.com/auth/callback

# Panel admin
GET /auth/google?redirect_uri=https://admin.panacea.com/auth/callback
```

Si `redirect_uri` no está en la whitelist el backend responde `400 Bad Request` antes de redirigir a Google. La URL válida se embebe en el JWT del `state` (firmado y con expiración de 10 min), por lo que no puede ser alterada en el callback.

#### Protección CSRF (state)

El parámetro `state` es un JWT firmado con `SECRET_KEY` que expira en **10 minutos**. Contiene un `jti` aleatorio y la `redirect_uri` del frontend. El backend lo verifica en el callback antes de continuar. Cualquier state inválido o expirado responde `400 Bad Request`.

---

### Método 3 — Facebook OAuth2 (Authorization Code Flow)

Idéntico al flujo de Google con la autorización de Facebook.

#### Variables de entorno requeridas

```
FACEBOOK_APP_ID=...
FACEBOOK_APP_SECRET=...
```

| Paso | Endpoint |
|------|---------|
| Inicio | `GET /auth/facebook?redirect_uri=https://app.tu-dominio.com` |
| Callback | `GET /auth/facebook/callback?code=...&state=...` |

---

### Método 4 — Apple Sign In (Authorization Code Flow con form_post)

Apple usa `response_mode=form_post`, por lo que el callback es un `POST` en lugar de `GET`.

#### Variables de entorno requeridas

```
APPLE_CLIENT_ID=...
APPLE_TEAM_ID=...
APPLE_KEY_ID=...
APPLE_PRIVATE_KEY=...
```

| Paso | Endpoint |
|------|---------|
| Inicio | `GET /auth/apple?redirect_uri=https://app.tu-dominio.com` |
| Callback | `POST /auth/apple/callback` (body form-encoded) |

---

### Admin Guard

Algunas rutas requieren rol de administrador. Se configura listando emails en la variable de entorno:

```
ADMIN_EMAILS=admin@panacea.com,otro@panacea.com
```

El guard valida que el JWT sea válido **y** que el email del socio esté en esa lista. Responde `403 Forbidden` si no.

---

## Programa de puntos

Endpoints: `/recompensas/*` (socio autenticado), `/canjes/{codigo}` (validación en caja),
`/admin/*` (beneficios, reglas de conversión, configuración y ajustes; requiere admin) y
`POST /ventas/` acepta `cupon_codigo` y genera los puntos de la compra.

- Migración: `alembic upgrade head` (revisión `0004`). Luego cargar la primera regla de
  conversión desde la pantalla "Maestro → Tabla de conversión" de Club Socios: sin regla
  vigente, las compras no generan puntos.
- Job diario (Vercel Cron, definido en `vercel.json`): `GET /jobs/diario`. Requiere la
  variable `CRON_SECRET` (Vercel la envía como `Authorization: Bearer …`).
- Puntos por ventas históricas: `scripts/ajustar_puntos_por_ventas_datagrip.sql` (1000 pesos = 1 punto
  sobre el total de ventas de cada socio; solo agrega lo que falta). Se ejecuta completo desde
  DataGrip y termina en `ROLLBACK` (simulación): cambiar la última línea por `COMMIT` para aplicar.

### Beneficio en el mostrador

El personal puede elegir un beneficio al registrar la venta, sin que el socio genere un cupón antes:

1. Al elegir el socio, `GET /ventas/beneficios-disponibles?socio_id=…&importe=…` devuelve
   `saldo_puntos` y los beneficios vigentes con `usable`, `motivo` (`SALDO_INSUFICIENTE`,
   `LIMITE_ALCANZADO`, `PROGRAMA_INACTIVO`, …) y `descuento_estimado`.
2. `POST /ventas/` con `beneficio_id` (requiere `socio_id`, excluye `cupon_codigo`; `importe` es el
   monto antes del descuento). En una sola transacción descuenta los puntos, crea el canje
   (origen `MOSTRADOR`, estado `USADO`), registra el neto y genera los puntos sobre el neto.
   La respuesta trae `descuento`, `puntos_canjeados`, `puntos_generados` y `saldo_puntos`.
3. Si la venta se elimina, el canje pasa a `CANCELADO` y se devuelven los puntos
   (movimiento `DEVOLUCION_CANJE`) y el stock. No se puede cambiar el socio ni el importe de
   una venta con beneficio (409 `VENTA_CON_BENEFICIO`).

El `limite_por_socio` de cada beneficio cuenta los canjes de la app y del mostrador (sin los anulados).

## Perfiles de preferencias con IA

Un proceso diario genera, para cada socio con compras nuevas, un perfil de gustos con Claude a
partir del detalle de productos de sus compras de los últimos 12 meses (ventas cruzadas con
`documentos` / `documentos_cp` y `panacea_sales_v2`; las que no se pueden cruzar se ignoran).
A Claude solo se le envían productos, categorías, cantidades y fechas, nunca datos personales.

- **Job**: `GET /jobs/perfiles` (Vercel Cron, 07:00 UTC, con `CRON_SECRET`). Usa la Message
  Batches API: cada corrida procesa el lote anterior si terminó y envía uno nuevo, así que los
  perfiles se actualizan con un día de demora. Para correrlo a mano:
  `curl -H "Authorization: Bearer $CRON_SECRET" https://<host>/jobs/perfiles` (una segunda
  llamada, cuando el lote terminó, guarda los perfiles).
- **Variables**:

  | Variable | Por defecto | Uso |
  |---|---|---|
  | `ANTHROPIC_API_KEY` | (vacía) | Sin ella el proceso no hace nada |
  | `PERFILES_ACTIVO` | `true` | `false` lo detiene sin desplegar |
  | `PERFILES_MODELO` | `claude-opus-5-5` | Modelo de Claude |
  | `PERFILES_MESES_HISTORIA` | `12` | Meses de compras analizados |
  | `PERFILES_MAX_POR_LOTE` | `500` | Socios por día (la carga inicial se reparte en varios días) |
  | `PERFILES_MAX_PRODUCTOS` | `100` | Productos enviados por socio |

- **Costo estimado** (precios de lote): ~US$0,02–0,03 por socio con `claude-opus-5-5`,
  ~US$0,01 con `claude-sonnet-5-5`, ~US$0,001 con `claude-haiku-5-5`. Solo se reprocesan los
  socios que compraron desde su último perfil.
- **Endpoints**:
  - `GET /socios/{id}/preferencias`: perfil del socio (404 `PERFIL_NO_DISPONIBLE` si no tiene).
  - `GET /reportes/preferencias?q=chocolate[&incluir_resumen=true&skip=&limit=]`: socios por
    etiqueta, producto o categoría (sin distinguir acentos), ordenados por relevancia.
  - `GET /reportes/preferencias/etiquetas`: etiquetas existentes con su cantidad de socios.

### Pruebas

Requieren un PostgreSQL **local** (las pruebas borran el esquema):

```bash
docker run -d --name puntos-test-pg -e POSTGRES_PASSWORD=test -e POSTGRES_DB=puntos -p 55432:5432 postgres:16-alpine
pip install -r requirements-dev.txt
TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/puntos pytest
```

---

## Seguridad

- `DATABASE_URL` nunca se hardcodea — siempre desde variable de entorno
- Validación de unicidad de DNI y email con respuesta `409 Conflict`
- Claves de preferencias controladas por enum (no acepta valores arbitrarios)
- `socio_id` en ventas es nullable con `SET NULL` — borrar un socio no destruye el historial de compras
