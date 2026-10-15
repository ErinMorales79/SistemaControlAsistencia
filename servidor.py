# servidor.py  ->  PASO 6 de la ruta de estudio
# servidor web hecho solo con la libreria estandar (http.server)
# recibe las peticiones del navegador, busca la funcion de la ruta y devuelve HTML
# depende de excepciones.py, red.py, sesiones.py y utilidades.py (NO conoce al gestor: solo sabe hablar HTTP)
# cada funcion de ruta recibe (parametros, formulario, codigo_sesion):
# codigo_sesion = codigo del trabajador conectado en ese aparato, o None si no inicio sesion

import mimetypes
import ssl
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from excepciones import AsistenciaError
from red import ARCHIVO_CERTIFICADO, ARCHIVO_CLAVE, ip_principal, ips_locales, preparar_certificado
from sesiones import GestorSesiones, token_de_cookie
from utilidades import log

CARPETA_BASE = Path(__file__).parent
CARPETA_PLANTILLAS = CARPETA_BASE / "plantillas"
CARPETA_ESTATICOS = CARPETA_BASE / "static"

# diccionario de rutas: ("GET", "/trabajadores") -> funcion que arma la pagina
RUTAS = {}

# candado: cada peticion corre en su propio hilo, asi solo una toca los datos a la vez
CANDADO = threading.Lock()


def ruta(metodo: str, camino: str):
    # decorador con parametros: registra la funcion en el diccionario RUTAS
    def decorador(funcion):
        RUTAS[(metodo, camino)] = funcion
        return funcion
    return decorador


def render(nombre_plantilla: str, **datos) -> str:
    # lee el archivo .html y cambia cada {{clave}} por su valor
    contenido = (CARPETA_PLANTILLAS / nombre_plantilla).read_text(encoding="utf-8")
    for clave, valor in datos.items():
        contenido = contenido.replace("{{" + clave + "}}", str(valor))
    return contenido


class Redireccion:
    # respuesta que le dice al navegador "ve a esta otra URL"
    # cookie (opcional): texto Set-Cookie para guardar o borrar la sesion en el navegador
    def __init__(self, url: str, cookie: str = ""):
        self.url = url
        self.cookie = cookie


class Descarga:
    # respuesta que envia un archivo para descargar
    def __init__(self, ruta_archivo: Path, tipo: str):
        self.ruta_archivo = ruta_archivo
        self.tipo = tipo


def destino_seguro(destino: str) -> str:
    # solo permitimos volver a paginas de nuestro propio sitio
    return destino if destino.startswith("/") and not destino.startswith("//") else "/"


def redirigir(destino: str, cookie: str = "", **mensajes) -> Redireccion:
    # agrega mensajes a la URL: /trabajadores?msg=Guardado
    mensajes = {clave: valor for clave, valor in mensajes.items() if valor}
    if mensajes:
        destino += ("&" if "?" in destino else "?") + urlencode(mensajes)
    return Redireccion(destino, cookie)


class ManejadorPeticiones(BaseHTTPRequestHandler):
    # PETICIONES HTTP: python llama do_GET o do_POST segun lo que pida el navegador

    # self.path = la URL pedida, self.headers = cabeceras,
    # self.rfile = lo que llega del navegador, self.wfile = lo que le respondemos

    def setup(self):
        # con https, el "saludo" cifrado (handshake) se hace aqui, en el hilo de esta peticion,
        # asi un aparato lento o que no envia nada no traba al servidor (maximo 10 segundos)
        if isinstance(self.request, ssl.SSLSocket):
            self.request.settimeout(10)
            self.request.do_handshake()
        super().setup()

    def do_GET(self):
        self.atender("GET")

    def do_POST(self):
        self.atender("POST")

    def atender(self, metodo: str):
        # urlparse separa "/asistencia?semana=2026-10-05" en path="/asistencia" y query="semana=2026-10-05"
        url = urlparse(self.path)

        # archivos estaticos (css)
        if metodo == "GET" and url.path.startswith("/static/"):
            return self.enviar_estatico(url.path.removeprefix("/static/"))

        funcion = RUTAS.get((metodo, url.path))
        if funcion is None:
            return self.enviar_html("<h1>404 - Página no encontrada</h1><a href='/'>Volver al inicio</a>", 404)

        # parametros de la URL (?semana=2026-10-05) y datos del formulario (POST)
        # parse_qs da {"semana": ["2026-10-05"]}; con valores[0] nos quedamos con el texto
        parametros = {clave: valores[0] for clave, valores in parse_qs(url.query).items()}
        formulario = self.leer_formulario() if metodo == "POST" else {}
        # la cookie trae el token de la sesion; el navegador la manda sola en cada peticion
        token = token_de_cookie(self.headers.get("Cookie", ""))

        try:
            with CANDADO:     # mientras una peticion esta aqui, las demas esperan
                codigo_sesion = GestorSesiones().codigo_de(token)
                respuesta = funcion(parametros, formulario, codigo_sesion)
        except AsistenciaError as error:
            # excepciones: un error nuestro se muestra como mensaje rojo en la pagina
            log.warning(f"Error controlado: {error}")
            respuesta = redirigir(destino_seguro(formulario.get("volver", "/")), error=str(error))
        except Exception:
            log.exception("Error inesperado")
            return self.enviar_html("<h1>500 - Error interno</h1><a href='/'>Volver al inicio</a>", 500)

        # segun el tipo de respuesta, enviamos una cosa u otra
        if isinstance(respuesta, Redireccion):
            self.send_response(303)                      # 303 = ve a otra pagina con GET
            self.send_header("Location", respuesta.url)
            if respuesta.cookie:
                self.send_header("Set-Cookie", respuesta.cookie)   # el navegador guarda (o borra) la sesion
            self.end_headers()
        elif isinstance(respuesta, Descarga):
            self.enviar_archivo(respuesta.ruta_archivo, respuesta.tipo, descargar=True)
        else:
            self.enviar_html(respuesta)

    def leer_formulario(self) -> dict:
        # el formulario llega en el cuerpo como texto: nombre=Ana&apellido=Lopez
        largo = int(self.headers.get("Content-Length", 0))
        cuerpo = self.rfile.read(largo).decode("utf-8")
        return {clave: valores[0].strip() for clave, valores in parse_qs(cuerpo, keep_blank_values=True).items()}

    def enviar_html(self, html: str, estado: int = 200):
        # una respuesta HTTP = estado (200 ok, 404...) + cabeceras + cuerpo en bytes
        datos = html.encode("utf-8")
        self.send_response(estado)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def enviar_estatico(self, nombre: str):
        archivo = (CARPETA_ESTATICOS / nombre).resolve()
        # seguridad: no dejamos salir de la carpeta static
        if CARPETA_ESTATICOS.resolve() not in archivo.parents or not archivo.is_file():
            return self.enviar_html("<h1>404</h1>", 404)
        tipo = mimetypes.guess_type(archivo.name)[0] or "application/octet-stream"
        self.enviar_archivo(archivo, tipo)

    def enviar_archivo(self, archivo: Path, tipo: str, descargar: bool = False):
        datos = archivo.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        if descargar:
            self.send_header("Content-Disposition", f'attachment; filename="{archivo.name}"')
        self.end_headers()
        self.wfile.write(datos)

    def log_message(self, formato, *args):
        # mandamos cada peticion a nuestro log (menos los archivos css y js)
        # client_address[0] = la IP del aparato que hizo la peticion (127.0.0.1 = esta misma PC)
        if "/static/" not in self.path:
            log.info(f"HTTP {self.command} {self.path} -> {args[1] if len(args) > 1 else ''} ({self.client_address[0]})")


class ServidorAsistencia(ThreadingHTTPServer):
    # herencia: igual que ThreadingHTTPServer pero sin compartir el puerto
    # (en Windows, si no, dos servidores abiertos usan el mismo puerto y responde el viejo)
    allow_reuse_address = False

    def handle_error(self, request, client_address):
        # errores de conexion: en vez de un error largo, una linea clara en el log
        error = sys.exc_info()[1]
        ip = client_address[0]
        # reason = el motivo que da OpenSSL (solo existe en los errores de ssl)
        motivo = getattr(error, "reason", "") or ""
        if motivo == "HTTP_REQUEST":
            # escribio http:// (sin s): el navegador mando texto normal a un puerto cifrado (la pagina no carga)
            log.warning(f"Conexión de {ip} rechazada: entró por http:// en vez de https://")
        elif "CERTIFICATE" in motivo or "UNKNOWN_CA" in motivo:
            # el navegador cerro una conexion extra por nuestro certificado propio; pasa aunque ya se haya
            # tocado "Continuar" (iconos, precargas), asi que NO es un error: va al nivel oculto
            log.debug(f"Conexión de {ip} cerrada por el certificado propio (normal)")
        elif isinstance(error, ssl.SSLError) and motivo != "UNEXPECTED_EOF_WHILE_READING":
            log.warning(f"Conexión de {ip} rechazada por un error de HTTPS: {motivo or error}")
        elif isinstance(error, OSError):
            # cortes de red o conexiones "por adelantado" que el navegador abre y cierra sin enviar nada
            # (UNEXPECTED_EOF): son normales y muy frecuentes, por eso van al nivel oculto (debug)
            log.debug(f"Conexión cerrada por {ip}: {error}")
        else:
            super().handle_error(request, client_address)


def iniciar_servidor(host: str, puerto: int, usar_https: bool = False, al_iniciar=None):
    # host "0.0.0.0" = acepta conexiones de cualquier aparato de la red (el telefono)
    # host "127.0.0.1" = solo de esta misma PC
    # ThreadingHTTPServer atiende cada peticion en un hilo (el navegador abre varias conexiones)
    try:
        servidor = ServidorAsistencia((host, puerto), ManejadorPeticiones)
    except OSError:
        # excepciones: el puerto ya esta ocupado por otra ventana del sistema
        log.error(f"El puerto {puerto} ya está en uso. Cierra la otra ventana del servidor (Ctrl + C) y vuelve a intentar.")
        return

    # HTTPS: "envolvemos" el socket del servidor con cifrado usando nuestro certificado
    protocolo = "http"
    if usar_https and preparar_certificado():
        contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        contexto.load_cert_chain(ARCHIVO_CERTIFICADO, ARCHIVO_CLAVE)
        # do_handshake_on_connect=False: el saludo cifrado lo hace cada hilo en setup() (ver arriba)
        servidor.socket = contexto.wrap_socket(servidor.socket, server_side=True, do_handshake_on_connect=False)
        protocolo = "https"

    url = f"{protocolo}://127.0.0.1:{puerto}"
    log.info(f"Servidor listo en {url}  (Ctrl + C para detener)")
    if host == "0.0.0.0":
        # las direcciones que hay que escribir en el telefono (debe estar en la misma red)
        log.info(f"Desde el teléfono (misma red Wi-Fi): {protocolo}://{ip_principal()}:{puerto}")
        otras = [ip for ip in ips_locales() if ip != ip_principal()]
        if otras:
            log.info(f"Otras IPs de esta PC (adaptadores virtuales u otras redes): {', '.join(otras)}")
    if al_iniciar:
        al_iniciar(url)     # callback: avisamos que el servidor ya arranco
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        log.info("Servidor detenido")
    finally:
        servidor.server_close()
