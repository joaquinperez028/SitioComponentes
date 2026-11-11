"""Extractor genérico: texto de la página -> Claude -> esquema Pydantic de la categoría (D-20).

Claude devuelve, para cada campo, el valor y el fragmento literal de la página del que lo sacó.
Se comprueba que el fragmento exista en la página: si no aparece, el dato queda marcado
(posible invención) además de `sin_verificar` (D-25).
"""

import json
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from app.esquemas import ESQUEMA_POR_CATEGORIA, Categoria
from app.extraccion.texto import fragmentoEnTexto, htmlATexto
from app.llm import ClienteLlm, ErrorLlm, extraerJson


class ErrorExtraccion(Exception):
    pass


@dataclass
class DatoExtraido:
    ruta: str  # "nucleos", "modelo.pesoKg", "configuraciones.0.tgpW"
    valor: object
    fragmento: str | None
    fragmentoEncontrado: bool


@dataclass
class ResultadoExtraccion:
    especificaciones: BaseModel
    datos: list[DatoExtraido]
    urlFuente: str

    def datosDe(self, prefijo: str) -> dict[str, DatoExtraido]:
        """Datos bajo un prefijo de ruta, indexados por nombre de campo. prefijo="" para el nivel raíz."""
        resultado = {}
        for dato in self.datos:
            if not prefijo and "." not in dato.ruta:
                resultado[dato.ruta] = dato
            elif prefijo and dato.ruta.startswith(prefijo + ".") and "." not in dato.ruta[len(prefijo) + 1 :]:
                resultado[dato.ruta[len(prefijo) + 1 :]] = dato
        return resultado


SISTEMA_EXTRACCION = """Extraes especificaciones técnicas de páginas oficiales de fabricantes de hardware.
Reglas:
- Usa SOLO información presente en el texto. Si un dato no aparece, pon "valor": null y "fragmento": null.
- No conviertas ni estimes lo que no esté escrito; sí puedes convertir unidades evidentes (p. ej. "2.4 GHz" -> 2.4).
- "fragmento" debe ser una cita LITERAL y breve del texto (copiada tal cual) de la que sale el valor.
- plataforma: "escritorio" o "movil".
- Responde SOLO con JSON, sin comentarios."""


def _plantillaRespuesta(esquema: type[BaseModel]) -> object:
    """Estructura que se pide a Claude: el esquema con cada hoja sustituida por {valor, fragmento}."""
    plantilla = {}
    for nombre, campo in esquema.model_fields.items():
        anotacion = campo.annotation
        argumentos = getattr(anotacion, "__args__", ())
        if isinstance(anotacion, type) and issubclass(anotacion, BaseModel):
            plantilla[nombre] = _plantillaRespuesta(anotacion)
        elif argumentos and isinstance(argumentos[0], type) and issubclass(argumentos[0], BaseModel):
            plantilla[nombre] = [_plantillaRespuesta(argumentos[0])]
        else:
            plantilla[nombre] = {"valor": f"<{campo.title or nombre}>", "fragmento": "<cita literal>"}
    return plantilla


def construirMensaje(categoria: Categoria, texto: str, nombreBuscado: str | None) -> str:
    esquema = ESQUEMA_POR_CATEGORIA[categoria]
    partes = [
        f"Categoría: {categoria.value}",
        f"Producto buscado: {nombreBuscado}" if nombreBuscado else "",
        "Esquema JSON de los valores (tipos y restricciones):",
        json.dumps(esquema.model_json_schema(), ensure_ascii=False),
        "Formato de respuesta (cada campo con valor y fragmento):",
        json.dumps(_plantillaRespuesta(esquema), ensure_ascii=False),
    ]
    if categoria == Categoria.portatil:
        partes.append("Incluye una entrada en 'configuraciones' por cada configuración de CPU/GPU listada.")
    partes += ["Texto de la página:", "<<<", texto, ">>>"]
    return "\n".join(p for p in partes if p)


def _aplanar(respuesta: object, texto: str, ruta: str, datos: list[DatoExtraido]) -> object:
    """Convierte la respuesta {valor, fragmento} en valores simples y registra cada dato."""
    if isinstance(respuesta, dict) and "valor" in respuesta and set(respuesta) <= {"valor", "fragmento"}:
        fragmento = respuesta.get("fragmento")
        fragmento = str(fragmento) if fragmento is not None else None
        valor = respuesta.get("valor")
        if valor is not None:
            datos.append(DatoExtraido(ruta, valor, fragmento, fragmentoEnTexto(fragmento, texto)))
        return valor
    if isinstance(respuesta, dict):
        return {
            clave: _aplanar(valor, texto, f"{ruta}.{clave}" if ruta else clave, datos)
            for clave, valor in respuesta.items()
        }
    if isinstance(respuesta, list):
        return [_aplanar(elemento, texto, f"{ruta}.{indice}", datos) for indice, elemento in enumerate(respuesta)]
    # Valor suelto sin fragmento: se acepta pero sin cita
    datos.append(DatoExtraido(ruta, respuesta, None, False))
    return respuesta


class ExtractorEspecificaciones:
    def __init__(self, clienteLlm: ClienteLlm):
        self.clienteLlm = clienteLlm

    def extraer(
        self, html: str, urlFuente: str, categoria: Categoria, nombreBuscado: str | None = None
    ) -> ResultadoExtraccion:
        texto = htmlATexto(html)
        if not texto:
            raise ErrorExtraccion("La página no tiene texto")
        try:
            respuesta = extraerJson(
                self.clienteLlm.completar(SISTEMA_EXTRACCION, construirMensaje(categoria, texto, nombreBuscado))
            )
        except ErrorLlm as error:
            raise ErrorExtraccion(str(error)) from error

        datos: list[DatoExtraido] = []
        valores = _aplanar(respuesta, texto, "", datos)
        esquema = ESQUEMA_POR_CATEGORIA[categoria]
        try:
            especificaciones = esquema.model_validate(valores)
        except ValidationError as error:
            raise ErrorExtraccion(f"Las specs extraídas no cumplen el esquema: {error}") from error
        return ResultadoExtraccion(especificaciones, datos, urlFuente)
