// auth-guard.js — Proteccion de rutas admin
// Incluir este script al inicio de cada pagina admin (antes del resto de JS)
(function () {
  function hasCookie(name) {
    return document.cookie.split(';').some(function (c) {
      return c.trim().indexOf(name + '=') === 0;
    });
  }

  if (!hasCookie('becubical_session')) {
    window.location.replace('/login.html');
    return;
  }

  // Interceptar fetch globalmente: redirigir a login si llega un 401
  var _fetch = window.fetch;
  window.fetch = function () {
    return _fetch.apply(this, arguments).then(function (response) {
      if (response.status === 401) {
        document.cookie = 'becubical_session=; max-age=0; path=/';
        window.location.replace('/login.html');
      }
      return response;
    });
  };
})();
