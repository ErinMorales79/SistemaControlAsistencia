# gestor.py  ->  PASO 5 de la ruta de estudio
# GestorAsistencia: guarda trabajadores y registros, maneja archivos,
# historial para deshacer (pila), alertas recientes (cola) y feriados (peticion HTTP)
# aqui esta el CRUD (Crear, Leer, Actualizar, Eliminar) de trabajadores, registros y sucursales
# los metodos que empiezan con _ son de uso interno (solo los usa esta clase)
# depende de calculos.py, modelos.py, sesiones.py, excepciones.py y utilidades.py
# los metodos que reciben "por" revisan los permisos de quien hace el cambio (por=None = el propio sistema)

import asyncio
import threading
from collections import deque
import copy
import json
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import requests     # libreria externa (practica 20): pip install requests

from calculos import (calcular_segundos_trabajados, evaluar_ubicacion, generar_alertas, lunes_de,
                      opciones_de_marca, ultima_hora_marcada)
from excepciones import (AsistenciaError, CredencialesInvalidasError, DatoInvalidoError, DiaNoLaboralError,
                         PermisoDenegadoError, TrabajadorNoEncontradoError)
from modelos import (CLAVES_MARCAS, DiaSemana, Marcacion, RegistroAsistencia, Rol, Sucursal, TipoMarca, Trabajador,
                     dia_de, segundos_entre)
from sesiones import GestorSesiones, es_erin, puede_gestionar, puede_ver, roles_que_puede_dar
from utilidades import (CARPETA_DATOS, LARGO_MINIMO_CLAVE, SEGUNDOS_ENTRE_MARCAS, SUPERADMIN_PRINCIPAL, cifrar_clave,
                        clave_inicial, es_sabado, log, medir_tiempo, registrar_log, segundos_a_texto, verificar_clave)

ARCHIVO_DATOS = CARPETA_DATOS / "datos.json"
ARCHIVO_EJEMPLO = CARPETA_DATOS.parent / "datos_ejemplo.json"
ARCHIVO_EXPORT_JSON = CARPETA_DATOS / "exportacion.json"
ARCHIVO_EXPORT_XML = CARPETA_DATOS / "exportacion.xml"

# API publica y gratuita de dias feriados (GT = Guatemala)
URL_FERIADOS = "https://date.nager.at/api/v3/PublicHolidays/{anio}/{pais}"
PAIS = "GT"


# la API trae los nombres en ingles: aqui los traducimos (ingles -> español)
FERIADOS_EN_ESPANOL = {
    "New Year's Day": "Año Nuevo",
    "Maundy Thursday": "Jueves Santo",
    "Good Friday": "Viernes Santo",
    "Holy Saturday": "Sábado Santo",
    "Easter Sunday": "Domingo de Resurrección",
    "International Workers' Day": "Día del Trabajo",
    "Army Day": "Día del Ejército",
    "Independence Day": "Día de la Independencia",
    "Revolution Day": "Día de la Revolución",
    "All Saints' Day": "Día de Todos los Santos",
    "Christmas Eve": "Nochebuena",
    "Christmas Day": "Navidad",
    "New Year's Eve": "Año Nuevo",
}

MAX_HISTORIAL = 20


class GestorAsistencia:
    # PATRON DE DISENO SINGLETON: solo puede existir UNA instancia del gestor
    _instancia = None

    def __new__(cls):
        # __new__ se ejecuta ANTES de __init__ y es el que crea el objeto
        # si ya existe una instancia, devolvemos esa misma en vez de crear otra
        if cls._instancia is None:
            cls._instancia = super().__new__(cls)
            cls._instancia._iniciado = False
        return cls._instancia

    def __init__(self):
        # evitamos que se reinicien los datos cada vez que se llama GestorAsistencia()
        if self._iniciado:
            return
        self._iniciado = True
        self.trabajadores = {}                          # diccionario: codigo -> Trabajador
        self.registros = []                             # lista de RegistroAsistencia
        self.sucursales = {}                            # diccionario: codigo -> Sucursal
        self.marcaciones = []                           # lista de Marcacion: evidencia de cada intento con GPS
        self.historial = []                             # PILA: ultimo en entrar, primero en salir
        self.alertas_recientes = deque(maxlen=50)       # COLA: guarda solo las 50 alertas mas nuevas
        self.feriados = {}                              # diccionario: fecha -> nombre del feriado
        self.cargar()

    # ---------------------------------------------------------------
    # FICHEROS (JSON)
    # ---------------------------------------------------------------
    @medir_tiempo
    def cargar(self):
        # lee datos/datos.json; si no existe crea datos de ejemplo
        if not ARCHIVO_DATOS.exists():
            log.info("No hay datos guardados, se crean datos de ejemplo")
            self._crear_datos_de_ejemplo()
            return
        try:
            # ficheros: 'with' abre y cierra el archivo automaticamente
            with open(ARCHIVO_DATOS, "r", encoding="utf-8") as archivo:
                datos = json.load(archivo)
            # **d desempaqueta cada diccionario del JSON como argumentos de la clase
            self.trabajadores = {d["codigo"]: Trabajador(**d) for d in datos["trabajadores"]}
            self.registros = [RegistroAsistencia(**d) for d in datos["registros"]]
            # .get(clave, []) porque los datos guardados antes de esta version no tienen sucursales
            self.sucursales = {d["codigo"]: Sucursal(**d) for d in datos.get("sucursales", [])}
            self.marcaciones = [Marcacion(**d) for d in datos.get("marcaciones", [])]
            log.info(f"Datos cargados: {len(self.trabajadores)} trabajadores, {len(self.registros)} registros, "
                     f"{len(self.sucursales)} sucursales")
            self._preparar_usuarios()
        except (json.JSONDecodeError, KeyError, TypeError, AsistenciaError) as error:
            # excepciones: si el archivo esta danado lo respaldamos y empezamos vacio
            log.error(f"No se pudo leer {ARCHIVO_DATOS.name}: {error}")
            ARCHIVO_DATOS.replace(ARCHIVO_DATOS.with_suffix(".danado.json"))
            self.trabajadores, self.registros, self.sucursales, self.marcaciones = {}, [], {}, []

    def _preparar_usuarios(self):
        # trabajadores guardados antes del inicio de sesion no tienen contraseña:
        # se les crea la generica (Nombre1234); y Erin siempre queda como superadmin
        sin_clave = [t for t in self.trabajadores.values() if not t.clave_hash]
        for trabajador in sin_clave:
            trabajador.clave_hash = cifrar_clave(clave_inicial(trabajador.nombre))
        erin = self.trabajadores.get(SUPERADMIN_PRINCIPAL)
        # Erin siempre es superadmin, y un superadmin no tiene sucursal ni horario
        erin_corregido = erin is not None and (erin.rol != Rol.SUPERADMIN or erin.codigo_sucursal or not erin.horario_libre)
        if erin_corregido:
            erin.hacer_superadmin()
        # solo se reescribe el archivo si algo cambio
        if sin_clave or erin_corregido:
            log.info(f"Se crearon contraseñas iniciales para {len(sin_clave)} trabajadores")
            self.guardar()

    def guardar(self):
        # escribe todo en datos/datos.json
        datos = {
            "sucursales": [s.a_diccionario() for s in self.sucursales.values()],
            "trabajadores": [t.a_diccionario() for t in self.trabajadores.values()],
            "registros": [r.a_diccionario() for r in self.registros],
            "marcaciones": [m.a_diccionario() for m in self.marcaciones],
        }
        with open(ARCHIVO_DATOS, "w", encoding="utf-8") as archivo:
            json.dump(datos, archivo, ensure_ascii=False, indent=2)

    # ---------------------------------------------------------------
    # PILA (deshacer)
    # ---------------------------------------------------------------
    def _guardar_en_historial(self, descripcion: str):
        # valor y referencia: deepcopy crea una copia nueva e independiente;
        # sin ella la "foto" apuntaria a las mismas listas y cambiaria junto con ellas
        foto = (descripcion, copy.deepcopy(self.trabajadores), copy.deepcopy(self.registros),
                copy.deepcopy(self.sucursales))
        self.historial.append(foto)              # pila: push (apilar)
        if len(self.historial) > MAX_HISTORIAL:
            self.historial.pop(0)                # quitamos la foto mas vieja

    @registrar_log
    def deshacer(self) -> str:
        if not self.historial:
            raise AsistenciaError("No hay acciones para deshacer")
        # pila: pop saca el ULTIMO elemento que entro (LIFO)
        descripcion, self.trabajadores, self.registros, self.sucursales = self.historial.pop()
        self.guardar()
        return descripcion

    # ---------------------------------------------------------------
    # CRUD TRABAJADORES
    # C = agregar_trabajador   R = buscar_trabajador / trabajadores_ordenados
    # U = actualizar_trabajador   D = eliminar_trabajador
    # ---------------------------------------------------------------
    def _siguiente_codigo(self) -> str:
        # cadenas: de "EMP-007" tomamos el 7 y generamos "EMP-008"
        numeros = [int(codigo.split("-")[1]) for codigo in self.trabajadores]
        return f"EMP-{max(numeros, default=0) + 1:03d}"

    def buscar_trabajador(self, codigo: str) -> Trabajador:
        if codigo not in self.trabajadores:
            raise TrabajadorNoEncontradoError(f"No existe el trabajador con código '{codigo}'")
        return self.trabajadores[codigo]

    def _aplicar_reglas_de_rol(self, datos: dict, por) -> dict:
        # ajusta los datos del formulario segun quien guarda (por = usuario que hace el cambio)
        # por = None significa "el propio sistema" (ej. datos de ejemplo): sin restricciones
        datos = dict(datos)                         # copia: no modificamos el diccionario original
        datos.setdefault("rol", Rol.TRABAJADOR.name)
        if por is None:
            return datos
        if datos["rol"] not in [rol.name for rol in roles_que_puede_dar(por)]:
            raise PermisoDenegadoError("No puedes asignar ese rol")
        if por.rol == Rol.ADMIN:
            # el encargado solo crea y edita gente de SU sucursal
            if not por.codigo_sucursal:
                raise PermisoDenegadoError("No tienes una sucursal asignada")
            datos["codigo_sucursal"] = por.codigo_sucursal
        return datos

    @registrar_log
    def agregar_trabajador(self, datos: dict, por=None) -> Trabajador:
        datos = self._aplicar_reglas_de_rol(datos, por)
        trabajador = Trabajador(codigo=self._siguiente_codigo(), **datos)
        # funcion de orden superior: any recorre y devuelve True si alguno cumple
        if any(t.correo == trabajador.correo for t in self.trabajadores.values()):
            raise DatoInvalidoError(f"Ya existe un trabajador con el correo {trabajador.correo}")
        self._revisar_sucursal(trabajador.codigo_sucursal)
        if es_erin(trabajador):
            trabajador.hacer_superadmin()               # Erin siempre es superadmin
        # contraseña generica: Nombre1234 (guardada como hash)
        trabajador.clave_hash = cifrar_clave(clave_inicial(trabajador.nombre))
        self._guardar_en_historial(f"agregar a {trabajador}")
        self.trabajadores[trabajador.codigo] = trabajador
        self.guardar()
        return trabajador

    @registrar_log
    def actualizar_trabajador(self, codigo: str, datos: dict, por=None) -> Trabajador:
        anterior = self.buscar_trabajador(codigo)
        if por is not None and not puede_gestionar(por, anterior):
            raise PermisoDenegadoError(f"No puedes editar a {anterior}")
        # si el formulario no trae rol (ej. el encargado no lo ve), se conserva el que tenia
        datos = dict(datos)
        if not datos.get("rol"):
            datos["rol"] = anterior.rol.name
        if datos["rol"] != anterior.rol.name:
            datos = self._aplicar_reglas_de_rol(datos, por)
        elif por is not None and por.rol == Rol.ADMIN:
            datos["codigo_sucursal"] = por.codigo_sucursal
        # creamos un trabajador nuevo con el mismo codigo (asi se validan otra vez todos los datos)
        nuevo = Trabajador(codigo=codigo, **datos)
        if any(t.correo == nuevo.correo and t.codigo != codigo for t in self.trabajadores.values()):
            raise DatoInvalidoError(f"Ya existe otro trabajador con el correo {nuevo.correo}")
        self._revisar_sucursal(nuevo.codigo_sucursal)
        # no puede tener asistencias antes de su (nueva) fecha de ingreso
        if any(r.fecha < nuevo.fecha_ingreso for r in self.iterar_registros(codigo)):
            raise DatoInvalidoError("Tiene asistencias antes de esa fecha de ingreso")
        if es_erin(nuevo):
            nuevo.hacer_superadmin()                    # nadie puede destituir a Erin
        nuevo.clave_hash = anterior.clave_hash          # editar los datos no cambia la contraseña
        self._guardar_en_historial(f"editar a {anterior}")
        self.trabajadores[codigo] = nuevo
        self.guardar()
        return nuevo

    @registrar_log
    def eliminar_trabajador(self, codigo: str, por=None) -> Trabajador:
        trabajador = self.buscar_trabajador(codigo)
        if es_erin(trabajador):
            raise PermisoDenegadoError("Nadie puede eliminar a Erin")
        if por is not None and not puede_gestionar(por, trabajador):
            raise PermisoDenegadoError(f"No puedes eliminar a {trabajador}")
        self._guardar_en_historial(f"eliminar a {trabajador}")
        del self.trabajadores[codigo]
        # funcion de orden superior: filter deja solo los registros de los demas
        # (las marcaciones NO se borran: son evidencia; si se usa Deshacer, el trabajador las recupera)
        self.registros = list(filter(lambda r: r.codigo_trabajador != codigo, self.registros))
        GestorSesiones().cerrar_sesiones_de(codigo)     # si estaba conectado, se le cierra la sesion
        self.guardar()
        return trabajador

    def trabajadores_ordenados(self) -> list:
        # sorted con key: ordena por nombre completo
        return sorted(self.trabajadores.values(), key=lambda t: t.nombre_completo)

    def trabajadores_visibles(self, usuario) -> list:
        # orden superior: filter deja solo los trabajadores que ese usuario puede ver
        return list(filter(lambda t: puede_ver(usuario, t), self.trabajadores_ordenados()))

    def empleados_visibles(self, usuario) -> list:
        # igual que trabajadores_visibles pero sin las cuentas de superadmin (no son empleados)
        return [t for t in self.trabajadores_visibles(usuario) if t.es_empleado]

    # ---------------------------------------------------------------
    # INICIO DE SESION Y CONTRASEÑAS
    # ---------------------------------------------------------------
    def autenticar(self, correo: str, clave: str) -> Trabajador:
        # busca al trabajador por su correo (el usuario) y revisa la contraseña
        correo = correo.strip().lower()
        trabajador = next((t for t in self.trabajadores.values() if t.correo == correo), None)
        if trabajador is None or not verificar_clave(clave, trabajador.clave_hash):
            # mismo mensaje en los dos casos: asi nadie averigua que correos existen
            raise CredencialesInvalidasError("Correo o contraseña incorrectos")
        log.info(f"Inicio de sesión: {trabajador} ({trabajador.rol.value})")
        return trabajador

    @registrar_log
    def restablecer_clave(self, codigo: str, por) -> str:
        # un admin devuelve la contraseña de un usuario comun a la generica (Nombre1234)
        trabajador = self.buscar_trabajador(codigo)
        if trabajador.rol != Rol.TRABAJADOR:
            raise PermisoDenegadoError("Solo se restablece la contraseña de usuarios comunes; "
                                       "cada admin cambia la suya en 'Mi cuenta'")
        if not puede_gestionar(por, trabajador):
            raise PermisoDenegadoError(f"No puedes restablecer la contraseña de {trabajador}")
        nueva = clave_inicial(trabajador.nombre)
        trabajador.clave_hash = cifrar_clave(nueva)
        GestorSesiones().cerrar_sesiones_de(codigo)     # debe volver a entrar con la nueva
        self.guardar()
        return nueva

    @registrar_log
    def cambiar_mi_clave(self, usuario, actual: str, nueva: str, confirmacion: str):
        # solo los admins cambian su propia contraseña (decision 6)
        if not usuario.es_admin:
            raise PermisoDenegadoError("Pide a tu encargado que restablezca tu contraseña")
        if not verificar_clave(actual, usuario.clave_hash):
            raise CredencialesInvalidasError("La contraseña actual no es correcta")
        if len(nueva) < LARGO_MINIMO_CLAVE:
            raise DatoInvalidoError(f"La nueva contraseña debe tener al menos {LARGO_MINIMO_CLAVE} caracteres")
        if nueva != confirmacion:
            raise DatoInvalidoError("La confirmación no coincide con la nueva contraseña")
        if nueva == actual:
            raise DatoInvalidoError("La nueva contraseña debe ser distinta de la actual")
        usuario.clave_hash = cifrar_clave(nueva)
        self.guardar()

    def puestos_en_uso(self) -> set:
        # conjunto: los puestos sin repetir
        return {t.puesto for t in self.trabajadores.values()}

    def _revisar_sucursal(self, codigo_sucursal: str):
        # un trabajador puede quedar sin sucursal (""), pero si trae una, debe existir
        if codigo_sucursal and codigo_sucursal not in self.sucursales:
            raise DatoInvalidoError(f"No existe la sucursal con código '{codigo_sucursal}'")

    # ---------------------------------------------------------------
    # CRUD SUCURSALES
    # C = agregar_sucursal   R = buscar_sucursal / sucursales_ordenadas / trabajadores_de_sucursal
    # U = actualizar_sucursal   D = eliminar_sucursal
    # ---------------------------------------------------------------
    def _siguiente_codigo_sucursal(self) -> str:
        # igual que los trabajadores: de "SUC-002" sacamos el 2 y generamos "SUC-003"
        numeros = [int(codigo.replace("SUC-", "")) for codigo in self.sucursales]
        return f"SUC-{max(numeros, default=0) + 1:03d}"

    def buscar_sucursal(self, codigo: str) -> Sucursal:
        if codigo not in self.sucursales:
            raise AsistenciaError(f"No existe la sucursal con código '{codigo}'")
        return self.sucursales[codigo]

    def _revisar_nombre_sucursal(self, sucursal: Sucursal):
        # no puede haber dos sucursales con el mismo nombre (sin importar mayusculas)
        for otra in self.sucursales.values():
            if otra.codigo != sucursal.codigo and otra.nombre.lower() == sucursal.nombre.lower():
                raise DatoInvalidoError(f"Ya existe una sucursal llamada '{otra.nombre}'")

    @registrar_log
    def agregar_sucursal(self, datos: dict) -> Sucursal:
        sucursal = Sucursal(codigo=self._siguiente_codigo_sucursal(), **datos)
        self._revisar_nombre_sucursal(sucursal)
        self._guardar_en_historial(f"agregar la sucursal {sucursal.nombre}")
        self.sucursales[sucursal.codigo] = sucursal
        self.guardar()
        return sucursal

    @registrar_log
    def actualizar_sucursal(self, codigo: str, datos: dict) -> Sucursal:
        anterior = self.buscar_sucursal(codigo)
        # igual que con los trabajadores: creamos una nueva con el mismo codigo para validar todo otra vez
        nueva = Sucursal(codigo=codigo, **datos)
        self._revisar_nombre_sucursal(nueva)
        self._guardar_en_historial(f"editar la sucursal {anterior.nombre}")
        self.sucursales[codigo] = nueva
        self.guardar()
        return nueva

    @registrar_log
    def eliminar_sucursal(self, codigo: str) -> Sucursal:
        sucursal = self.buscar_sucursal(codigo)
        # regla: no se borra una sucursal que todavia tiene trabajadores asignados
        asignados = self.trabajadores_de_sucursal(codigo)
        if asignados:
            nombres = ", ".join(t.nombre_completo for t in asignados)
            raise AsistenciaError(f"Primero reasigna a: {nombres}")
        self._guardar_en_historial(f"eliminar la sucursal {sucursal.nombre}")
        del self.sucursales[codigo]
        self.guardar()
        return sucursal

    def sucursales_ordenadas(self) -> list:
        # orden superior: primero las bodegas y luego las tiendas, cada grupo por nombre
        return sorted(self.sucursales.values(), key=lambda s: (s.tipo.name, s.nombre))

    def trabajadores_de_sucursal(self, codigo: str) -> list:
        # lista por comprension: los trabajadores asignados a esa sucursal, ordenados por nombre
        return [t for t in self.trabajadores_ordenados() if t.codigo_sucursal == codigo]

    # ---------------------------------------------------------------
    # CRUD REGISTROS DE ASISTENCIA
    # C = registrar_asistencia   R = buscar_registro / iterar_registros
    # U = actualizar_registro    D = eliminar_registro
    # ---------------------------------------------------------------
    def _revisar_permiso_registro(self, codigo_trabajador: str, por):
        # para corregir marcas a mano hay que poder gestionar a ese trabajador
        trabajador = self.buscar_trabajador(codigo_trabajador)
        if por is not None and not puede_gestionar(por, trabajador):
            raise PermisoDenegadoError(f"No puedes modificar la asistencia de {trabajador}")
        return trabajador

    @registrar_log
    def registrar_asistencia(self, datos: dict, por=None) -> tuple:
        # CREATE: guarda las marcas de un dia (si ese dia ya existia, se reemplaza)
        return self._guardar_registro(datos, por=por)

    @registrar_log
    def actualizar_registro(self, codigo_original: str, fecha_original: str, datos: dict, por=None) -> tuple:
        # UPDATE: cambia un registro; si se cambio la fecha o el trabajador, se borra el original
        original = self.buscar_registro(codigo_original, fecha_original)
        if original is None:
            raise AsistenciaError("No se encontró el registro que querías editar")
        self._revisar_permiso_registro(original.codigo_trabajador, por)
        return self._guardar_registro(datos, quitar=original, por=por)

    def _guardar_registro(self, datos: dict, quitar=None, por=None) -> tuple:
        # parte comun de crear y actualizar: valida, guarda y revisa alertas
        trabajador = self._revisar_permiso_registro(datos.get("codigo_trabajador", ""), por)
        if trabajador.horario_libre:
            raise AsistenciaError(f"{trabajador} tiene horario libre, no marca asistencia")
        registro = RegistroAsistencia(**datos)
        if registro.fecha > date.today():
            raise DatoInvalidoError("No se puede registrar asistencia en una fecha futura")
        if registro.fecha < trabajador.fecha_ingreso:
            raise DatoInvalidoError(f"{trabajador} ingresó a la empresa el {trabajador.fecha_ingreso:%d/%m/%Y}")
        if registro.dia == DiaSemana.SABADO and not trabajador.trabaja_sabado:
            raise DiaNoLaboralError(f"{trabajador} no trabaja los sábados")

        self._guardar_en_historial(f"registro de {trabajador} del {registro.fecha:%d/%m}")
        # quitamos el registro de ese mismo dia (si habia) y el original que se esta editando
        self.registros = [r for r in self.registros
                          if r is not quitar
                          and not (r.codigo_trabajador == registro.codigo_trabajador and r.fecha == registro.fecha)]
        self.registros.append(registro)
        self.guardar()

        # CALLBACK: le pasamos nuestro metodo para que nos avise de cada alerta
        alertas = generar_alertas(registro, trabajador, hoy=date.today(), al_generar_alerta=self._al_generar_alerta)
        return registro, alertas

    def buscar_registro(self, codigo: str, fecha: str):
        # devuelve el registro de ese trabajador en esa fecha, o None
        return next((r for r in self.registros if r.codigo_trabajador == codigo and r.fecha.isoformat() == fecha), None)

    def _al_generar_alerta(self, trabajador, registro, alerta):
        # este metodo es el callback: se ejecuta por cada alerta encontrada
        texto = f"{trabajador.nombre_completo} · {registro.dia.value} {registro.fecha:%d/%m}: {alerta.detalle}"
        # cola: entra por el final; guardamos tambien el codigo para filtrar por sucursal
        self.alertas_recientes.append((alerta.tipo, texto, trabajador.codigo))
        log.warning(f"ALERTA {alerta.tipo.name}: {texto}")

    @registrar_log
    def eliminar_registro(self, codigo: str, fecha: str, por=None):
        registro = self.buscar_registro(codigo, fecha)
        if registro is None:
            raise AsistenciaError("No se encontró ese registro")
        self._revisar_permiso_registro(codigo, por)
        self._guardar_en_historial(f"eliminar registro del {fecha}")
        self.registros.remove(registro)
        self.guardar()

    def iterar_registros(self, codigo=None, lunes=None):
        # GENERADOR (iteraciones): con yield entrega los registros uno por uno
        for registro in sorted(self.registros, key=lambda r: (r.fecha, r.entrada)):
            if codigo and registro.codigo_trabajador != codigo:
                continue
            if lunes and lunes_de(registro.fecha) != lunes:
                continue
            yield registro

    def feriados_de_semana(self, lunes: date) -> dict:
        # feriados entre el lunes y el sabado de esa semana
        sabado = lunes + timedelta(days=5)
        return {fecha: nombre for fecha, nombre in self.feriados.items() if lunes <= fecha <= sabado}

    # ---------------------------------------------------------------
    # MARCAR ASISTENCIA CON UBICACION (Fase 3)
    # ---------------------------------------------------------------
    def opciones_de_hoy(self, usuario, hoy: date) -> list:
        # que botones de marca le tocan hoy al usuario (lista vacia = no puede marcar)
        if not usuario.es_empleado or usuario.horario_libre or hoy.weekday() == 6:
            return []
        if es_sabado(hoy) and not usuario.trabaja_sabado:
            return []
        return opciones_de_marca(self.buscar_registro(usuario.codigo, hoy.isoformat()), es_sabado(hoy))

    @registrar_log
    def marcar_asistencia(self, usuario, tipo_marca: str, latitud, longitud, precision, ahora=None) -> Marcacion:
        # el empleado marca desde su telefono: la HORA la pone el servidor y la UBICACION decide
        # ahora: solo se pasa en las pruebas; normalmente es la hora actual del servidor
        ahora = ahora or datetime.now()
        hoy = ahora.date()
        hora = ahora.strftime("%H:%M:%S")

        # 1) reglas que no son anomalias sino errores (el boton ni siquiera deberia aparecer)
        if not usuario.es_empleado or usuario.horario_libre:
            raise AsistenciaError("Tu cuenta no marca asistencia")
        dia_de(hoy)                                        # si es domingo lanza DiaNoLaboralError
        if es_sabado(hoy) and not usuario.trabaja_sabado:
            raise DiaNoLaboralError("No trabajas los sábados")
        try:
            marca = TipoMarca[tipo_marca]
        except KeyError:
            raise DatoInvalidoError(f"Marca desconocida: '{tipo_marca}'")
        registro = self.buscar_registro(usuario.codigo, hoy.isoformat())
        opciones = opciones_de_marca(registro, es_sabado(hoy))
        if marca not in opciones:
            if not opciones:
                raise AsistenciaError("Ya marcaste tu salida de hoy")
            raise AsistenciaError(f"Ahora te toca marcar: {' o '.join(o.etiqueta for o in opciones)}")
        # regla de 5 minutos entre marcas (evita toques dobles)
        if registro and segundos_entre(ultima_hora_marcada(registro), hora) < SEGUNDOS_ENTRE_MARCAS:
            raise AsistenciaError("Espera al menos 5 minutos entre una marca y la siguiente")

        # 2) evaluamos la ubicacion contra SU sucursal y guardamos la evidencia con la "foto" de la sucursal
        sucursal = self.sucursales.get(usuario.codigo_sucursal)
        anomalia, distancia = evaluar_ubicacion(sucursal, latitud, longitud, precision)
        marcacion = Marcacion(
            codigo_trabajador=usuario.codigo, fecha_hora=ahora.isoformat(timespec="seconds"), tipo_marca=marca.name,
            latitud=latitud, longitud=longitud, precision=precision,
            sucursal_codigo=sucursal.codigo if sucursal else "", sucursal_nombre=sucursal.nombre if sucursal else "",
            sucursal_latitud=sucursal.latitud if sucursal else None, sucursal_longitud=sucursal.longitud if sucursal else None,
            sucursal_radio=sucursal.radio_metros if sucursal else None,
            distancia=distancia, anomalia=anomalia.name if anomalia else "",
        )
        self.marcaciones.append(marcacion)

        # 3a) rechazada: no cuenta como asistencia; se avisa con el callback
        if anomalia:
            self._al_detectar_anomalia(usuario, marcacion)
            self.guardar()
            return marcacion

        # 3b) valida: se escribe la hora en el registro del dia (lo crea si es la entrada)
        datos = registro.a_diccionario() if registro else {"codigo_trabajador": usuario.codigo, "fecha": hoy.isoformat()}
        datos[marca.campo] = hora
        self._guardar_registro(datos)                      # valida el orden, guarda y revisa alertas
        return marcacion

    def _al_detectar_anomalia(self, trabajador, marcacion):
        # CALLBACK de anomalias: igual que _al_generar_alerta, va a la cola de alertas y al log
        lugar = f"a {marcacion.distancia} m de {marcacion.sucursal_nombre}" if marcacion.distancia is not None else ""
        texto = (f"{trabajador.nombre_completo} · {marcacion.tipo_marca.etiqueta} {marcacion.fecha_hora:%d/%m %H:%M}: "
                 f"{marcacion.anomalia.etiqueta} {lugar}").strip()
        self.alertas_recientes.append((marcacion.anomalia, texto, trabajador.codigo))
        log.warning(f"ANOMALIA {marcacion.anomalia.name}: {texto} | ubicacion: {marcacion.latitud}, {marcacion.longitud} "
                    f"(precision {marcacion.precision} m)")

    def anomalias_visibles(self, usuario, lunes: date) -> list:
        # marcas rechazadas de esa semana que el usuario puede ver (decision 17), de la mas nueva a la mas vieja
        anomalias = [m for m in self.marcaciones
                     if not m.valida and lunes_de(m.fecha_hora.date()) == lunes
                     and m.codigo_trabajador in self.trabajadores
                     and puede_ver(usuario, self.trabajadores[m.codigo_trabajador])]
        return sorted(anomalias, key=lambda m: m.fecha_hora, reverse=True)

    # ---------------------------------------------------------------
    # PETICIONES HTTP (feriados)
    # ---------------------------------------------------------------
    def cargar_feriados_en_segundo_plano(self, al_terminar=None):
        # usamos un hilo para no detener el servidor mientras se descarga
        # target = funcion que corre en el hilo; daemon=True = el hilo se cierra junto con el programa
        hilo = threading.Thread(target=self._descargar_feriados, args=(date.today().year, al_terminar), daemon=True)
        hilo.start()

    def _descargar_feriados(self, anio: int, al_terminar=None):
        url = URL_FERIADOS.format(anio=anio, pais=PAIS)
        try:
            # peticion HTTP GET con requests (practica 20); timeout = segundos maximos de espera
            respuesta = requests.get(url, timeout=5)
            # si la API respondio con error (404, 500...) esto lanza una excepcion
            respuesta.raise_for_status()
            datos = respuesta.json()       # convierte el JSON de la respuesta a lista de diccionarios
            self.feriados = {date.fromisoformat(f["date"]): FERIADOS_EN_ESPANOL.get(f["localName"], f["localName"]) for f in datos}
            log.info(f"Feriados {anio} descargados desde {url}")
        except (requests.RequestException, KeyError, ValueError) as error:
            # RequestException atrapa: sin internet, tiempo agotado, 404/500 y respuesta que no es JSON
            log.warning(f"No se pudieron descargar los feriados (se sigue sin ellos): {error}")
        finally:
            # callback: avisamos que terminamos, haya salido bien o mal
            if al_terminar:
                al_terminar(len(self.feriados))

    # ---------------------------------------------------------------
    # EXPORTAR JSON Y XML (asincronia)
    # ---------------------------------------------------------------
    def _filas_de_reporte(self) -> list:
        # una fila (diccionario) por registro, lista para escribir en JSON o XML
        filas = []
        for registro in self.iterar_registros():
            trabajador = self.trabajadores[registro.codigo_trabajador]
            filas.append({
                "codigo": trabajador.codigo,
                "trabajador": trabajador.nombre_completo,
                "puesto": trabajador.puesto.value,
                "fecha": registro.fecha.isoformat(),
                "dia": registro.dia.value,
                **registro.a_diccionario(),     # ** mete aqui todas las claves de ese diccionario
                "total": segundos_a_texto(calcular_segundos_trabajados(registro)),
                "alertas": [a.detalle for a in generar_alertas(registro, trabajador)],
            })
        return filas

    async def _exportar_json(self, filas: list):
        texto = json.dumps({"generado": datetime.now().isoformat(timespec="seconds"), "registros": filas},
                           ensure_ascii=False, indent=2)
        # asyncio.to_thread escribe el archivo sin bloquear las otras tareas
        await asyncio.to_thread(ARCHIVO_EXPORT_JSON.write_text, texto, encoding="utf-8")
        log.info(f"Exportado {ARCHIVO_EXPORT_JSON.name}")

    async def _exportar_xml(self, filas: list):
        # xml: construimos el arbol con ElementTree
        raiz = ET.Element("asistencia", generado=datetime.now().isoformat(timespec="seconds"))
        for fila in filas:
            nodo = ET.SubElement(raiz, "registro", codigo=fila["codigo"], fecha=fila["fecha"])
            for clave in ("trabajador", "puesto", "dia", *CLAVES_MARCAS, "total"):
                ET.SubElement(nodo, clave).text = fila[clave]
            nodo_alertas = ET.SubElement(nodo, "alertas")
            for detalle in fila["alertas"]:
                ET.SubElement(nodo_alertas, "alerta").text = detalle
        arbol = ET.ElementTree(raiz)
        ET.indent(arbol)
        await asyncio.to_thread(arbol.write, ARCHIVO_EXPORT_XML, encoding="utf-8", xml_declaration=True)
        log.info(f"Exportado {ARCHIVO_EXPORT_XML.name}")

    async def _exportar_todo(self):
        filas = self._filas_de_reporte()
        # asincronia: gather ejecuta las dos exportaciones al mismo tiempo
        await asyncio.gather(self._exportar_json(filas), self._exportar_xml(filas))

    @registrar_log          # dos decoradores: primero se aplica medir_tiempo, luego registrar_log
    @medir_tiempo
    def exportar(self):
        # asyncio.run arranca las tareas asincronas desde codigo normal
        asyncio.run(self._exportar_todo())

    # ---------------------------------------------------------------
    # DATOS DE EJEMPLO (leidos del fichero datos_ejemplo.json)
    # ---------------------------------------------------------------
    def _crear_datos_de_ejemplo(self):
        if not ARCHIVO_EJEMPLO.exists():
            log.warning(f"No existe {ARCHIVO_EJEMPLO.name}, se empieza sin datos")
            return
        # ficheros + json: leemos el archivo de ejemplo
        with open(ARCHIVO_EJEMPLO, "r", encoding="utf-8") as archivo:
            ejemplo = json.load(archivo)

        # 1) primero las sucursales (los trabajadores las necesitan); .get por si el archivo no trae
        for datos_sucursal in ejemplo.get("sucursales", []):
            self.agregar_sucursal(datos_sucursal)

        # 2) agregamos los trabajadores y guardamos su codigo dentro de cada item
        for item in ejemplo["trabajadores"]:
            item["codigo"] = self.agregar_trabajador(item["datos"]).codigo

        # 3) recorremos las semanas, los dias (lunes a sabado) y los trabajadores
        hoy = date.today()
        for semanas_atras in range(ejemplo["semanas_de_ejemplo"]):
            lunes = lunes_de(hoy) - timedelta(weeks=semanas_atras)
            for numero in range(6):                 # 0 = lunes ... 5 = sabado
                fecha = lunes + timedelta(days=numero)
                if fecha > hoy:
                    break
                for item in ejemplo["trabajadores"]:
                    marcas = self._marcas_de_ejemplo(item, semanas_atras, fecha)
                    if marcas:                      # None = ese dia no vino
                        self.registrar_asistencia({"codigo_trabajador": item["codigo"], "fecha": fecha.isoformat(), **marcas})
        # las acciones de ejemplo no se pueden deshacer
        self.historial.clear()
        log.info(f"Datos de ejemplo cargados desde {ARCHIVO_EJEMPLO.name}")

    def _marcas_de_ejemplo(self, item: dict, semanas_atras: int, fecha: date):
        # marcas de ese dia: las de un dia especial, las del sabado o las de siempre
        dia = dia_de(fecha).name
        for especial in item.get("dias_especiales", []):
            if especial["semanas_atras"] == semanas_atras and especial["dia"] == dia:
                return especial.get("marcas")       # si no tiene "marcas" es una falta
        if es_sabado(fecha):
            return item.get("marcas_sabado")        # None si no trabaja sabados
        return item.get("marcas_tipicas")           # None si no marca asistencia (horario libre)
