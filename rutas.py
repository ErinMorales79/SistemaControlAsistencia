# rutas.py  ->  PASO 7 de la ruta de estudio
# paginas del sistema: cada funcion responde a una URL
# GET = mostrar una pagina, POST = recibir un formulario y guardar
# es el "puente": recibe datos del servidor, llama al gestor y arma el HTML con las plantillas
# cada pagina lleva el decorador @requiere_rol(...): revisa la sesion y le pasa el usuario a la funcion

from collections import Counter
from datetime import date, timedelta
from functools import wraps
from html import escape

from calculos import (calcular_segundos_trabajados, estado_jornada, generar_alertas, lunes_de,
                      resumen_semanal, sumar_recursivo)
from excepciones import AsistenciaError, PermisoDenegadoError
from gestor import ARCHIVO_EXPORT_JSON, ARCHIVO_EXPORT_XML, GestorAsistencia
from modelos import CLAVES_MARCAS, EstadoJornada, Puesto, Rol, TipoAlerta, TipoSucursal, dia_de
from servidor import Descarga, destino_seguro, redirigir, render, ruta
from sesiones import (GestorSesiones, borrar_cookie, crear_cookie, es_erin, puede_gestionar,
                      roles_que_puede_dar)
from utilidades import (HORA_ENTRADA_DEFECTO, HORA_SALIDA_DEFECTO, HORAS_SEMANALES, RADIO_DEFECTO,
                        RADIO_MAXIMO, RADIO_MINIMO, SABADO_ENTRADA_DEFECTO, SABADO_SALIDA_DEFECTO,
                        TOLERANCIA_SEMANAL, clave_inicial, es_sabado, log, numero_o_none, segundos_a_texto,
                        separar_coordenadas)

# singleton: esta es la MISMA instancia que crea main.py
gestor = GestorAsistencia()

CAMPOS_TRABAJADOR = ("nombre", "apellido", "correo", "telefono", "puesto", "fecha_ingreso",
                     "hora_entrada", "hora_salida", "horario_libre",
                     "trabaja_sabado", "sabado_entrada", "sabado_salida", "codigo_sucursal", "rol")
LETRAS_DIAS = ("L", "M", "M", "J", "V", "S")

# grupos de roles para los permisos de cada pagina (tuplas)
TODOS = (Rol.SUPERADMIN, Rol.ADMIN, Rol.TRABAJADOR)
ADMINS = (Rol.SUPERADMIN, Rol.ADMIN)
SOLO_SUPERADMIN = (Rol.SUPERADMIN,)
EMPLEADOS = (Rol.ADMIN, Rol.TRABAJADOR)            # los que marcan asistencia (el superadmin no es empleado)

# opciones del menu: (nombre, url, icono, texto, roles que la ven)
MENU = (
    ("inicio", "/", "house", "Inicio", ADMINS),
    ("mi_asistencia", "/mi-asistencia", "person-check", "Mi asistencia", EMPLEADOS),
    ("trabajadores", "/trabajadores", "people", "Trabajadores", ADMINS),
    ("sucursales", "/sucursales", "shop", "Sucursales", SOLO_SUPERADMIN),
    ("asistencia", "/asistencia", "calendar-check", "Asistencia", ADMINS),
    ("anomalias", "/anomalias", "geo-alt", "Anomalías", ADMINS),
    ("reporte", "/reporte", "bar-chart", "Reporte", ADMINS),
)


# ---------------------------------------------------------------
# PATRON DECORADOR: permisos de cada pagina
# ---------------------------------------------------------------
def requiere_rol(*roles):
    # decorador con parametros (practica 24): @requiere_rol(Rol.SUPERADMIN, Rol.ADMIN)
    # 1) convierte el codigo de la sesion en el usuario (Trabajador)
    # 2) si no inicio sesion lo manda al login; si su rol no esta permitido lanza PermisoDenegadoError
    # 3) si todo esta bien ejecuta la pagina pasandole el usuario
    def decorador(funcion):
        @wraps(funcion)
        def envoltura(parametros, formulario, codigo_sesion):
            usuario = gestor.trabajadores.get(codigo_sesion) if codigo_sesion else None
            if usuario is None:
                return redirigir("/login", aviso="Inicia sesión para continuar")
            if usuario.rol not in roles:
                raise PermisoDenegadoError("No tienes permiso para entrar a esa página")
            return funcion(parametros, formulario, usuario)
        return envoltura
    return decorador


# ---------------------------------------------------------------
# AYUDANTES PARA ARMAR HTML
# ---------------------------------------------------------------
def e(texto) -> str:
    # escapa el texto para que nadie pueda meter codigo HTML en un nombre
    # ejemplo: "<b>Ana</b>" se convierte en "&lt;b&gt;Ana&lt;/b&gt;" y se muestra como texto
    return escape(str(texto))


def pagina(parametros: dict, usuario, titulo: str, plantilla: str, activo: str, **datos) -> str:
    # arma la pagina completa: base.html + la plantilla de la seccion
    # el menu y la barra de usuario dependen de quien inicio sesion (usuario None = login)
    contenido = render(plantilla, **datos)
    return render("base.html", titulo=titulo, contenido=contenido, mensajes=html_mensajes(parametros),
                  menu=html_menu(usuario, activo), barra_usuario=html_barra_usuario(usuario))


def html_menu(usuario, activo: str) -> str:
    # solo las opciones que el rol del usuario puede ver
    if usuario is None:
        return ""
    return "".join(
        f'<li class="nav-item"><a class="nav-link {"active" if nombre == activo else ""}" href="{url}">'
        f'<i class="bi bi-{icono} me-1"></i>{texto}</a></li>'
        for nombre, url, icono, texto, roles in MENU if usuario.rol in roles
    )


def html_barra_usuario(usuario) -> str:
    # nombre, rol, "Mi cuenta" (solo admins) y el boton "Salir"
    if usuario is None:
        return ""
    mi_cuenta = (f'<a class="btn btn-sm btn-outline-light" href="/mi-cuenta"><i class="bi bi-key me-1"></i>Mi cuenta</a>'
                 if usuario.es_admin else "")
    return (f'<div class="d-flex flex-wrap align-items-center gap-2 ms-lg-3 mt-2 mt-lg-0">'
            f'<span class="text-white small"><i class="bi bi-person-circle me-1"></i>{e(usuario.nombre_completo)} '
            f'<span class="badge text-bg-light">{usuario.rol.value}</span></span>{mi_cuenta}'
            f'<form method="post" action="/salir" class="d-inline">'
            f'<button class="btn btn-sm btn-light"><i class="bi bi-box-arrow-right me-1"></i>Salir</button></form></div>')


def html_mensajes(parametros: dict) -> str:
    # muestra los mensajes que vienen en la URL (?msg=..., ?aviso=..., ?error=...)
    estilos = {"msg": ("success", "check-circle"), "aviso": ("warning", "exclamation-triangle"), "error": ("danger", "x-circle")}
    bloques = []
    for clave, (color, icono) in estilos.items():
        if clave in parametros:
            bloques.append(
                f'<div class="alert alert-{color} alert-dismissible fade show shadow-sm" role="alert">'
                f'<i class="bi bi-{icono} me-2"></i>{e(parametros[clave])}'
                f'<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Cerrar"></button></div>'
            )
    return "".join(bloques)


def mensajes_de(parametros: dict) -> dict:
    # copia los mensajes de la URL para pasarlos a otra redireccion
    return {clave: parametros[clave] for clave in ("msg", "aviso", "error") if clave in parametros}


def html_jornada(estado: EstadoJornada) -> str:
    # señal de la jornada: verde completa, roja incompleta, azul en curso
    return f'<span class="badge text-bg-{estado.color}"><i class="bi bi-{estado.icono} me-1"></i>{estado.etiqueta}</span>'


def html_rol(trabajador) -> str:
    # etiqueta del rol: los admins resaltan, el trabajador comun no lleva etiqueta
    if trabajador.rol == Rol.SUPERADMIN:
        return '<span class="badge text-bg-dark ms-1">Superadmin</span>'
    if trabajador.rol == Rol.ADMIN:
        return '<span class="badge text-bg-primary ms-1">Admin</span>'
    return ""


def html_horario(t) -> str:
    # muestra el horario de lunes a viernes, el del sabado y si su horario llega a 44 horas
    sabado = f"{t.sabado_entrada[:5]} – {t.sabado_salida[:5]}" if t.trabaja_sabado else "no trabaja"
    if not t.es_empleado:
        return '<span class="text-body-secondary">Cuenta de administración<br>(no es empleado)</span>'
    if t.horario_libre:
        return (f'{html_jornada(EstadoJornada.LIBRE)}<br>'
                f'<span class="text-body-secondary">No marca asistencia</span>')

    # su horario debe sumar 44 horas (con la tolerancia semanal)
    if t.horas_de_horario >= HORAS_SEMANALES - TOLERANCIA_SEMANAL:
        semana = f'<span class="badge text-bg-success">{segundos_a_texto(t.horas_de_horario)} / semana</span>'
    else:
        semana = (f'<span class="badge text-bg-warning" title="Su horario no llega a 44 horas">'
                  f'{segundos_a_texto(t.horas_de_horario)} / semana</span>')
    return (f'<span class="font-monospace">L-V {t.hora_entrada[:5]} – {t.hora_salida[:5]}</span><br>'
            f'<span class="font-monospace">Sáb {sabado}</span><br>{semana}')


def html_alertas(alertas: list) -> str:
    if not alertas:
        return '<span class="text-body-secondary small">Sin alertas</span>'
    # generador dentro de join: una linea por alerta
    return "".join(
        f'<div class="alerta-item"><span class="badge text-bg-{a.tipo.color}">{e(a.tipo.etiqueta)}</span> '
        f'<small class="text-body-secondary">{e(a.detalle)}</small></div>'
        for a in alertas
    )


def obtener_semana(parametros: dict) -> date:
    # lee ?semana=AAAA-MM-DD; si no viene, esta mal o es futura usamos la semana actual
    actual = lunes_de(date.today())
    try:
        lunes = lunes_de(date.fromisoformat(parametros.get("semana", "")))
    except ValueError:
        return actual
    return min(lunes, actual)


def navegacion_semana(camino: str, lunes: date) -> str:
    # botones anterior / siguiente / esta semana
    actual = lunes_de(date.today())
    anterior, siguiente = lunes - timedelta(days=7), lunes + timedelta(days=7)
    sabado = lunes + timedelta(days=5)
    es_actual = lunes >= actual

    boton_anterior = (f'<a class="btn btn-outline-secondary btn-sm" href="{camino}?semana={anterior}">'
                      f'<i class="bi bi-chevron-left"></i> Anterior</a>')
    # no se puede ir a semanas futuras: el boton queda deshabilitado
    if es_actual:
        boton_siguiente = '<span class="btn btn-outline-secondary btn-sm disabled">Siguiente <i class="bi bi-chevron-right"></i></span>'
        boton_actual = '<span class="badge text-bg-primary">Semana actual</span>'
    else:
        boton_siguiente = (f'<a class="btn btn-outline-secondary btn-sm" href="{camino}?semana={siguiente}">'
                           f'Siguiente <i class="bi bi-chevron-right"></i></a>')
        boton_actual = f'<a class="btn btn-primary btn-sm" href="{camino}"><i class="bi bi-calendar-event me-1"></i>Ir a esta semana</a>'

    return (f'<div class="navegacion-semana">{boton_anterior}'
            f'<span class="fw-semibold">Semana del {lunes:%d/%m} al {sabado:%d/%m/%Y}</span>'
            f'{boton_siguiente}{boton_actual}</div>')


def opciones_trabajadores(usuario, seleccionado: str = "") -> str:
    # <option> de cada trabajador al que el usuario le puede corregir marcas
    # (los de horario libre no aparecen porque no marcan asistencia)
    return "".join(
        f'<option value="{e(t.codigo)}" {"selected" if t.codigo == seleccionado else ""}>{e(t.nombre_completo)} ({e(t.codigo)})</option>'
        for t in gestor.trabajadores_ordenados() if not t.horario_libre and puede_gestionar(usuario, t)
    )


def estado_del_dia(registro, trabajador, hoy) -> tuple:
    # devuelve (texto, color) segun las marcas que tenga hoy
    if trabajador.horario_libre:
        return "Horario libre", "info"
    if es_sabado(hoy) and not trabajador.trabaja_sabado:
        return "Descansa sábados", "light"
    if registro is None:
        return "Sin marcar", "secondary"
    if registro.salida:
        return "Ya salió", "success"
    if registro.salida_almuerzo and not registro.regreso_almuerzo:
        return "En almuerzo", "warning"
    return "Trabajando", "primary"


# ---------------------------------------------------------------
# INICIO DE SESION
# ---------------------------------------------------------------
@ruta("GET", "/login")
def ver_login(parametros, formulario, codigo_sesion):
    # pagina publica (sin decorador): si ya inicio sesion, lo mandamos adentro
    if codigo_sesion in gestor.trabajadores:
        return redirigir("/")
    return pagina(parametros, None, "Iniciar sesión", "login.html", "")


@ruta("POST", "/login")
def iniciar_sesion(parametros, formulario, codigo_sesion):
    # autenticar lanza CredencialesInvalidasError si algo no coincide (vuelve al login con el error)
    usuario = gestor.autenticar(formulario.get("correo", ""), formulario.get("clave", ""))
    token = GestorSesiones().iniciar_sesion(usuario.codigo)
    # la cookie guarda el token en el navegador: desde ahora cada peticion dice quien es
    return redirigir("/", cookie=crear_cookie(token), msg=f"Bienvenido/a, {usuario.nombre}")


@ruta("POST", "/salir")
def cerrar_sesion(parametros, formulario, codigo_sesion):
    # cierra la sesion de ese usuario y le pide al navegador borrar la cookie
    if codigo_sesion:
        GestorSesiones().cerrar_sesiones_de(codigo_sesion)
    return redirigir("/login", cookie=borrar_cookie(), msg="Sesión cerrada")


# ---------------------------------------------------------------
# INICIO (panel de los admins)
# ---------------------------------------------------------------
@ruta("GET", "/")
@requiere_rol(*TODOS)
def ver_inicio(parametros, formulario, usuario):
    # el trabajador comun no tiene panel: su pagina es "Mi asistencia"
    if not usuario.es_admin:
        return redirigir("/mi-asistencia", **mensajes_de(parametros))

    hoy = date.today()
    lunes = lunes_de(hoy)
    # el superadmin ve a todos; el encargado solo a su sucursal (sin las cuentas de superadmin)
    visibles = gestor.empleados_visibles(usuario)
    codigos = {t.codigo for t in visibles}                  # conjunto: busquedas rapidas
    registros = [r for r in gestor.iterar_registros(lunes=lunes) if r.codigo_trabajador in codigos]
    alertas = [a for r in registros for a in generar_alertas(r, gestor.trabajadores[r.codigo_trabajador], hoy)]
    # jornadas completas: solo se cuentan los trabajadores con horario fijo
    con_horario = [r for r in registros if not gestor.trabajadores[r.codigo_trabajador].horario_libre]
    completas = [r for r in con_horario
                 if estado_jornada(r, gestor.trabajadores[r.codigo_trabajador], hoy) == EstadoJornada.COMPLETA]
    # map + recursividad: suma de los segundos trabajados de toda la semana
    segundos_semana = sumar_recursivo(list(map(calcular_segundos_trabajados, registros)))

    # tabla de "hoy"
    filas = []
    for numero, trabajador in enumerate(visibles, start=1):
        # next con generador: busca el registro de hoy de este trabajador (o None)
        registro = next((r for r in registros if r.codigo_trabajador == trabajador.codigo and r.fecha == hoy), None)
        texto, color = estado_del_dia(registro, trabajador, hoy)
        marcas = " · ".join(hora[:5] for _, hora in registro.marcas() if hora) if registro else "—"
        total = segundos_a_texto(calcular_segundos_trabajados(registro)) if registro else "—"
        jornada = html_jornada(estado_jornada(registro, trabajador, hoy)) if registro else "—"
        filas.append(
            f'<tr><td class="text-body-secondary">{numero}</td>'
            f'<td><div class="fw-semibold">{e(trabajador.nombre_completo)}</div><small class="text-body-secondary">{e(trabajador.puesto.value)}</small></td>'
            f'<td><span class="badge text-bg-{color}">{texto}</span></td>'
            f'<td class="font-monospace small">{marcas}</td><td class="font-monospace small">{total}</td><td>{jornada}</td></tr>'
        )
    tabla_hoy = "".join(filas) or '<tr><td colspan="6" class="text-center text-body-secondary py-4">No hay trabajadores</td></tr>'

    # conteo de alertas por tipo (iteramos el enum completo)
    conteo = Counter(a.tipo for a in alertas)
    anomalias = len(gestor.anomalias_visibles(usuario, lunes))
    resumen_alertas = (
        f'<li class="list-group-item d-flex justify-content-between align-items-center fw-semibold">'
        f'<span><i class="bi bi-check-circle-fill text-success me-2"></i>Jornadas completas</span>'
        f'<span class="badge rounded-pill text-bg-success">{len(completas)} de {len(con_horario)}</span></li>'
        f'<a class="list-group-item list-group-item-action d-flex justify-content-between align-items-center fw-semibold" href="/anomalias">'
        f'<span><i class="bi bi-geo-alt-fill text-danger me-2"></i>Anomalías de ubicación</span>'
        f'<span class="badge rounded-pill text-bg-danger">{anomalias}</span></a>'
    ) + "".join(
        f'<li class="list-group-item d-flex justify-content-between align-items-center">'
        f'<span><span class="punto bg-{tipo.color}"></span>{e(tipo.etiqueta)}</span>'
        f'<span class="badge rounded-pill text-bg-{tipo.color}">{conteo[tipo]}</span></li>'
        for tipo in TipoAlerta
    )

    # cola de alertas recientes: solo las de su gente, las 10 mas nuevas
    propias = [(tipo, texto) for tipo, texto, codigo in gestor.alertas_recientes if codigo in codigos]
    recientes = "".join(
        f'<li class="list-group-item small"><span class="badge text-bg-{tipo.color} me-1">{e(tipo.etiqueta)}</span>{e(texto)}</li>'
        for tipo, texto in reversed(propias[-10:])
    ) or '<li class="list-group-item small text-body-secondary">Aún no hay alertas en esta sesión</li>'

    proximos = sorted((f, n) for f, n in gestor.feriados.items() if f >= hoy)[:4]
    feriados = "".join(
        f'<li class="list-group-item small d-flex justify-content-between"><span>{e(nombre)}</span><span class="text-body-secondary">{fecha:%d/%m/%Y}</span></li>'
        for fecha, nombre in proximos
    ) or '<li class="list-group-item small text-body-secondary">Sin información de feriados (requiere internet)</li>'

    # el encargado ve en el titulo de que sucursal es el panel
    if usuario.rol == Rol.ADMIN:
        sucursal = gestor.sucursales.get(usuario.codigo_sucursal)
        alcance = f"Sucursal {e(sucursal.nombre)}" if sucursal else "Sin sucursal asignada"
    else:
        alcance = "Toda la empresa"

    es_domingo = hoy.weekday() == 6
    return pagina(
        parametros, usuario, "Inicio", "inicio.html", "inicio",
        fecha_hoy=f"{hoy:%d/%m/%Y}",
        alcance=alcance,
        aviso_hoy='<div class="alert alert-info small mb-3">Hoy es domingo, nadie trabaja.</div>' if es_domingo else "",
        total_trabajadores=len(visibles),
        total_completas=f"{len(completas)} / {len(con_horario)}",
        total_alertas=len(alertas),
        horas_semana=segundos_a_texto(segundos_semana),
        tabla_hoy=tabla_hoy,
        resumen_alertas=resumen_alertas,
        alertas_recientes=recientes,
        feriados=feriados,
    )


# ---------------------------------------------------------------
# MI ASISTENCIA (cualquier usuario: solo sus propios datos)
# ---------------------------------------------------------------
@ruta("GET", "/mi-asistencia")
@requiere_rol(*EMPLEADOS)
def ver_mi_asistencia(parametros, formulario, usuario):
    hoy = date.today()
    lunes = obtener_semana(parametros)
    sucursal = gestor.sucursales.get(usuario.codigo_sucursal)

    if usuario.horario_libre:
        contenido = ('<div class="alert alert-info mb-0"><i class="bi bi-infinity me-2"></i>'
                     'Tienes <strong>horario libre</strong>: no marcas asistencia.</div>')
    else:
        registros = list(gestor.iterar_registros(usuario.codigo, lunes))
        resumen = resumen_semanal(usuario, registros, lunes, set(gestor.feriados_de_semana(lunes)), hoy)
        filas = "".join(
            f'<tr><td><div class="fw-semibold">{r.dia.value}</div><small class="text-body-secondary">{r.fecha:%d/%m/%Y}</small></td>'
            f'<td class="font-monospace small">{" · ".join(hora[:5] for _, hora in r.marcas() if hora)}</td>'
            f'<td class="font-monospace small fw-semibold">{segundos_a_texto(calcular_segundos_trabajados(r))}</td>'
            f'<td>{html_jornada(estado_jornada(r, usuario, hoy))}</td>'
            f'<td>{html_alertas(generar_alertas(r, usuario, hoy))}</td></tr>'
            for r in registros
        ) or '<tr><td colspan="5" class="text-center text-body-secondary py-4">No tienes marcas esta semana</td></tr>'
        faltas = ", ".join(dia_de(f).value for f in resumen["faltas"]) or "Ninguna"
        contenido = (
            f'<div class="d-flex flex-wrap gap-3 mb-3 small">'
            f'<span><strong>Trabajado:</strong> <span class="font-monospace">{segundos_a_texto(resumen["total"])}</span></span>'
            f'<span><strong>Meta:</strong> <span class="font-monospace">{segundos_a_texto(resumen["esperado"])}</span></span>'
            f'<span><strong>Faltas:</strong> {faltas}</span></div>'
            f'<div class="table-responsive"><table class="table table-hover align-middle mb-0">'
            f'<thead><tr><th>Día</th><th>Marcas</th><th>Total</th><th>Jornada</th><th>Alertas</th></tr></thead>'
            f'<tbody>{filas}</tbody></table></div>'
        )

    return pagina(
        parametros, usuario, "Mi asistencia", "mi_asistencia.html", "mi_asistencia",
        nombre=e(usuario.nombre),
        sucursal=e(sucursal) if sucursal else "Sin sucursal asignada",
        horario=html_horario(usuario),
        navegacion=navegacion_semana("/mi-asistencia", lunes),
        contenido_semana=contenido,
        marcar=html_marcar(usuario, hoy),
        rechazados=html_mis_rechazos(usuario, lunes),
    )


def html_marcar(usuario, hoy) -> str:
    # tarjeta con el boton (o los dos botones) de la marca que le toca ahora
    opciones = gestor.opciones_de_hoy(usuario, hoy)
    if not opciones:
        if usuario.horario_libre or hoy.weekday() == 6 or (es_sabado(hoy) and not usuario.trabaja_sabado):
            texto = "Hoy no te toca marcar asistencia."
        else:
            texto = "Ya marcaste tu salida de hoy. ¡Hasta mañana!"
        return f'<p class="text-body-secondary mb-0"><i class="bi bi-check2-circle me-1"></i>{texto}</p>'

    # un boton por cada opcion; el JavaScript lee data-marca para saber cual tocaron
    botones = "".join(
        f'<button type="button" class="btn {"btn-primary" if numero == 0 else "btn-outline-primary"} btn-lg" data-marca="{opcion.name}">'
        f'<i class="bi bi-geo-alt-fill me-1"></i>{opcion.etiqueta}</button>'
        for numero, opcion in enumerate(opciones)
    )
    # campos ocultos: los llena ubicacion.js con lo que responde el GPS; el trabajador nunca los ve
    return (
        f'<form id="form-marcar" method="post" action="/marcar">'
        f'<input type="hidden" name="volver" value="/mi-asistencia">'
        f'<input type="hidden" name="tipo_marca"><input type="hidden" name="latitud">'
        f'<input type="hidden" name="longitud"><input type="hidden" name="precision"><input type="hidden" name="error_gps">'
        f'<div class="d-grid gap-2">{botones}</div></form>'
        f'<p id="estado-gps" class="small text-body-secondary mt-2 mb-0">Al tocar el botón, tu teléfono pedirá permiso para usar tu ubicación.</p>'
    )


def html_mis_rechazos(usuario, lunes) -> str:
    # los intentos rechazados del propio usuario en esa semana (decision 17: cada quien ve los suyos)
    rechazos = [m for m in gestor.anomalias_visibles(usuario, lunes) if m.codigo_trabajador == usuario.codigo]
    if not rechazos:
        return '<p class="small text-body-secondary mb-0">No tienes intentos rechazados esta semana.</p>'
    return '<ul class="list-group list-group-flush">' + "".join(
        f'<li class="list-group-item small px-0"><span class="badge text-bg-{m.anomalia.color} me-1">{m.anomalia.etiqueta}</span>'
        f'{dia_de(m.fecha_hora.date()).value} {m.fecha_hora:%d/%m %H:%M} · {m.tipo_marca.etiqueta}'
        f'{f" · a {m.distancia} m de {e(m.sucursal_nombre)}" if m.distancia is not None else ""}</li>'
        for m in rechazos
    ) + '</ul>'


@ruta("POST", "/marcar")
@requiere_rol(*EMPLEADOS)
def marcar(parametros, formulario, usuario):
    # llega desde ubicacion.js con la ubicacion en los campos ocultos (o vacios si el GPS fallo)
    if formulario.get("error_gps"):
        log.info(f"GPS sin respuesta para {usuario}: {formulario['error_gps']}")
    marcacion = gestor.marcar_asistencia(
        usuario, formulario.get("tipo_marca", ""),
        numero_o_none(formulario.get("latitud")), numero_o_none(formulario.get("longitud")),
        numero_o_none(formulario.get("precision")),
    )
    marca = marcacion.tipo_marca.etiqueta
    if marcacion.valida:
        return redirigir("/mi-asistencia", msg=f"{marca} marcada a las {marcacion.fecha_hora:%H:%M:%S} en "
                                               f"{marcacion.sucursal_nombre} (a {marcacion.distancia} m)")
    # rechazada: explicamos el motivo con palabras simples
    motivos = {
        "FUERA_DE_SUCURSAL": f"estás a {marcacion.distancia} m de {marcacion.sucursal_nombre} (máximo {marcacion.sucursal_radio} m)",
        "UBICACION_IMPRECISA": "la ubicación de tu teléfono no es precisa; sal a un lugar abierto o activa el GPS e intenta de nuevo",
        "SIN_UBICACION": "no se pudo leer tu ubicación; permite el acceso a la ubicación e intenta de nuevo",
        "SIN_SUCURSAL": "no tienes una sucursal asignada; avisa a tu encargado",
    }
    return redirigir("/mi-asistencia", error=f"{marca} rechazada: {motivos[marcacion.anomalia.name]}. "
                                             f"Se registró como anomalía.")


# ---------------------------------------------------------------
# ANOMALIAS (admins: solo las de su gente)
# ---------------------------------------------------------------
@ruta("GET", "/anomalias")
@requiere_rol(*ADMINS)
def ver_anomalias(parametros, formulario, usuario):
    lunes = obtener_semana(parametros)
    filas = []
    for m in gestor.anomalias_visibles(usuario, lunes):
        trabajador = gestor.trabajadores[m.codigo_trabajador]
        distancia = f"{m.distancia} m" if m.distancia is not None else "—"
        precision = f"± {round(m.precision)} m" if m.precision is not None else "—"
        mapa = (f'<a class="btn btn-sm btn-outline-secondary" href="{m.url_ubicacion}" target="_blank" rel="noopener">'
                f'<i class="bi bi-geo-alt"></i> Ver punto</a>' if m.url_ubicacion else '<span class="text-body-secondary small">Sin ubicación</span>')
        filas.append(
            f'<tr><td><div class="fw-semibold">{dia_de(m.fecha_hora.date()).value}</div>'
            f'<small class="text-body-secondary">{m.fecha_hora:%d/%m/%Y %H:%M:%S}</small></td>'
            f'<td><div class="fw-semibold">{e(trabajador.nombre_completo)}</div><small class="text-body-secondary">{e(trabajador.puesto.value)}</small></td>'
            f'<td>{m.tipo_marca.etiqueta}</td>'
            f'<td><span class="badge text-bg-{m.anomalia.color}">{m.anomalia.etiqueta}</span></td>'
            f'<td class="small">{e(m.sucursal_nombre) or "—"}<br><span class="text-body-secondary">radio {m.sucursal_radio or "—"} m</span></td>'
            f'<td class="font-monospace small">{distancia}</td><td class="font-monospace small">{precision}</td>'
            f'<td class="text-end">{mapa}</td></tr>'
        )
    tabla = "".join(filas) or '<tr><td colspan="8" class="text-center text-body-secondary py-4">No hay anomalías esta semana</td></tr>'
    return pagina(
        parametros, usuario, "Anomalías", "anomalias.html", "anomalias",
        navegacion=navegacion_semana("/anomalias", lunes), filas=tabla, total=len(filas),
    )


# ---------------------------------------------------------------
# MI CUENTA (admins: cambiar su propia contraseña)
# ---------------------------------------------------------------
@ruta("GET", "/mi-cuenta")
@requiere_rol(*ADMINS)
def ver_mi_cuenta(parametros, formulario, usuario):
    sucursal = gestor.sucursales.get(usuario.codigo_sucursal)
    return pagina(
        parametros, usuario, "Mi cuenta", "mi_cuenta.html", "",
        nombre=e(usuario.nombre_completo), correo=e(usuario.correo), rol=usuario.rol.value,
        sucursal=e(sucursal) if sucursal else "Sin sucursal asignada",
    )


@ruta("POST", "/mi-cuenta")
@requiere_rol(*ADMINS)
def cambiar_mi_clave(parametros, formulario, usuario):
    gestor.cambiar_mi_clave(usuario, formulario.get("actual", ""), formulario.get("nueva", ""),
                            formulario.get("confirmacion", ""))
    return redirigir("/mi-cuenta", msg="Contraseña actualizada")


# ---------------------------------------------------------------
# TRABAJADORES (CRUD)
# R: GET /trabajadores   C: POST /trabajadores/agregar
# U: POST /trabajadores/actualizar   D: POST /trabajadores/eliminar
# ---------------------------------------------------------------
@ruta("GET", "/trabajadores")
@requiere_rol(*ADMINS)
def ver_trabajadores(parametros, formulario, usuario):
    # si viene ?editar=EMP-001 el formulario se llena con ese trabajador (solo si lo puede gestionar)
    editando = gestor.trabajadores.get(parametros.get("editar", ""))
    if editando and not puede_gestionar(usuario, editando):
        editando = None

    filas = []
    visibles = gestor.trabajadores_visibles(usuario)
    for numero, t in enumerate(visibles, start=1):
        clase = "table-primary" if editando and t.codigo == editando.codigo else ""
        filas.append(
            f'<tr class="{clase}"><td class="text-body-secondary">{numero}</td>'
            f'<td><span class="badge codigo">{e(t.codigo)}</span></td>'
            f'<td><div class="fw-semibold">{e(t.nombre_completo)}{html_rol(t)}</div><small class="text-body-secondary">Desde {t.fecha_ingreso:%d/%m/%Y}</small></td>'
            f'<td>{e(t.puesto.value)}</td>'
            f'<td>{html_sucursal_de(t)}</td>'
            f'<td><small>{e(t.correo)}<br>{e(t.telefono)}</small></td>'
            f'<td class="small">{html_horario(t)}</td>'
            f'<td class="text-end">{html_acciones_trabajador(usuario, t)}</td></tr>'
        )
    tabla = "".join(filas) or '<tr><td colspan="8" class="text-center text-body-secondary py-4">No hay trabajadores registrados</td></tr>'

    # <select> de sucursales: el superadmin elige cualquiera; el encargado solo la suya
    sucursal_actual = editando.codigo_sucursal if editando else usuario.codigo_sucursal
    if usuario.rol == Rol.SUPERADMIN:
        opciones_sucursal = '<option value="">Sin asignar</option>' + "".join(
            f'<option value="{e(s.codigo)}" {"selected" if s.codigo == sucursal_actual else ""}>{e(s)}</option>'
            for s in gestor.sucursales_ordenadas()
        )
    else:
        sucursal = gestor.sucursales.get(usuario.codigo_sucursal)
        opciones_sucursal = f'<option value="{e(usuario.codigo_sucursal)}">{e(sucursal) if sucursal else "Sin sucursal"}</option>'

    # iteramos el enum Puesto para llenar el <select> (marcando el puesto actual al editar)
    puesto_actual = editando.puesto if editando else None
    opciones_puesto = "".join(
        f'<option value="{p.name}" {"selected" if p is puesto_actual else ""}>{e(p.value)}</option>' for p in Puesto
    )
    # conjunto de puestos en uso, ordenado por nombre
    puestos = "".join(
        f'<span class="badge rounded-pill text-bg-light border me-1">{e(p.value)}</span>'
        for p in sorted({t.puesto for t in visibles}, key=lambda p: p.value)
    ) or '<span class="text-body-secondary small">Ninguno</span>'

    if editando:
        formulario_html = dict(
            form_titulo=f'<i class="bi bi-pencil-square me-2"></i>Editando a {e(editando.nombre_completo)}',
            form_accion="/trabajadores/actualizar",
            volver=f"/trabajadores?editar={e(editando.codigo)}",
            boton='<i class="bi bi-save me-1"></i>Guardar cambios',
            cancelar='<a class="btn btn-outline-secondary" href="/trabajadores">Cancelar</a>',
            nota_clave="",
        )
    else:
        formulario_html = dict(
            form_titulo='<i class="bi bi-person-plus me-2"></i>Nuevo trabajador',
            form_accion="/trabajadores/agregar",
            volver="/trabajadores",
            boton='<i class="bi bi-save me-1"></i>Guardar trabajador',
            cancelar="",
            nota_clave=('<div class="col-12 form-text"><i class="bi bi-key me-1"></i>Su usuario será su <strong>correo</strong> '
                        'y su contraseña inicial <strong>Nombre1234</strong> (ej. Erin1234).</div>'),
        )

    return pagina(
        parametros, usuario, "Trabajadores", "trabajadores.html", "trabajadores",
        filas=tabla, total=len(visibles), opciones_puesto=opciones_puesto, puestos_en_uso=puestos,
        opciones_sucursal=opciones_sucursal, campo_rol=html_campo_rol(usuario, editando),
        hoy=date.today().isoformat(), **formulario_html, **valores_trabajador(editando),
    )


def html_acciones_trabajador(usuario, t) -> str:
    # botones de cada fila: solo aparecen si el usuario puede gestionar a ese trabajador
    if not puede_gestionar(usuario, t):
        return '<span class="text-body-secondary small">—</span>'
    # los botones van uno debajo del otro (d-flex flex-column) para que la tabla no se salga de la pantalla
    botones = f'<a class="btn btn-sm btn-outline-primary" href="/trabajadores?editar={e(t.codigo)}" title="Editar datos"><i class="bi bi-pencil"></i></a>'
    if t.rol == Rol.TRABAJADOR:
        botones += (f'<form method="post" action="/trabajadores/restablecer">'
                    f'<input type="hidden" name="codigo" value="{e(t.codigo)}"><input type="hidden" name="volver" value="/trabajadores">'
                    f'<button class="btn btn-sm btn-outline-warning w-100" title="Restablecer contraseña a {e(clave_inicial(t.nombre))}"><i class="bi bi-key"></i></button></form>')
    if not es_erin(t):
        botones += (f'<form method="post" action="/trabajadores/eliminar">'
                    f'<input type="hidden" name="codigo" value="{e(t.codigo)}"><input type="hidden" name="volver" value="/trabajadores">'
                    f'<button class="btn btn-sm btn-outline-danger w-100" title="Eliminar trabajador y sus registros"><i class="bi bi-trash"></i></button></form>')
    return f'<div class="d-flex flex-column gap-1 align-items-end">{botones}</div>'


def html_campo_rol(usuario, editando) -> str:
    # el encargado solo crea trabajadores comunes: el rol va oculto
    roles = roles_que_puede_dar(usuario)
    rol_actual = editando.rol if editando else Rol.TRABAJADOR
    if editando and es_erin(editando):
        return ('<input type="hidden" name="rol" value="SUPERADMIN">'
                '<div class="col-12 form-text"><i class="bi bi-shield-lock me-1"></i>Erin es el superadmin principal: su rol no se puede cambiar.</div>')
    if len(roles) == 1:
        return f'<input type="hidden" name="rol" value="{rol_actual.name}">'
    opciones = "".join(
        f'<option value="{r.name}" {"selected" if r is rol_actual else ""}>{r.value}</option>' for r in roles
    )
    return (f'<div class="col-12"><label class="form-label" for="rol">Rol en el sistema</label>'
            f'<select class="form-select" id="rol" name="rol">{opciones}</select>'
            f'<div class="form-text">El rol da permisos en el sistema; no es lo mismo que el puesto. '
            f'Un <strong>Superadmin</strong> no es empleado: pierde su sucursal y su horario.</div></div>')


def valores_trabajador(t) -> dict:
    # valores que llenan el formulario de trabajadores
    # nuevo (t es None): vacio con horas por defecto; editar: los datos del trabajador
    if t is None:
        return {
            "v_codigo": "", "v_nombre": "", "v_apellido": "", "v_correo": "", "v_telefono": "",
            "v_fecha_ingreso": date.today().isoformat(),
            "v_hora_entrada": HORA_ENTRADA_DEFECTO, "v_hora_salida": HORA_SALIDA_DEFECTO,
            "v_sabado_entrada": SABADO_ENTRADA_DEFECTO, "v_sabado_salida": SABADO_SALIDA_DEFECTO,
            "v_horario_libre": "", "v_trabaja_sabado": "",
        }
    # [:5] deja "08:00" de "08:00:00"; "or" pone la hora por defecto si estaba vacia
    return {
        "v_codigo": e(t.codigo), "v_nombre": e(t.nombre), "v_apellido": e(t.apellido),
        "v_correo": e(t.correo), "v_telefono": e(t.telefono),
        "v_fecha_ingreso": t.fecha_ingreso.isoformat(),
        "v_hora_entrada": t.hora_entrada[:5] or HORA_ENTRADA_DEFECTO,
        "v_hora_salida": t.hora_salida[:5] or HORA_SALIDA_DEFECTO,
        "v_sabado_entrada": t.sabado_entrada[:5] or SABADO_ENTRADA_DEFECTO,
        "v_sabado_salida": t.sabado_salida[:5] or SABADO_SALIDA_DEFECTO,
        "v_horario_libre": "checked" if t.horario_libre else "",
        "v_trabaja_sabado": "checked" if t.trabaja_sabado else "",
    }


def html_sucursal_de(trabajador) -> str:
    # nombre de la sucursal del trabajador, o "Sin asignar" en gris
    if not trabajador.es_empleado:
        return '<span class="text-body-secondary small">Toda la empresa</span>'
    if trabajador.codigo_sucursal in gestor.sucursales:
        sucursal = gestor.sucursales[trabajador.codigo_sucursal]
        return f'{e(sucursal.nombre)}<br><small class="text-body-secondary">{sucursal.tipo.value}</small>'
    return '<span class="badge text-bg-light border">Sin asignar</span>'


@ruta("POST", "/trabajadores/agregar")
@requiere_rol(*ADMINS)
def agregar_trabajador(parametros, formulario, usuario):
    # tomamos solo los campos que nos interesan del formulario; "por" = quien lo crea (reglas de rol)
    datos = {campo: formulario.get(campo, "") for campo in CAMPOS_TRABAJADOR}
    trabajador = gestor.agregar_trabajador(datos, por=usuario)
    return redirigir("/trabajadores", msg=f"{trabajador.nombre_completo} agregado con el código {trabajador.codigo}. "
                                          f"Usuario: {trabajador.correo} · Contraseña: {clave_inicial(trabajador.nombre)}")


@ruta("POST", "/trabajadores/actualizar")
@requiere_rol(*ADMINS)
def actualizar_trabajador(parametros, formulario, usuario):
    datos = {campo: formulario.get(campo, "") for campo in CAMPOS_TRABAJADOR}
    trabajador = gestor.actualizar_trabajador(formulario.get("codigo", ""), datos, por=usuario)
    return redirigir("/trabajadores", msg=f"Datos de {trabajador.nombre_completo} actualizados")


@ruta("POST", "/trabajadores/eliminar")
@requiere_rol(*ADMINS)
def eliminar_trabajador(parametros, formulario, usuario):
    trabajador = gestor.eliminar_trabajador(formulario.get("codigo", ""), por=usuario)
    return redirigir("/trabajadores", msg=f"{trabajador.nombre_completo} fue eliminado")


@ruta("POST", "/trabajadores/restablecer")
@requiere_rol(*ADMINS)
def restablecer_clave(parametros, formulario, usuario):
    codigo = formulario.get("codigo", "")
    nueva = gestor.restablecer_clave(codigo, por=usuario)
    nombre = gestor.trabajadores[codigo].nombre_completo
    return redirigir("/trabajadores", msg=f"Contraseña de {nombre} restablecida a: {nueva}")


# ---------------------------------------------------------------
# SUCURSALES (CRUD) - solo superadmin
# R: GET /sucursales   C: POST /sucursales/agregar
# U: POST /sucursales/actualizar   D: POST /sucursales/eliminar
# ---------------------------------------------------------------
@ruta("GET", "/sucursales")
@requiere_rol(*SOLO_SUPERADMIN)
def ver_sucursales(parametros, formulario, usuario):
    # si viene ?editar=SUC-001 el formulario se llena con esa sucursal
    editando = gestor.sucursales.get(parametros.get("editar", ""))

    tarjetas = "".join(html_tarjeta_sucursal(s, editando) for s in gestor.sucursales_ordenadas())
    if not tarjetas:
        tarjetas = '<p class="text-body-secondary">Todavía no hay sucursales. Agrega la primera con el formulario.</p>'

    # iteramos el enum TipoSucursal para el <select> (marcando el tipo actual al editar)
    tipo_actual = editando.tipo if editando else TipoSucursal.TIENDA
    opciones_tipo = "".join(
        f'<option value="{t.name}" {"selected" if t is tipo_actual else ""}>{t.value}</option>' for t in TipoSucursal
    )

    # trabajadores que todavia no tienen sucursal
    sin_sucursal = [t for t in gestor.trabajadores_ordenados()
                    if t.es_empleado and t.codigo_sucursal not in gestor.sucursales]
    lista_sin_sucursal = "".join(
        f'<a class="badge text-bg-light border me-1 mb-1 text-decoration-none" href="/trabajadores?editar={e(t.codigo)}">'
        f'{e(t.nombre_completo)}</a>' for t in sin_sucursal
    ) or '<span class="text-body-secondary small">Todos tienen sucursal asignada</span>'

    if editando:
        formulario_html = dict(
            form_titulo=f'<i class="bi bi-pencil-square me-2"></i>Editando {e(editando.nombre)}',
            form_accion="/sucursales/actualizar",
            volver=f"/sucursales?editar={e(editando.codigo)}",
            boton='<i class="bi bi-save me-1"></i>Guardar cambios',
            cancelar='<a class="btn btn-outline-secondary" href="/sucursales">Cancelar</a>',
            v_codigo=e(editando.codigo), v_nombre=e(editando.nombre), v_direccion=e(editando.direccion),
            v_coordenadas=editando.coordenadas, v_radio=editando.radio_metros,
        )
    else:
        formulario_html = dict(
            form_titulo='<i class="bi bi-shop me-2"></i>Nueva sucursal',
            form_accion="/sucursales/agregar",
            volver="/sucursales",
            boton='<i class="bi bi-save me-1"></i>Guardar sucursal',
            cancelar="",
            v_codigo="", v_nombre="", v_direccion="", v_coordenadas="", v_radio=RADIO_DEFECTO,
        )

    return pagina(
        parametros, usuario, "Sucursales", "sucursales.html", "sucursales",
        tarjetas=tarjetas, total=len(gestor.sucursales), opciones_tipo=opciones_tipo,
        sin_sucursal=lista_sin_sucursal, total_sin_sucursal=len(sin_sucursal),
        radio_minimo=RADIO_MINIMO, radio_maximo=RADIO_MAXIMO, **formulario_html,
    )


def html_tarjeta_sucursal(s, editando) -> str:
    # una tarjeta por sucursal: datos, mapa embebido y quienes trabajan ahi
    trabajadores = gestor.trabajadores_de_sucursal(s.codigo)
    personas = "".join(
        f'<span class="badge text-bg-light border me-1 mb-1">{e(t.nombre_completo)}</span>' for t in trabajadores
    ) or '<span class="text-body-secondary small">Nadie asignado</span>'
    color = "primary" if s.tipo is TipoSucursal.BODEGA else "success"
    borde = "border-primary" if editando and s.codigo == editando.codigo else ""

    return f'''
    <div class="col-xl-6">
      <div class="card tarjeta h-100 {borde}">
        <div class="ratio ratio-16x9">
          <iframe src="{s.url_mapa}" title="Mapa de {e(s.nombre)}" loading="lazy" referrerpolicy="no-referrer-when-downgrade"></iframe>
        </div>
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-start mb-2">
            <div>
              <h6 class="mb-0">{e(s.nombre)}</h6>
              <small class="text-body-secondary">{e(s.codigo)} · {e(s.direccion) or "Sin dirección"}</small>
            </div>
            <span class="badge text-bg-{color}">{s.tipo.value}</span>
          </div>
          <dl class="row small mb-2">
            <dt class="col-5 fw-normal text-body-secondary">Coordenadas</dt><dd class="col-7 text-end mb-1 font-monospace">{s.coordenadas}</dd>
            <dt class="col-5 fw-normal text-body-secondary">Radio permitido</dt><dd class="col-7 text-end mb-1">{s.radio_metros} m</dd>
            <dt class="col-5 fw-normal text-body-secondary">Trabajadores</dt><dd class="col-7 text-end mb-1">{len(trabajadores)}</dd>
          </dl>
          <div class="mb-3">{personas}</div>
          <div class="d-flex gap-2">
            <a class="btn btn-sm btn-outline-secondary" href="{s.url_google_maps}" target="_blank" rel="noopener"><i class="bi bi-geo-alt me-1"></i>Abrir en Google Maps</a>
            <a class="btn btn-sm btn-outline-primary ms-auto" href="/sucursales?editar={e(s.codigo)}" title="Editar sucursal"><i class="bi bi-pencil"></i></a>
            <form method="post" action="/sucursales/eliminar" class="d-inline">
              <input type="hidden" name="codigo" value="{e(s.codigo)}"><input type="hidden" name="volver" value="/sucursales">
              <button class="btn btn-sm btn-outline-danger" title="Eliminar sucursal"><i class="bi bi-trash"></i></button>
            </form>
          </div>
        </div>
      </div>
    </div>'''


def datos_de_sucursal(formulario: dict) -> dict:
    # convierte el formulario en los datos que necesita la clase Sucursal
    # las coordenadas llegan en un solo campo ("14.63, -90.50") y las separamos en dos numeros
    latitud, longitud = separar_coordenadas(formulario.get("coordenadas", ""))
    return {
        "nombre": formulario.get("nombre", ""),
        "tipo": formulario.get("tipo", ""),
        "direccion": formulario.get("direccion", ""),
        "latitud": latitud,
        "longitud": longitud,
        "radio_metros": formulario.get("radio_metros", ""),
    }


@ruta("POST", "/sucursales/agregar")
@requiere_rol(*SOLO_SUPERADMIN)
def agregar_sucursal(parametros, formulario, usuario):
    sucursal = gestor.agregar_sucursal(datos_de_sucursal(formulario))
    return redirigir("/sucursales", msg=f"Sucursal {sucursal.nombre} agregada con el código {sucursal.codigo}")


@ruta("POST", "/sucursales/actualizar")
@requiere_rol(*SOLO_SUPERADMIN)
def actualizar_sucursal(parametros, formulario, usuario):
    sucursal = gestor.actualizar_sucursal(formulario.get("codigo", ""), datos_de_sucursal(formulario))
    return redirigir("/sucursales", msg=f"Sucursal {sucursal.nombre} actualizada")


@ruta("POST", "/sucursales/eliminar")
@requiere_rol(*SOLO_SUPERADMIN)
def eliminar_sucursal(parametros, formulario, usuario):
    sucursal = gestor.eliminar_sucursal(formulario.get("codigo", ""))
    return redirigir("/sucursales", msg=f"Sucursal {sucursal.nombre} eliminada (puedes deshacerlo en Asistencia)")


# ---------------------------------------------------------------
# ASISTENCIA (CRUD de correcciones manuales)
# R: GET /asistencia   C: POST /asistencia/registrar
# U: POST /asistencia/actualizar   D: POST /asistencia/eliminar
# ---------------------------------------------------------------
@ruta("GET", "/asistencia")
@requiere_rol(*ADMINS)
def ver_asistencia(parametros, formulario, usuario):
    hoy = date.today()
    lunes = obtener_semana(parametros)
    volver = f"/asistencia?semana={lunes}"
    codigos = {t.codigo for t in gestor.empleados_visibles(usuario)}
    # si viene ?editar=EMP-001&fecha=... llenamos el formulario con ese registro (si lo puede gestionar)
    editando = gestor.buscar_registro(parametros.get("editar", ""), parametros.get("fecha", ""))
    if editando and not puede_gestionar(usuario, gestor.trabajadores[editando.codigo_trabajador]):
        editando = None

    filas = []
    for registro in gestor.iterar_registros(lunes=lunes):
        if registro.codigo_trabajador not in codigos:
            continue                                        # no es de su gente
        trabajador = gestor.trabajadores[registro.codigo_trabajador]
        almuerzo = f"{registro.salida_almuerzo or '—'} → {registro.regreso_almuerzo or '—'}"
        clase = "table-primary" if registro is editando else ""
        if puede_gestionar(usuario, trabajador):
            acciones = (
                f'<a class="btn btn-sm btn-outline-primary" href="{volver}&editar={e(registro.codigo_trabajador)}&fecha={registro.fecha}" title="Editar marcas"><i class="bi bi-pencil"></i></a> '
                f'<form method="post" action="/asistencia/eliminar" class="d-inline">'
                f'<input type="hidden" name="codigo" value="{e(registro.codigo_trabajador)}">'
                f'<input type="hidden" name="fecha" value="{registro.fecha}"><input type="hidden" name="volver" value="{volver}">'
                f'<button class="btn btn-sm btn-outline-danger" title="Eliminar registro"><i class="bi bi-trash"></i></button></form>'
            )
        else:
            acciones = '<span class="text-body-secondary small">—</span>'
        filas.append(
            f'<tr class="{clase}"><td><div class="fw-semibold">{registro.dia.value}</div><small class="text-body-secondary">{registro.fecha:%d/%m/%Y}</small></td>'
            f'<td><div class="fw-semibold">{e(trabajador.nombre_completo)}</div><small class="text-body-secondary">{e(trabajador.puesto.value)}</small></td>'
            f'<td class="font-monospace small">{registro.entrada}</td>'
            f'<td class="font-monospace small">{almuerzo}</td>'
            f'<td class="font-monospace small">{registro.salida or "—"}</td>'
            f'<td class="font-monospace small fw-semibold">{segundos_a_texto(calcular_segundos_trabajados(registro))}</td>'
            f'<td>{html_jornada(estado_jornada(registro, trabajador, hoy))}</td>'
            f'<td>{html_alertas(generar_alertas(registro, trabajador, hoy))}</td>'
            f'<td class="text-end text-nowrap">{acciones}</td></tr>'
        )
    tabla = "".join(filas) or '<tr><td colspan="9" class="text-center text-body-secondary py-4">No hay registros en esta semana</td></tr>'

    if editando:
        nombre = gestor.trabajadores[editando.codigo_trabajador].nombre_completo
        valores = dict(v_entrada=editando.entrada, v_salida_almuerzo=editando.salida_almuerzo,
                       v_regreso_almuerzo=editando.regreso_almuerzo, v_salida=editando.salida)
        extra = dict(
            form_titulo=f'<i class="bi bi-pencil-square me-2"></i>Editando: {e(nombre)} · {editando.dia.value} {editando.fecha:%d/%m/%Y}',
            v_fecha=editando.fecha.isoformat(),
            opciones_trabajadores=opciones_trabajadores(usuario, editando.codigo_trabajador),
            cancelar=f'<a class="btn btn-outline-secondary" href="{volver}">Cancelar</a>',
            form_accion="/asistencia/actualizar",
            # campos ocultos: de que registro venimos (por si se cambia la fecha o el trabajador)
            originales=(f'<input type="hidden" name="codigo_original" value="{e(editando.codigo_trabajador)}">'
                        f'<input type="hidden" name="fecha_original" value="{editando.fecha}">'),
        )
    else:
        valores = dict(v_entrada="", v_salida_almuerzo="", v_regreso_almuerzo="", v_salida="")
        # la fecha propuesta es hoy si ves la semana actual, o el lunes de la semana que estas viendo
        fecha_sugerida = hoy if lunes == lunes_de(hoy) else lunes
        extra = dict(
            form_titulo='<i class="bi bi-clock me-2"></i>Registrar un día (corrección manual)',
            v_fecha=fecha_sugerida.isoformat(),
            opciones_trabajadores=opciones_trabajadores(usuario),
            cancelar="",
            form_accion="/asistencia/registrar",
            originales="",
        )

    return pagina(
        parametros, usuario, "Asistencia", "asistencia.html", "asistencia",
        navegacion=navegacion_semana("/asistencia", lunes),
        hoy=hoy.isoformat(),
        volver=volver,
        filas=tabla,
        boton_deshacer=html_boton_deshacer(usuario, volver),
        **extra, **valores,
    )


def html_boton_deshacer(usuario, volver: str) -> str:
    # deshacer revierte la ultima accion de TODA la empresa: solo para superadmins
    if usuario.rol != Rol.SUPERADMIN:
        return ""
    ultima = gestor.historial[-1][0] if gestor.historial else ""
    deshabilitado = "" if ultima else "disabled"
    titulo = e(f"Deshacer: {ultima}" if ultima else "Nada que deshacer")
    return (f'<form method="post" action="/deshacer"><input type="hidden" name="volver" value="{volver}">'
            f'<button class="btn btn-outline-secondary" title="{titulo}" {deshabilitado}>'
            f'<i class="bi bi-arrow-counterclockwise me-1"></i>Deshacer</button></form>')


def datos_de_marcas(formulario: dict) -> dict:
    # desempaquetado con *: ("codigo_trabajador", "fecha", "entrada", ...)
    return {campo: formulario.get(campo, "") for campo in ("codigo_trabajador", "fecha", *CLAVES_MARCAS)}


@ruta("POST", "/asistencia/registrar")
@requiere_rol(*ADMINS)
def registrar_asistencia(parametros, formulario, usuario):
    registro, alertas = gestor.registrar_asistencia(datos_de_marcas(formulario), por=usuario)
    return mensaje_de_registro(registro, alertas)


@ruta("POST", "/asistencia/actualizar")
@requiere_rol(*ADMINS)
def actualizar_registro(parametros, formulario, usuario):
    registro, alertas = gestor.actualizar_registro(formulario.get("codigo_original", ""),
                                                   formulario.get("fecha_original", ""),
                                                   datos_de_marcas(formulario), por=usuario)
    return mensaje_de_registro(registro, alertas)


def mensaje_de_registro(registro, alertas):
    # arma el mensaje verde (sin alertas) o amarillo (con alertas) despues de guardar
    trabajador = gestor.trabajadores[registro.codigo_trabajador]
    total = segundos_a_texto(calcular_segundos_trabajados(registro))
    estado = estado_jornada(registro, trabajador, date.today())
    destino = f"/asistencia?semana={lunes_de(registro.fecha)}"
    texto = f"{trabajador.nombre_completo} · {registro.dia.value}: {total} trabajadas. {estado.etiqueta}."
    if alertas:
        tipos = ", ".join(a.tipo.etiqueta for a in alertas)
        return redirigir(destino, aviso=f"{texto} Alertas: {tipos}")
    return redirigir(destino, msg=f"{texto} Sin alertas.")


@ruta("POST", "/asistencia/eliminar")
@requiere_rol(*ADMINS)
def eliminar_registro(parametros, formulario, usuario):
    gestor.eliminar_registro(formulario.get("codigo", ""), formulario.get("fecha", ""), por=usuario)
    return redirigir(destino_seguro(formulario.get("volver", "/asistencia")), msg="Registro eliminado")


@ruta("POST", "/deshacer")
@requiere_rol(*SOLO_SUPERADMIN)
def deshacer(parametros, formulario, usuario):
    descripcion = gestor.deshacer()
    return redirigir(destino_seguro(formulario.get("volver", "/")), msg=f"Se deshizo: {descripcion}")


# ---------------------------------------------------------------
# REPORTE SEMANAL
# ---------------------------------------------------------------
def html_tarjeta_resumen(resumen: dict) -> str:
    t = resumen["trabajador"]
    # horario libre: no marca asistencia, asi que su tarjeta solo lo indica
    if t.horario_libre:
        return f'''
    <div class="col-md-6 col-xl-4">
      <div class="card tarjeta h-100">
        <div class="card-body">
          <h6 class="mb-0">{e(t.nombre_completo)}</h6>
          <small class="text-body-secondary">{e(t.puesto.value)} · {e(t.codigo)}</small>
          <div class="mt-3">{html_jornada(EstadoJornada.LIBRE)}</div>
          <p class="small text-body-secondary mt-2 mb-0">No marca asistencia: no tiene meta de horas, faltas ni alertas.</p>
        </div>
      </div>
    </div>'''

    porcentaje = resumen["porcentaje"]
    color = "success" if porcentaje >= 100 else "warning" if porcentaje >= 80 else "danger"
    # señal de la semana: completa (44h, con la tolerancia semanal) o no
    if resumen["semana_completa"]:
        senal = '<span class="badge text-bg-success"><i class="bi bi-check-circle-fill me-1"></i>Semana completa</span>'
    else:
        senal = '<span class="badge text-bg-danger"><i class="bi bi-x-circle-fill me-1"></i>Semana incompleta</span>'
    completas = f'{resumen["jornadas_completas"]} de {resumen["dias_trabajados"]}'

    # cuadritos L M M J V S con el estado de cada dia (zip une letra con dia)
    dias = "".join(
        f'<span class="dia dia-{estado}" title="{fecha:%d/%m} · {estado.replace("-", " ")}">{letra}</span>'
        for letra, (fecha, estado) in zip(LETRAS_DIAS, resumen["dias"])
    )
    faltas = ", ".join(dia_de(f).value for f in resumen["faltas"]) or "Ninguna"
    conteo = "".join(
        f'<span class="badge text-bg-{tipo.color} me-1 mb-1">{e(tipo.etiqueta)}: {cantidad}</span>'
        for tipo, cantidad in resumen["conteo_alertas"].items()
    ) or '<span class="text-body-secondary small">Sin alertas</span>'

    return f'''
    <div class="col-md-6 col-xl-4">
      <div class="card tarjeta h-100">
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-start mb-2">
            <div><h6 class="mb-0">{e(t.nombre_completo)}</h6><small class="text-body-secondary">{e(t.puesto.value)} · {e(t.codigo)}</small></div>
            <div class="dias">{dias}</div>
          </div>
          <div class="mb-2">{senal}</div>
          <div class="d-flex justify-content-between small mb-1">
            <span class="font-monospace fw-semibold">{segundos_a_texto(resumen["total"])}</span>
            <span class="text-body-secondary">meta {segundos_a_texto(resumen["esperado"])}</span>
          </div>
          <div class="progress mb-3" role="progressbar" aria-valuenow="{porcentaje}" aria-valuemin="0" aria-valuemax="100">
            <div class="progress-bar bg-{color}" style="width: {min(porcentaje, 100)}%">{porcentaje}%</div>
          </div>
          <dl class="row small mb-2">
            <dt class="col-7 fw-normal text-body-secondary">Días trabajados</dt><dd class="col-5 text-end mb-1">{resumen["dias_trabajados"]}</dd>
            <dt class="col-7 fw-normal text-body-secondary">Jornadas completas</dt><dd class="col-5 text-end mb-1">{completas}</dd>
            <dt class="col-7 fw-normal text-body-secondary">Le falta</dt><dd class="col-5 text-end mb-1 font-monospace">{segundos_a_texto(resumen["faltante"])}</dd>
            <dt class="col-7 fw-normal text-body-secondary">Faltas</dt><dd class="col-5 text-end mb-1">{faltas}</dd>
          </dl>
          <div>{conteo}</div>
        </div>
      </div>
    </div>'''


@ruta("GET", "/reporte")
@requiere_rol(*ADMINS)
def ver_reporte(parametros, formulario, usuario):
    lunes = obtener_semana(parametros)
    hoy = date.today()
    feriados = gestor.feriados_de_semana(lunes)
    # solo los trabajadores que el usuario puede ver (su sucursal, o todos si es superadmin)
    resumenes = [
        resumen_semanal(t, list(gestor.iterar_registros(t.codigo, lunes)), lunes, set(feriados), hoy)
        for t in gestor.empleados_visibles(usuario)
    ]
    # funcion de orden superior: sorted con lambda, de mas horas a menos
    resumenes = sorted(resumenes, key=lambda r: r["total"], reverse=True)
    # map aplica nuestra propia funcion a cada resumen
    tarjetas = "".join(map(html_tarjeta_resumen, resumenes)) or '<p class="text-body-secondary">No hay trabajadores.</p>'

    lista_feriados = "".join(
        f'<span class="badge text-bg-light border me-1"><i class="bi bi-calendar-heart me-1"></i>{fecha:%d/%m} {e(nombre)}</span>'
        for fecha, nombre in sorted(feriados.items())
    )
    volver = f"/reporte?semana={lunes}"
    return pagina(
        parametros, usuario, "Reporte semanal", "reporte.html", "reporte",
        navegacion=navegacion_semana("/reporte", lunes),
        tarjetas=tarjetas,
        feriados=lista_feriados,
        acciones_exportar=html_acciones_exportar(usuario, volver),
    )


def html_acciones_exportar(usuario, volver: str) -> str:
    # exportar incluye los datos de toda la empresa: solo para superadmins
    if usuario.rol != Rol.SUPERADMIN:
        return ""
    descargas = "".join(
        f'<a class="btn btn-outline-secondary btn-sm" href="/descargar?archivo={tipo}"><i class="bi bi-download me-1"></i>{archivo.name}</a>'
        for tipo, archivo in (("json", ARCHIVO_EXPORT_JSON), ("xml", ARCHIVO_EXPORT_XML)) if archivo.exists()
    )
    return (f'{descargas}<form method="post" action="/exportar"><input type="hidden" name="volver" value="{volver}">'
            f'<button class="btn btn-primary btn-sm"><i class="bi bi-filetype-json me-1"></i>Exportar JSON y XML</button></form>')


@ruta("POST", "/exportar")
@requiere_rol(*SOLO_SUPERADMIN)
def exportar(parametros, formulario, usuario):
    gestor.exportar()
    return redirigir(destino_seguro(formulario.get("volver", "/reporte")),
                     msg=f"Exportado: {ARCHIVO_EXPORT_JSON.name} y {ARCHIVO_EXPORT_XML.name} (carpeta datos)")


@ruta("GET", "/descargar")
@requiere_rol(*SOLO_SUPERADMIN)
def descargar(parametros, formulario, usuario):
    # diccionario como "switch": tipo -> (archivo, content-type)
    archivos = {"json": (ARCHIVO_EXPORT_JSON, "application/json"), "xml": (ARCHIVO_EXPORT_XML, "application/xml")}
    archivo, tipo = archivos.get(parametros.get("archivo"), (None, None))
    if archivo is None or not archivo.exists():
        raise AsistenciaError("Primero exporta los archivos")
    return Descarga(archivo, tipo)
