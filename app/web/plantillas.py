"""Entorno Jinja2 (D-30). Independiente de FastAPI para poder probar las plantillas directamente."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

DIRECTORIO_PLANTILLAS = Path(__file__).parent / "plantillas"

NOMBRES_CATEGORIA = {"cpu": "CPU", "gpu": "GPU", "portatil": "Portátiles"}
NOMBRES_PLATAFORMA = {"escritorio": "Escritorio", "movil": "Móvil"}


def formatearValor(valor) -> str:
    if valor is None:
        return "—"
    if isinstance(valor, float):
        return f"{valor:g}"
    return NOMBRES_PLATAFORMA.get(valor, str(valor)) if isinstance(valor, str) else str(valor)


def crearEntorno() -> Environment:
    entorno = Environment(
        loader=FileSystemLoader(DIRECTORIO_PLANTILLAS),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    entorno.filters["valor"] = formatearValor
    entorno.globals["nombresCategoria"] = NOMBRES_CATEGORIA
    entorno.globals["nombresPlataforma"] = NOMBRES_PLATAFORMA
    return entorno
