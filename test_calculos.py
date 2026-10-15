# test_calculos.py  ->  PASO 10 de la ruta de estudio
# pruebas unitarias de la logica (sin servidor ni archivos)
# ejecutar con:  python -m unittest -v

import unittest
from datetime import date

from calculos import (calcular_segundos_trabajados, distancia_metros, estado_jornada, evaluar_ubicacion,
                      generar_alertas, lunes_de, opciones_de_marca, resumen_semanal, sumar_recursivo)
from modelos import Marcacion, TipoAnomalia, TipoMarca
from utilidades import numero_o_none
from excepciones import DatoInvalidoError, DiaNoLaboralError, HorarioInvalidoError
from modelos import (DiaSemana, EstadoJornada, Puesto, RegistroAsistencia, Sucursal, TipoAlerta, TipoSucursal,
                     Trabajador, dia_de)
from utilidades import (HORAS_SEMANALES, cifrar_clave, clave_inicial, hora_a_segundos, segundos_a_texto,
                        separar_coordenadas, verificar_clave)
from modelos import Rol
from sesiones import (GestorSesiones, crear_cookie, puede_gestionar, puede_ver, roles_que_puede_dar,
                      token_de_cookie)

LUNES = date(2026, 10, 5)
JUEVES = date(2026, 10, 8)
SABADO = date(2026, 10, 10)
DOMINGO = date(2026, 10, 11)


def crear_trabajador(**cambios):
    # funcion de ayuda: trabajador con horario 08:00 - 17:00
    datos = {"codigo": "EMP-001", "nombre": "ana", "apellido": "lopez", "correo": "Ana@Empresa.com",
             "telefono": "5512-3456", "puesto": "GERENTE", "fecha_ingreso": "2024-01-01"}
    datos.update(cambios)
    return Trabajador(**datos)


def crear_registro(entrada="08:00:00", salida_almuerzo="12:00:00", regreso="13:00:00", salida="17:00:00", fecha=JUEVES):
    # la fecha se pasa como texto "2026-10-08", igual que llega del formulario
    return RegistroAsistencia("EMP-001", fecha.isoformat(), entrada, salida_almuerzo, regreso, salida)


def crear_sucursal(**cambios):
    # funcion de ayuda: una tienda de ejemplo con radio de 100 m
    datos = {"codigo": "SUC-001", "nombre": "  Tienda   Zona 10 ", "tipo": "TIENDA", "direccion": "zona 10",
             "latitud": 14.5995, "longitud": -90.5082, "radio_metros": "100"}
    datos.update(cambios)
    return Sucursal(**datos)


class PruebasUbicacion(unittest.TestCase):

    def setUp(self):
        # tienda en 14.5995, -90.5082 con radio de 100 m
        self.tienda = crear_sucursal()

    def test_haversine_mismo_punto(self):
        self.assertEqual(distancia_metros(14.5995, -90.5082, 14.5995, -90.5082), 0)

    def test_haversine_un_grado_de_latitud(self):
        # un grado de latitud mide unos 111 195 m en cualquier parte de la Tierra
        self.assertAlmostEqual(distancia_metros(14, -90, 15, -90), 111_195, delta=1)

    def test_dentro_del_radio(self):
        # 0.0005 grados de latitud son unos 56 m: esta dentro de los 100 m
        anomalia, distancia = evaluar_ubicacion(self.tienda, 14.6000, -90.5082, 15)
        self.assertIsNone(anomalia)
        self.assertEqual(distancia, 56)

    def test_fuera_del_radio(self):
        # 0.002 grados son unos 222 m: fuera de los 100 m
        anomalia, distancia = evaluar_ubicacion(self.tienda, 14.6015, -90.5082, 10)
        self.assertIs(anomalia, TipoAnomalia.FUERA_DE_SUCURSAL)
        self.assertEqual(distancia, 222)

    def test_gps_impreciso(self):
        anomalia, _ = evaluar_ubicacion(self.tienda, 14.5995, -90.5082, 250)    # el GPS se equivoca 250 m
        self.assertIs(anomalia, TipoAnomalia.UBICACION_IMPRECISA)

    def test_sin_ubicacion_y_sin_sucursal(self):
        self.assertIs(evaluar_ubicacion(self.tienda, None, None, None)[0], TipoAnomalia.SIN_UBICACION)
        self.assertIs(evaluar_ubicacion(None, 14.5995, -90.5082, 10)[0], TipoAnomalia.SIN_SUCURSAL)

    def test_numero_o_none_rechaza_trampas(self):
        self.assertEqual(numero_o_none("14.59"), 14.59)
        self.assertIsNone(numero_o_none(""))
        self.assertIsNone(numero_o_none("nan"))          # "nan" engañaria la comparacion del radio
        self.assertIsNone(numero_o_none("inf"))

    def test_orden_de_las_marcas(self):
        self.assertEqual(opciones_de_marca(None, False), [TipoMarca.ENTRADA])
        solo_entrada = crear_registro(salida_almuerzo="", regreso="", salida="")
        # decision 20: al mediodia puede salir a almorzar o terminar sin almuerzo
        self.assertEqual(opciones_de_marca(solo_entrada, False), [TipoMarca.SALIDA_ALMUERZO, TipoMarca.SALIDA])
        en_almuerzo = crear_registro(regreso="", salida="")
        self.assertEqual(opciones_de_marca(en_almuerzo, False), [TipoMarca.REGRESO_ALMUERZO])
        self.assertEqual(opciones_de_marca(crear_registro(), False), [])                       # ya salio
        self.assertEqual(opciones_de_marca(solo_entrada, True), [TipoMarca.SALIDA])             # sabado sin almuerzo

    def test_marcacion_guarda_la_foto_de_la_sucursal(self):
        marcacion = Marcacion("EMP-001", "2026-10-12T08:01:15", "ENTRADA", 14.6015, -90.5082, 10,
                              "SUC-001", "Tienda Zona 10", 14.5995, -90.5082, 100, 222, "FUERA_DE_SUCURSAL")
        copia = Marcacion(**marcacion.a_diccionario())     # ida y vuelta por el JSON
        self.assertFalse(copia.valida)
        self.assertEqual(copia.sucursal_latitud, 14.5995)
        self.assertIn("14.6015,-90.5082", copia.url_ubicacion)


class PruebasSesionesYPermisos(unittest.TestCase):

    def setUp(self):
        # personajes: Erin (superadmin principal), Victor (superadmin nombrado), un encargado y trabajadores
        self.erin = crear_trabajador(codigo="EMP-004", nombre="Erin", rol="SUPERADMIN")
        self.victor = crear_trabajador(codigo="EMP-008", nombre="Victor", rol="SUPERADMIN")
        self.encargado_a = crear_trabajador(codigo="EMP-010", rol="ADMIN", codigo_sucursal="SUC-001")
        self.trabajador_a = crear_trabajador(codigo="EMP-011", codigo_sucursal="SUC-001")
        self.trabajador_b = crear_trabajador(codigo="EMP-012", codigo_sucursal="SUC-002")

    def test_clave_se_guarda_como_hash(self):
        guardado = cifrar_clave("Erin1234")
        self.assertNotIn("Erin1234", guardado)                   # nunca la clave real
        self.assertTrue(verificar_clave("Erin1234", guardado))
        self.assertFalse(verificar_clave("erin1234", guardado))  # distingue mayusculas
        self.assertNotEqual(guardado, cifrar_clave("Erin1234"))  # sal distinta: hash distinto

    def test_superadmin_no_es_empleado(self):
        # aunque el formulario traiga sucursal y horario, un superadmin no los conserva
        cuenta = crear_trabajador(codigo="EMP-020", rol="SUPERADMIN", codigo_sucursal="SUC-001", trabaja_sabado="si",
                                  sabado_entrada="08:00", sabado_salida="12:00")
        self.assertFalse(cuenta.es_empleado)
        self.assertEqual(cuenta.codigo_sucursal, "")
        self.assertTrue(cuenta.horario_libre)          # no marca asistencia
        self.assertTrue(self.trabajador_a.es_empleado)

    def test_clave_inicial(self):
        self.assertEqual(clave_inicial("Erin"), "Erin1234")

    def test_superadmin_ve_a_todos(self):
        self.assertTrue(puede_ver(self.victor, self.trabajador_b))

    def test_encargado_solo_ve_su_sucursal(self):
        self.assertTrue(puede_ver(self.encargado_a, self.trabajador_a))
        self.assertFalse(puede_ver(self.encargado_a, self.trabajador_b))
        self.assertTrue(puede_ver(self.encargado_a, self.encargado_a))   # se ve a si mismo

    def test_trabajador_solo_se_ve_a_si_mismo(self):
        self.assertTrue(puede_ver(self.trabajador_a, self.trabajador_a))
        self.assertFalse(puede_ver(self.trabajador_a, self.trabajador_b))

    def test_nadie_gestiona_a_erin(self):
        self.assertFalse(puede_gestionar(self.victor, self.erin))
        self.assertTrue(puede_gestionar(self.erin, self.erin))

    def test_solo_erin_gestiona_superadmins(self):
        self.assertTrue(puede_gestionar(self.erin, self.victor))
        otro_super = crear_trabajador(codigo="EMP-009", rol="SUPERADMIN")
        self.assertFalse(puede_gestionar(self.victor, otro_super))

    def test_encargado_gestiona_solo_trabajadores_de_su_sucursal(self):
        self.assertTrue(puede_gestionar(self.encargado_a, self.trabajador_a))
        self.assertFalse(puede_gestionar(self.encargado_a, self.trabajador_b))
        self.assertFalse(puede_gestionar(self.encargado_a, self.encargado_a))   # no a si mismo

    def test_roles_que_puede_dar(self):
        self.assertIn(Rol.SUPERADMIN, roles_que_puede_dar(self.erin))        # solo Erin nombra superadmins
        self.assertNotIn(Rol.SUPERADMIN, roles_que_puede_dar(self.victor))
        self.assertEqual(roles_que_puede_dar(self.encargado_a), [Rol.TRABAJADOR])

    def test_sesion_iniciar_leer_y_cerrar(self):
        sesiones = GestorSesiones()
        token = sesiones.iniciar_sesion("EMP-011")
        self.assertEqual(sesiones.codigo_de(token), "EMP-011")
        self.assertIsNone(sesiones.codigo_de("token-inventado"))
        sesiones.cerrar_sesiones_de("EMP-011")
        self.assertIsNone(sesiones.codigo_de(token))

    def test_cookie_ida_y_vuelta(self):
        # lo que el servidor manda en Set-Cookie, el navegador lo devuelve en Cookie
        cabecera = crear_cookie("abc123")
        self.assertIn("HttpOnly", cabecera)
        self.assertEqual(token_de_cookie("sesion=abc123"), "abc123")
        self.assertEqual(token_de_cookie(""), "")


class PruebasSucursales(unittest.TestCase):

    def test_separar_coordenadas_de_google_maps(self):
        self.assertEqual(separar_coordenadas("14.634915, -90.506882"), (14.634915, -90.506882))
        self.assertEqual(separar_coordenadas("14.63,-90.50"), (14.63, -90.50))      # sin espacio tambien sirve

    def test_coordenadas_mal_escritas(self):
        with self.assertRaises(DatoInvalidoError):
            separar_coordenadas("zona 10")

    def test_sucursal_formatea_datos(self):
        sucursal = crear_sucursal()
        self.assertEqual(sucursal.nombre, "Tienda Zona 10")          # se quitan los espacios sobrantes
        self.assertEqual(sucursal.tipo, TipoSucursal.TIENDA)
        self.assertEqual(sucursal.radio_metros, 100)                  # el texto "100" se convierte a numero
        self.assertIn("14.5995,-90.5082", sucursal.url_mapa)

    def test_tipo_de_sucursal_invalido(self):
        with self.assertRaises(DatoInvalidoError):
            crear_sucursal(tipo="OFICINA")

    def test_coordenadas_fuera_del_mapa(self):
        with self.assertRaises(DatoInvalidoError):
            crear_sucursal(latitud=95)                                # la latitud llega maximo a 90

    def test_radio_fuera_de_rango(self):
        with self.assertRaises(DatoInvalidoError):
            crear_sucursal(radio_metros="5")
        with self.assertRaises(DatoInvalidoError):
            crear_sucursal(radio_metros="cien")

    def test_trabajador_guarda_su_sucursal(self):
        trabajador = crear_trabajador(codigo_sucursal="SUC-001")
        self.assertEqual(trabajador.a_diccionario()["codigo_sucursal"], "SUC-001")
        self.assertEqual(crear_trabajador().codigo_sucursal, "")      # sin asignar por defecto


class PruebasUtilidades(unittest.TestCase):

    def test_hora_a_segundos(self):
        self.assertEqual(hora_a_segundos("08:15:30"), 8 * 3600 + 15 * 60 + 30)
        self.assertEqual(hora_a_segundos("08:15"), 8 * 3600 + 15 * 60)

    def test_hora_invalida(self):
        with self.assertRaises(DatoInvalidoError):
            hora_a_segundos("25:00")

    def test_segundos_a_texto(self):
        self.assertEqual(segundos_a_texto(8 * 3600 + 5 * 60 + 9), "8h 05m 09s")

    def test_sumar_recursivo(self):
        self.assertEqual(sumar_recursivo([1, 2, 3, 4]), 10)
        self.assertEqual(sumar_recursivo([]), 0)

    def test_lunes_de(self):
        self.assertEqual(lunes_de(JUEVES), LUNES)


class PruebasModelos(unittest.TestCase):

    def test_trabajador_formatea_datos(self):
        trabajador = crear_trabajador()
        self.assertEqual(trabajador.nombre_completo, "Ana Lopez")
        self.assertEqual(trabajador.correo, "ana@empresa.com")
        self.assertEqual(trabajador.puesto, Puesto.GERENTE)
        self.assertEqual(trabajador.jornada_semana, 8 * 3600)
        self.assertEqual(trabajador.horas_de_horario, 40 * 3600)     # 8h x 5 dias, sin sabado

    def test_correo_invalido(self):
        with self.assertRaises(DatoInvalidoError):
            crear_trabajador(correo="sin-arroba")

    def test_puesto_invalido(self):
        with self.assertRaises(DatoInvalidoError):
            crear_trabajador(puesto="ASTRONAUTA")

    def test_dia_semana(self):
        self.assertEqual(dia_de(JUEVES), DiaSemana.JUEVES)
        self.assertEqual(dia_de(SABADO), DiaSemana.SABADO)

    def test_domingo_no_permitido(self):
        with self.assertRaises(DiaNoLaboralError):
            crear_registro(fecha=DOMINGO)

    def test_horario_con_sabado_suma_44_horas(self):
        trabajador = crear_trabajador(trabaja_sabado="si", sabado_entrada="08:00", sabado_salida="12:00")
        self.assertEqual(trabajador.jornada_sabado, 4 * 3600)
        self.assertEqual(trabajador.horas_de_horario, HORAS_SEMANALES)

    def test_sabado_sin_horas_da_error(self):
        with self.assertRaises(HorarioInvalidoError):
            crear_trabajador(trabaja_sabado="si", sabado_entrada="", sabado_salida="")

    def test_horas_desordenadas(self):
        with self.assertRaises(HorarioInvalidoError):
            crear_registro(entrada="12:00:00", salida="11:00:00", salida_almuerzo="", regreso="")


class PruebasCalculos(unittest.TestCase):

    def setUp(self):
        # setUp se ejecuta antes de cada prueba
        self.trabajador = crear_trabajador()

    def test_jornada_completa_sin_alertas(self):
        registro = crear_registro()
        self.assertEqual(calcular_segundos_trabajados(registro), 8 * 3600)
        self.assertEqual(generar_alertas(registro, self.trabajador), [])

    def test_llegada_tarde(self):
        registro = crear_registro(entrada="08:20:00")
        tipos = [a.tipo for a in generar_alertas(registro, self.trabajador)]
        self.assertIn(TipoAlerta.LLEGADA_TARDE, tipos)
        self.assertIn(TipoAlerta.JORNADA_INCOMPLETA, tipos)

    def test_tolerancia_de_5_minutos(self):
        registro = crear_registro(entrada="08:04:59", salida="17:05:00")
        tipos = [a.tipo for a in generar_alertas(registro, self.trabajador)]
        self.assertNotIn(TipoAlerta.LLEGADA_TARDE, tipos)

    def test_salida_temprana(self):
        registro = crear_registro(salida="16:30:00")
        tipos = [a.tipo for a in generar_alertas(registro, self.trabajador)]
        self.assertIn(TipoAlerta.SALIDA_TEMPRANA, tipos)

    def test_marcas_incompletas(self):
        registro = crear_registro(salida_almuerzo="12:00:00", regreso="", salida="")
        self.assertEqual(calcular_segundos_trabajados(registro), 4 * 3600)
        tipos = [a.tipo for a in generar_alertas(registro, self.trabajador)]
        self.assertIn(TipoAlerta.REGISTRO_INCOMPLETO, tipos)

    def test_callback_se_ejecuta(self):
        recibidas = []
        registro = crear_registro(entrada="09:00:00")
        # pasamos una lambda como callback
        generar_alertas(registro, self.trabajador, al_generar_alerta=lambda t, r, a: recibidas.append(a))
        self.assertTrue(len(recibidas) >= 1)

    def test_senal_jornada_completa(self):
        self.assertIs(estado_jornada(crear_registro(), self.trabajador), EstadoJornada.COMPLETA)
        self.assertIs(estado_jornada(crear_registro(salida="16:00:00"), self.trabajador), EstadoJornada.INCOMPLETA)

    def test_jornada_en_curso_no_alerta(self):
        # hoy, sin salida: aun puede completar, no se alerta jornada incompleta
        registro = crear_registro(regreso="", salida_almuerzo="", salida="")
        self.assertIs(estado_jornada(registro, self.trabajador, hoy=JUEVES), EstadoJornada.EN_CURSO)
        tipos = [a.tipo for a in generar_alertas(registro, self.trabajador, hoy=JUEVES)]
        self.assertNotIn(TipoAlerta.JORNADA_INCOMPLETA, tipos)

    def test_horario_libre_sin_alertas(self):
        # horario libre no marca asistencia: aunque hubiera un registro incompleto, no hay alertas
        gerente = crear_trabajador(horario_libre=True)
        registro = crear_registro(entrada="10:00:00", salida_almuerzo="", regreso="", salida="")
        self.assertEqual(gerente.jornada_semana, 0)
        self.assertEqual(generar_alertas(registro, gerente), [])      # lista vacia, no 0
        self.assertIs(estado_jornada(registro, gerente), EstadoJornada.LIBRE)

    def test_horario_libre_sin_meta_ni_faltas(self):
        # Victor (horario libre) sin ningun registro en la semana: no debe tener faltas ni meta
        gerente = crear_trabajador(horario_libre=True)
        resumen = resumen_semanal(gerente, [], LUNES, set(), SABADO)
        self.assertEqual(resumen["faltas"], [])
        self.assertEqual(resumen["esperado"], 0)
        self.assertEqual(resumen["faltante"], 0)
        self.assertEqual(resumen["alertas"], [])

    def test_horario_fijo_sin_horas_da_error(self):
        with self.assertRaises(HorarioInvalidoError):
            crear_trabajador(hora_entrada="", hora_salida="")

    def test_resumen_respeta_fecha_ingreso(self):
        # entro el miercoles: lunes y martes no son faltas
        trabajador = crear_trabajador(fecha_ingreso="2026-10-07")
        resumen = resumen_semanal(trabajador, [crear_registro(fecha=JUEVES)], LUNES, set(), JUEVES)
        self.assertEqual(resumen["faltas"], [date(2026, 10, 7)])
        self.assertEqual(resumen["esperado"], HORAS_SEMANALES * 3 // 5)     # 3 de 5 dias de la meta de 44h
        self.assertEqual(resumen["dias"][0][1], "sin-ingresar")

    def test_resumen_semanal_cuenta_faltas(self):
        registros = [crear_registro(fecha=LUNES), crear_registro(fecha=JUEVES)]
        resumen = resumen_semanal(self.trabajador, registros, LUNES, set(), JUEVES)
        self.assertEqual(resumen["total"], 16 * 3600)
        self.assertEqual(resumen["esperado"], HORAS_SEMANALES)
        self.assertEqual(resumen["faltas"], [date(2026, 10, 6), date(2026, 10, 7)])   # martes y miercoles
        self.assertEqual(resumen["dias"][4][1], "pendiente")                         # viernes aun no llega
        self.assertEqual(len(resumen["dias"]), 5)                                    # no trabaja sabados

    def test_sabado_sin_almuerzo_ni_alertas(self):
        # sabado 08:00 - 12:00: no pide almuerzo y cumple su jornada
        trabajador = crear_trabajador(trabaja_sabado="si", sabado_entrada="08:00", sabado_salida="12:00")
        registro = crear_registro(fecha=SABADO, salida_almuerzo="", regreso="", salida="12:00:00")
        self.assertEqual(generar_alertas(registro, trabajador), [])
        self.assertIs(estado_jornada(registro, trabajador), EstadoJornada.COMPLETA)

    def test_semana_completa_con_tolerancia(self):
        # 5 dias de 8h 47m = 43h 55m: esta dentro de la tolerancia (desde 43h 45m), se acepta
        trabajador = crear_trabajador(hora_salida="17:48")
        dias = [date(2026, 10, d) for d in range(5, 10)]
        registros = [crear_registro(fecha=d, salida="17:47:00") for d in dias]
        resumen = resumen_semanal(trabajador, registros, LUNES, set(), SABADO)
        self.assertEqual(resumen["total"], 43 * 3600 + 55 * 60)
        self.assertTrue(resumen["semana_completa"])

    def test_semana_incompleta_fuera_de_tolerancia(self):
        # 5 dias de 8h = 40h: no llega a 44h
        registros = [crear_registro(fecha=date(2026, 10, d)) for d in range(5, 10)]
        resumen = resumen_semanal(self.trabajador, registros, LUNES, set(), SABADO)
        self.assertFalse(resumen["semana_completa"])
        self.assertEqual(resumen["faltante"], 4 * 3600)


if __name__ == "__main__":
    unittest.main()
