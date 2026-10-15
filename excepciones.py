# excepciones.py
# excepciones personalizadas del sistema de asistencia
# no depende de ningun otro archivo del proyecto
#AGREGAMOS UNA LINEA PARA HACER UN GIT PUSH


# aplicamos herencia: todas nuestras excepciones heredan de Exception
class AsistenciaError(Exception):
    # excepcion base del proyecto, el servidor atrapa esta para mostrar el error en pantalla
    pass


class DatoInvalidoError(AsistenciaError):
    # cuando un dato del formulario no cumple el formato (correo, telefono, hora...)
    pass


class DiaNoLaboralError(AsistenciaError):
    # cuando se intenta registrar asistencia en sabado o domingo
    pass


class HorarioInvalidoError(AsistenciaError):
    # cuando las horas no van en orden (ej. salida antes que la entrada)
    pass


class TrabajadorNoEncontradoError(AsistenciaError):
    # cuando se busca un codigo de trabajador que no existe
    pass


class CredencialesInvalidasError(AsistenciaError):
    # cuando el correo o la contraseña no coinciden al iniciar sesion
    pass


class PermisoDenegadoError(AsistenciaError):
    # cuando un usuario intenta algo que su rol no le permite
    pass
