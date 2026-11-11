"""Punto de entrada: uvicorn app.main:app --reload"""

from app.web.principal import crearApp

app = crearApp()
