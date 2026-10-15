# red.py
# todo lo necesario para que el telefono entre a la PC: averiguar la IP y crear el certificado HTTPS
# depende solo de utilidades.py

import shutil
import socket
import subprocess

from utilidades import CARPETA_CERTIFICADO, log

ARCHIVO_CERTIFICADO = CARPETA_CERTIFICADO / "certificado.pem"   # parte publica: se le muestra al navegador
ARCHIVO_CLAVE = CARPETA_CERTIFICADO / "clave.pem"               # parte privada: NUNCA se comparte


# ---------------------------------------------------------------
# IP DE LA PC
# ---------------------------------------------------------------
def ips_locales() -> list:
    # socket (libreria de red de python): todas las IPs que tiene esta PC
    # quitamos las 127.x.x.x porque significan "esta misma maquina" y el telefono no puede usarlas
    nombre_pc = socket.gethostname()
    ips = socket.gethostbyname_ex(nombre_pc)[2]
    return [ip for ip in ips if not ip.startswith("127.")]


def ip_principal() -> str:
    # truco comun: "conectamos" un socket UDP hacia una IP de internet (no se envia nada)
    # y el sistema nos dice que IP usaria para salir: esa es la de la red Wi-Fi activa
    conexion = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        conexion.connect(("8.8.8.8", 80))
        return conexion.getsockname()[0]
    except OSError:
        # sin red: devolvemos la primera IP que tenga la PC (o la propia maquina)
        ips = ips_locales()
        return ips[0] if ips else "127.0.0.1"
    finally:
        conexion.close()


# ---------------------------------------------------------------
# CERTIFICADO HTTPS PROPIO ("autofirmado")
# ---------------------------------------------------------------
def buscar_openssl():
    # shutil.which busca un programa en el PATH (igual que escribirlo en la terminal)
    # openssl viene incluido con Git para Windows
    return shutil.which("openssl") or shutil.which(r"C:\Program Files\Git\usr\bin\openssl.exe")


def preparar_certificado() -> bool:
    # devuelve True si hay certificado listo para usar HTTPS (lo crea la primera vez)
    if ARCHIVO_CERTIFICADO.exists() and ARCHIVO_CLAVE.exists():
        return True
    openssl = buscar_openssl()
    if openssl is None:
        log.error("No se encontró openssl (viene con Git para Windows). Se usará http sin GPS en el teléfono.")
        return False

    CARPETA_CERTIFICADO.mkdir(exist_ok=True)
    # el certificado dice para que direcciones vale: localhost y las IPs actuales de la PC
    direcciones = "DNS:localhost,IP:127.0.0.1" + "".join(f",IP:{ip}" for ip in ips_locales())
    # subprocess.run ejecuta un programa externo, como si lo escribieramos en la terminal
    # (una lista de partes, sin shell: asi ningun texto se interpreta como comando)
    resultado = subprocess.run(
        [openssl, "req", "-x509",                   # crear un certificado autofirmado
         "-newkey", "rsa:2048", "-nodes",           # clave nueva de 2048 bits, sin contraseña
         "-days", "825",                            # vale unos 2 años
         "-keyout", str(ARCHIVO_CLAVE), "-out", str(ARCHIVO_CERTIFICADO),
         "-subj", "/CN=MiniProyecto Asistencia",    # nombre que aparece en el certificado
         "-addext", f"subjectAltName={direcciones}"],
        capture_output=True, text=True,
    )
    if resultado.returncode != 0:
        log.error(f"openssl no pudo crear el certificado: {resultado.stderr.strip()[-300:]}")
        return False
    log.info(f"Certificado HTTPS creado en {CARPETA_CERTIFICADO}")
    return True
