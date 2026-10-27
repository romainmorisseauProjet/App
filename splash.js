// --- Écran de démarrage ---
// Reste affiché au moins DUREE_MIN millisecondes (pour laisser le temps de
// voir l'animation), puis disparaît dès que le pont Python répond — avec un
// filet de sécurité si jamais la connexion tarde anormalement.
(function () {
  const splash = document.getElementById('splashScreen');
  if (!splash) return;

  const DUREE_MIN = 3200;
  const debut = Date.now();
  let dejaCachee = false;

  function masquerSplash() {
    if (dejaCachee) return;
    dejaCachee = true;
    const ecoule = Date.now() - debut;
    const attente = Math.max(0, DUREE_MIN - ecoule);
    setTimeout(() => {
      splash.classList.add('splash-cachee');
      setTimeout(() => splash.remove(), 650);
    }, attente);
  }

  function attendreApi() {
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.ping === 'function') {
      window.pywebview.api.ping().then(masquerSplash).catch(masquerSplash);
    } else {
      setTimeout(attendreApi, 150);
    }
  }
  attendreApi();

  // Filet de sécurité : si la connexion Python met vraiment trop de temps,
  // on n'attend pas indéfiniment et on laisse l'utilisateur entrer.
  setTimeout(masquerSplash, 6000);
})();
