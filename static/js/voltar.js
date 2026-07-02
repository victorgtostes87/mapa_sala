(function(){
  function guardarAbaAnterior(){
    try {
      if (!document.referrer) return;
      var origem = new URL(document.referrer);
      if (origem.origin !== window.location.origin) return;
      if (origem.pathname === window.location.pathname) return;
      if (origem.pathname === '/login' || origem.pathname === '/logout') return;
      sessionStorage.setItem('abaAnteriorMapaSala', origem.pathname + origem.search + origem.hash);
    } catch (err) {}
  }

  window.voltarAbaAnterior = function(event, destinoPadrao){
    if (event) event.preventDefault();
    var destino = destinoPadrao || '/mapa';

    try {
      var salvo = sessionStorage.getItem('abaAnteriorMapaSala');
      if (salvo) {
        var url = new URL(salvo, window.location.origin);
        if (url.origin === window.location.origin && url.pathname !== window.location.pathname) {
          window.location.href = url.pathname + url.search + url.hash;
          return;
        }
      }
    } catch (err) {}

    window.location.href = destino;
  };

  guardarAbaAnterior();
})();
