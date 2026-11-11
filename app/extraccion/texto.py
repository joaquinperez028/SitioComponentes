"""Conversión de HTML de fabricante a texto plano para enviar a Claude y para comprobar fragmentos."""

import re

from bs4 import BeautifulSoup

ETIQUETAS_DESCARTADAS = ("script", "style", "noscript", "svg", "nav", "footer", "iframe", "template", "form")


def htmlATexto(html: str, limiteCaracteres: int = 60_000) -> str:
    sopa = BeautifulSoup(html, "lxml")
    for etiqueta in sopa(ETIQUETAS_DESCARTADAS):
        etiqueta.decompose()
    # En tablas de specs, "etiqueta: valor" en una sola línea ayuda a Claude
    for fila in sopa.find_all("tr"):
        celdas = [c.get_text(" ", strip=True) for c in fila.find_all(["th", "td"])]
        celdas = [c for c in celdas if c]
        fila.replace_with(sopa.new_string("\n" + ": ".join(celdas) + "\n"))
    lineas = []
    for linea in sopa.get_text("\n").splitlines():
        linea = re.sub(r"\s+", " ", linea).strip()
        if linea and (not lineas or lineas[-1] != linea):
            lineas.append(linea)
    return "\n".join(lineas)[:limiteCaracteres]


def normalizarParaBusqueda(texto: str) -> str:
    texto = texto.replace(" ", " ").casefold()
    texto = re.sub(r"\s*:\s*", ": ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def fragmentoEnTexto(fragmento: str | None, texto: str) -> bool:
    """True si el fragmento citado por Claude aparece literalmente (salvo espacios y mayúsculas) en la página."""
    if not fragmento or not fragmento.strip():
        return False
    return normalizarParaBusqueda(fragmento) in normalizarParaBusqueda(texto)
