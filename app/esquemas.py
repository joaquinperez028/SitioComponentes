"""Esquemas Pydantic por categoría (D-20, D-29).

- El `title` de cada campo es la etiqueta en inglés que ve el usuario (D-11).
- `mejor` en json_schema_extra indica al comparador qué valor destacar:
  "mayor", "menor" o ausente (no se destaca, p. ej. TDP).
- `filtrable` documenta qué campos usan los filtros básicos (D-08).
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Categoria(str, Enum):
    """Categorías que ve el usuario en la fase 1."""

    cpu = "cpu"
    gpu = "gpu"
    portatil = "portatil"


# Categorías de almacenamiento (tablas). Un portátil se guarda como modelo + configuración.
TABLA_POR_CATEGORIA_DATO = {
    "cpu": "cpu",
    "gpu": "gpu",
    "modelo_portatil": "modelo_portatil",
    "configuracion_portatil": "configuracion_portatil",
}

Plataforma = Literal["escritorio", "movil"]


def _mayor(**extra):
    return {"mejor": "mayor", **extra}


def _menor(**extra):
    return {"mejor": "menor", **extra}


class EsquemaBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def vaciosANulo(cls, valor):
        # Claude a veces devuelve "" o "N/A" cuando la página no tiene el dato
        if isinstance(valor, str) and valor.strip().lower() in {"", "n/a", "na", "none", "null", "-"}:
            return None
        return valor


class EspecificacionesCpu(EsquemaBase):
    nombre: str = Field(title="Model")
    fabricante: str = Field(title="Manufacturer")
    plataforma: Plataforma = Field(title="Platform")
    nucleos: int | None = Field(None, ge=1, le=512, title="Cores", json_schema_extra=_mayor())
    hilos: int | None = Field(None, ge=1, le=1024, title="Threads", json_schema_extra=_mayor())
    relojBaseGhz: float | None = Field(None, gt=0, lt=10, title="Base Clock (GHz)", json_schema_extra=_mayor())
    relojBoostGhz: float | None = Field(None, gt=0, lt=10, title="Boost Clock (GHz)", json_schema_extra=_mayor())
    tdpW: int | None = Field(None, gt=0, le=1000, title="TDP (W)")
    cacheL3Mb: float | None = Field(None, ge=0, le=2048, title="L3 Cache (MB)", json_schema_extra=_mayor())
    socket: str | None = Field(None, title="Socket")
    fechaLanzamiento: str | None = Field(None, title="Launch Date")


class EspecificacionesGpu(EsquemaBase):
    nombre: str = Field(title="Model")
    fabricante: str = Field(title="Manufacturer")
    plataforma: Plataforma = Field(title="Platform")
    vramGb: float | None = Field(None, gt=0, le=256, title="VRAM (GB)", json_schema_extra=_mayor())
    tipoVram: str | None = Field(None, title="Memory Type")
    anchoBusBits: int | None = Field(None, gt=0, le=8192, title="Memory Bus (bit)", json_schema_extra=_mayor())
    unidadesShader: int | None = Field(None, gt=0, title="Shader Units", json_schema_extra=_mayor())
    relojBoostMhz: int | None = Field(None, gt=0, lt=5000, title="Boost Clock (MHz)", json_schema_extra=_mayor())
    tdpW: int | None = Field(None, gt=0, le=1500, title="TDP / TGP (W)")
    fechaLanzamiento: str | None = Field(None, title="Launch Date")


class EspecificacionesModeloPortatil(EsquemaBase):
    nombre: str = Field(title="Model")
    fabricante: str = Field(title="Manufacturer")
    pantallaPulgadas: float | None = Field(None, gt=5, lt=25, title="Screen Size (in)")
    resolucionPantalla: str | None = Field(None, title="Resolution")
    tasaRefrescoHz: int | None = Field(None, gt=0, le=1000, title="Refresh Rate (Hz)", json_schema_extra=_mayor())
    tipoPanel: str | None = Field(None, title="Panel")
    pesoKg: float | None = Field(None, gt=0, lt=10, title="Weight (kg)", json_schema_extra=_menor())
    refrigeracion: str | None = Field(None, title="Cooling")
    bateriaWh: float | None = Field(None, gt=0, le=150, title="Battery (Wh)", json_schema_extra=_mayor())


class EspecificacionesConfiguracionPortatil(EsquemaBase):
    nombre: str = Field(title="Configuration")
    cpuNombre: str | None = Field(None, title="CPU")
    gpuNombre: str | None = Field(None, title="GPU")
    tgpW: int | None = Field(None, gt=0, le=300, title="GPU TGP (W)", json_schema_extra=_mayor())
    pl1W: int | None = Field(None, gt=0, le=300, title="CPU PL1 (W)", json_schema_extra=_mayor())
    pl2W: int | None = Field(None, gt=0, le=400, title="CPU PL2 (W)", json_schema_extra=_mayor())
    ramGb: int | None = Field(None, gt=0, le=512, title="RAM (GB)", json_schema_extra=_mayor())
    almacenamientoGb: int | None = Field(None, gt=0, title="Storage (GB)", json_schema_extra=_mayor())


class EspecificacionesPortatil(BaseModel):
    """Lo que se extrae de una página de portátil: un modelo y una o más configuraciones."""

    model_config = ConfigDict(extra="forbid")

    modelo: EspecificacionesModeloPortatil
    configuraciones: list[EspecificacionesConfiguracionPortatil] = Field(min_length=1)


ESQUEMA_POR_CATEGORIA: dict[Categoria, type[BaseModel]] = {
    Categoria.cpu: EspecificacionesCpu,
    Categoria.gpu: EspecificacionesGpu,
    Categoria.portatil: EspecificacionesPortatil,
}


def etiquetaCampo(esquema: type[BaseModel], campo: str) -> str:
    informacion = esquema.model_fields.get(campo)
    return (informacion.title if informacion and informacion.title else campo)


def direccionMejor(esquema: type[BaseModel], campo: str) -> str | None:
    informacion = esquema.model_fields.get(campo)
    extra = informacion.json_schema_extra if informacion else None
    return extra.get("mejor") if isinstance(extra, dict) else None
