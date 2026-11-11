"""Acceso a la API de Claude (D-26) detrás de una interfaz mínima, para poder usar dobles en pruebas."""

import json
import re
from typing import Protocol


class ErrorLlm(Exception):
    pass


class ClienteLlm(Protocol):
    def completar(self, sistema: str, mensaje: str, maxTokens: int = 4096) -> str: ...


class ClienteClaude:
    """Implementación real con el SDK oficial de Anthropic (importado al usarse)."""

    def __init__(self, claveApi: str, modelo: str):
        if not claveApi:
            raise ErrorLlm("Falta ANTHROPIC_API_KEY en .env")
        import anthropic

        self._cliente = anthropic.Anthropic(api_key=claveApi)
        self._modelo = modelo

    def completar(self, sistema: str, mensaje: str, maxTokens: int = 4096) -> str:
        respuesta = self._cliente.messages.create(
            model=self._modelo,
            max_tokens=maxTokens,
            system=sistema,
            messages=[{"role": "user", "content": mensaje}],
        )
        return "".join(bloque.text for bloque in respuesta.content if getattr(bloque, "type", "") == "text")


def extraerJson(texto: str) -> dict:
    """Obtiene el primer objeto JSON de una respuesta, tolerando ```json ... ``` o texto alrededor."""
    bloque = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texto, re.DOTALL)
    candidato = bloque.group(1) if bloque else None
    if candidato is None:
        inicio, fin = texto.find("{"), texto.rfind("}")
        if inicio == -1 or fin <= inicio:
            raise ErrorLlm("La respuesta no contiene JSON")
        candidato = texto[inicio : fin + 1]
    try:
        resultado = json.loads(candidato)
    except json.JSONDecodeError as error:
        raise ErrorLlm(f"JSON inválido en la respuesta: {error}") from error
    if not isinstance(resultado, dict):
        raise ErrorLlm("Se esperaba un objeto JSON")
    return resultado
