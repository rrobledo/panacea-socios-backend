from datetime import date

from pydantic import BaseModel, EmailStr, Field


class SocioBase(BaseModel):
    nombre_apellido: str = Field(..., max_length=200, examples=["Juan Pérez"])
    telefono: str | None = Field(None, max_length=30, examples=["+54 9 11 1234-5678"])
    email: EmailStr = Field(..., examples=["juan@example.com"])
    fecha_nacimiento: date | None = Field(None, examples=["1990-05-15"])
    dni: str = Field(..., max_length=20, examples=["30123456"])


class SocioCreate(SocioBase):
    pass


class SocioUpdate(BaseModel):
    nombre_apellido: str | None = Field(None, max_length=200)
    telefono: str | None = Field(None, max_length=30)
    email: EmailStr | None = None
    fecha_nacimiento: date | None = None
    dni: str | None = Field(None, max_length=20)


class SocioResponse(SocioBase):
    id: int

    model_config = {"from_attributes": True}
