// --- Petit loader réutilisable ---
// Un clin d'œil miniature au logo, à réutiliser dans n'importe quel module
// pendant un chargement (fetch d'appareils, conversion de fichier, etc.).

function creerMiniEspritLoader() {
  const span = document.createElement('span');
  span.className = 'mini-esprit-loader';
  return span;
}

// Construit un bloc "● Texte" prêt à insérer dans un conteneur pendant un chargement.
function creerBlocChargement(texte) {
  const div = document.createElement('div');
  div.className = 'chargement-inline';
  div.appendChild(creerMiniEspritLoader());
  div.appendChild(document.createTextNode(texte));
  return div;
}
