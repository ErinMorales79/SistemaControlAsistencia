# calculos.py  ->  PASO 4 de la ruta de estudio
# logica pura: horas trabajadas, alertas y resumen semanal
# (no guarda nada, solo calcula; por eso es facil de probar con unittest)
# depende de modelos.py y utilidades.py

from collections import Counter
from datetime import date, timedelta
from math import asin, cos, radians, sin, sqrt

from modelos import Alerta, EstadoJornada, TipoAlerta, TipoAnomalia, TipoMarca, segundos_entre
from utilidades import (ALMUERZO_SEGUNDOS, HORAS_SEMANALES, PRECISION_MINIMA, RADIO_TIERRA_METROS,
                        TOLERANCIA_SEGUNDOS, TOLERANCIA_SEMANAL, hora_a_segundos, segundos_a_texto)


def sumar_recursivo(valores: list) -> int:
    # aplicamos recursividad: suma el primero + la suma del resto
    if not valores:            # caso base: lista vacia
        return 0
    return valores[0] + sumar_recursivo(valores[1:])


def lunes_de(fecha: date) -> date:
    # fechas: retrocede hasta el lunes de esa semana
    return fecha - timedelta(days=fecha.weekday())


def obtener_tramos(registro) -> list:
    # devuelve los tramos trabajados como lista de tuplas (inicio, fin) en segundos
    entrada = hora_a_segundos(registro.entrada)
    tramos = []
    if registro.salida_almuerzo:
        # tramo de la manana: entrada -> salida a almorzar
        tramos.append((entrada, hora_a_segundos(registro.salida_almuerzo)))
        if registro.regreso_almuerzo and registro.salida:
            # tramo de la tarde: regreso -> salida
            tramos.append((hora_a_segundos(registro.regreso_almuerzo), hora_a_segundos(registro.salida)))
    elif registro.salida:
        # no marco almuerzo (o es sabado): se cuenta de entrada a salida
        tramos.append((entrada, hora_a_segundos(registro.salida)))
    return tramos


def calcular_segundos_trabajados(registro) -> int:
    # funcion de orden superior: map aplica la lambda a cada tramo (fin - inicio)
    # lambda tramo: tramo[1] - tramo[0]  es una funcion corta sin nombre
    duraciones = list(map(lambda tramo: tramo[1] - tramo[0], obtener_tramos(registro)))
    return sumar_recursivo(duraciones)


def en_curso(registro, hoy=None) -> bool:
    # el dia sigue abierto si es hoy y todavia no marco salida
    return registro.fecha == hoy and not registro.salida


def estado_jornada(registro, trabajador, hoy=None) -> EstadoJornada:
    # aplicamos enumeraciones: devuelve LIBRE, COMPLETA, INCOMPLETA o EN_CURSO
    if trabajador.horario_libre:
        return EstadoJornada.LIBRE
    if calcular_segundos_trabajados(registro) >= trabajador.jornada_del_dia(registro.fecha):
        return EstadoJornada.COMPLETA
    if en_curso(registro, hoy):
        return EstadoJornada.EN_CURSO
    return EstadoJornada.INCOMPLETA


def generar_alertas(registro, trabajador, hoy=None, al_generar_alerta=None) -> list:
    # revisa un registro y devuelve la lista de alertas
    # hoy: si el registro es de hoy y no ha salido, no se alerta lo que aun puede completar
    # al_generar_alerta es un CALLBACK: una funcion que nos pasan para avisar de cada alerta
    alertas = []
    abierto = en_curso(registro, hoy)

    def agregar(tipo, detalle):
        # funcion interna (alcance): puede usar la lista 'alertas' de la funcion de afuera
        alerta = Alerta(tipo, detalle)
        alertas.append(alerta)
        if al_generar_alerta:
            al_generar_alerta(trabajador, registro, alerta)   # ejecutamos el callback

    # con horario libre no se marca asistencia: no hay nada que revisar
    # devolvemos [] (lista vacia) y no 0, porque quien llama recorre el resultado con un for
    if trabajador.horario_libre:
        return []

    # 1) marcas que faltan (el sabado no se pide almuerzo)
    faltantes = registro.marcas_faltantes()
    if faltantes and not abierto:
        agregar(TipoAlerta.REGISTRO_INCOMPLETO, "Falta: " + ", ".join(faltantes))

    # horario que le toca ese dia (lunes a viernes o sabado)
    hora_entrada, hora_salida = trabajador.horario_del_dia(registro.fecha)

    # 2) llegada tarde (con 5 minutos de tolerancia)
    retraso = segundos_entre(hora_entrada, registro.entrada)
    if retraso > TOLERANCIA_SEGUNDOS:
        agregar(TipoAlerta.LLEGADA_TARDE, f"Llegó {segundos_a_texto(retraso)} tarde")

    # 3) salida antes de la hora
    if registro.salida:
        adelanto = segundos_entre(registro.salida, hora_salida)
        if adelanto > 0:
            agregar(TipoAlerta.SALIDA_TEMPRANA, f"Salió {segundos_a_texto(adelanto)} antes")

    # 4) almuerzo mas largo de lo permitido
    if registro.salida_almuerzo and registro.regreso_almuerzo:
        almuerzo = segundos_entre(registro.salida_almuerzo, registro.regreso_almuerzo)
        if almuerzo > ALMUERZO_SEGUNDOS + TOLERANCIA_SEGUNDOS:
            agregar(TipoAlerta.ALMUERZO_EXTENDIDO, f"Almuerzo de {segundos_a_texto(almuerzo)}")

    # 5) no cumplio la jornada de ese dia
    faltante = trabajador.jornada_del_dia(registro.fecha) - calcular_segundos_trabajados(registro)
    if faltante > 0 and not abierto:
        agregar(TipoAlerta.JORNADA_INCOMPLETA, f"Le faltaron {segundos_a_texto(faltante)}")

    return alertas


# ---------------------------------------------------------------
# UBICACION (Fase 3)
# ---------------------------------------------------------------
def distancia_metros(latitud1, longitud1, latitud2, longitud2) -> float:
    # FORMULA DE HAVERSINE: distancia en metros entre dos puntos sobre la Tierra (que es redonda,
    # por eso no basta con restar las coordenadas como si fuera un plano)
    # 1) las funciones sin/cos de python trabajan en radianes, no en grados
    #    (map aplica radians a los 4 numeros: funcion de orden superior)
    lat1, lon1, lat2, lon2 = map(radians, (latitud1, longitud1, latitud2, longitud2))
    # 2) diferencia de latitud y de longitud
    d_lat = lat2 - lat1
    d_lon = lon2 - lon1
    # 3) "a" mide que tan separados estan los puntos sobre la esfera (entre 0 y 1)
    a = sin(d_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(d_lon / 2) ** 2
    # 4) angulo entre los dos puntos visto desde el centro de la Tierra, por el radio = metros
    return 2 * RADIO_TIERRA_METROS * asin(sqrt(a))


def evaluar_ubicacion(sucursal, latitud, longitud, precision) -> tuple:
    # decide si una marca es valida segun donde esta el telefono
    # devuelve (anomalia, distancia): anomalia = None si es valida
    if sucursal is None:
        return TipoAnomalia.SIN_SUCURSAL, None
    if latitud is None or longitud is None:
        return TipoAnomalia.SIN_UBICACION, None             # no dio permiso o el GPS estaba apagado
    distancia = round(distancia_metros(latitud, longitud, sucursal.latitud, sucursal.longitud))
    if precision is None or precision > PRECISION_MINIMA:
        return TipoAnomalia.UBICACION_IMPRECISA, distancia  # el GPS se equivoca demasiado para confiar
    if distancia > sucursal.radio_metros:
        return TipoAnomalia.FUERA_DE_SUCURSAL, distancia
    return None, distancia


def opciones_de_marca(registro, sabado: bool) -> list:
    # que botones de marca le tocan ahora segun lo que ya marco hoy (lista de TipoMarca)
    if registro is None:
        return [TipoMarca.ENTRADA]
    if registro.salida:
        return []                                           # ya termino su dia
    if sabado:
        return [TipoMarca.SALIDA]                           # el sabado no hay almuerzo
    if not registro.salida_almuerzo:
        # puede salir a almorzar o terminar el dia sin almuerzo (decision 20)
        return [TipoMarca.SALIDA_ALMUERZO, TipoMarca.SALIDA]
    if not registro.regreso_almuerzo:
        return [TipoMarca.REGRESO_ALMUERZO]
    return [TipoMarca.SALIDA]


def ultima_hora_marcada(registro) -> str:
    # la hora mas reciente que tiene el registro (para la regla de 5 minutos entre marcas)
    horas = [hora for _, hora in registro.marcas() if hora]
    return horas[-1] if horas else ""


def resumen_semanal(trabajador, registros: list, lunes: date, feriados: set, hoy: date) -> dict:
    # resumen de la semana de un trabajador (lunes a viernes, o hasta sabado si trabaja sabados)
    cantidad_dias = 6 if trabajador.trabaja_sabado else 5

    # conjunto por comprension: los dias laborales de esa semana
    dias_laborales = {lunes + timedelta(days=i) for i in range(cantidad_dias)}
    # solo cuentan los dias desde que el trabajador entro a la empresa
    dias_validos = {d for d in dias_laborales if d >= trabajador.fecha_ingreso}
    dias_registrados = {r.fecha for r in registros}
    dias_pasados = {d for d in dias_validos if d <= hoy}
    # operaciones de conjuntos: dias que ya pasaron - dias marcados - feriados = faltas
    # (el signo - es lo mismo que .difference() de la practica 18)
    faltas = sorted(dias_pasados - dias_registrados - feriados)

    total = sumar_recursivo([calcular_segundos_trabajados(r) for r in registros])
    # meta: 44 horas; si hubo feriados o entro a mitad de semana, la meta baja en proporcion
    esperado = HORAS_SEMANALES * len(dias_validos - feriados) // cantidad_dias

    # horario libre: no marca asistencia, asi que no tiene meta ni faltas
    if trabajador.horario_libre:
        esperado = 0
        faltas = []

    # diccionario por comprension: fecha -> lista de alertas de ese dia
    alertas_por_dia = {r.fecha: generar_alertas(r, trabajador, hoy) for r in registros}
    # aplanamos todas las alertas en una sola lista
    todas = [alerta for lista in alertas_por_dia.values() for alerta in lista]
    completas = [r for r in registros if estado_jornada(r, trabajador, hoy) == EstadoJornada.COMPLETA]

    # estado de cada dia (para pintar los cuadritos L M M J V S)
    dias = []
    for fecha in sorted(dias_laborales):
        if fecha not in dias_validos:
            estado = "sin-ingresar"
        elif fecha in feriados:
            estado = "feriado"
        elif fecha in alertas_por_dia:
            estado = "con-alertas" if alertas_por_dia[fecha] else "completo"
        elif fecha > hoy:
            estado = "pendiente"
        else:
            estado = "falta"
        dias.append((fecha, estado))

    return {
        "trabajador": trabajador,
        "total": total,
        "esperado": esperado,
        "faltante": max(esperado - total, 0),
        "porcentaje": round(total / esperado * 100) if esperado else 0,
        "dias_trabajados": len(dias_registrados),
        "jornadas_completas": len(completas),
        # se acepta hasta 15 minutos menos (ej. 43h 45m cuenta como completa)
        "semana_completa": esperado > 0 and total >= esperado - TOLERANCIA_SEMANAL,
        "faltas": faltas,
        "dias": dias,
        "alertas": todas,
        # Counter cuenta cuantas alertas hay de cada tipo
        "conteo_alertas": Counter(alerta.tipo for alerta in todas),
    }
