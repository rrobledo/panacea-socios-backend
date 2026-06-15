from pydantic import BaseModel, Field

from app.models.pregunta import ClavePregunta


class PreguntaCreate(BaseModel):
    clave: ClavePregunta = Field(..., examples=[ClavePregunta.producto_deseado])
    valor: str = Field(..., min_length=1, examples=["Cervezas artesanales"])


class PreguntaUpdate(BaseModel):
    valor: str = Field(..., min_length=1)


class PreguntaResponse(BaseModel):
    id: int
    socio_id: int
    clave: ClavePregunta
    valor: str

    model_config = {"from_attributes": True}
