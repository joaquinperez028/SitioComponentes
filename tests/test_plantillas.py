"""Renderiza las plantillas con datos reales de la BD de pruebas, sin servidor (solo Jinja2)."""

import pytest

from app.benchmarks import agregarBenchmark, benchmarksDe
from app.comparador import compararProductos, filasDeFicha
from app.esquemas import Categoria
from app.filtros import FILTROS_POR_CATEGORIA, fabricantesDisponibles, filtrar
from app.repositorios import datosVerificablesDe, obtenerProducto
from app.web.plantillas import crearEntorno, formatearValor
from tests.test_comparador import bench


@pytest.fixture
def entorno():
    return crearEntorno()


@pytest.mark.parametrize("valor, esperado", [(None, "—"), (2.0, "2"), (2.3, "2.3"), (14, "14"), ("movil", "Móvil"), ("AM5", "AM5")])
def test_formatear_valor(valor, esperado):
    assert formatearValor(valor) == esperado


def test_ficha_marca_lo_no_verificado_y_la_cita(entorno, conexion, catalogo):
    producto = obtenerProducto(conexion, Categoria.cpu, catalogo["i7"])
    datos = datosVerificablesDe(conexion, Categoria.cpu, catalogo["i7"])
    html = entorno.get_template("producto.html").render(
        categoria=Categoria.cpu, producto=producto, filas=filasDeFicha(Categoria.cpu, producto, datos),
        benchmarks=[], resumenes=[],
    )
    assert "<h1>Core i7-13700H</h1>" in html
    assert "Cores" in html and "Boost Clock (GHz)" in html  # etiquetas en inglés (D-11)
    assert "sin verificar" in html
    assert f'hx-post="/datos/{datos["nucleos"]["id"]}/verificar"' in html
    assert "Total Cores: 14" in html  # fragmento de origen visible
    assert "Buscar fuentes nuevas" in html
    assert "cita no encontrada" not in html


def test_ficha_de_portatil_enlaza_cpu_y_gpu(entorno, conexion, catalogo):
    idA = catalogo["portatil"][0]
    producto = obtenerProducto(conexion, Categoria.portatil, idA)
    datos = datosVerificablesDe(conexion, Categoria.portatil, idA)
    agregarBenchmark(conexion, Categoria.portatil, idA, bench())
    html = entorno.get_template("producto.html").render(
        categoria=Categoria.portatil, producto=producto, filas=filasDeFicha(Categoria.portatil, producto, datos),
        benchmarks=benchmarksDe(conexion, Categoria.portatil, idA), resumenes=[],
    )
    assert f'href="/producto/cpu/{catalogo["i7"]}"' in html
    assert f'href="/producto/gpu/{catalogo["rtx4060l"]}"' in html
    assert "GPU TGP (W)" in html and "Weight (kg)" in html
    assert "Cyberpunk 2077" in html and "60 fps" in html


def test_comparacion_destaca_el_mejor(entorno, conexion, catalogo):
    comparacion = compararProductos(conexion, Categoria.cpu, [catalogo["i7"], catalogo["ryzen"]])
    html = entorno.get_template("comparar.html").render(comparacion=comparacion, categoria=Categoria.cpu)
    assert html.count('class="mejor"') == 4  # Cores, Threads, Base Clock y L3 Cache (Boost empata)
    assert "No hay benchmarks comparables" in html


def test_catalogo_con_filtros(entorno, conexion, catalogo):
    parametros = {"plataforma": "movil"}
    html = entorno.get_template("catalogo.html").render(
        categoria=Categoria.cpu, productos=filtrar(conexion, Categoria.cpu, parametros),
        filtros=FILTROS_POR_CATEGORIA[Categoria.cpu].model_validate(parametros),
        fabricantes=fabricantesDisponibles(conexion, Categoria.cpu),
    )
    assert "Core i7-13700H" in html and "Ryzen 7 7800X3D" not in html
    assert '<option value="movil" selected>' in html
    assert 'name="ids"' in html


def test_busqueda_sin_resultados_ofrece_importar(entorno):
    html = entorno.get_template("_resultados.html").render(
        consulta="RX 7900 XTX", resultados=[], categorias=list(Categoria), nombresCategoria={"cpu": "CPU", "gpu": "GPU", "portatil": "Portátiles"},
    )
    assert 'hx-post="/trabajos/importar"' in html
    assert 'value="RX 7900 XTX"' in html


@pytest.mark.parametrize("estado, sondea", [("pendiente", True), ("en_curso", True), ("completado", False), ("error", False)])
def test_estado_de_trabajo_sondea_solo_mientras_esta_activo(entorno, estado, sondea):
    trabajo = {"id": 7, "estado": estado, "mensaje": None,
               "resultado": {"categoria": "cpu", "productoIds": [3]} if estado == "completado" else None}
    html = entorno.get_template("_estado_trabajo.html").render(trabajo=trabajo)
    assert ('hx-trigger="every 2s"' in html) == sondea
    if estado == "completado":
        assert 'href="/producto/cpu/3"' in html


def test_las_plantillas_escapan_html(entorno):
    html = entorno.get_template("_error.html").render(mensaje="<script>alert(1)</script>")
    assert "<script>" not in html
