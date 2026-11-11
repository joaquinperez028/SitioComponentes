import pytest
from pydantic import ValidationError

from app.esquemas import Categoria
from app.filtros import fabricantesDisponibles, filtrar


def nombres(filas):
    return {f["nombre"] for f in filas}


@pytest.mark.parametrize(
    "parametros, esperado",
    [
        ({}, {"Core i7-13700H", "Ryzen 7 7800X3D"}),
        ({"fabricante": "amd"}, {"Ryzen 7 7800X3D"}),
        ({"plataforma": "movil"}, {"Core i7-13700H"}),
        ({"nucleosMin": "10"}, {"Core i7-13700H"}),
        ({"tdpMax": 65}, {"Core i7-13700H"}),
        ({"fabricante": "", "nucleosMin": "", "tdpMax": ""}, {"Core i7-13700H", "Ryzen 7 7800X3D"}),
        ({"nucleosMin": 32}, set()),
    ],
)
def test_filtros_cpu(conexion, catalogo, parametros, esperado):
    assert nombres(filtrar(conexion, Categoria.cpu, parametros)) == esperado


def test_filtros_gpu(conexion, catalogo):
    assert nombres(filtrar(conexion, Categoria.gpu, {"vramMin": 8, "plataforma": "movil"})) == {"GeForce RTX 4060 Laptop GPU"}
    assert filtrar(conexion, Categoria.gpu, {"vramMin": 12}) == []


@pytest.mark.parametrize(
    "parametros, esperado",
    [
        ({}, {"Ejemplo Gaming 16 Gen 1 EG16-A", "Ejemplo Gaming 16 Gen 1 EG16-B"}),
        ({"tgpMin": 100}, {"Ejemplo Gaming 16 Gen 1 EG16-A"}),
        ({"gpu": "4060"}, {"Ejemplo Gaming 16 Gen 1 EG16-A"}),
        ({"cpu": "13700H", "ramMin": 16}, {"Ejemplo Gaming 16 Gen 1 EG16-A", "Ejemplo Gaming 16 Gen 1 EG16-B"}),
        ({"pesoMax": 2.0}, set()),
        ({"pantallaMin": 15, "pantallaMax": 16}, {"Ejemplo Gaming 16 Gen 1 EG16-A", "Ejemplo Gaming 16 Gen 1 EG16-B"}),
        ({"pantallaMax": 14}, set()),
    ],
)
def test_filtros_portatil(conexion, catalogo, parametros, esperado):
    assert nombres(filtrar(conexion, Categoria.portatil, parametros)) == esperado


def test_valores_invalidos_se_rechazan(conexion):
    with pytest.raises(ValidationError):
        filtrar(conexion, Categoria.cpu, {"plataforma": "servidor"})
    with pytest.raises(ValidationError):
        filtrar(conexion, Categoria.cpu, {"nucleosMin": "muchos"})


def test_parametros_desconocidos_se_ignoran_y_no_inyectan_sql(conexion, catalogo):
    filas = filtrar(conexion, Categoria.cpu, {"fabricante": "AMD' OR '1'='1", "orden": "DROP TABLE cpu"})
    assert filas == []
    assert conexion.execute("SELECT COUNT(*) FROM cpu").fetchone()[0] == 2


def test_fabricantes_disponibles(conexion, catalogo):
    assert fabricantesDisponibles(conexion, Categoria.cpu) == ["AMD", "Intel"]
    assert fabricantesDisponibles(conexion, Categoria.portatil) == ["Ejemplo"]
