"""Comparador lado a lado de 2 a 4 productos de la misma categoría (D-07)."""

from dataclasses import dataclass, field

from app.benchmarks import GrupoBenchmark, compararBenchmarks
from app.esquemas import (
    Categoria,
    EspecificacionesConfiguracionPortatil,
    EspecificacionesCpu,
    EspecificacionesGpu,
    EspecificacionesModeloPortatil,
    direccionMejor,
    etiquetaCampo,
)
from app.repositorios import datosVerificablesDe, obtenerProducto

MINIMO_PRODUCTOS = 2
MAXIMO_PRODUCTOS = 4


class ErrorComparacion(ValueError):
    pass


@dataclass
class FilaComparacion:
    campo: str
    etiqueta: str
    valores: list
    datos: list[dict | None]          # dato verificable de cada celda (fuente, fragmento, estado)
    mejorIndices: set[int] = field(default_factory=set)


@dataclass
class Comparacion:
    categoria: Categoria
    productos: list[dict]
    filas: list[FilaComparacion]
    benchmarks: list[GrupoBenchmark]


# (clave del dato verificable, esquema, campo del esquema, columna en el producto leído)
def filasDeCategoria(categoria: Categoria) -> list[tuple[str, type, str, str]]:
    if categoria == Categoria.cpu:
        return [(c, EspecificacionesCpu, c, c) for c in EspecificacionesCpu.model_fields if c != "nombre"]
    if categoria == Categoria.gpu:
        return [(c, EspecificacionesGpu, c, c) for c in EspecificacionesGpu.model_fields if c != "nombre"]
    filas = [
        (f"modelo.{c}", EspecificacionesModeloPortatil, c, "modeloNombre" if c == "nombre" else c)
        for c in EspecificacionesModeloPortatil.model_fields
    ]
    filas += [
        (c, EspecificacionesConfiguracionPortatil, c, c)
        for c in EspecificacionesConfiguracionPortatil.model_fields
        if c != "nombre"
    ]
    return filas


def filasDeFicha(categoria: Categoria, producto: dict, datos: dict[str, dict]) -> list[dict]:
    """Specs de un producto para su ficha: etiqueta en inglés, valor y dato verificable."""
    filas = []
    for claveDato, esquema, campo, columna in filasDeCategoria(categoria):
        valor = producto.get(columna)
        if valor is not None:
            filas.append({"etiqueta": etiquetaCampo(esquema, campo), "valor": valor, "dato": datos.get(claveDato)})
    return filas


def _mejores(valores: list, direccion: str | None) -> set[int]:
    numericos = {i: v for i, v in enumerate(valores) if isinstance(v, (int, float)) and not isinstance(v, bool)}
    if direccion is None or len(numericos) < 2 or len(set(numericos.values())) == 1:
        return set()
    objetivo = max(numericos.values()) if direccion == "mayor" else min(numericos.values())
    return {i for i, v in numericos.items() if v == objetivo}


def compararProductos(conexion, categoria: Categoria, productoIds: list[int]) -> Comparacion:
    idsUnicos = list(dict.fromkeys(productoIds))
    if not MINIMO_PRODUCTOS <= len(idsUnicos) <= MAXIMO_PRODUCTOS:
        raise ErrorComparacion(f"Se comparan entre {MINIMO_PRODUCTOS} y {MAXIMO_PRODUCTOS} productos distintos")

    productos = [obtenerProducto(conexion, categoria, productoId) for productoId in idsUnicos]
    datos = [datosVerificablesDe(conexion, categoria, productoId) for productoId in idsUnicos]

    filas = []
    for claveDato, esquema, campo, columna in filasDeCategoria(categoria):
        valores = [producto.get(columna) for producto in productos]
        if all(v is None for v in valores):
            continue
        filas.append(
            FilaComparacion(
                campo=claveDato,
                etiqueta=etiquetaCampo(esquema, campo),
                valores=valores,
                datos=[d.get(claveDato) for d in datos],
                mejorIndices=_mejores(valores, direccionMejor(esquema, campo)),
            )
        )
    return Comparacion(categoria, productos, filas, compararBenchmarks(conexion, categoria, idsUnicos))
