"""Casos de uso: búsqueda, importación en segundo plano y búsqueda de fuentes nuevas (D-17, D-18)."""

from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlparse

from app.benchmarks import categoriaDatoBenchmark
from app.esquemas import Categoria
from app.extraccion.descarga import Descargador
from app.extraccion.extractor import ExtractorEspecificaciones
from app.llm import ClienteLlm
from app.normalizacion import Normalizador
from app.rendimiento import (
    RecolectorFuentes,
    estaEnListaBlanca,
    generarResumen,
    guardarResumen,
    listaBlancaActiva,
)
from app.repositorios import buscarPorNombre, guardarResultado, obtenerProducto
from app.trabajos import ColaTrabajos

TIPO_IMPORTAR = "importar_producto"
TIPO_FUENTES_NUEVAS = "buscar_fuentes_nuevas"


class SolicitudInvalida(ValueError):
    pass


@dataclass
class Dependencias:
    """Lo que necesitan los trabajos. Se crea perezosamente para no exigir API key en las pruebas."""

    obtenerClienteLlm: Callable[[], ClienteLlm]
    descargador: Descargador
    umbralConfianzaAlias: float = 0.85
    recolectores: list[RecolectorFuentes] = field(default_factory=list)


def crearManejadores(dependencias: Dependencias) -> dict:
    def importarProducto(parametros: dict, conexion) -> dict:
        categoria = Categoria(parametros["categoria"])
        url = parametros["url"]
        clienteLlm: ClienteLlm = dependencias.obtenerClienteLlm()
        html = dependencias.descargador.descargar(url)
        resultado = ExtractorEspecificaciones(clienteLlm).extraer(html, url, categoria, parametros.get("nombre"))
        normalizador = Normalizador(conexion, clienteLlm, dependencias.umbralConfianzaAlias)
        productoIds = guardarResultado(conexion, categoria, resultado, normalizador)
        sinCita = [d.ruta for d in resultado.datos if not d.fragmentoEncontrado]
        mensaje = f"Importado: {len(productoIds)} producto(s)."
        if sinCita:
            mensaje += f" {len(sinCita)} dato(s) con fragmento no encontrado en la página: revisar."
        return {"categoria": categoria.value, "productoIds": productoIds, "datosSinCita": sinCita, "mensaje": mensaje}

    def buscarFuentesNuevas(parametros: dict, conexion) -> dict:
        categoria = Categoria(parametros["categoria"])
        productoId = int(parametros["productoId"])
        producto = obtenerProducto(conexion, categoria, productoId)
        listaBlanca = listaBlancaActiva(conexion)

        fuentes = []
        for recolector in dependencias.recolectores:
            fuentes += recolector.recolectar(categoria, producto)
        descartadas = [f.url for f in fuentes if not estaEnListaBlanca(f, listaBlanca)]
        fuentes = [f for f in fuentes if estaEnListaBlanca(f, listaBlanca)]

        resultado = {"categoria": categoria.value, "productoId": productoId,
                     "fuentesUsadas": len(fuentes), "fuentesDescartadas": descartadas}
        if not dependencias.recolectores:
            resultado["mensaje"] = "Todavía no hay recolectores de reviews configurados (Reddit, YouTube, webs)."
            return resultado
        if not fuentes:
            resultado["mensaje"] = "No se encontraron fuentes nuevas de la lista blanca."
            return resultado
        resumen = generarResumen(dependencias.obtenerClienteLlm(), producto["nombre"], fuentes)
        resultado["resumenId"] = guardarResumen(conexion, categoriaDatoBenchmark(categoria), productoId, resumen)
        resultado["mensaje"] = f"Resumen generado con {len(fuentes)} fuente(s). Pendiente de revisión."
        return resultado

    return {TIPO_IMPORTAR: importarProducto, TIPO_FUENTES_NUEVAS: buscarFuentesNuevas}


def buscar(conexion, texto: str) -> list[dict]:
    """Si el producto está en la BD se devuelve al instante (D-18.1)."""
    return buscarPorNombre(conexion, texto.strip())


def validarUrl(url: str) -> str:
    url = (url or "").strip()
    partes = urlparse(url)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        raise SolicitudInvalida("La URL de la ficha oficial debe empezar por http:// o https://")
    return url


def solicitarImportacion(cola: ColaTrabajos, nombre: str, categoria: str, url: str) -> int:
    """Lanza la importación en segundo plano (D-18.2). Si ya hay una igual en marcha, devuelve esa."""
    try:
        categoriaValida = Categoria(categoria)
    except ValueError as error:
        raise SolicitudInvalida(f"Categoría desconocida: {categoria}") from error
    parametros = {"nombre": nombre.strip(), "categoria": categoriaValida.value, "url": validarUrl(url)}
    existente = cola.buscarActivo(TIPO_IMPORTAR, parametros)
    return existente["id"] if existente else cola.encolar(TIPO_IMPORTAR, parametros)


def solicitarFuentesNuevas(cola: ColaTrabajos, conexion, categoria: Categoria, productoId: int) -> int:
    """Botón "buscar fuentes nuevas": re-scrapea solo las reviews (D-18.3)."""
    obtenerProducto(conexion, categoria, productoId)  # lanza ProductoNoEncontrado si no existe
    parametros = {"categoria": categoria.value, "productoId": productoId}
    existente = cola.buscarActivo(TIPO_FUENTES_NUEVAS, parametros)
    return existente["id"] if existente else cola.encolar(TIPO_FUENTES_NUEVAS, parametros)
