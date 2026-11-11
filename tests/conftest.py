import json
from pathlib import Path

import pytest

from app.db import abrirConexion, migrar

DIRECTORIO_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def conexion(tmp_path):
    conexionBd = abrirConexion(tmp_path / "prueba.sqlite3")
    migrar(conexionBd)
    yield conexionBd
    conexionBd.close()


@pytest.fixture
def rutaBd(tmp_path):
    ruta = tmp_path / "prueba.sqlite3"
    conexionBd = abrirConexion(ruta)
    migrar(conexionBd)
    conexionBd.close()
    return ruta


def leerFixtureHtml(nombre: str) -> str:
    return (DIRECTORIO_FIXTURES / "html" / nombre).read_text(encoding="utf-8")


def leerRespuestaClaude(nombre: str) -> str:
    """Respuesta de Claude guardada (texto tal cual, puede incluir ```json)."""
    return (DIRECTORIO_FIXTURES / "respuestas_claude" / nombre).read_text(encoding="utf-8")


class ClienteLlmFalso:
    """Doble de la API de Claude: devuelve respuestas predefinidas y registra las llamadas."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []

    def completar(self, sistema, mensaje, maxTokens=4096):
        self.llamadas.append({"sistema": sistema, "mensaje": mensaje})
        if not self.respuestas:
            raise AssertionError("ClienteLlmFalso sin más respuestas")
        respuesta = self.respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta if isinstance(respuesta, str) else json.dumps(respuesta, ensure_ascii=False)


@pytest.fixture
def crearLlmFalso():
    return ClienteLlmFalso


FICHAS_CATALOGO = [
    ("i7", "intel_ark_core_i7_13700h.html", "cpu_core_i7_13700h.json", "cpu", "https://www.intel.com/ark/i7-13700h"),
    ("ryzen", "amd_ryzen_7_7800x3d.html", "cpu_ryzen_7_7800x3d.json", "cpu", "https://www.amd.com/7800x3d"),
    ("rtx4060l", "nvidia_rtx_4060_laptop.html", "gpu_rtx_4060_laptop.json", "gpu", "https://www.nvidia.com/rtx4060-laptop"),
    ("portatil", "portatil_ejemplo_psref.html", "portatil_ejemplo.json", "portatil", "https://psref.ejemplo/eg16"),
]


@pytest.fixture
def catalogo(conexion):
    """Importa las fichas de ejemplo por el camino real: HTML -> extractor -> BD. Devuelve los ids por clave."""
    from app.esquemas import Categoria
    from app.extraccion.extractor import ExtractorEspecificaciones
    from app.normalizacion import Normalizador
    from app.repositorios import guardarResultado

    normalizador = Normalizador(conexion)
    ids = {}
    for clave, html, respuesta, categoria, url in FICHAS_CATALOGO:
        extractor = ExtractorEspecificaciones(ClienteLlmFalso([leerRespuestaClaude(respuesta)]))
        resultado = extractor.extraer(leerFixtureHtml(html), url, Categoria(categoria))
        productoIds = guardarResultado(conexion, Categoria(categoria), resultado, normalizador)
        ids[clave] = productoIds[0] if len(productoIds) == 1 else productoIds
    return ids
