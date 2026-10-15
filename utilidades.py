# utilidades.py 
# funciones de apoyo: logs, decoradores, conversion de horas y validaciones
# solo depende de excepciones.py\
#   VAMOS A PROBAR LAS HERRAMIENTAS GUI DE GIT

import hashlib
import hmac
import logging
import math
import re
import secrets
import time
from datetime import date
from functools import wraps
from pathlib import Path

from excepciones import DatoInvalidoError

# carpeta donde se guardan los datos (json, xml y log)
# Path(__file__).parent = la carpeta donde esta este archivo; "/" une rutas
CARPETA_DATOS = Path(__file__).parent / "datos"
CARPETA_DATOS.mkdir(exist_ok=True)

# configuracion de red (Fase 4)
# HTTPS: el telefono solo entrega el GPS a paginas seguras (https). False = http normal (solo para la PC)
USAR_HTTPS = True
CARPETA_CERTIFICADO = Path(__file__).parent / "certificado"     # certificado propio + su clave privada

# constantes del horario laboral (en segundos)
TOLERANCIA_SEGUNDOS = 5 * 60       # 5 minutos de gracia para llegar
ALMUERZO_SEGUNDOS = 60 * 60         # 1 hora de almuerzo permitida (lunes a viernes)
HORAS_SEMANALES = 44 * 3600         # todos deben completar 44 horas por semana
TOLERANCIA_SEMANAL = 15 * 60         # 43h 45m tambien cuenta como semana completa
HORA_ENTRADA_DEFECTO = "08:00"
HORA_SALIDA_DEFECTO = "17:00"
SABADO_ENTRADA_DEFECTO = "08:00"
SABADO_SALIDA_DEFECTO = "12:00"

# constantes de ubicacion (en metros)
RADIO_DEFECTO = 100                 # distancia maxima a la sucursal para que la marca sea valida
RADIO_MINIMO = 10
RADIO_MAXIMO = 1000
PRECISION_MINIMA = 100              # si el GPS del telefono se equivoca mas que esto, la marca se rechaza
RADIO_TIERRA_METROS = 6_371_000     # radio promedio de la Tierra (para la formula de Haversine)
SEGUNDOS_ENTRE_MARCAS = 5 * 60      # minimo 5 minutos entre una marca y la siguiente (evita toques dobles)

# constantes de inicio de sesion
SUPERADMIN_PRINCIPAL = "EMP-004"    # Erin: superadmin fijo, nadie puede quitarle el rol ni eliminarlo
DURACION_SESION = 12 * 3600         # una sesion dura 12 horas (una jornada)
ITERACIONES_CLAVE = 100_000         # cuantas veces se repite el hash (mas veces = mas dificil de adivinar)
LARGO_MINIMO_CLAVE = 8


def es_si(valor) -> bool:
    # un checkbox del formulario llega como "si"; en el JSON se guarda como True
    return valor in (True, "si")


def es_sabado(fecha: date) -> bool:
    # weekday(): 0 = lunes ... 5 = sabado, 6 = domingo
    return fecha.weekday() == 5


# ---------------------------------------------------------------
# LOGS
# ---------------------------------------------------------------
# usamos logging: escribe en consola y en el archivo datos/asistencia.log
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(CARPETA_DATOS / "asistencia.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("asistencia")


# ---------------------------------------------------------------
# PATRON DE DISENO DECORADOR
# ---------------------------------------------------------------
def registrar_log(funcion):
    # decorador: recibe una funcion y devuelve otra que hace lo mismo + escribe en el log
    @wraps(funcion)                      # conserva el nombre original de la funcion
    def envoltura(*args, **kwargs):      # *args y **kwargs reciben cualquier argumento
        log.info(f"Ejecutando: {funcion.__name__}")
        return funcion(*args, **kwargs)
    return envoltura


def medir_tiempo(funcion):
    # decorador: mide cuanto tarda la funcion y lo escribe en el log
    @wraps(funcion)
    def envoltura(*args, **kwargs):
        inicio = time.perf_counter()
        resultado = funcion(*args, **kwargs)
        log.info(f"{funcion.__name__} tardó {time.perf_counter() - inicio:.4f} s")
        return resultado
    return envoltura


# ---------------------------------------------------------------
# EXPRESIONES REGULARES
# ---------------------------------------------------------------
# aplicamos expresiones regulares para validar formatos
PATRON_HORA = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?$")   # HH:MM o HH:MM:SS
PATRON_CORREO = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.]+$")
PATRON_TELEFONO = re.compile(r"^\d{4}-?\d{4}$")                           # 5512-3456 o 55123456
PATRON_NOMBRE = re.compile(r"^[A-Za-zÁÉÍÓÚÜáéíóúüÑñ ]{2,40}$")             # solo letras y espacios
# coordenadas como las copia Google Maps: "14.634915, -90.506882"
PATRON_COORDENADAS = re.compile(r"^(-?\d{1,3}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)$")


def validar_con_patron(valor: str, patron: re.Pattern, campo: str) -> str:
    # cadenas: quitamos espacios sobrantes y validamos con el patron
    valor = " ".join(valor.split())
    if not patron.match(valor):
        raise DatoInvalidoError(f"El campo '{campo}' no es válido: '{valor}'")
    return valor


def separar_coordenadas(texto: str) -> tuple:
    # "14.634915, -90.506882" (copiado de Google Maps) -> (14.634915, -90.506882)
    coincidencia = PATRON_COORDENADAS.match(texto.strip())
    if not coincidencia:
        raise DatoInvalidoError(f"Coordenadas no válidas: '{texto}'. Usa 'latitud, longitud' (ej. 14.634915, -90.506882)")
    # groups() devuelve los dos numeros como texto; float() los convierte a decimal
    latitud, longitud = coincidencia.groups()
    return float(latitud), float(longitud)


def numero_o_none(texto):
    # convierte el texto de un campo oculto a numero; si viene vacio o mal, devuelve None
    # (el telefono puede no mandar ubicacion: eso no es un error del programa, es una anomalia)
    try:
        numero = float(texto)
    except (TypeError, ValueError):
        return None
    # float() tambien acepta "nan" e "inf"; no son coordenadas reales y engañarian las comparaciones
    return numero if math.isfinite(numero) else None


# ---------------------------------------------------------------
# FECHAS Y HORAS
# ---------------------------------------------------------------
def convertir_fecha(texto: str, campo: str = "fecha") -> date:
    # fechas: convierte "2026-10-08" a un objeto date
    try:
        return date.fromisoformat(texto.strip())
    except ValueError:
        raise DatoInvalidoError(f"La {campo} no es válida: '{texto}'")


def hora_a_segundos(hora: str) -> int:
    # convierte "08:15:30" a segundos desde la medianoche
    coincidencia = PATRON_HORA.match(hora.strip())
    if not coincidencia:
        raise DatoInvalidoError(f"Hora inválida: '{hora}' (usa HH:MM o HH:MM:SS)")
    # haciendo uso de una tupla: groups() devuelve (horas, minutos, segundos)
    horas, minutos, segundos = coincidencia.groups()
    return int(horas) * 3600 + int(minutos) * 60 + int(segundos or 0)


def segundos_a_hora(segundos: int) -> str:
    # convierte segundos a texto "HH:MM:SS"
    # divmod(a, b) devuelve una tupla: (division entera, residuo)
    horas, resto = divmod(segundos, 3600)
    minutos, seg = divmod(resto, 60)
    return f"{horas:02d}:{minutos:02d}:{seg:02d}"


def normalizar_hora(hora: str) -> str:
    # deja toda hora con el mismo formato "HH:MM:SS"
    return segundos_a_hora(hora_a_segundos(hora))


def segundos_a_texto(segundos: int) -> str:
    # convierte segundos a texto legible: "8h 05m 30s"
    signo = "-" if segundos < 0 else ""
    horas, resto = divmod(abs(segundos), 3600)
    minutos, seg = divmod(resto, 60)
    return f"{signo}{horas}h {minutos:02d}m {seg:02d}s"


# ---------------------------------------------------------------
# CONTRASEÑAS (hash)
# ---------------------------------------------------------------
def cifrar_clave(clave: str) -> str:
    # nunca guardamos la contraseña real: guardamos su "hash" (huella que no se puede revertir)
    # sal: texto aleatorio distinto para cada usuario, asi dos claves iguales dan hashes distintos
    sal = secrets.token_hex(16)
    resumen = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), bytes.fromhex(sal), ITERACIONES_CLAVE)
    # se guarda "sal$hash" para poder repetir el calculo al iniciar sesion
    return f"{sal}${resumen.hex()}"


def verificar_clave(clave: str, guardado: str) -> bool:
    # repetimos el hash con la misma sal y comparamos con el guardado
    if "$" not in guardado:
        return False
    sal, resumen_guardado = guardado.split("$")
    resumen = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), bytes.fromhex(sal), ITERACIONES_CLAVE)
    # compare_digest compara tardando siempre lo mismo (evita adivinar midiendo el tiempo)
    return hmac.compare_digest(resumen.hex(), resumen_guardado)


def clave_inicial(nombre: str) -> str:
    # contraseña generica de un usuario nuevo o restablecido: su nombre + 1234 (ej. "Erin1234")
    return f"{nombre}1234"
