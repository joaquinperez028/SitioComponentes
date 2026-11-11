"""Normalización de nombres: modelo canónico + tabla de alias (D-21).

1. Reglas: minúsculas, quitar marca, símbolos y espacios; sinónimos de "móvil".
2. Si las reglas no encuentran el producto, Claude elige entre candidatos parecidos.
3. Con confianza baja, el alias queda pendiente de confirmación manual.
"""

import difflib
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field

from app.esquemas import TABLA_POR_CATEGORIA_DATO
from app.llm import ClienteLlm, ErrorLlm, extraerJson

MARCAS = (
    "amd", "intel", "nvidia", "geforce", "radeon", "apple", "qualcomm",
    "lenovo", "asus", "rog", "msi", "hp", "dell", "acer", "gigabyte", "razer", "samsung", "microsoft",
)
PALABRAS_RUIDO = ("processor", "procesador", "graphics", "graficos", "gpu", "cpu", "series")
# "Mobile", "Laptop GPU", "Notebook" son el mismo producto: se unifican en "laptop"
SINONIMOS_MOVIL = (r"laptop\s*gpu", r"mobile", r"notebook", r"laptop")


def claveNormalizada(nombre: str) -> str:
    # Quitar ® y ™ antes de NFKC, que convierte "™" en "TM"
    texto = nombre.replace("®", " ").replace("™", " ")
    texto = unicodedata.normalize("NFKC", texto).casefold()
    texto = re.sub(r"\((r|tm)\)", " ", texto)
    # "Ryzen 7 7840HS w/ Radeon 780M Graphics" -> la gráfica integrada no forma parte del nombre del CPU
    texto = re.sub(r"\s(with|w/)\s.*$", " ", texto)
    for patron in SINONIMOS_MOVIL:
        texto = re.sub(rf"\b{patron}\b", " laptop ", texto)
    texto = re.sub(r"\b(laptop\s+)+", "laptop ", texto)
    palabras = [p for p in re.split(r"[^0-9a-z]+", texto) if p]
    palabras = [p for p in palabras if p not in MARCAS and p not in PALABRAS_RUIDO]
    return "".join(palabras)


@dataclass
class ResultadoNormalizacion:
    productoId: int | None
    metodo: str  # "alias", "reglas", "claude", "pendiente", "no_encontrado"
    confianza: float = 0.0
    requiereConfirmacion: bool = False
    aliasPendienteId: int | None = None
    candidatos: list[dict] = field(default_factory=list)


SISTEMA_EMPAREJAR = (
    "Eres un experto en hardware. Decides si un nombre de producto corresponde exactamente al mismo "
    "modelo que alguno de los candidatos. Variantes distintas (Ti, Super, X3D, versión móvil frente a "
    "escritorio, distinta VRAM) son productos DISTINTOS. Responde solo con JSON: "
    '{"productoId": <id o null>, "confianza": <0..1>, "motivo": "<breve>"}'
)


class Normalizador:
    def __init__(self, conexion: sqlite3.Connection, clienteLlm: ClienteLlm | None = None, umbral: float = 0.85):
        self.conexion = conexion
        self.clienteLlm = clienteLlm
        self.umbral = umbral

    def _productos(self, categoria: str) -> list[sqlite3.Row]:
        tabla = TABLA_POR_CATEGORIA_DATO[categoria]
        return list(self.conexion.execute(f"SELECT id, nombre FROM {tabla}"))

    def guardarAlias(self, categoria: str, alias: str, productoId: int, origen: str) -> None:
        with self.conexion:
            self.conexion.execute(
                "INSERT INTO alias (categoria, alias, clave, productoId, origen) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (categoria, clave) DO UPDATE SET productoId = excluded.productoId, origen = excluded.origen",
                (categoria, alias, claveNormalizada(alias), productoId, origen),
            )

    def resolver(self, categoria: str, nombre: str) -> ResultadoNormalizacion:
        clave = claveNormalizada(nombre)
        if not clave:
            return ResultadoNormalizacion(None, "no_encontrado")

        fila = self.conexion.execute(
            "SELECT productoId FROM alias WHERE categoria = ? AND clave = ?", (categoria, clave)
        ).fetchone()
        if fila:
            return ResultadoNormalizacion(fila["productoId"], "alias", 1.0)

        productos = self._productos(categoria)
        clavesPorId = {p["id"]: claveNormalizada(p["nombre"]) for p in productos}
        for productoId, claveProducto in clavesPorId.items():
            if claveProducto == clave:
                self.guardarAlias(categoria, nombre, productoId, "reglas")
                return ResultadoNormalizacion(productoId, "reglas", 1.0)

        candidatos = self._candidatos(clave, productos, clavesPorId)
        if not candidatos:
            return ResultadoNormalizacion(None, "no_encontrado")
        if self.clienteLlm is None:
            return ResultadoNormalizacion(None, "no_encontrado", candidatos=candidatos)
        return self._resolverConClaude(categoria, nombre, candidatos)

    def _candidatos(self, clave: str, productos, clavesPorId: dict[int, str], limite: int = 5) -> list[dict]:
        puntuados = []
        for producto in productos:
            similitud = difflib.SequenceMatcher(None, clave, clavesPorId[producto["id"]]).ratio()
            if similitud >= 0.6:
                puntuados.append({"id": producto["id"], "nombre": producto["nombre"], "similitud": round(similitud, 3)})
        puntuados.sort(key=lambda c: c["similitud"], reverse=True)
        return puntuados[:limite]

    def _resolverConClaude(self, categoria: str, nombre: str, candidatos: list[dict]) -> ResultadoNormalizacion:
        mensaje = json.dumps(
            {"nombre": nombre, "candidatos": [{"id": c["id"], "nombre": c["nombre"]} for c in candidatos]},
            ensure_ascii=False,
        )
        try:
            respuesta = extraerJson(self.clienteLlm.completar(SISTEMA_EMPAREJAR, mensaje, maxTokens=300))
            productoId = respuesta.get("productoId")
            confianza = float(respuesta.get("confianza") or 0.0)
            motivo = str(respuesta.get("motivo") or "")
        except (ErrorLlm, TypeError, ValueError) as error:
            productoId, confianza, motivo = None, 0.0, f"Error de Claude: {error}"

        idsValidos = {c["id"] for c in candidatos}
        if productoId not in idsValidos:
            productoId = None

        if productoId is not None and confianza >= self.umbral:
            self.guardarAlias(categoria, nombre, productoId, "claude")
            return ResultadoNormalizacion(productoId, "claude", confianza, candidatos=candidatos)

        if productoId is None and confianza >= self.umbral:
            # Claude está seguro de que no es ninguno de los candidatos: es un producto nuevo
            return ResultadoNormalizacion(None, "no_encontrado", confianza, candidatos=candidatos)

        with self.conexion:
            cursor = self.conexion.execute(
                "INSERT INTO alias_pendiente (categoria, alias, productoIdPropuesto, confianza, motivo) "
                "VALUES (?, ?, ?, ?, ?)",
                (categoria, nombre, productoId, confianza, motivo),
            )
        return ResultadoNormalizacion(
            productoId, "pendiente", confianza, requiereConfirmacion=True,
            aliasPendienteId=cursor.lastrowid, candidatos=candidatos,
        )

    def confirmarPendiente(self, aliasPendienteId: int, productoId: int) -> None:
        fila = self.conexion.execute(
            "SELECT categoria, alias FROM alias_pendiente WHERE id = ?", (aliasPendienteId,)
        ).fetchone()
        if fila is None:
            raise KeyError(aliasPendienteId)
        self.guardarAlias(fila["categoria"], fila["alias"], productoId, "manual")
        with self.conexion:
            self.conexion.execute("UPDATE alias_pendiente SET estado = 'confirmado' WHERE id = ?", (aliasPendienteId,))

    def rechazarPendiente(self, aliasPendienteId: int) -> None:
        with self.conexion:
            self.conexion.execute("UPDATE alias_pendiente SET estado = 'rechazado' WHERE id = ?", (aliasPendienteId,))
