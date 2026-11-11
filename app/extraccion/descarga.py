"""Descarga de páginas con Playwright (D-20). No se usa en las pruebas (D-33): nada contra webs en vivo."""

from typing import Protocol


class Descargador(Protocol):
    def descargar(self, url: str) -> str: ...


class DescargadorPlaywright:
    def __init__(self, tiempoEsperaMs: int = 30_000):
        self.tiempoEsperaMs = tiempoEsperaMs

    def descargar(self, url: str) -> str:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            navegador = playwright.chromium.launch(headless=True)
            try:
                pagina = navegador.new_page(locale="en-US")
                pagina.goto(url, wait_until="networkidle", timeout=self.tiempoEsperaMs)
                return pagina.content()
            finally:
                navegador.close()
