import pytest

from app.db import abrirConexion
from app.esquemas import Categoria
from app.rendimiento import (
    ErrorResumen,
    FuenteTexto,
    estaEnListaBlanca,
    generarResumen,
    listaBlancaActiva,
    resumenesDe,
    verificarResumen,
)
from app.repositorios import ProductoNoEncontrado, buscarPorNombre, datosVerificablesDe
from app.servicios import (
    Dependencias,
    SolicitudInvalida,
    crearManejadores,
    solicitarFuentesNuevas,
    solicitarImportacion,
)
from app.trabajos import ColaTrabajos
from tests.conftest import ClienteLlmFalso, leerFixtureHtml, leerRespuestaClaude


class DescargadorFixtures:
    """Sustituye a Playwright: sirve HTML guardado según la URL."""

    def __init__(self, paginas: dict[str, str]):
        self.paginas = paginas
        self.descargadas = []

    def descargar(self, url):
        self.descargadas.append(url)
        if url not in self.paginas:
            raise ConnectionError(f"Sin fixture para {url}")
        return leerFixtureHtml(self.paginas[url])


def crearCola(rutaBd, respuestasLlm, paginas, recolectores=()):
    llm = ClienteLlmFalso(respuestasLlm)
    descargador = DescargadorFixtures(paginas)
    dependencias = Dependencias(lambda: llm, descargador, recolectores=list(recolectores))
    return ColaTrabajos(rutaBd, crearManejadores(dependencias)), llm, descargador


URL_RYZEN = "https://www.amd.com/en/products/processors/desktops/ryzen/7000-series/amd-ryzen-7-7800x3d.html"


class TestImportacion:
    def test_flujo_completo_buscar_importar_y_encontrar(self, rutaBd):
        cola, llm, descargador = crearCola(
            rutaBd, [leerRespuestaClaude("cpu_ryzen_7_7800x3d.json")], {URL_RYZEN: "amd_ryzen_7_7800x3d.html"}
        )
        conexion = abrirConexion(rutaBd)
        assert buscarPorNombre(conexion, "7800X3D") == []  # no está: hay que importar

        trabajoId = solicitarImportacion(cola, "Ryzen 7 7800X3D", "cpu", URL_RYZEN)
        cola.procesarPendientes()

        trabajo = cola.obtener(trabajoId)
        assert trabajo["estado"] == "completado", trabajo["mensaje"]
        assert trabajo["resultado"]["datosSinCita"] == []
        [producto] = buscarPorNombre(conexion, "7800X3D")
        assert producto["categoria"] == "cpu" and producto["id"] == trabajo["resultado"]["productoIds"][0]
        assert descargador.descargadas == [URL_RYZEN]
        assert "Producto buscado: Ryzen 7 7800X3D" in llm.llamadas[0]["mensaje"]
        conexion.close()

    def test_no_duplica_un_trabajo_en_marcha(self, rutaBd):
        cola, _, _ = crearCola(rutaBd, [], {})
        primero = solicitarImportacion(cola, "Ryzen 7 7800X3D", "cpu", URL_RYZEN)
        assert solicitarImportacion(cola, " Ryzen 7 7800X3D ", "cpu", URL_RYZEN) == primero

    @pytest.mark.parametrize(
        "categoria, url",
        [("cpu", "ftp://amd.com/x"), ("cpu", "amd.com/x"), ("cpu", ""), ("ram", URL_RYZEN)],
    )
    def test_solicitud_invalida(self, rutaBd, categoria, url):
        cola, _, _ = crearCola(rutaBd, [], {})
        with pytest.raises(SolicitudInvalida):
            solicitarImportacion(cola, "x", categoria, url)

    def test_fallo_de_descarga_queda_como_error(self, rutaBd):
        cola, llm, _ = crearCola(rutaBd, [], {})
        trabajoId = solicitarImportacion(cola, "x", "cpu", "https://www.amd.com/no-existe")
        cola.procesarPendientes()
        trabajo = cola.obtener(trabajoId)
        assert trabajo["estado"] == "error" and "ConnectionError" in trabajo["mensaje"]
        assert llm.llamadas == []

    def test_importar_portatil_enlaza_con_cpu_ya_importada(self, rutaBd):
        urlPortatil = "https://psref.ejemplo/eg16"
        urlCpu = "https://www.intel.com/ark/i7-13700h"
        cola, _, _ = crearCola(
            rutaBd,
            [leerRespuestaClaude("cpu_core_i7_13700h.json"), leerRespuestaClaude("portatil_ejemplo.json")],
            {urlCpu: "intel_ark_core_i7_13700h.html", urlPortatil: "portatil_ejemplo_psref.html"},
        )
        solicitarImportacion(cola, "i7-13700H", "cpu", urlCpu)
        trabajoId = solicitarImportacion(cola, "Ejemplo Gaming 16", "portatil", urlPortatil)
        cola.procesarPendientes()
        resultado = cola.obtener(trabajoId)["resultado"]
        conexion = abrirConexion(rutaBd)
        cpuIds = {f["cpuId"] for f in conexion.execute("SELECT cpuId FROM configuracion_portatil")}
        assert len(resultado["productoIds"]) == 2 and cpuIds == {1}
        conexion.close()

    def test_avisa_de_datos_con_fragmento_no_encontrado(self, rutaBd):
        import json

        respuesta = json.loads(leerRespuestaClaude("cpu_ryzen_7_7800x3d.json"))
        respuesta["hilos"] = {"valor": 32, "fragmento": "# of Threads 32"}
        cola, _, _ = crearCola(rutaBd, [respuesta], {URL_RYZEN: "amd_ryzen_7_7800x3d.html"})
        trabajoId = solicitarImportacion(cola, "7800X3D", "cpu", URL_RYZEN)
        cola.procesarPendientes()
        trabajo = cola.obtener(trabajoId)
        assert trabajo["resultado"]["datosSinCita"] == ["hilos"]
        assert "revisar" in trabajo["mensaje"]
        conexion = abrirConexion(rutaBd)
        assert datosVerificablesDe(conexion, Categoria.cpu, 1)["hilos"]["fragmentoEncontrado"] == 0
        conexion.close()


def fuente(nombre="Notebookcheck", tipo="web", identificador="notebookcheck.net",
           url="https://www.notebookcheck.net/Review.123.0.html", texto="En Cyberpunk 2077 a 1080p Ultra logra 62 fps."):
    return FuenteTexto(nombre, tipo, identificador, url, "Review", texto)


class RecolectorFijo:
    def __init__(self, fuentes):
        self.fuentes = fuentes

    def recolectar(self, categoria, producto):
        return self.fuentes


class TestFuentesNuevasYResumenes:
    def test_lista_blanca_por_dominio_subreddit_y_canal(self, conexion):
        listaBlanca = listaBlancaActiva(conexion)
        assert estaEnListaBlanca(fuente(), listaBlanca)
        assert estaEnListaBlanca(fuente(url="https://notebookcheck.net/x"), listaBlanca)
        assert not estaEnListaBlanca(fuente(url="https://notebookcheck.net.estafa.com/x"), listaBlanca)
        assert not estaEnListaBlanca(fuente(url="https://blograndom.com/x"), listaBlanca)
        assert estaEnListaBlanca(fuente(tipo="reddit", identificador="GamingLaptops"), listaBlanca)
        assert not estaEnListaBlanca(fuente(tipo="reddit", identificador="pcmasterrace"), listaBlanca)
        assert estaEnListaBlanca(fuente(tipo="youtube", identificador="GamersNexus"), listaBlanca)

    def test_fuente_desactivada_no_cuenta(self, conexion):
        conexion.execute("UPDATE fuente_lista_blanca SET activa = 0 WHERE nombre = 'Notebookcheck'")
        assert not estaEnListaBlanca(fuente(), listaBlancaActiva(conexion))

    def test_resumen_en_espanol_con_citas(self):
        llm = ClienteLlmFalso([{"texto": "Rinde unos 62 fps en Cyberpunk 2077 a 1080p Ultra [1]."}])
        resumen = generarResumen(llm, "RTX 4060 Laptop", [fuente()])
        assert resumen.citas == [{"numero": 1, "nombreFuente": "Notebookcheck",
                                  "url": "https://www.notebookcheck.net/Review.123.0.html", "titulo": "Review"}]
        assert "español" in llm.llamadas[0]["sistema"]

    @pytest.mark.parametrize("texto", ["Sin citas.", "Cita inventada [3].", ""])
    def test_resumen_sin_citas_validas_se_rechaza(self, texto):
        with pytest.raises(ErrorResumen):
            generarResumen(ClienteLlmFalso([{"texto": texto}]), "x", [fuente()])

    def test_sin_recolectores_el_trabajo_lo_indica(self, rutaBd):
        cola, llm, _ = crearCola(rutaBd, [leerRespuestaClaude("cpu_ryzen_7_7800x3d.json")], {URL_RYZEN: "amd_ryzen_7_7800x3d.html"})
        solicitarImportacion(cola, "7800X3D", "cpu", URL_RYZEN)
        cola.procesarPendientes()
        conexion = abrirConexion(rutaBd)
        trabajoId = solicitarFuentesNuevas(cola, conexion, Categoria.cpu, 1)
        cola.procesarPendientes()
        trabajo = cola.obtener(trabajoId)
        assert trabajo["estado"] == "completado" and "recolectores" in trabajo["mensaje"]
        conexion.close()

    def test_fuentes_nuevas_filtra_lista_blanca_y_guarda_resumen(self, rutaBd):
        recolector = RecolectorFijo([fuente(), fuente(nombre="Blog", url="https://blograndom.com/x")])
        cola, llm, _ = crearCola(
            rutaBd,
            [leerRespuestaClaude("cpu_ryzen_7_7800x3d.json"), {"texto": "Muy rápido en juegos [1]."}],
            {URL_RYZEN: "amd_ryzen_7_7800x3d.html"},
            recolectores=[recolector],
        )
        solicitarImportacion(cola, "7800X3D", "cpu", URL_RYZEN)
        cola.procesarPendientes()
        conexion = abrirConexion(rutaBd)
        trabajoId = solicitarFuentesNuevas(cola, conexion, Categoria.cpu, 1)
        cola.procesarPendientes()

        resultado = cola.obtener(trabajoId)["resultado"]
        assert resultado["fuentesUsadas"] == 1
        assert resultado["fuentesDescartadas"] == ["https://blograndom.com/x"]
        assert "blograndom" not in llm.llamadas[-1]["mensaje"]
        [resumen] = resumenesDe(conexion, "cpu", 1)
        assert resumen["estado"] == "sin_verificar" and resumen["citas"][0]["nombreFuente"] == "Notebookcheck"
        verificarResumen(conexion, resumen["id"])
        assert resumenesDe(conexion, "cpu", 1)[0]["estado"] == "verificado"
        conexion.close()

    def test_fuentes_nuevas_de_producto_inexistente(self, rutaBd):
        cola, _, _ = crearCola(rutaBd, [], {})
        conexion = abrirConexion(rutaBd)
        with pytest.raises(ProductoNoEncontrado):
            solicitarFuentesNuevas(cola, conexion, Categoria.gpu, 42)
        conexion.close()
