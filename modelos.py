# modelos.py
# enumeraciones y clases principales: Persona, Trabajador y RegistroAsistencia
# depende de excepciones.py y utilidades.py

from collections import namedtuple
from datetime import datetime
from enum import Enum

from excepciones import DatoInvalidoError, DiaNoLaboralError, HorarioInvalidoError
from utilidades import (
    ALMUERZO_SEGUNDOS, HORA_ENTRADA_DEFECTO, HORA_SALIDA_DEFECTO,
    PATRON_CORREO, PATRON_NOMBRE, PATRON_TELEFONO, RADIO_DEFECTO, RADIO_MAXIMO, RADIO_MINIMO,
    convertir_fecha, es_sabado, es_si, hora_a_segundos, normalizar_hora, validar_con_patron,
)


# ---------------------------------------------------------------
# ENUMERACIONES
# ---------------------------------------------------------------
class DiaSemana(Enum):
    # aplicamos enumeraciones: dias laborales (el domingo nadie trabaja)
    LUNES = "Lunes"
    MARTES = "Martes"
    MIERCOLES = "Miércoles"
    JUEVES = "Jueves"
    VIERNES = "Viernes"
    SABADO = "Sábado"


def dia_de(fecha) -> DiaSemana:
    # devuelve el dia de la semana de una fecha; el domingo no se permite
    numero = fecha.weekday()            # 0 = lunes ... 6 = domingo
    if numero == 6:
        raise DiaNoLaboralError(f"El {fecha:%d/%m/%Y} es domingo, nadie trabaja los domingos")
    # el enum se puede recorrer como lista: posicion 0 = LUNES ... 5 = SABADO
    return list(DiaSemana)[numero]


class Puesto(Enum):
    # aplicamos enumeraciones: puestos disponibles en la empresa
    GERENTE = "Gerente"
    ADMINISTRADOR = "Administrador"
    CONTADOR = "Contador"
    VENDEDOR = "Vendedor"
    BODEGUERO = "Bodeguero"
    DESARROLLADOR = "Desarrollador"
    RECEPCIONISTA = "Recepcionista"
    REPARTIDOR = 'Repartidor'


class TipoSucursal(Enum):
    # aplicamos enumeraciones: tipos de localizacion de la empresa
    BODEGA = "Bodega"
    TIENDA = "Tienda"


class TipoMarca(Enum):
    # enumeracion con tuplas: (campo del RegistroAsistencia donde se guarda, texto del boton)
    ENTRADA = ("entrada", "Entrada")
    SALIDA_ALMUERZO = ("salida_almuerzo", "Salida a almorzar")
    REGRESO_ALMUERZO = ("regreso_almuerzo", "Regreso de almuerzo")
    SALIDA = ("salida", "Salida")

    def __init__(self, campo, etiqueta):
        self.campo = campo
        self.etiqueta = etiqueta


class TipoAnomalia(Enum):
    # por que se rechazo una marca: (texto que se muestra, color de bootstrap)
    FUERA_DE_SUCURSAL = ("Fuera de su sucursal", "danger")
    UBICACION_IMPRECISA = ("Ubicación imprecisa", "warning")
    SIN_UBICACION = ("Sin ubicación", "secondary")
    SIN_SUCURSAL = ("Sin sucursal asignada", "dark")

    def __init__(self, etiqueta, color):
        self.etiqueta = etiqueta
        self.color = color


class Rol(Enum):
    # aplicamos enumeraciones: permisos dentro del sistema (no es lo mismo que el puesto)
    SUPERADMIN = "Superadmin"       # ve y maneja toda la empresa
    ADMIN = "Admin"                 # encargado: solo su sucursal
    TRABAJADOR = "Trabajador"       # solo marca y ve su propio historial


class TipoAlerta(Enum):
    # enumeracion con tuplas: (texto que se muestra, color de bootstrap)
    LLEGADA_TARDE = ("Llegada tarde", "warning")
    SALIDA_TEMPRANA = ("Salida anticipada", "info")
    JORNADA_INCOMPLETA = ("Jornada incompleta", "danger")
    ALMUERZO_EXTENDIDO = ("Almuerzo extendido", "secondary")
    REGISTRO_INCOMPLETO = ("Marcas incompletas", "dark")

    def __init__(self, etiqueta, color):
        # cada valor del enum guarda su etiqueta y su color
        self.etiqueta = etiqueta
        self.color = color


class EstadoJornada(Enum):
    # enumeracion: como termino (o va) la jornada de un dia
    COMPLETA = ("Jornada completa", "success", "check-circle-fill")
    INCOMPLETA = ("Jornada incompleta", "danger", "x-circle-fill")
    EN_CURSO = ("Jornada en curso", "primary", "hourglass-split")
    LIBRE = ("Horario libre", "info", "infinity")

    def __init__(self, etiqueta, color, icono):
        # igual que TipoAlerta: separamos la tupla en 3 atributos
        self.etiqueta = etiqueta
        self.color = color
        self.icono = icono


# haciendo uso de una tupla con nombre: cada alerta tiene tipo y detalle
# se usa como alerta.tipo y alerta.detalle (en vez de alerta[0] y alerta[1])
Alerta = namedtuple("Alerta", ["tipo", "detalle"])


# tupla con los nombres de las 4 marcas del dia (en orden)
CLAVES_MARCAS = ("entrada", "salida_almuerzo", "regreso_almuerzo", "salida")
NOMBRES_MARCAS = ("Entrada", "Salida a almorzar", "Regreso de almuerzo", "Salida")


def segundos_entre(entrada: str, salida: str) -> int:
    # segundos que hay entre dos horas "HH:MM:SS"
    return hora_a_segundos(salida) - hora_a_segundos(entrada)


# ---------------------------------------------------------------
# CLASES Y HERENCIA
# ---------------------------------------------------------------
class Persona:
    # clase base con los datos generales de cualquier persona
    def __init__(self, nombre: str, apellido: str, correo: str, telefono: str):
        # cadenas: validamos y damos formato (title = primera letra en mayuscula)
        self.nombre = validar_con_patron(nombre, PATRON_NOMBRE, "nombre").title()
        self.apellido = validar_con_patron(apellido, PATRON_NOMBRE, "apellido").title()
        self.correo = validar_con_patron(correo, PATRON_CORREO, "correo").lower()
        self.telefono = validar_con_patron(telefono, PATRON_TELEFONO, "teléfono")

    @property   # se usa como atributo: persona.nombre_completo (sin parentesis)
    def nombre_completo(self) -> str:
        return f"{self.nombre} {self.apellido}"

    def __str__(self):
        # lo que se muestra al hacer print(persona) o f"{persona}"
        return self.nombre_completo



class Trabajador(Persona):
    # aplicamos herencia: Trabajador es una Persona con datos laborales extra
    def __init__(self, codigo, nombre, apellido, correo, telefono, puesto, fecha_ingreso,
                 hora_entrada=HORA_ENTRADA_DEFECTO, hora_salida=HORA_SALIDA_DEFECTO, horario_libre=False,
                 trabaja_sabado=False, sabado_entrada="", sabado_salida="", codigo_sucursal="",
                 rol="TRABAJADOR", clave_hash=""):
        # super() ejecuta el constructor de Persona
        super().__init__(nombre, apellido, correo, telefono)
        self.codigo = codigo
        # sucursal donde trabaja ("" = sin asignar); el gestor revisa que exista
        self.codigo_sucursal = codigo_sucursal
        # inicio de sesion: el usuario es su correo; la contraseña se guarda como hash
        try:
            self.rol = Rol[rol]
        except KeyError:
            raise DatoInvalidoError(f"Rol desconocido: '{rol}'")
        self.clave_hash = clave_hash
        self.fecha_ingreso = convertir_fecha(fecha_ingreso, "fecha de ingreso")
        # buscamos el puesto por su nombre: Puesto["GERENTE"] -> Puesto.GERENTE
        try:
            self.puesto = Puesto[puesto]
        except KeyError:
            raise DatoInvalidoError(f"Puesto desconocido: '{puesto}'")

        self.horario_libre = es_si(horario_libre)
        self.trabaja_sabado = es_si(trabaja_sabado)
        # las horas quedan vacias si no aplican (horario libre o no trabaja sabados)
        self.hora_entrada = self.hora_salida = self.sabado_entrada = self.sabado_salida = ""

        # un superadmin es una cuenta de administracion, no un empleado:
        # no tiene sucursal ni horario (como horario libre), asi que no marca asistencia
        if self.rol == Rol.SUPERADMIN:
            self.hacer_superadmin()
            return

        if not self.horario_libre:
            self.hora_entrada, self.hora_salida = validar_horario(hora_entrada, hora_salida, "de lunes a viernes")
            if self.jornada_semana <= 0:
                raise HorarioInvalidoError("De lunes a viernes la salida debe ser más de 1 hora después de la entrada (por el almuerzo)")
            if self.trabaja_sabado:
                self.sabado_entrada, self.sabado_salida = validar_horario(sabado_entrada, sabado_salida, "del sábado")

    def hacer_superadmin(self):
        # convierte la cuenta en superadmin: sin sucursal, sin horario y sin sabados
        self.rol = Rol.SUPERADMIN
        self.horario_libre = True
        self.trabaja_sabado = False
        self.codigo_sucursal = ""
        self.hora_entrada = self.hora_salida = self.sabado_entrada = self.sabado_salida = ""

    @property
    def es_admin(self) -> bool:
        # superadmin y admin pueden entrar a las paginas de administracion
        return self.rol in (Rol.SUPERADMIN, Rol.ADMIN)

    @property
    def es_empleado(self) -> bool:
        # los superadmins son cuentas de administracion: no cuentan como empleados
        return self.rol != Rol.SUPERADMIN

    @property
    def jornada_semana(self) -> int:
        # segundos que debe trabajar de lunes a viernes: (salida - entrada) - almuerzo
        if self.horario_libre:
            return 0
        return segundos_entre(self.hora_entrada, self.hora_salida) - ALMUERZO_SEGUNDOS

    @property
    def jornada_sabado(self) -> int:
        # segundos que debe trabajar el sabado (sin almuerzo)
        if self.horario_libre or not self.trabaja_sabado:
            return 0
        return segundos_entre(self.sabado_entrada, self.sabado_salida)

    @property
    def horas_de_horario(self) -> int:
        # cuanto suma su horario en toda la semana (para compararlo con las 44 horas)
        return self.jornada_semana * 5 + self.jornada_sabado

    def jornada_del_dia(self, fecha) -> int:
        # segundos que le toca trabajar esa fecha
        return self.jornada_sabado if es_sabado(fecha) else self.jornada_semana

    def horario_del_dia(self, fecha) -> tuple:
        # (entrada, salida) que le toca esa fecha
        if es_sabado(fecha):
            return self.sabado_entrada, self.sabado_salida
        return self.hora_entrada, self.hora_salida

    def a_diccionario(self) -> dict:
        # haciendo uso de un diccionario para poder guardarlo en JSON
        return {
            "codigo": self.codigo,
            "nombre": self.nombre,
            "apellido": self.apellido,
            "correo": self.correo,
            "telefono": self.telefono,
            "puesto": self.puesto.name,
            "fecha_ingreso": self.fecha_ingreso.isoformat(),
            "hora_entrada": self.hora_entrada,
            "hora_salida": self.hora_salida,
            "horario_libre": self.horario_libre,
            "trabaja_sabado": self.trabaja_sabado,
            "sabado_entrada": self.sabado_entrada,
            "sabado_salida": self.sabado_salida,
            "codigo_sucursal": self.codigo_sucursal,
            "rol": self.rol.name,
            "clave_hash": self.clave_hash,
        }


class Sucursal:
    # una localizacion de la empresa (la bodega o una tienda) con su punto en el mapa
    def __init__(self, codigo, nombre, tipo, direccion, latitud, longitud, radio_metros=RADIO_DEFECTO):
        self.codigo = codigo
        # cadenas: quitamos espacios sobrantes
        self.nombre = " ".join(nombre.split())
        if not 2 <= len(self.nombre) <= 60:
            raise DatoInvalidoError("El nombre de la sucursal debe tener entre 2 y 60 caracteres")
        try:
            self.tipo = TipoSucursal[tipo]
        except KeyError:
            raise DatoInvalidoError(f"Tipo de sucursal desconocido: '{tipo}'")
        self.direccion = " ".join(direccion.split())

        # coordenadas: la latitud va de -90 a 90 y la longitud de -180 a 180
        self.latitud = float(latitud)
        self.longitud = float(longitud)
        if not -90 <= self.latitud <= 90 or not -180 <= self.longitud <= 180:
            raise DatoInvalidoError("Las coordenadas están fuera del mapa (latitud -90 a 90, longitud -180 a 180)")

        # radio: cuantos metros alrededor del punto cuentan como "estar en la sucursal"
        try:
            self.radio_metros = int(radio_metros)
        except ValueError:
            raise DatoInvalidoError(f"El radio debe ser un número entero de metros: '{radio_metros}'")
        if not RADIO_MINIMO <= self.radio_metros <= RADIO_MAXIMO:
            raise DatoInvalidoError(f"El radio debe estar entre {RADIO_MINIMO} y {RADIO_MAXIMO} metros")

    @property
    def coordenadas(self) -> str:
        # texto "latitud, longitud" igual al que copia Google Maps
        return f"{self.latitud}, {self.longitud}"

    @property
    def url_mapa(self) -> str:
        # mapa de Google embebido (para un <iframe>): no necesita clave ni cuenta
        return f"https://maps.google.com/maps?q={self.latitud},{self.longitud}&z=17&output=embed"

    @property
    def url_google_maps(self) -> str:
        # enlace para abrir el punto en Google Maps (pagina o app del telefono)
        return f"https://www.google.com/maps?q={self.latitud},{self.longitud}"

    def __str__(self):
        return f"{self.nombre} ({self.tipo.value})"

    def a_diccionario(self) -> dict:
        return {
            "codigo": self.codigo,
            "nombre": self.nombre,
            "tipo": self.tipo.name,
            "direccion": self.direccion,
            "latitud": self.latitud,
            "longitud": self.longitud,
            "radio_metros": self.radio_metros,
        }


def validar_horario(entrada: str, salida: str, cuando: str) -> tuple:
    # revisa que vengan las dos horas y que la salida sea despues de la entrada
    if not entrada or not salida:
        raise HorarioInvalidoError(f"Indica la hora de entrada y de salida {cuando}, o marca 'Horario libre'")
    entrada, salida = normalizar_hora(entrada), normalizar_hora(salida)
    if segundos_entre(entrada, salida) <= 0:
        raise HorarioInvalidoError(f"La hora de salida {cuando} debe ser después de la entrada")
    return entrada, salida


class RegistroAsistencia:
    # un registro = las marcas de UN trabajador en UN dia
    def __init__(self, codigo_trabajador, fecha, entrada, salida_almuerzo="", regreso_almuerzo="", salida=""):
        self.codigo_trabajador = codigo_trabajador
        self.fecha = convertir_fecha(fecha)
        # aplicamos enumeraciones: si es domingo lanza DiaNoLaboralError
        self.dia = dia_de(self.fecha)
        if not entrada:
            raise DatoInvalidoError("La hora de entrada es obligatoria")
        self.entrada = normalizar_hora(entrada)
        # operador ternario: las marcas opcionales quedan vacias si no vienen
        self.salida_almuerzo = normalizar_hora(salida_almuerzo) if salida_almuerzo else ""
        self.regreso_almuerzo = normalizar_hora(regreso_almuerzo) if regreso_almuerzo else ""
        self.salida = normalizar_hora(salida) if salida else ""
        self._validar_orden()

    def marcas(self) -> list:
        # zip une dos tuplas: [("Entrada", "08:00:00"), ("Salida a almorzar", "12:00:00"), ...]
        valores = (self.entrada, self.salida_almuerzo, self.regreso_almuerzo, self.salida)
        return list(zip(NOMBRES_MARCAS, valores))

    def marcas_faltantes(self) -> list:
        # nombres de las marcas vacias; el sabado no hay almuerzo, solo se piden entrada y salida
        faltantes = [nombre for nombre, hora in self.marcas() if not hora]
        if self.dia == DiaSemana.SABADO:
            faltantes = [nombre for nombre in faltantes if nombre in ("Entrada", "Salida")]
        return faltantes

    def _validar_orden(self):
        # estructuras de control: revisamos que las marcas tengan sentido
        if self.regreso_almuerzo and not self.salida_almuerzo:
            raise HorarioInvalidoError("Hay regreso de almuerzo pero falta la salida a almorzar")
        if self.salida and self.salida_almuerzo and not self.regreso_almuerzo:
            raise HorarioInvalidoError("Marcó salida a almorzar y salida final, pero falta el regreso de almuerzo")
        # lista por comprension: solo las marcas que tienen hora, en segundos
        horas = [(nombre, hora_a_segundos(hora)) for nombre, hora in self.marcas() if hora]
        # comparamos cada marca con la siguiente: zip(lista, lista[1:]) da parejas (1a,2a), (2a,3a)...
        for (nombre_a, seg_a), (nombre_b, seg_b) in zip(horas, horas[1:]):
            if seg_b <= seg_a:
                raise HorarioInvalidoError(f"'{nombre_b}' debe ser después de '{nombre_a}'")

    def a_diccionario(self) -> dict:
        return {
            "codigo_trabajador": self.codigo_trabajador,
            "fecha": self.fecha.isoformat(),
            "entrada": self.entrada,
            "salida_almuerzo": self.salida_almuerzo,
            "regreso_almuerzo": self.regreso_almuerzo,
            "salida": self.salida,
        }


class Marcacion:
    # evidencia de UN intento de marcar con ubicacion (aceptado o rechazado)
    # guarda una "foto" de la sucursal de ese momento: si despues la sucursal se muda,
    # esta evidencia no cambia (igual que deepcopy en el deshacer: copia del valor, no referencia)
    def __init__(self, codigo_trabajador, fecha_hora, tipo_marca, latitud=None, longitud=None, precision=None,
                 sucursal_codigo="", sucursal_nombre="", sucursal_latitud=None, sucursal_longitud=None,
                 sucursal_radio=None, distancia=None, anomalia=""):
        # todo llega como texto (igual que al leer el JSON): fecha_hora "2026-10-12T08:01:15", tipo_marca "ENTRADA"
        self.codigo_trabajador = codigo_trabajador
        self.fecha_hora = datetime.fromisoformat(fecha_hora)     # hora del SERVIDOR, no del telefono
        self.tipo_marca = TipoMarca[tipo_marca]
        # donde estaba el telefono (None si no mando ubicacion) y que tan exacto era el GPS (metros)
        self.latitud = latitud
        self.longitud = longitud
        self.precision = precision
        # "foto" de la sucursal en ese momento
        self.sucursal_codigo = sucursal_codigo
        self.sucursal_nombre = sucursal_nombre
        self.sucursal_latitud = sucursal_latitud
        self.sucursal_longitud = sucursal_longitud
        self.sucursal_radio = sucursal_radio
        # resultado: distancia a la sucursal y motivo del rechazo ("" = marca valida)
        self.distancia = distancia
        self.anomalia = TipoAnomalia[anomalia] if anomalia else None

    @property
    def valida(self) -> bool:
        return self.anomalia is None

    @property
    def url_ubicacion(self) -> str:
        # enlace a Google Maps del punto exacto desde donde se intento marcar
        if self.latitud is None or self.longitud is None:
            return ""
        return f"https://www.google.com/maps?q={self.latitud},{self.longitud}"

    def a_diccionario(self) -> dict:
        return {
            "codigo_trabajador": self.codigo_trabajador,
            "fecha_hora": self.fecha_hora.isoformat(timespec="seconds"),
            "tipo_marca": self.tipo_marca.name,
            "latitud": self.latitud,
            "longitud": self.longitud,
            "precision": self.precision,
            "sucursal_codigo": self.sucursal_codigo,
            "sucursal_nombre": self.sucursal_nombre,
            "sucursal_latitud": self.sucursal_latitud,
            "sucursal_longitud": self.sucursal_longitud,
            "sucursal_radio": self.sucursal_radio,
            "distancia": self.distancia,
            "anomalia": self.anomalia.name if self.anomalia else "",
        }
