from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


class SocioBase(BaseModel):
    nombre_apellido: str = Field(..., max_length=200, examples=["Juan Pérez"])
    telefono: str | None = Field(None, max_length=30, examples=["+54 9 11 1234-5678"])
    email: str | None = Field(None, examples=["juan@example.com"])
    fecha_nacimiento: date | None = Field(None, examples=["1990-05-15"])
    dni: str = Field(..., max_length=20, examples=["30123456"])

    @field_validator("fecha_nacimiento", mode="before")
    @classmethod
    def parse_fecha_nacimiento(cls, v):
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, str) and "T" in v:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).date()
        return v


class SocioCreate(SocioBase):
    pass


class SocioUpdate(BaseModel):
    nombre_apellido: str | None = Field(None, max_length=200)
    telefono: str | None = Field(None, max_length=30)
    email: str | None = None
    fecha_nacimiento: date | None = None
    dni: str | None = Field(None, max_length=20)


class SocioResponse(SocioBase):
    id: int

    model_config = {"from_attributes": True}
