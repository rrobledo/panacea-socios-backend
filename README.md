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
| POST | `/ventas/` | Registrar venta con detalles |
| GET | `/ventas/{id}` | Obtener venta con detalles |
| PUT | `/ventas/{id}` | Actualizar cabecera de venta |
| DELETE | `/ventas/{id}` | Eliminar venta y detalles |

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

## Seguridad

- `DATABASE_URL` nunca se hardcodea — siempre desde variable de entorno
- Validación de unicidad de DNI y email con respuesta `409 Conflict`
- Claves de preferencias controladas por enum (no acepta valores arbitrarios)
- `socio_id` en ventas es nullable con `SET NULL` — borrar un socio no destruye el historial de compras
