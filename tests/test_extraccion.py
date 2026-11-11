import json

import pytest

from app.esquemas import Categoria, EspecificacionesCpu, EspecificacionesGpu, EspecificacionesPortatil
from app.extraccion.extractor import ErrorExtraccion, ExtractorEspecificaciones
from app.extraccion.texto import fragmentoEnTexto, htmlATexto
from tests.conftest import ClienteLlmFalso, leerFixtureHtml, leerRespuestaClaude


class TestHtmlATexto:
    def test_descarta_scripts_estilos_nav_y_footer(self):
        texto = htmlATexto(leerFixtureHtml("intel_ark_core_i7_13700h.html"))
        assert "Total Cores 999" not in texto  # dentro de <script>
        assert "Total Cores 1" not in texto  # dentro de <footer>
        assert "font-weight" not in texto
        assert "Products > Processors" not in texto

    def test_filas_de_tabla_quedan_como_etiqueta_valor(self):
        texto = htmlATexto(leerFixtureHtml("intel_ark_core_i7_13700h.html"))
        assert "Total Cores: 14" in texto.splitlines()
        assert "Processor Base Power: 45 W" in texto.splitlines()

    def test_respeta_el_limite_de_caracteres(self):
        assert len(htmlATexto("<p>" + "x " * 50_000 + "</p>", limiteCaracteres=1000)) == 1000


class TestFragmentoEnTexto:
    def test_ignora_mayusculas_y_espacios(self):
        assert fragmentoEnTexto("total   CORES:14", "Total Cores: 14\nTotal Threads: 20")

    def test_lista_dt_dd_en_lineas_separadas(self):
        texto = htmlATexto(leerFixtureHtml("amd_ryzen_7_7800x3d.html"))
        assert fragmentoEnTexto("# of CPU Cores 8", texto)

    def test_fragmento_inventado_o_vacio(self):
        assert not fragmentoEnTexto("Total Cores: 16", "Total Cores: 14")
        assert not fragmentoEnTexto("", "algo")
        assert not fragmentoEnTexto(None, "algo")


@pytest.mark.parametrize(
    "fixtureHtml, fixtureRespuesta, categoria, esquema, esperado",
    [
        ("intel_ark_core_i7_13700h.html", "cpu_core_i7_13700h.json", Categoria.cpu, EspecificacionesCpu,
         {"nucleos": 14, "hilos": 20, "relojBoostGhz": 5.0, "tdpW": 45, "plataforma": "movil"}),
        ("amd_ryzen_7_7800x3d.html", "cpu_ryzen_7_7800x3d.json", Categoria.cpu, EspecificacionesCpu,
         {"nucleos": 8, "cacheL3Mb": 96, "socket": "AM5", "plataforma": "escritorio"}),
        ("nvidia_rtx_4060_laptop.html", "gpu_rtx_4060_laptop.json", Categoria.gpu, EspecificacionesGpu,
         {"vramGb": 8, "anchoBusBits": 128, "tdpW": 115, "fechaLanzamiento": None}),
    ],
)
def test_extrae_specs_de_fichas_de_fabricante(fixtureHtml, fixtureRespuesta, categoria, esquema, esperado):
    llm = ClienteLlmFalso([leerRespuestaClaude(fixtureRespuesta)])
    resultado = ExtractorEspecificaciones(llm).extraer(leerFixtureHtml(fixtureHtml), "https://ejemplo/ficha", categoria)

    assert isinstance(resultado.especificaciones, esquema)
    for campo, valor in esperado.items():
        assert getattr(resultado.especificaciones, campo) == valor
    # Todos los fragmentos citados en las respuestas guardadas existen en la página
    noEncontrados = [d.ruta for d in resultado.datos if not d.fragmentoEncontrado]
    assert noEncontrados == []
    # Los campos nulos no generan datos verificables
    assert all(d.valor is not None for d in resultado.datos)


def test_el_mensaje_a_claude_incluye_texto_limpio_y_esquema():
    llm = ClienteLlmFalso([leerRespuestaClaude("cpu_core_i7_13700h.json")])
    ExtractorEspecificaciones(llm).extraer(
        leerFixtureHtml("intel_ark_core_i7_13700h.html"), "u", Categoria.cpu, "i7-13700H"
    )
    mensaje = llm.llamadas[0]["mensaje"]
    assert "Total Cores: 14" in mensaje
    assert "relojBoostGhz" in mensaje and "Boost Clock (GHz)" in mensaje
    assert "Producto buscado: i7-13700H" in mensaje
    assert "dataLayer" not in mensaje


def test_extrae_portatil_con_varias_configuraciones():
    llm = ClienteLlmFalso([leerRespuestaClaude("portatil_ejemplo.json")])
    resultado = ExtractorEspecificaciones(llm).extraer(
        leerFixtureHtml("portatil_ejemplo_psref.html"), "u", Categoria.portatil
    )
    especificaciones = resultado.especificaciones
    assert isinstance(especificaciones, EspecificacionesPortatil)
    assert especificaciones.modelo.pesoKg == 2.3
    assert [c.tgpW for c in especificaciones.configuraciones] == [115, None]
    assert especificaciones.configuraciones[1].gpuNombre is None
    assert set(resultado.datosDe("modelo")) >= {"pesoKg", "pantallaPulgadas"}
    assert resultado.datosDe("configuraciones.0")["tgpW"].fragmentoEncontrado
    assert "tgpW" not in resultado.datosDe("configuraciones.1")


def test_marca_fragmentos_que_no_estan_en_la_pagina():
    respuesta = json.loads(leerRespuestaClaude("cpu_core_i7_13700h.json"))
    respuesta["nucleos"] = {"valor": 16, "fragmento": "Total Cores: 16"}  # Claude se equivoca
    llm = ClienteLlmFalso([respuesta])
    resultado = ExtractorEspecificaciones(llm).extraer(
        leerFixtureHtml("intel_ark_core_i7_13700h.html"), "u", Categoria.cpu
    )
    dato = resultado.datosDe("")["nucleos"]
    assert dato.valor == 16 and not dato.fragmentoEncontrado


def test_valores_fuera_de_rango_se_rechazan():
    respuesta = json.loads(leerRespuestaClaude("cpu_core_i7_13700h.json"))
    respuesta["relojBoostGhz"] = {"valor": 5000, "fragmento": "Max Turbo Frequency: 5 GHz"}  # MHz por GHz
    with pytest.raises(ErrorExtraccion, match="esquema"):
        ExtractorEspecificaciones(ClienteLlmFalso([respuesta])).extraer(
            leerFixtureHtml("intel_ark_core_i7_13700h.html"), "u", Categoria.cpu
        )


def test_plataforma_desconocida_se_rechaza():
    respuesta = json.loads(leerRespuestaClaude("cpu_core_i7_13700h.json"))
    respuesta["plataforma"] = {"valor": "servidor", "fragmento": "Vertical Segment: Mobile"}
    with pytest.raises(ErrorExtraccion):
        ExtractorEspecificaciones(ClienteLlmFalso([respuesta])).extraer(
            leerFixtureHtml("intel_ark_core_i7_13700h.html"), "u", Categoria.cpu
        )


def test_respuesta_sin_json_da_error_de_extraccion():
    with pytest.raises(ErrorExtraccion):
        ExtractorEspecificaciones(ClienteLlmFalso(["Lo siento, no puedo"])).extraer(
            leerFixtureHtml("intel_ark_core_i7_13700h.html"), "u", Categoria.cpu
        )


def test_pagina_vacia_no_llama_a_claude():
    llm = ClienteLlmFalso([])
    with pytest.raises(ErrorExtraccion):
        ExtractorEspecificaciones(llm).extraer("<html><script>x</script></html>", "u", Categoria.cpu)
    assert llm.llamadas == []
