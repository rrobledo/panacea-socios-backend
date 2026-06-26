from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


class RegisterRequest(BaseModel):
    nombre_apellido: str = Field(..., max_length=200, examples=["Juan Pérez"])
    email: str = Field(..., examples=["juan@example.com"])
    password: str = Field(..., min_length=8, examples=["s3cr3tPass!"])
    dni: str = Field(..., max_length=20, examples=["30123456"])
    telefono: str | None = Field(None, max_length=30)
    fecha_nacimiento: date | None = None

    @field_validator("fecha_nacimiento", mode="before")
    @classmethod
    def parse_fecha(cls, v):
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, str) and "T" in v:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).date()
        return v


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    socio_id: int


