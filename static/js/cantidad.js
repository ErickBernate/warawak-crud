(function () {
  document.querySelectorAll(".cantidad").forEach(function (bloque) {
    var entrada = bloque.querySelector("input[type=number]");
    var menos = bloque.querySelector("[data-cantidad-menos]");
    var mas = bloque.querySelector("[data-cantidad-mas]");
    if (!entrada || !menos || !mas) return;

    var minimo = parseInt(entrada.min, 10) || 1;
    var maximo = parseInt(entrada.max, 10) || 20;

    function ajustar(delta) {
      var actual = parseInt(entrada.value, 10);
      if (isNaN(actual)) actual = minimo;
      entrada.value = Math.min(maximo, Math.max(minimo, actual + delta));
    }

    menos.addEventListener("click", function () { ajustar(-1); });
    mas.addEventListener("click", function () { ajustar(1); });
  });
})();
