(function () {
  var MAX_BYTES = 2 * 1024 * 1024;
  var entrada = document.getElementById("foto");
  var boton = document.getElementById("boton-foto");
  var imagen = document.getElementById("vista-previa-imagen");
  var icono = document.getElementById("vista-previa-icono");
  var ayuda = document.getElementById("ayuda-foto");
  var ayudaOriginal = ayuda.textContent.trim();
  // Al editar, la foto actual ya viene cargada en la vista previa.
  var srcOriginal = imagen.hidden ? null : imagen.getAttribute("src");
  var urlActual = null;

  function restaurar(mensaje) {
    entrada.value = "";
    if (srcOriginal) {
      imagen.src = srcOriginal;
      imagen.hidden = false;
      icono.hidden = true;
    } else {
      imagen.hidden = true;
      icono.hidden = false;
    }
    ayuda.textContent = mensaje || ayudaOriginal;
  }

  boton.addEventListener("click", function () {
    entrada.click();
  });

  entrada.addEventListener("change", function () {
    var archivo = entrada.files && entrada.files[0];
    if (urlActual) {
      URL.revokeObjectURL(urlActual);
      urlActual = null;
    }
    if (!archivo) {
      restaurar();
      return;
    }
    if (archivo.size > MAX_BYTES) {
      restaurar("La imagen pesa más de 2 MB. Elige una más liviana.");
      return;
    }
    urlActual = URL.createObjectURL(archivo);
    imagen.src = urlActual;
    imagen.hidden = false;
    icono.hidden = true;
    ayuda.textContent = archivo.name;
  });
})();
