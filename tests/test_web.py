"""Pruebas HTTP de la app FastAPI. Requieren fastapi y httpx (requirements.txt)."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Configuracion  # noqa: E402
from app.servicios import Dependencias  # noqa: E402
from app.web.principal import crearApp  # noqa: E402
from tests.conftest import ClienteLlmFalso, leerRespuestaClaude  # noqa: E402
from tests.test_servicios import URL_RYZEN, DescargadorFixtures  # noqa: E402


@pytest.fixture
def cliente(tmp_path):
    llm = ClienteLlmFalso([leerRespuestaClaude("cpu_ryzen_7_7800x3d.json"), leerRespuestaClaude("cpu_core_i7_13700h.json")])
    descargador = DescargadorFixtures({
        URL_RYZEN: "amd_ryzen_7_7800x3d.html",
        "https://www.intel.com/ark/i7-13700h": "intel_ark_core_i7_13700h.html",
    })
    configuracion = Configuracion(tmp_path / "web.sqlite3", "", "modelo-falso", 0.85)
    app = crearApp(configuracion, Dependencias(lambda: llm, descargador), iniciarCola=False)
    with TestClient(app) as clienteHttp:
        clienteHttp.cola = app.state.cola
        yield clienteHttp


def importar(cliente, nombre, url):
    respuesta = cliente.post("/trabajos/importar", data={"nombre": nombre, "categoria": "cpu", "url": url})
    assert respuesta.status_code == 200
    cliente.cola.procesarPendientes()
    return respuesta


def test_inicio(cliente):
    respuesta = cliente.get("/")
    assert respuesta.status_code == 200 and "htmx" in respuesta.text


def test_busqueda_importacion_y_ficha(cliente):
    sinResultados = cliente.get("/buscar", params={"q": "7800X3D"}, headers={"HX-Request": "true"})
    assert "/trabajos/importar" in sinResultados.text and "<html" not in sinResultados.text

    respuesta = importar(cliente, "Ryzen 7 7800X3D", URL_RYZEN)
    assert 'hx-trigger="every 2s"' in respuesta.text  # sondeo mientras está en cola

    estado = cliente.get("/trabajos/1")
    assert "Completado" in estado.text and 'href="/producto/cpu/1"' in estado.text

    resultados = cliente.get("/buscar", params={"q": "7800X3D"})
    assert 'href="/producto/cpu/1"' in resultados.text

    ficha = cliente.get("/producto/cpu/1")
    assert ficha.status_code == 200 and "L3 Cache (MB)" in ficha.text and "sin verificar" in ficha.text


def test_importacion_con_url_invalida(cliente):
    respuesta = cliente.post("/trabajos/importar", data={"nombre": "x", "categoria": "cpu", "url": "nada"},
                             headers={"HX-Request": "true"})
    assert respuesta.status_code == 400 and "http" in respuesta.text


def test_verificar_dato(cliente):
    importar(cliente, "7800X3D", URL_RYZEN)
    respuesta = cliente.post("/datos/1/verificar", headers={"HX-Request": "true"})
    assert respuesta.status_code == 200 and "✓ verificado" in respuesta.text


def test_catalogo_filtros_y_comparador(cliente):
    importar(cliente, "7800X3D", URL_RYZEN)
    importar(cliente, "i7-13700H", "https://www.intel.com/ark/i7-13700h")

    catalogo = cliente.get("/catalogo/cpu", params={"plataforma": "escritorio", "nucleosMin": ""})
    assert "Ryzen 7 7800X3D" in catalogo.text and "Core i7-13700H" not in catalogo.text
    assert cliente.get("/catalogo/cpu", params={"nucleosMin": "muchos"}).status_code == 400

    comparacion = cliente.get("/comparar/cpu", params=[("ids", 1), ("ids", 2)])
    assert comparacion.status_code == 200 and 'class="mejor"' in comparacion.text
    assert cliente.get("/comparar/cpu", params={"ids": 1}).status_code == 400


def test_fuentes_nuevas_y_producto_inexistente(cliente):
    importar(cliente, "7800X3D", URL_RYZEN)
    respuesta = cliente.post("/producto/cpu/1/fuentes-nuevas")
    assert respuesta.status_code == 200 and "Trabajo #" in respuesta.text
    assert cliente.get("/producto/gpu/99").status_code == 404
    assert cliente.get("/catalogo/ram").status_code == 422  # categoría fuera de la fase 1


def test_alias_pendientes(cliente):
    assert "No hay alias pendientes" in cliente.get("/alias-pendientes").text
