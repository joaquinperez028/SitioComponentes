"""Configuración leída de variables de entorno y de .env (D-32)."""

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - python-dotenv está en requirements
    load_dotenv = None


@dataclass(frozen=True)
class Configuracion:
    rutaBd: Path
    claveApiAnthropic: str
    modeloClaude: str
    umbralConfianzaAlias: float


def cargarConfiguracion() -> Configuracion:
    if load_dotenv is not None:
        load_dotenv()
    return Configuracion(
        rutaBd=Path(os.getenv("RUTA_BD", "datos/componentes.sqlite3")),
        claveApiAnthropic=os.getenv("ANTHROPIC_API_KEY", ""),
        modeloClaude=os.getenv("CLAUDE_MODELO", "claude-sonnet-5-5"),
        umbralConfianzaAlias=float(os.getenv("UMBRAL_CONFIANZA_ALIAS", "0.85")),
    )
