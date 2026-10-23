// --- Menu hamburger ---
const sidebar = document.getElementById('sidebar');
const burgerBtn = document.getElementById('burgerBtn');
burgerBtn.addEventListener('click', () => {
  sidebar.classList.toggle('open');
});

// --- Bascule des onglets ---
const navItems = document.querySelectorAll('.nav-item');
const panels = document.querySelectorAll('.tab-panel');
const pageTitle = document.getElementById('pageTitle');

const titles = {
  accueil: 'ACCUEIL',
  meteo: 'MÉTÉO',
  modules: 'MODULES',
  domotique: 'DOMOTIQUE',
  conversion: 'CONVERSION',
  actualites: 'ACTUALITÉS',
  musique: 'MUSIQUE',
  carburants: 'CARBURANTS',
  iss: 'STATION SPATIALE',
  projets: 'PROJETS',
  calcul: 'CALCUL',
  parametres: 'PARAMÈTRES',
};

// Les futurs modules ouverts depuis la grille "Modules" n'auront pas
// d'entrée directe dans le menu : on garde alors l'onglet "Modules"
// surligné dans le menu latéral. Exemple : { manga: 'modules' }
const PARENT_TAB = { domotique: 'modules', conversion: 'modules', actualites: 'modules', musique: 'modules', carburants: 'modules', iss: 'modules', projets: 'modules', calcul: 'modules' };

function activateTab(tab) {
  const navTab = PARENT_TAB[tab] || tab;
  navItems.forEach(i => i.classList.toggle('active', i.dataset.tab === navTab));
  panels.forEach(p => p.classList.toggle('hidden', p.dataset.panel !== tab));
  pageTitle.textContent = titles[tab] || '';
  document.dispatchEvent(new CustomEvent('tab:opened', { detail: tab }));
}

navItems.forEach(item => {
  item.addEventListener('click', () => activateTab(item.dataset.tab));
});

// Cartes de la grille "Modules" : ouvrent le module cliqué
document.querySelectorAll('[data-open-tab]').forEach(card => {
  card.addEventListener('click', () => activateTab(card.dataset.openTab));
});

// Boutons "retour" à l'intérieur d'un module
document.querySelectorAll('[data-back-to]').forEach(btn => {
  btn.addEventListener('click', () => activateTab(btn.dataset.backTo));
});

// --- Réorganisation des modules par glisser-déposer ---
// L'ordre choisi est mémorisé en base (table modules_ordre) pour survivre
// au redémarrage de l'application.
const modulesGrid = document.querySelector('.modules-grid');

function appliquerOrdreModules(ordre) {
  if (!modulesGrid || !Array.isArray(ordre)) return;
  ordre.forEach(cle => {
    const carte = modulesGrid.querySelector(`[data-module-key="${cle}"]`);
    if (carte) modulesGrid.appendChild(carte);
  });
}

async function chargerOrdreModules() {
  if (!window.pywebview || !window.pywebview.api) {
    setTimeout(chargerOrdreModules, 200);
    return;
  }
  try {
    const ordre = await window.pywebview.api.get_ordre_modules();
    appliquerOrdreModules(ordre);
  } catch (e) { /* pas grave, on garde l'ordre par défaut du HTML */ }
}

function sauvegarderOrdreModules() {
  if (!modulesGrid || !window.pywebview || !window.pywebview.api) return;
  const ordre = [...modulesGrid.querySelectorAll('.module-card')].map(c => c.dataset.moduleKey);
  window.pywebview.api.set_ordre_modules(ordre);
}

if (modulesGrid) {
  let carteGlissee = null;

  modulesGrid.querySelectorAll('.module-card').forEach(carte => {
    carte.setAttribute('draggable', 'true');

    carte.addEventListener('dragstart', () => {
      carteGlissee = carte;
      // Laisse le temps au navigateur de capturer l'image de drag avant de styliser
      setTimeout(() => carte.classList.add('dragging'), 0);
    });

    carte.addEventListener('dragend', () => {
      carte.classList.remove('dragging');
      carteGlissee = null;
      sauvegarderOrdreModules();
    });
  });

  // Verrou anti va-et-vient : après un déplacement, la grille se réorganise
  // sous le curseur ; sans pause, la carte serait replacée dans l'autre sens
  // à chaque événement suivant (effet de "clignotement").
  let verrouDeplacement = false;

  modulesGrid.addEventListener('dragover', (e) => {
    e.preventDefault();
    if (!carteGlissee || verrouDeplacement) return;

    // On ne réagit que si le curseur est réellement au-dessus d'une AUTRE carte
    const cible = e.target.closest('.module-card');
    if (!cible || cible === carteGlissee) return;

    const cartes = [...modulesGrid.querySelectorAll('.module-card')];
    const indexGlissee = cartes.indexOf(carteGlissee);
    const indexCible = cartes.indexOf(cible);

    // Échange simple : la carte prend la place de celle qu'elle survole
    if (indexGlissee < indexCible) {
      modulesGrid.insertBefore(carteGlissee, cible.nextSibling);
    } else {
      modulesGrid.insertBefore(carteGlissee, cible);
    }

    verrouDeplacement = true;
    setTimeout(() => { verrouDeplacement = false; }, 180);
  });

  chargerOrdreModules();
}

// --- Horloge ---
function updateClock() {
  const now = new Date();
  const h = String(now.getHours()).padStart(2, '0');
  const m = String(now.getMinutes()).padStart(2, '0');
  document.getElementById('clock').textContent = `${h}:${m}`;
}
updateClock();
setInterval(updateClock, 15000);

// --- Barre de message (onglet Accueil) ---
const input = document.getElementById('msgInput');
const sendBtn = document.getElementById('sendBtn');
function pulseSend() {
  if (!input.value.trim()) return;
  input.value = '';
  const stateEl = document.querySelector('.core-status .state');
  stateEl.textContent = 'Réception…';
  setTimeout(() => { stateEl.textContent = 'En attente'; }, 1400);
}
sendBtn.addEventListener('click', pulseSend);
input.addEventListener('keydown', e => { if (e.key === 'Enter') pulseSend(); });

// --- Test du pont Python <-> interface ---
function testBridge() {
  if (!window.pywebview || !window.pywebview.api) {
    setTimeout(testBridge, 200); // pywebview met parfois un instant à s'initialiser
    return;
  }
  window.pywebview.api.ping().then(result => {
    document.getElementById('bridgeResult').textContent = result;
    document.getElementById('bridgeResult').classList.add('ok');
    document.getElementById('statusDot').classList.remove('error');
    document.getElementById('statusText').textContent = 'Système connecté';
  }).catch(() => {
    document.getElementById('bridgeResult').textContent = 'Échec de connexion';
    document.getElementById('statusDot').classList.add('error');
    document.getElementById('statusText').textContent = 'Erreur de connexion';
  });
}
testBridge();
