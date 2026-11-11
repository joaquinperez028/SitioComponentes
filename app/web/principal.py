"""Aplicación FastAPI: HTML renderizado con Jinja2 + HTMX, sin build (D-30).

Arranque:  uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.benchmarks import benchmarksDe, categoriaDatoBenchmark, verificarBenchmark
from app.comparador import ErrorComparacion, compararProductos, filasDeFicha
from app.config import Configuracion, cargarConfiguracion
from app.db import abrirConexion, migrar
from app.esquemas import Categoria
from app.extraccion.descarga import DescargadorPlaywright
from app.filtros import FILTROS_POR_CATEGORIA, fabricantesDisponibles, filtrar
from app.llm import ClienteClaude
from app.normalizacion import Normalizador
from app.rendimiento import resumenesDe, verificarResumen
from app.repositorios import ProductoNoEncontrado, datosVerificablesDe, obtenerProducto, verificarDato
from app.servicios import (
    Dependencias,
    SolicitudInvalida,
    buscar,
    crearManejadores,
    solicitarFuentesNuevas,
    solicitarImportacion,
)
from app.trabajos import ColaTrabajos
from app.web.plantillas import crearEntorno

DIRECTORIO_ESTATICOS = Path(__file__).parent / "estaticos"


def dependenciasPorDefecto(configuracion: Configuracion) -> Dependencias:
    clientes = {}

    def obtenerClienteLlm():
        # Se crea al primer uso: la app arranca y muestra lo guardado aunque falte la API key
        if "claude" not in clientes:
            clientes["claude"] = ClienteClaude(configuracion.claveApiAnthropic, configuracion.modeloClaude)
        return clientes["claude"]

    return Dependencias(obtenerClienteLlm, DescargadorPlaywright(), configuracion.umbralConfianzaAlias)


def crearApp(
    configuracion: Configuracion | None = None,
    dependencias: Dependencias | None = None,
    iniciarCola: bool = True,
) -> FastAPI:
    configuracion = configuracion or cargarConfiguracion()
    dependencias = dependencias or dependenciasPorDefecto(configuracion)
    rutaBd = configuracion.rutaBd

    conexionInicial = abrirConexion(rutaBd)
    migrar(conexionInicial)
    conexionInicial.close()

    cola = ColaTrabajos(rutaBd, crearManejadores(dependencias))

    @asynccontextmanager
    async def cicloDeVida(_app: FastAPI):
        if iniciarCola:
            cola.iniciar()  # retoma los trabajos pendientes (D-31)
        yield
        cola.detener()

    app = FastAPI(title="SitioComponentes", lifespan=cicloDeVida)
    app.state.cola = cola
    app.state.configuracion = configuracion
    app.mount("/estaticos", StaticFiles(directory=DIRECTORIO_ESTATICOS), name="estaticos")
    plantillas = Jinja2Templates(env=crearEntorno())

    def obtenerConexion():
        conexion = abrirConexion(rutaBd)
        try:
            yield conexion
        finally:
            conexion.close()

    def esHtmx(request: Request) -> bool:
        return request.headers.get("HX-Request") == "true"

    def responder(request: Request, plantilla: str, contexto: dict | None = None, estado: int = 200):
        return plantillas.TemplateResponse(request, plantilla, contexto or {}, status_code=estado)

    def paginaError(request: Request, mensaje: str, estado: int):
        plantilla = "_error.html" if esHtmx(request) else "error.html"
        return responder(request, plantilla, {"mensaje": mensaje}, estado)

    @app.exception_handler(ProductoNoEncontrado)
    async def productoNoEncontrado(request: Request, error: ProductoNoEncontrado):
        return paginaError(request, f"No existe: {error}", 404)

    # --- Inicio y búsqueda --------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def inicio(request: Request, conexion=Depends(obtenerConexion)):
        pendientes = conexion.execute("SELECT COUNT(*) FROM alias_pendiente WHERE estado = 'pendiente'").fetchone()[0]
        return responder(request, "inicio.html", {"aliasPendientes": pendientes})

    @app.get("/buscar", response_class=HTMLResponse)
    def buscarProducto(request: Request, q: str = "", conexion=Depends(obtenerConexion)):
        contexto = {"consulta": q, "resultados": buscar(conexion, q) if q.strip() else [], "categorias": list(Categoria)}
        return responder(request, "_resultados.html" if esHtmx(request) else "busqueda.html", contexto)

    # --- Trabajos -----------------------------------------------------------------------------

    @app.post("/trabajos/importar", response_class=HTMLResponse)
    def importar(request: Request, nombre: str = Form(""), categoria: str = Form(...), url: str = Form("")):
        try:
            trabajoId = solicitarImportacion(cola, nombre, categoria, url)
        except SolicitudInvalida as error:
            return paginaError(request, str(error), 400)
        return responder(request, "_estado_trabajo.html", {"trabajo": cola.obtener(trabajoId)})

    @app.get("/trabajos/{trabajoId}", response_class=HTMLResponse)
    def estadoTrabajo(request: Request, trabajoId: int):
        trabajo = cola.obtener(trabajoId)
        if trabajo is None:
            return paginaError(request, f"No existe el trabajo {trabajoId}", 404)
        return responder(request, "_estado_trabajo.html", {"trabajo": trabajo})

    # --- Catálogo con filtros -----------------------------------------------------------------

    @app.get("/catalogo/{categoria}", response_class=HTMLResponse)
    def catalogo(request: Request, categoria: Categoria, conexion=Depends(obtenerConexion)):
        parametros = dict(request.query_params)
        try:
            productos = filtrar(conexion, categoria, parametros)
        except ValidationError:
            return paginaError(request, "Algún filtro tiene un valor no válido", 400)
        contexto = {
            "categoria": categoria,
            "productos": productos,
            "filtros": FILTROS_POR_CATEGORIA[categoria].model_validate(parametros),
            "fabricantes": fabricantesDisponibles(conexion, categoria),
        }
        return responder(request, "_tabla_catalogo.html" if esHtmx(request) else "catalogo.html", contexto)

    # --- Ficha de producto --------------------------------------------------------------------

    @app.get("/producto/{categoria}/{productoId}", response_class=HTMLResponse)
    def ficha(request: Request, categoria: Categoria, productoId: int, conexion=Depends(obtenerConexion)):
        producto = obtenerProducto(conexion, categoria, productoId)
        datos = datosVerificablesDe(conexion, categoria, productoId)
        contexto = {
            "categoria": categoria,
            "producto": producto,
            "filas": filasDeFicha(categoria, producto, datos),
            "benchmarks": benchmarksDe(conexion, categoria, productoId),
            "resumenes": resumenesDe(conexion, categoriaDatoBenchmark(categoria), productoId),
        }
        return responder(request, "producto.html", contexto)

    @app.post("/producto/{categoria}/{productoId}/fuentes-nuevas", response_class=HTMLResponse)
    def fuentesNuevas(request: Request, categoria: Categoria, productoId: int, conexion=Depends(obtenerConexion)):
        trabajoId = solicitarFuentesNuevas(cola, conexion, categoria, productoId)
        return responder(request, "_estado_trabajo.html", {"trabajo": cola.obtener(trabajoId)})

    # --- Verificación con un clic (D-25) ------------------------------------------------------

    @app.post("/datos/{datoId}/verificar", response_class=HTMLResponse)
    def verificarUnDato(request: Request, datoId: int, conexion=Depends(obtenerConexion)):
        return responder(request, "_dato.html", {"dato": verificarDato(conexion, datoId)})

    @app.post("/benchmarks/{benchmarkId}/verificar", response_class=HTMLResponse)
    def verificarUnBenchmark(request: Request, benchmarkId: int, conexion=Depends(obtenerConexion)):
        verificarBenchmark(conexion, benchmarkId)
        return responder(request, "_verificado.html")

    @app.post("/resumenes/{resumenId}/verificar", response_class=HTMLResponse)
    def verificarUnResumen(request: Request, resumenId: int, conexion=Depends(obtenerConexion)):
        verificarResumen(conexion, resumenId)
        return responder(request, "_verificado.html")

    # --- Comparador (D-07) --------------------------------------------------------------------

    @app.get("/comparar/{categoria}", response_class=HTMLResponse)
    def comparar(request: Request, categoria: Categoria, ids: list[int] = Query(default=[]),
                 conexion=Depends(obtenerConexion)):
        try:
            comparacion = compararProductos(conexion, categoria, ids)
        except ErrorComparacion as error:
            return paginaError(request, str(error), 400)
        return responder(request, "comparar.html", {"comparacion": comparacion, "categoria": categoria})

    # --- Alias pendientes de confirmación (D-21) ----------------------------------------------

    @app.get("/alias-pendientes", response_class=HTMLResponse)
    def aliasPendientes(request: Request, conexion=Depends(obtenerConexion)):
        filas = [dict(f) for f in conexion.execute(
            "SELECT * FROM alias_pendiente WHERE estado = 'pendiente' ORDER BY id")]
        for fila in filas:
            tabla = "configuracion_portatil" if fila["categoria"] == "portatil" else fila["categoria"]
            fila["opciones"] = [dict(o) for o in conexion.execute(f"SELECT id, nombre FROM {tabla} ORDER BY nombre")]
        return responder(request, "alias_pendientes.html", {"pendientes": filas})

    @app.post("/alias-pendientes/{aliasId}/confirmar")
    def confirmarAlias(aliasId: int, productoId: int = Form(...), conexion=Depends(obtenerConexion)):
        Normalizador(conexion).confirmarPendiente(aliasId, productoId)
        return RedirectResponse("/alias-pendientes", status_code=303)

    @app.post("/alias-pendientes/{aliasId}/rechazar")
    def rechazarAlias(aliasId: int, conexion=Depends(obtenerConexion)):
        Normalizador(conexion).rechazarPendiente(aliasId)
        return RedirectResponse("/alias-pendientes", status_code=303)

    return app
