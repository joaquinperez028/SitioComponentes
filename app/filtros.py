"""Filtros básicos por specs (D-08). Los parámetros se validan con Pydantic y se traducen a SQL parametrizado."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.esquemas import Categoria
from app.repositorios import CONSULTA_PORTATIL, completarPortatil


class FiltrosBase(BaseModel):
    model_config = ConfigDict(extra="ignore")

    @field_validator("*", mode="before")
    @classmethod
    def vaciosANulo(cls, valor):
        # Los formularios HTML envían "" para los campos sin rellenar
        return None if valor == "" else valor


class FiltrosCpu(FiltrosBase):
    fabricante: str | None = None
    nucleosMin: int | None = Field(None, ge=1)
    plataforma: str | None = Field(None, pattern="^(escritorio|movil)$")
    tdpMax: int | None = Field(None, ge=1)


class FiltrosGpu(FiltrosBase):
    fabricante: str | None = None
    vramMin: float | None = Field(None, gt=0)
    plataforma: str | None = Field(None, pattern="^(escritorio|movil)$")
    tdpMax: int | None = Field(None, ge=1)


class FiltrosPortatil(FiltrosBase):
    cpu: str | None = None
    gpu: str | None = None
    tgpMin: int | None = Field(None, ge=1)
    ramMin: int | None = Field(None, ge=1)
    pantallaMin: float | None = Field(None, gt=0)
    pantallaMax: float | None = Field(None, gt=0)
    pesoMax: float | None = Field(None, gt=0)


FILTROS_POR_CATEGORIA = {Categoria.cpu: FiltrosCpu, Categoria.gpu: FiltrosGpu, Categoria.portatil: FiltrosPortatil}


def construirConsulta(categoria: Categoria, filtros: BaseModel) -> tuple[str, list]:
    condiciones: list[str] = []
    parametros: list = []

    def agregar(condicion: str, valor):
        if valor is not None:
            condiciones.append(condicion)
            parametros.append(valor)

    if categoria in (Categoria.cpu, Categoria.gpu):
        sql = f"SELECT * FROM {categoria.value}"
        agregar("fabricante = ? COLLATE NOCASE", filtros.fabricante)
        agregar("plataforma = ?", filtros.plataforma)
        agregar("tdpW <= ?", filtros.tdpMax)
        if categoria == Categoria.cpu:
            agregar("nucleos >= ?", filtros.nucleosMin)
        else:
            agregar("vramGb >= ?", filtros.vramMin)
        orden = " ORDER BY fabricante, nombre"
    else:
        sql = CONSULTA_PORTATIL
        agregar("cpu.nombre LIKE ?", f"%{filtros.cpu}%" if filtros.cpu else None)
        agregar("gpu.nombre LIKE ?", f"%{filtros.gpu}%" if filtros.gpu else None)
        agregar("c.tgpW >= ?", filtros.tgpMin)
        agregar("c.ramGb >= ?", filtros.ramMin)
        agregar("m.pantallaPulgadas >= ?", filtros.pantallaMin)
        agregar("m.pantallaPulgadas <= ?", filtros.pantallaMax)
        agregar("m.pesoKg <= ?", filtros.pesoMax)
        orden = " ORDER BY m.nombre, c.nombre"

    if condiciones:
        sql += " WHERE " + " AND ".join(condiciones)
    return sql + orden, parametros


def filtrar(conexion, categoria: Categoria, parametros: dict) -> list[dict]:
    filtros = FILTROS_POR_CATEGORIA[categoria].model_validate(parametros)
    sql, valores = construirConsulta(categoria, filtros)
    filas = conexion.execute(sql, valores)
    if categoria == Categoria.portatil:
        return [completarPortatil(fila) for fila in filas]
    return [dict(fila) for fila in filas]


def fabricantesDisponibles(conexion, categoria: Categoria) -> list[str]:
    tabla = "modelo_portatil" if categoria == Categoria.portatil else categoria.value
    return [fila[0] for fila in conexion.execute(f"SELECT DISTINCT fabricante FROM {tabla} ORDER BY fabricante")]
