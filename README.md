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
  config.py                 ← Settings (DATABASE_URL)
  database.py               ← Engine + sesión SQLAlchemy
  models/
    socio.py                ← Tabla socios
    pregunta.py             ← Tabla preguntas_por_socios
    venta.py                ← Tablas registro_ventas + detalle
  schemas/
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

## Seguridad

- `DATABASE_URL` nunca se hardcodea — siempre desde variable de entorno
- Validación de unicidad de DNI y email con respuesta `409 Conflict`
- Claves de preferencias controladas por enum (no acepta valores arbitrarios)
- `socio_id` en ventas es nullable con `SET NULL` — borrar un socio no destruye el historial de compras
