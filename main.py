# main.py  ->  PASO 8 de la ruta de estudio (el ultimo: une todas las piezas)
# punto de inicio: crea el gestor, descarga feriados y levanta el servidor web
# ejecutar con:  python main.py   y abrir https://127.0.0.1:8080 (la consola muestra la direccion para el telefono)

import threading
import webbrowser

import rutas  # al importarlo, los decoradores @ruta registran todas las paginas
from gestor import GestorAsistencia
from servidor import iniciar_servidor
from utilidades import USAR_HTTPS, log

# "0.0.0.0" = el telefono (en la misma red Wi-Fi) puede entrar; "127.0.0.1" = solo esta PC
HOST = "0.0.0.0"
PUERTO = 8080


def al_cargar_feriados(cantidad: int):
    # callback: se ejecuta cuando termina la descarga de feriados
    log.info(f"Feriados disponibles: {cantidad}")


def abrir_navegador(url: str):
    # callback: se ejecuta cuando el servidor ya esta listo; abre el navegador en 1 segundo
    threading.Timer(1, webbrowser.open, args=[url]).start()


# este bloque solo corre si ejecutas "python main.py" (no si otro archivo importa main)
if __name__ == "__main__":
    gestor = GestorAsistencia()
    # singleton: rutas.gestor y este gestor son el mismo objeto
    log.info(f"¿Es la misma instancia? {gestor is rutas.gestor}")
    gestor.cargar_feriados_en_segundo_plano(al_terminar=al_cargar_feriados)
    iniciar_servidor(HOST, PUERTO, usar_https=USAR_HTTPS, al_iniciar=abrir_navegador)
