(function () {
  // Evita enviar dos veces el pedido por un doble clic (el servidor también lo impide).
  document.querySelectorAll("form[data-una-vez]").forEach(function (formulario) {
    formulario.addEventListener("submit", function () {
      var boton = formulario.querySelector("button[type=submit]");
      if (boton) {
        boton.disabled = true;
        boton.textContent = "Enviando…";
      }
    });
  });
})();
