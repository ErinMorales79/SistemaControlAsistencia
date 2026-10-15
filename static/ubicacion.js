// ubicacion.js
// UNICO archivo JavaScript del proyecto: corre en el navegador (telefono o PC), no en Python.
// Su unico trabajo es leer la ubicacion del aparato (Geolocation API) y ponerla en el formulario.
// Todas las decisiones (si la marca es valida, la hora, la distancia) las toma Python en el servidor.

// opciones para pedir la ubicacion:
// enableHighAccuracy = usar el GPS real; maximumAge = 0 no reusar una ubicacion vieja; timeout = esperar maximo 15 s
const OPCIONES_GPS = { enableHighAccuracy: true, maximumAge: 0, timeout: 15000 };


// ---------------------------------------------------------------
// 1) MARCAR ASISTENCIA (pagina "Mi asistencia")
// ---------------------------------------------------------------
const formMarcar = document.getElementById("form-marcar");
let botonTocado = null;                                            // el boton que toco el empleado

// el if evita errores en las paginas que no tienen este formulario
if (formMarcar) {
    // cada boton trae en data-marca que marca es (ENTRADA, SALIDA_ALMUERZO, ...)
    formMarcar.querySelectorAll("[data-marca]").forEach(function (boton) {
        boton.addEventListener("click", function () {
            botonTocado = boton;
            formMarcar.tipo_marca.value = boton.dataset.marca;      // campo oculto: que marca toco
            desactivarBotones(formMarcar);                         // evita toques dobles mientras espera
            // el mismo boton muestra que esta trabajando (spinner = circulo que gira, de bootstrap)
            cambiarTextoBoton("Obteniendo tu ubicación…");
            mostrarEstado("El GPS puede tardar unos segundos. No cierres la página.");
            pedirUbicacion(ubicacionParaMarcar, sinUbicacionParaMarcar);
        });
    });
}

// callback si el GPS respondio: llenamos los campos ocultos y enviamos el formulario a Python
function ubicacionParaMarcar(posicion) {
    formMarcar.latitud.value = posicion.coords.latitude;
    formMarcar.longitud.value = posicion.coords.longitude;
    formMarcar.precision.value = posicion.coords.accuracy;        // en metros
    cambiarTextoBoton("Enviando…");
    formMarcar.submit();
}

// callback si fallo (sin permiso, GPS apagado, tiempo agotado):
// igual enviamos el formulario SIN coordenadas; Python lo registra como anomalia "Sin ubicacion"
function sinUbicacionParaMarcar(error) {
    formMarcar.error_gps.value = error.message;
    cambiarTextoBoton("Sin ubicación, enviando…");
    formMarcar.submit();
}

function cambiarTextoBoton(texto) {
    // reemplaza el contenido del boton tocado por un spinner + el texto
    if (botonTocado) {
        botonTocado.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status"></span>' + texto;
    }
}


// ---------------------------------------------------------------
// 2) "USAR MI UBICACION ACTUAL" (formulario de sucursales, solo superadmin)
// ---------------------------------------------------------------
const botonUbicacion = document.getElementById("usar-ubicacion");

if (botonUbicacion) {
    botonUbicacion.addEventListener("click", function () {
        mostrarEstado("Obteniendo tu ubicación...");
        pedirUbicacion(ubicacionParaSucursal, function (error) {
            mostrarEstado("No se pudo obtener la ubicación: " + error.message);
        });
    });
}

// callback: escribimos "latitud, longitud" en el campo de coordenadas (6 decimales = unos 10 cm)
function ubicacionParaSucursal(posicion) {
    const latitud = posicion.coords.latitude.toFixed(6);
    const longitud = posicion.coords.longitude.toFixed(6);
    document.getElementById("coordenadas").value = latitud + ", " + longitud;
    mostrarEstado("Ubicación tomada (precisión ± " + Math.round(posicion.coords.accuracy) + " m). Revisa y guarda.");
}


// ---------------------------------------------------------------
// AYUDANTES
// ---------------------------------------------------------------
function pedirUbicacion(siFunciona, siFalla) {
    // navigator.geolocation solo existe en paginas seguras (https o localhost)
    if (!navigator.geolocation) {
        siFalla({ message: "Este navegador no permite leer la ubicación (se necesita https)" });
        return;
    }
    // getCurrentPosition recibe DOS CALLBACKS: uno si funciona y otro si falla (como la practica 21)
    navigator.geolocation.getCurrentPosition(siFunciona, siFalla, OPCIONES_GPS);
}

function mostrarEstado(texto) {
    // escribe un mensaje en el elemento con id="estado-gps" (si la pagina lo tiene)
    const estado = document.getElementById("estado-gps");
    if (estado) {
        estado.textContent = texto;
    }
}

function desactivarBotones(formulario) {
    formulario.querySelectorAll("button").forEach(function (boton) {
        boton.disabled = true;
    });
}
