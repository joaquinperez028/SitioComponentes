import pytest
from pydantic import ValidationError

from app.benchmarks import Benchmark, agregarBenchmark, benchmarksDe, compararBenchmarks, verificarBenchmark
from app.comparador import ErrorComparacion, compararProductos
from app.esquemas import Categoria


def bench(**cambios):
    datos = dict(prueba="Cyberpunk 2077", resolucion="1080p", preset="Ultra", valor=60.0, unidad="fps",
                 nombreFuente="Notebookcheck", urlFuente="https://www.notebookcheck.net/review.html", fecha="2024-01-10")
    datos.update(cambios)
    return Benchmark(**datos)


class TestBenchmarks:
    def test_solo_compara_misma_prueba_resolucion_y_preset(self, conexion, catalogo):
        i7, ryzen = catalogo["i7"], catalogo["ryzen"]
        agregarBenchmark(conexion, Categoria.cpu, i7, bench(prueba="Cinebench 2024 Multi", resolucion="", preset="", valor=1000, unidad="pts"))
        agregarBenchmark(conexion, Categoria.cpu, ryzen, bench(prueba="cinebench 2024 multi ", resolucion="", preset="", valor=1100, unidad="pts"))
        # Misma prueba pero distinto preset: no es comparable
        agregarBenchmark(conexion, Categoria.cpu, i7, bench(preset="Ultra"))
        agregarBenchmark(conexion, Categoria.cpu, ryzen, bench(preset="Medium"))

        grupos = compararBenchmarks(conexion, Categoria.cpu, [i7, ryzen])

        assert len(grupos) == 1
        assert grupos[0].prueba == "Cinebench 2024 Multi"
        assert grupos[0].mejorProductoId == ryzen

    def test_distinta_unidad_no_es_comparable(self, conexion, catalogo):
        agregarBenchmark(conexion, Categoria.cpu, catalogo["i7"], bench(unidad="fps"))
        agregarBenchmark(conexion, Categoria.cpu, catalogo["ryzen"], bench(unidad="ms", mayorEsMejor=False))
        assert compararBenchmarks(conexion, Categoria.cpu, [catalogo["i7"], catalogo["ryzen"]]) == []

    def test_menor_es_mejor_y_media_de_varias_fuentes(self, conexion, catalogo):
        i7, ryzen = catalogo["i7"], catalogo["ryzen"]
        for productoId, valor in [(i7, 10), (i7, 14), (ryzen, 13)]:
            agregarBenchmark(conexion, Categoria.cpu, productoId,
                             bench(prueba="Compilación kernel", resolucion="", preset="", valor=valor, unidad="min", mayorEsMejor=False))
        [grupo] = compararBenchmarks(conexion, Categoria.cpu, [i7, ryzen])
        assert grupo.media(i7) == 12 and grupo.mejorProductoId == i7

    def test_benchmark_de_portatil_va_por_configuracion(self, conexion, catalogo):
        idA, _ = catalogo["portatil"]
        agregarBenchmark(conexion, Categoria.portatil, idA, bench())
        [fila] = benchmarksDe(conexion, Categoria.portatil, idA)
        assert fila["categoria"] == "configuracion_portatil" and fila["estado"] == "sin_verificar"
        verificarBenchmark(conexion, fila["id"])
        assert benchmarksDe(conexion, Categoria.portatil, idA)[0]["estado"] == "verificado"

    def test_benchmark_exige_fuente_valida(self):
        with pytest.raises(ValidationError):
            bench(urlFuente="no es una url")
        with pytest.raises(ValidationError):
            bench(nombreFuente="")


class TestComparador:
    def test_compara_cpus_y_destaca_el_mejor(self, conexion, catalogo):
        comparacion = compararProductos(conexion, Categoria.cpu, [catalogo["i7"], catalogo["ryzen"]])
        filas = {f.etiqueta: f for f in comparacion.filas}

        assert filas["Cores"].valores == [14, 8] and filas["Cores"].mejorIndices == {0}
        assert filas["L3 Cache (MB)"].mejorIndices == {1}
        assert filas["Boost Clock (GHz)"].mejorIndices == set()  # empate: 5.0 y 5.0
        assert filas["TDP (W)"].mejorIndices == set()  # el TDP no se destaca
        assert filas["Cores"].datos[0]["fragmento"] == "Total Cores: 14"
        assert "Model" not in filas  # el nombre va en la cabecera

    def test_compara_configuraciones_de_portatil(self, conexion, catalogo):
        comparacion = compararProductos(conexion, Categoria.portatil, catalogo["portatil"])
        filas = {f.etiqueta: f for f in comparacion.filas}
        assert filas["GPU TGP (W)"].valores == [115, None]
        assert filas["GPU TGP (W)"].mejorIndices == set()  # un solo valor numérico
        assert filas["Weight (kg)"].valores == [2.3, 2.3]
        assert filas["GPU"].valores == ["GeForce RTX 4060 Laptop GPU", None]
        assert filas["Weight (kg)"].datos[0]["campo"] == "pesoKg"
        assert "CPU PL1 (W)" not in filas  # filas totalmente vacías se omiten

    @pytest.mark.parametrize("cantidad", [0, 1, 5])
    def test_entre_dos_y_cuatro_productos(self, conexion, catalogo, cantidad):
        with pytest.raises(ErrorComparacion):
            compararProductos(conexion, Categoria.cpu, list(range(1, cantidad + 1)))

    def test_ids_repetidos_cuentan_una_vez(self, conexion, catalogo):
        with pytest.raises(ErrorComparacion):
            compararProductos(conexion, Categoria.cpu, [catalogo["i7"], catalogo["i7"]])

    def test_no_mezcla_categorias(self, conexion, catalogo):
        from app.repositorios import ProductoNoEncontrado

        with pytest.raises(ProductoNoEncontrado):
            compararProductos(conexion, Categoria.gpu, [catalogo["rtx4060l"], 999])
