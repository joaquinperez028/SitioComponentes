"""Lectura y escritura de productos y de sus datos verificables en SQLite."""

import sqlite3

from pydantic import BaseModel

from app.esquemas import (
    Categoria,
    EspecificacionesConfiguracionPortatil,
    EspecificacionesCpu,
    EspecificacionesGpu,
    EspecificacionesModeloPortatil,
    EspecificacionesPortatil,
)
from app.extraccion.extractor import DatoExtraido, ResultadoExtraccion
from app.normalizacion import Normalizador, claveNormalizada


class ProductoNoEncontrado(Exception):
    pass


def _upsert(conexion: sqlite3.Connection, tabla: str, valores: dict) -> int:
    """Inserta o actualiza por nombre (único). Devuelve el id."""
    columnas = list(valores)
    marcadores = ", ".join("?" for _ in columnas)
    actualizacion = ", ".join(f"{c} = excluded.{c}" for c in columnas if c != "nombre")
    conexion.execute(
        f"INSERT INTO {tabla} ({', '.join(columnas)}) VALUES ({marcadores}) "
        f"ON CONFLICT (nombre) DO UPDATE SET {actualizacion}",
        [valores[c] for c in columnas],
    )
    return conexion.execute(f"SELECT id FROM {tabla} WHERE nombre = ?", (valores["nombre"],)).fetchone()["id"]


def guardarDatosVerificables(
    conexion: sqlite3.Connection,
    categoriaDato: str,
    productoId: int,
    especificaciones: BaseModel,
    datosPorCampo: dict[str, DatoExtraido],
    urlFuente: str,
) -> None:
    """Un registro por spec con valor, fuente, fragmento y estado sin_verificar (D-25)."""
    for campo, valor in especificaciones.model_dump().items():
        if valor is None or isinstance(valor, (dict, list)):
            continue
        dato = datosPorCampo.get(campo)
        conexion.execute(
            "INSERT INTO dato_verificable (categoria, productoId, campo, valor, urlFuente, fragmento, fragmentoEncontrado) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (categoria, productoId, campo) DO UPDATE SET valor = excluded.valor, "
            "urlFuente = excluded.urlFuente, fragmento = excluded.fragmento, "
            "fragmentoEncontrado = excluded.fragmentoEncontrado, estado = 'sin_verificar'",
            (
                categoriaDato, productoId, campo, str(valor), urlFuente,
                dato.fragmento if dato else None, int(dato.fragmentoEncontrado) if dato else 0,
            ),
        )


def guardarCpu(conexion, especificaciones: EspecificacionesCpu, urlFuente: str, datos: dict[str, DatoExtraido]) -> int:
    with conexion:
        productoId = _upsert(conexion, "cpu", {**especificaciones.model_dump(), "urlFuente": urlFuente})
        guardarDatosVerificables(conexion, "cpu", productoId, especificaciones, datos, urlFuente)
    return productoId


def guardarGpu(conexion, especificaciones: EspecificacionesGpu, urlFuente: str, datos: dict[str, DatoExtraido]) -> int:
    with conexion:
        productoId = _upsert(conexion, "gpu", {**especificaciones.model_dump(), "urlFuente": urlFuente})
        guardarDatosVerificables(conexion, "gpu", productoId, especificaciones, datos, urlFuente)
    return productoId


def guardarPortatil(
    conexion, resultado: ResultadoExtraccion, normalizador: Normalizador
) -> tuple[int, list[int]]:
    """Guarda el modelo y sus configuraciones, enlazando CPU y GPU al catálogo (D-06, D-09)."""
    especificaciones: EspecificacionesPortatil = resultado.especificaciones
    url = resultado.urlFuente
    with conexion:
        modelo: EspecificacionesModeloPortatil = especificaciones.modelo
        modeloId = _upsert(conexion, "modelo_portatil", {**modelo.model_dump(), "urlFuente": url})
        guardarDatosVerificables(conexion, "modelo_portatil", modeloId, modelo, resultado.datosDe("modelo"), url)

    configuracionIds = []
    for indice, configuracion in enumerate(especificaciones.configuraciones):
        cpuId = _enlazar(normalizador, "cpu", configuracion.cpuNombre)
        gpuId = _enlazar(normalizador, "gpu", configuracion.gpuNombre)
        valores = configuracion.model_dump(exclude={"cpuNombre", "gpuNombre"})
        valores.update(
            modeloId=modeloId, cpuId=cpuId, gpuId=gpuId, urlFuente=url,
            cpuNombreOriginal=configuracion.cpuNombre, gpuNombreOriginal=configuracion.gpuNombre,
        )
        with conexion:
            configuracionId = _upsert(conexion, "configuracion_portatil", valores)
            guardarDatosVerificables(
                conexion, "configuracion_portatil", configuracionId, configuracion,
                resultado.datosDe(f"configuraciones.{indice}"), url,
            )
        configuracionIds.append(configuracionId)
    return modeloId, configuracionIds


def _enlazar(normalizador: Normalizador, categoria: str, nombre: str | None) -> int | None:
    if not nombre:
        return None
    return normalizador.resolver(categoria, nombre).productoId


def guardarResultado(conexion, categoria: Categoria, resultado: ResultadoExtraccion, normalizador: Normalizador) -> list[int]:
    """Guarda lo extraído y devuelve los ids de los productos que ve el usuario."""
    if categoria == Categoria.cpu:
        return [guardarCpu(conexion, resultado.especificaciones, resultado.urlFuente, resultado.datosDe(""))]
    if categoria == Categoria.gpu:
        return [guardarGpu(conexion, resultado.especificaciones, resultado.urlFuente, resultado.datosDe(""))]
    return guardarPortatil(conexion, resultado, normalizador)[1]


# --- Lectura -------------------------------------------------------------------------------------

CONSULTA_PORTATIL = """
SELECT c.*, m.nombre AS modeloNombre, m.fabricante, m.pantallaPulgadas, m.resolucionPantalla,
       m.tasaRefrescoHz, m.tipoPanel, m.pesoKg, m.refrigeracion, m.bateriaWh,
       cpu.nombre AS cpuNombre, gpu.nombre AS gpuNombre
FROM configuracion_portatil c
JOIN modelo_portatil m ON m.id = c.modeloId
LEFT JOIN cpu ON cpu.id = c.cpuId
LEFT JOIN gpu ON gpu.id = c.gpuId
"""


def completarPortatil(fila: sqlite3.Row | dict) -> dict:
    """Si la CPU o GPU no se pudo enlazar al catálogo, se muestra el nombre tal cual venía en la fuente."""
    producto = dict(fila)
    producto["cpuEnlazada"] = producto.get("cpuId") is not None
    producto["gpuEnlazada"] = producto.get("gpuId") is not None
    producto["cpuNombre"] = producto.get("cpuNombre") or producto.get("cpuNombreOriginal")
    producto["gpuNombre"] = producto.get("gpuNombre") or producto.get("gpuNombreOriginal")
    return producto


def obtenerProducto(conexion, categoria: Categoria, productoId: int) -> dict:
    if categoria == Categoria.portatil:
        fila = conexion.execute(CONSULTA_PORTATIL + " WHERE c.id = ?", (productoId,)).fetchone()
    else:
        fila = conexion.execute(f"SELECT * FROM {categoria.value} WHERE id = ?", (productoId,)).fetchone()
    if fila is None:
        raise ProductoNoEncontrado(f"{categoria.value} {productoId}")
    return completarPortatil(fila) if categoria == Categoria.portatil else dict(fila)


def datosVerificablesDe(conexion, categoria: Categoria, productoId: int) -> dict[str, dict]:
    """Datos verificables indexados por campo. En portátiles, los del modelo llevan el prefijo "modelo."."""
    if categoria == Categoria.portatil:
        modeloId = obtenerProducto(conexion, categoria, productoId)["modeloId"]
        pares = [("modelo_portatil", modeloId, "modelo."), ("configuracion_portatil", productoId, "")]
    else:
        pares = [(categoria.value, productoId, "")]
    resultado = {}
    for categoriaDato, identificador, prefijo in pares:
        for fila in conexion.execute(
            "SELECT * FROM dato_verificable WHERE categoria = ? AND productoId = ?", (categoriaDato, identificador)
        ):
            resultado[prefijo + fila["campo"]] = dict(fila)
    return resultado


def verificarDato(conexion, datoId: int) -> dict:
    with conexion:
        conexion.execute("UPDATE dato_verificable SET estado = 'verificado' WHERE id = ?", (datoId,))
    fila = conexion.execute("SELECT * FROM dato_verificable WHERE id = ?", (datoId,)).fetchone()
    if fila is None:
        raise ProductoNoEncontrado(f"dato {datoId}")
    return dict(fila)


def buscarPorNombre(conexion, texto: str, limite: int = 20) -> list[dict]:
    """Búsqueda instantánea en la BD: por clave normalizada (contiene) y por tabla de alias."""
    clave = claveNormalizada(texto)
    if not clave:
        return []
    encontrados: dict[tuple[str, int], dict] = {}

    def agregar(categoria: str, productoId: int, nombre: str):
        encontrados.setdefault((categoria, productoId), {"categoria": categoria, "id": productoId, "nombre": nombre})

    for categoria in (Categoria.cpu, Categoria.gpu):
        for fila in conexion.execute(f"SELECT id, nombre FROM {categoria.value}"):
            if clave in claveNormalizada(fila["nombre"]):
                agregar(categoria.value, fila["id"], fila["nombre"])
    for fila in conexion.execute(
        "SELECT c.id, c.nombre, m.nombre AS modeloNombre FROM configuracion_portatil c "
        "JOIN modelo_portatil m ON m.id = c.modeloId"
    ):
        if clave in claveNormalizada(fila["nombre"]) or clave in claveNormalizada(fila["modeloNombre"]):
            agregar(Categoria.portatil.value, fila["id"], fila["nombre"])

    for fila in conexion.execute(
        "SELECT categoria, productoId FROM alias WHERE clave = ? AND categoria IN ('cpu', 'gpu')", (clave,)
    ):
        producto = conexion.execute(f"SELECT nombre FROM {fila['categoria']} WHERE id = ?", (fila["productoId"],)).fetchone()
        if producto:
            agregar(fila["categoria"], fila["productoId"], producto["nombre"])
    return list(encontrados.values())[:limite]


ESQUEMAS_FICHA = {
    Categoria.cpu: [EspecificacionesCpu],
    Categoria.gpu: [EspecificacionesGpu],
    Categoria.portatil: [EspecificacionesModeloPortatil, EspecificacionesConfiguracionPortatil],
}
