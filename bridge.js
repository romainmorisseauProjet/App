// --- Pont navigateur -> serveur ---
// Recrée l'objet window.pywebview.api utilisé par tous les modules : chaque
// appel window.pywebview.api.methode(a, b) devient une requête
// POST /api/methode avec { args: [a, b] }, traitée par server.py.
// Grâce à ça, les modules existants n'ont presque pas besoin d'être modifiés.
(function () {
  async function appeler(nom, args) {
    // pywebview ignorait les arguments non fournis : on retire les undefined de fin
    // pour que les valeurs par défaut Python (ex. titre="Nouvelle page") s'appliquent.
    while (args.length && args[args.length - 1] === undefined) args.pop();

    const reponse = await fetch('/api/' + nom, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ args }),
    });
    if (reponse.status === 401) {
      window.location.href = '/login';
      throw new Error('Session expirée');
    }
    if (!reponse.ok) {
      let detail = 'Erreur ' + reponse.status;
      try { detail = (await reponse.json()).error || detail; } catch (e) {}
      throw new Error(detail);
    }
    return reponse.json();
  }

  const api = new Proxy({}, {
    get(_, nom) {
      // « then » doit rester indéfini, sinon await/resolve prendrait l'objet pour une promesse.
      if (typeof nom !== 'string' || nom === 'then') return undefined;
      // Ouvrir un lien se fait dans le navigateur lui-même, plus besoin du serveur.
      if (nom === 'ouvrir_lien') {
        return async (url) => { window.open(url, '_blank', 'noopener'); return { ok: true }; };
      }
      return (...args) => appeler(nom, args);
    },
  });

  window.pywebview = { api };
})();
