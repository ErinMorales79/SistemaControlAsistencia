# sesiones.py
# inicio de sesion: quien esta conectado en cada aparato, cookies y reglas de permisos
# depende de modelos.py y utilidades.py (NO conoce al gestor)

import secrets
from datetime import datetime, timedelta
from http.cookies import CookieError, SimpleCookie

from modelos import Rol
from utilidades import DURACION_SESION, SUPERADMIN_PRINCIPAL

NOMBRE_COOKIE = "sesion"


class GestorSesiones:
    # PATRON SINGLETON (practica 23): igual que UserSession, pero guarda VARIAS sesiones
    # porque al servidor se conectan varios aparatos a la vez
    _instancia = None

    def __new__(cls):
        if cls._instancia is None:
            cls._instancia = super().__new__(cls)
            cls._instancia._iniciado = False
        return cls._instancia

    def __init__(self):
        if self._iniciado:
            return
        self._iniciado = True
        # diccionario: token -> (codigo del trabajador, fecha y hora en que vence)
        # vive en memoria: si se reinicia el servidor, todos vuelven a iniciar sesion
        self.sesiones = {}

    def iniciar_sesion(self, codigo: str) -> str:
        # token: texto aleatorio imposible de adivinar; es la "pulsera" de ese aparato
        token = secrets.token_urlsafe(32)
        vence = datetime.now() + timedelta(seconds=DURACION_SESION)
        self.sesiones[token] = (codigo, vence)
        return token

    def codigo_de(self, token: str):
        # devuelve el codigo del trabajador de esa sesion, o None si no existe o ya vencio
        if token not in self.sesiones:
            return None
        codigo, vence = self.sesiones[token]
        if datetime.now() > vence:
            del self.sesiones[token]
            return None
        return codigo

    def cerrar_sesion(self, token: str):
        # pop con valor por defecto: si el token no existe, no da error
        self.sesiones.pop(token, None)

    def cerrar_sesiones_de(self, codigo: str):
        # cierra todas las sesiones de un trabajador (ej. al restablecer su contraseña o eliminarlo)
        tokens = [token for token, (dueno, _) in self.sesiones.items() if dueno == codigo]
        for token in tokens:
            del self.sesiones[token]


# ---------------------------------------------------------------
# COOKIES
# ---------------------------------------------------------------
def token_de_cookie(cabecera: str) -> str:
    # el navegador manda la cookie asi: "sesion=abc123"; SimpleCookie la separa por nombre
    try:
        galleta = SimpleCookie(cabecera)
    except CookieError:
        return ""                                       # cookie mal formada: como si no hubiera
    return galleta[NOMBRE_COOKIE].value if NOMBRE_COOKIE in galleta else ""


def crear_cookie(token: str, segundos: int = DURACION_SESION) -> str:
    # texto de la cabecera Set-Cookie que le pide al navegador guardar el token
    galleta = SimpleCookie()
    galleta[NOMBRE_COOKIE] = token
    galleta[NOMBRE_COOKIE]["path"] = "/"              # vale para todas las paginas
    galleta[NOMBRE_COOKIE]["max-age"] = segundos      # cuanto tiempo la guarda el navegador
    galleta[NOMBRE_COOKIE]["httponly"] = True         # JavaScript no puede leerla (mas seguro)
    galleta[NOMBRE_COOKIE]["samesite"] = "Lax"        # otras paginas no pueden usarla
    return galleta[NOMBRE_COOKIE].OutputString()


def borrar_cookie() -> str:
    # una cookie vacia que dura 0 segundos: el navegador la borra
    return crear_cookie("", 0)


# ---------------------------------------------------------------
# REGLAS DE PERMISOS (funciones puras: faciles de probar)
# ---------------------------------------------------------------
def es_erin(trabajador) -> bool:
    return trabajador.codigo == SUPERADMIN_PRINCIPAL


def puede_ver(usuario, trabajador) -> bool:
    # ¿el usuario puede VER los datos de ese trabajador?
    if usuario.rol == Rol.SUPERADMIN:
        return True                                       # toda la empresa
    if trabajador.codigo == usuario.codigo:
        return True                                       # cada quien se ve a si mismo
    if usuario.rol == Rol.ADMIN:
        # el encargado ve a la gente de su sucursal
        return usuario.codigo_sucursal != "" and trabajador.codigo_sucursal == usuario.codigo_sucursal
    return False


def puede_gestionar(usuario, trabajador) -> bool:
    # ¿el usuario puede EDITAR, eliminar o corregir marcas de ese trabajador?
    if es_erin(trabajador):
        return es_erin(usuario)                           # a Erin solo lo toca Erin
    if usuario.rol == Rol.SUPERADMIN:
        # los superadmins solo los maneja Erin; a los demas, cualquier superadmin
        return trabajador.rol != Rol.SUPERADMIN or es_erin(usuario)
    if usuario.rol == Rol.ADMIN:
        # el encargado solo maneja trabajadores comunes de su sucursal (no a otros admins ni a si mismo)
        return (trabajador.rol == Rol.TRABAJADOR and usuario.codigo_sucursal != ""
                and trabajador.codigo_sucursal == usuario.codigo_sucursal)
    return False


def roles_que_puede_dar(usuario) -> list:
    # que roles puede asignar el usuario en el formulario de trabajadores
    if es_erin(usuario):
        return [Rol.TRABAJADOR, Rol.ADMIN, Rol.SUPERADMIN]   # solo Erin nombra superadmins
    if usuario.rol == Rol.SUPERADMIN:
        return [Rol.TRABAJADOR, Rol.ADMIN]
    return [Rol.TRABAJADOR]                                 # el encargado solo crea trabajadores
