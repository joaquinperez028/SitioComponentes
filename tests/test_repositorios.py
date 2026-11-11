import pytest

from app.db import migrar
from app.esquemas import Categoria
from app.repositorios import (
    ProductoNoEncontrado,
    buscarPorNombre,
    datosVerificablesDe,
    obtenerProducto,
    verificarDato,
)


def test_migrar_es_idempotente(conexion):
    assert migrar(conexion) == []
    tablas = {f[0] for f in conexion.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"cpu", "gpu", "modelo_portatil", "configuracion_portatil", "alias", "trabajo", "benchmark"} <= tablas


def test_lista_blanca_inicial(conexion):
    nombres = {f["nombre"] for f in conexion.execute("SELECT nombre FROM fuente_lista_blanca")}
    assert {"Notebookcheck", "TechPowerUp", "Gamers Nexus", "r/GamingLaptops"} <= nombres


def test_guarda_cpu_con_columnas_tipadas(conexion, catalogo):
    cpu = obtenerProducto(conexion, Categoria.cpu, catalogo["i7"])
    assert cpu["nucleos"] == 14 and isinstance(cpu["relojBoostGhz"], float)
    assert cpu["urlFuente"] == "https://www.intel.com/ark/i7-13700h"


def test_cada_spec_guarda_fuente_fragmento_y_estado(conexion, catalogo):
    datos = datosVerificablesDe(conexion, Categoria.cpu, catalogo["i7"])
    nucleos = datos["nucleos"]
    assert nucleos["valor"] == "14"
    assert nucleos["fragmento"] == "Total Cores: 14"
    assert nucleos["fragmentoEncontrado"] == 1
    assert nucleos["estado"] == "sin_verificar"
    assert nucleos["urlFuente"] == "https://www.intel.com/ark/i7-13700h"
    assert "fechaLanzamiento" in datos


def test_verificar_un_dato_con_un_clic(conexion, catalogo):
    dato = datosVerificablesDe(conexion, Categoria.cpu, catalogo["i7"])["tdpW"]
    assert verificarDato(conexion, dato["id"])["estado"] == "verificado"
    with pytest.raises(ProductoNoEncontrado):
        verificarDato(conexion, 99999)


def test_reimportar_actualiza_sin_duplicar_y_vuelve_a_sin_verificar(conexion, catalogo):
    from tests.conftest import FICHAS_CATALOGO, ClienteLlmFalso, leerFixtureHtml, leerRespuestaClaude
    from app.extraccion.extractor import ExtractorEspecificaciones
    from app.normalizacion import Normalizador
    from app.repositorios import guardarResultado

    dato = datosVerificablesDe(conexion, Categoria.cpu, catalogo["i7"])["nucleos"]
    verificarDato(conexion, dato["id"])
    _, html, respuesta, _, url = FICHAS_CATALOGO[0]
    resultado = ExtractorEspecificaciones(ClienteLlmFalso([leerRespuestaClaude(respuesta)])).extraer(
        leerFixtureHtml(html), url, Categoria.cpu
    )
    assert guardarResultado(conexion, Categoria.cpu, resultado, Normalizador(conexion)) == [catalogo["i7"]]
    assert conexion.execute("SELECT COUNT(*) FROM cpu").fetchone()[0] == 2
    assert datosVerificablesDe(conexion, Categoria.cpu, catalogo["i7"])["nucleos"]["estado"] == "sin_verificar"


def test_portatil_enlaza_cpu_y_gpu_del_catalogo(conexion, catalogo):
    idA, idB = catalogo["portatil"]
    configuracionA = obtenerProducto(conexion, Categoria.portatil, idA)
    assert configuracionA["cpuId"] == catalogo["i7"]
    assert configuracionA["gpuId"] == catalogo["rtx4060l"]
    assert configuracionA["gpuNombre"] == "GeForce RTX 4060 Laptop GPU"  # nombre canónico
    assert configuracionA["tgpW"] == 115  # TGP por configuración (D-10)
    assert configuracionA["pesoKg"] == 2.3  # dato heredado del modelo padre

    configuracionB = obtenerProducto(conexion, Categoria.portatil, idB)
    assert configuracionB["gpuId"] is None and configuracionB["tgpW"] is None
    assert configuracionA["modeloId"] == configuracionB["modeloId"]
    assert conexion.execute("SELECT COUNT(*) FROM modelo_portatil").fetchone()[0] == 1


def test_portatil_con_cpu_desconocida_conserva_el_nombre_original(conexion):
    from app.esquemas import EspecificacionesPortatil
    from app.extraccion.extractor import ResultadoExtraccion
    from app.normalizacion import Normalizador
    from app.repositorios import guardarPortatil

    especificaciones = EspecificacionesPortatil.model_validate({
        "modelo": {"nombre": "Otro 14", "fabricante": "Otro"},
        "configuraciones": [{"nombre": "Otro 14 A", "cpuNombre": "Snapdragon X Elite X1E-78-100"}],
    })
    _, [configuracionId] = guardarPortatil(conexion, ResultadoExtraccion(especificaciones, [], "u"), Normalizador(conexion))
    producto = obtenerProducto(conexion, Categoria.portatil, configuracionId)
    assert producto["cpuId"] is None and not producto["cpuEnlazada"]
    assert producto["cpuNombre"] == "Snapdragon X Elite X1E-78-100"


def test_datos_del_portatil_separan_modelo_y_configuracion(conexion, catalogo):
    datos = datosVerificablesDe(conexion, Categoria.portatil, catalogo["portatil"][0])
    assert datos["modelo.pesoKg"]["valor"] == "2.3"
    assert datos["modelo.nombre"]["valor"] == "Ejemplo Gaming 16 Gen 1"
    assert datos["nombre"]["valor"] == "Ejemplo Gaming 16 Gen 1 EG16-A"
    assert datos["tgpW"]["fragmento"] == "115W TGP"


def test_producto_inexistente(conexion):
    with pytest.raises(ProductoNoEncontrado):
        obtenerProducto(conexion, Categoria.gpu, 1)


@pytest.mark.parametrize(
    "consulta, esperado",
    [
        ("7800x3d", {("cpu", "Ryzen 7 7800X3D")}),
        ("Intel Core i7-13700H", {("cpu", "Core i7-13700H")}),
        ("RTX 4060 Mobile", {("gpu", "GeForce RTX 4060 Laptop GPU")}),
        ("Ejemplo Gaming 16", {("portatil", "Ejemplo Gaming 16 Gen 1 EG16-A"), ("portatil", "Ejemplo Gaming 16 Gen 1 EG16-B")}),
        ("RX 7900 XTX", set()),
        ("   ", set()),
    ],
)
def test_busqueda_por_nombre(conexion, catalogo, consulta, esperado):
    assert {(r["categoria"], r["nombre"]) for r in buscarPorNombre(conexion, consulta)} == esperado
