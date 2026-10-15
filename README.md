# Control de Asistencia con Ubicación

Sistema web en **Python** y **Bootstrap** para controlar la asistencia de los empleados de una empresa con varias sucursales (bodega y tiendas).

Cada empleado inicia sesión desde su celular y marca su entrada, almuerzo y salida. El sistema toma la **ubicación del celular** y revisa que esté dentro de **su** sucursal. Si marca desde otro lugar, la marca se rechaza y queda registrada como **anomalía** para que la revise su encargado.

También calcula las horas trabajadas, las alertas (llegada tarde, salida anticipada, jornada incompleta) y el reporte semanal con la meta de **44 horas**.

> Prototipo para una red local. No está preparado para publicarse en internet.

## Funciones principales

- Inicio de sesión con tres roles: **Superadmin**, **Admin** (encargado de sucursal) y **Trabajador**.
- Sucursales con su ubicación en el mapa (Google Maps embebido) y un radio permitido en metros.
- Marcación con GPS: la distancia se calcula con la fórmula de Haversine y la hora la pone el servidor.
- Registro de anomalías (fuera de la sucursal, GPS impreciso, sin ubicación, sin sucursal).
- Cálculo de horas, alertas diarias y reporte semanal.
- Exportación a JSON y XML.
- Conexión cifrada (HTTPS) con un certificado propio.

## Requisitos

| Requisito | Para qué |
|---|---|
| Python 3.13 o superior | Ejecutar el sistema |
| Librería `requests` | Descargar los días feriados |
| `openssl` (en Windows viene con **Git para Windows**) | Crear el certificado HTTPS la primera vez |
| Un celular con GPS y navegador | Marcar asistencia (en iPhone, usar **Safari**) |

Instalar `requests`:

```
pip install requests
```

## Cómo arrancarlo

En Windows, doble clic en `iniciar.bat`, o desde una terminal **dentro de la carpeta del proyecto**:

```
python main.py
```

Al arrancar, la consola muestra dos direcciones:

```
Servidor listo en https://127.0.0.1:8080
Desde el teléfono (misma red Wi-Fi): https://192.168.x.x:8080
```

- La primera es para entrar desde la misma PC.
- La segunda es para el celular.
- La ventana de la consola debe quedar abierta: es el servidor. Para detenerlo: `Ctrl + C`.

La primera vez se crean solas:

- La carpeta `datos/`: `datos.json` con todo lo guardado, el log y las exportaciones.
- La carpeta `certificado/`: el certificado HTTPS propio.

## Datos de ejemplo

Si no existe `datos/datos.json`, el sistema arranca con los datos de `datos_ejemplo.json`: 2 sucursales, 4 usuarios y 3 semanas de marcas.

| Usuario (correo) | Contraseña | Rol | Sucursal |
|---|---|---|---|
| `erin.morales@empresa.com` | `Erin1234` | **Superadmin** | Toda la empresa |
| `luis.perez@empresa.com` | `Luis1234` | Trabajador | Tienda Zona 10 (trabaja sábados) |
| `maria.garcia@empresa.com` | `María1234` | Trabajador | Bodega Central |
| `ana.lopez@empresa.com` | `Ana1234` | Trabajador (horario libre) | Bodega Central |

Las coordenadas de las sucursales de ejemplo son inventadas. Para probar el GPS de verdad, crea una sucursal con tu ubicación real (botón **"Usar mi ubicación actual"**).

Para volver a empezar con los datos de ejemplo, borra la carpeta `datos/`.

## Usuarios y roles

El **usuario es el correo**. La contraseña inicial de cada empleado es **su nombre + 1234** (por ejemplo `Erin1234`).

| Rol | Qué puede hacer |
|---|---|
| **Superadmin** | Toda la empresa: sucursales, trabajadores, roles, asistencia, anomalías, reporte, exportar y deshacer. No es empleado: no marca asistencia. El superadmin principal (código `EMP-004`) no se puede destituir ni eliminar, y es el único que nombra a otros superadmins |
| **Admin** (encargado) | Solo su sucursal: crea y edita trabajadores, corrige marcas, ve la asistencia, el reporte y las anomalías, y restablece contraseñas. También marca su propia asistencia |
| **Trabajador** | Inicia sesión, marca su asistencia y ve su propio historial |

- Solo un admin puede **restablecer** la contraseña de un trabajador (vuelve a `Nombre1234`).
- Cada admin cambia la suya en **Mi cuenta**.

## Conectarse desde el celular

### Con el Wi-Fi de la casa u oficina

1. El celular y la PC deben estar en la **misma red Wi-Fi** (no en la red de invitados).
2. Arranca el servidor en la PC.
3. Copia la dirección *"Desde el teléfono"* que muestra la consola.
4. En el celular, escríbela **completa**, con `https://` al inicio y `:8080` al final.
5. Aparece *"La conexión no es privada"* (por el certificado propio): toca **Configuración avanzada / Mostrar detalles** y luego **Continuar / Visitar este sitio web**.
6. Inicia sesión, toca **Marcar** y **permite el uso de la ubicación**.

### Sin Wi-Fi (zona Wi-Fi del celular)

1. En el celular, activa la **Zona Wi-Fi** (con datos móviles activos).
2. Conecta la PC a esa red.
3. Arranca el servidor y copia la nueva dirección (la IP cambia cada vez).
4. Sigue igual que arriba desde el paso 4.

La PC debe quedar cerca del celular, dentro del alcance de su Wi-Fi.

La primera vez, Windows puede preguntar si Python puede usar la red: acepta en **Redes privadas**.

## Cómo se marca

1. El empleado entra a **Mi asistencia** y toca el botón que le toca: **Entrada** → **Salida a almorzar** (o **Salida**, si no almuerza) → **Regreso de almuerzo** → **Salida**. El sábado, solo Entrada y Salida.
2. El celular toma la ubicación. Puede tardar unos segundos; el botón lo indica.
3. Resultado:
   - **Aceptada:** está dentro del radio de su sucursal. La hora la pone el servidor.
   - **Rechazada:** está fuera del radio, el GPS es impreciso (más de 100 m de error), no dio permiso de ubicación o no tiene sucursal asignada.
4. Entre una marca y la siguiente hay que esperar **5 minutos**.

**Radio recomendado por sucursal:**

| Tipo | Radio |
|---|---|
| Tienda pequeña | 35 m |
| Tienda grande o en centro comercial | 50 m |
| Bodega | 60 a 100 m |

No conviene usar menos de 25–30 m: dentro de los edificios el GPS puede equivocarse entre 15 y 30 m.

## Configuración

Los valores principales están en `utilidades.py` y `main.py`:

| Constante | Valor | Qué controla |
|---|---|---|
| `HOST` (`main.py`) | `"0.0.0.0"` | Acepta aparatos de la red (`"127.0.0.1"` = solo esta PC) |
| `PUERTO` (`main.py`) | `8080` | Puerto del servidor |
| `USAR_HTTPS` | `True` | HTTPS (necesario para el GPS en el celular) |
| `RADIO_DEFECTO` | `100` | Radio de una sucursal nueva, en metros |
| `PRECISION_MINIMA` | `100` | Error máximo del GPS aceptado, en metros |
| `SEGUNDOS_ENTRE_MARCAS` | `5 * 60` | Tiempo mínimo entre marcas |
| `HORAS_SEMANALES` | `44 * 3600` | Meta semanal |
| `TOLERANCIA_SEMANAL` | `15 * 60` | Desde 43 h 45 m cuenta como semana completa |
| `DURACION_SESION` | `12 * 3600` | Duración de una sesión |

## Problemas frecuentes

| Problema | Solución |
|---|---|
| La página queda en blanco en el celular | Se entró con `http://` en vez de `https://`. La consola lo avisa: *"Conexión de … rechazada: entró por http:// en vez de https://"* |
| En iPhone aparece la página del operador (por ejemplo *"miclaro.com.gt"*) y no deja pasar | La línea no tiene paquete de datos y Chrome confunde la red. Usa **Safari** |
| El celular no carga y la consola no muestra nada | Revisa que ambos estén en la misma red y que en Windows la red sea **Privada** |
| *"Ubicación imprecisa"* | Sal a un lugar abierto unos segundos para que el GPS se afine |
| *"El puerto 8080 ya está en uso"* | Hay otra ventana del servidor abierta: ciérrala con `Ctrl + C` |

## Pruebas automáticas

```
python -m unittest -v
```

57 pruebas de la lógica: cálculo de horas, alertas, distancias (Haversine), validación de ubicación, contraseñas y permisos.

## Archivos

| Archivo | Qué hace |
|---|---|
| `main.py` | Arranca todo |
| `servidor.py` | Recibe las peticiones del navegador (HTTP/HTTPS, cookies) |
| `rutas.py` | Una función por página y los permisos de cada una |
| `gestor.py` | Guarda y maneja los datos (CRUD, marcar con GPS, anomalías) |
| `calculos.py` | Horas, alertas, reporte semanal, distancia y ubicación |
| `modelos.py` | Las clases: Trabajador, Sucursal, RegistroAsistencia, Marcacion |
| `sesiones.py` | Inicio de sesión y reglas de permisos |
| `red.py` | IP de la PC y certificado HTTPS |
| `utilidades.py` | Constantes, log, decoradores, horas, contraseñas |
| `excepciones.py` | Errores propios del sistema |
| `static/ubicacion.js` | Único JavaScript: lee el GPS del celular |
| `static/estilos.css` | Estilos propios encima de Bootstrap |
| `plantillas/` | Las páginas HTML |
| `datos_ejemplo.json` | Datos de ejemplo (solo se usan si no existe `datos/datos.json`) |
| `test_calculos.py` | Pruebas automáticas |
| `iniciar.bat` | Arranque con doble clic (Windows) |

**No se suben al repositorio** (están en `.gitignore`):

- `datos/` → datos reales (trabajadores, marcas, ubicaciones y log).
- `certificado/` → contiene la clave privada del certificado; se crea sola al arrancar.
- `__pycache__/` → archivos que Python genera solo.

## Seguridad

- Las contraseñas se guardan cifradas (hash `pbkdf2` con sal), nunca tal cual.
- `certificado/clave.pem` es la clave privada del certificado: no la compartas.
- El navegador muestra *"conexión no privada"* porque el certificado es propio (autofirmado). La conexión sí va cifrada.
- Cambia las contraseñas iniciales (`Nombre1234`) antes de cualquier uso real.


#ignore. Esta linea es para una prueba tecnica del 'gig pull'
