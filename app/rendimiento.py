"""Resúmenes de rendimiento con Claude sobre fuentes de la lista blanca (D-15, D-22, D-23).

Los recolectores de fuentes (Reddit API, YouTube Data API + transcripciones, webs de review)
implementan `RecolectorFuentes`. En esta primera versión no hay ninguno implementado todavía:
el trabajo "buscar fuentes nuevas" funciona de punta a punta, pero sin recolectores no encuentra nada.
"""

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from app.esquemas import Categoria
from app.llm import ClienteLlm, ErrorLlm, extraerJson


@dataclass
class FuenteTexto:
    nombreFuente: str      # debe coincidir con una entrada activa de la lista blanca
    tipo: str              # web, reddit, youtube
    identificador: str     # dominio, subreddit o canal
    url: str
    titulo: str
    texto: str             # artículo, hilo o transcripción
    fecha: str | None = None


class RecolectorFuentes(Protocol):
    def recolectar(self, categoria: Categoria, producto: dict) -> list[FuenteTexto]: ...


class ErrorResumen(Exception):
    pass


def listaBlancaActiva(conexion: sqlite3.Connection) -> list[dict]:
    return [dict(f) for f in conexion.execute("SELECT * FROM fuente_lista_blanca WHERE activa = 1 ORDER BY nombre")]


def _dominio(url: str) -> str:
    dominio = (urlparse(url).hostname or "").casefold()
    return dominio[4:] if dominio.startswith("www.") else dominio


def estaEnListaBlanca(fuente: FuenteTexto, listaBlanca: list[dict]) -> bool:
    for entrada in listaBlanca:
        if entrada["tipo"] != fuente.tipo:
            continue
        identificador = entrada["identificador"].casefold()
        if fuente.tipo == "web":
            dominio = _dominio(fuente.url)
            if dominio == identificador or dominio.endswith("." + identificador):
                return True
        elif fuente.identificador.casefold() == identificador:
            return True
    return False


SISTEMA_RESUMEN = """Resumes el rendimiento de un componente o equipo informático a partir de fuentes reconocidas.
Reglas:
- Escribe en español, aunque las fuentes estén en inglés.
- Usa SOLO lo que dicen las fuentes. No inventes cifras.
- Cita cada afirmación con el número de la fuente entre corchetes, p. ej. [1] o [2][3].
- Si las fuentes se contradicen, dilo.
- Responde solo con JSON: {"texto": "<resumen con citas>"}"""


@dataclass
class ResumenGenerado:
    texto: str
    citas: list[dict]   # [{"numero", "nombreFuente", "url", "titulo"}]


def generarResumen(clienteLlm: ClienteLlm, nombreProducto: str, fuentes: list[FuenteTexto],
                   limitePorFuente: int = 15_000) -> ResumenGenerado:
    if not fuentes:
        raise ErrorResumen("No hay fuentes para resumir")
    bloques = [f"Producto: {nombreProducto}"]
    for numero, fuente in enumerate(fuentes, start=1):
        bloques.append(f"[{numero}] {fuente.nombreFuente} — {fuente.titulo} ({fuente.url})\n{fuente.texto[:limitePorFuente]}")
    try:
        respuesta = extraerJson(clienteLlm.completar(SISTEMA_RESUMEN, "\n\n".join(bloques), maxTokens=2000))
    except ErrorLlm as error:
        raise ErrorResumen(str(error)) from error
    texto = str(respuesta.get("texto") or "").strip()
    if not texto:
        raise ErrorResumen("Resumen vacío")

    citadas = sorted({int(n) for n in re.findall(r"\[(\d+)\]", texto)})
    if not citadas:
        raise ErrorResumen("El resumen no cita ninguna fuente")
    inexistentes = [n for n in citadas if not 1 <= n <= len(fuentes)]
    if inexistentes:
        raise ErrorResumen(f"El resumen cita fuentes que no existen: {inexistentes}")
    citas = [
        {"numero": n, "nombreFuente": fuentes[n - 1].nombreFuente, "url": fuentes[n - 1].url, "titulo": fuentes[n - 1].titulo}
        for n in citadas
    ]
    return ResumenGenerado(texto, citas)


def guardarResumen(conexion, categoriaDato: str, productoId: int, resumen: ResumenGenerado) -> int:
    with conexion:
        cursor = conexion.execute(
            "INSERT INTO resumen_rendimiento (categoria, productoId, texto, citas) VALUES (?, ?, ?, ?)",
            (categoriaDato, productoId, resumen.texto, json.dumps(resumen.citas, ensure_ascii=False)),
        )
    return cursor.lastrowid


def resumenesDe(conexion, categoriaDato: str, productoId: int) -> list[dict]:
    filas = conexion.execute(
        "SELECT * FROM resumen_rendimiento WHERE categoria = ? AND productoId = ? ORDER BY id DESC",
        (categoriaDato, productoId),
    )
    return [{**dict(f), "citas": json.loads(f["citas"])} for f in filas]


def verificarResumen(conexion, resumenId: int) -> None:
    with conexion:
        conexion.execute("UPDATE resumen_rendimiento SET estado = 'verificado' WHERE id = ?", (resumenId,))
