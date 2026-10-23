// --- Module Actualités ---

let actuCategorieActive = 'politique_france';

// Cache par catégorie : on ne retélécharge que si les données ont plus de
// 10 minutes (ou si on clique sur "actualiser"). Ainsi, rouvrir l'onglet le
// lendemain donne toujours des infos fraîches, sans requête inutile entre-temps.
const ACTU_VALIDITE_MS = 10 * 60 * 1000;
const actuCache = {};   // { categorie: { articles, chargeA } }

function actuEchapper(texte) {
  const d = document.createElement('div');
  d.textContent = texte || '';
  return d.innerHTML;
}

function actuFormaterDate(dateBrute) {
  if (!dateBrute) return '';
  const d = new Date(dateBrute);
  if (isNaN(d)) return '';
  const minutes = Math.round((Date.now() - d.getTime()) / 60000);
  if (minutes >= 0 && minutes < 60) return `il y a ${Math.max(minutes, 1)} min`;
  const heures = Math.round(minutes / 60);
  if (minutes >= 0 && heures < 24) return `il y a ${heures} h`;
  return d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function actuAfficher(categorie) {
  const liste = document.getElementById('actuList');
  const entree = actuCache[categorie];
  if (!entree) return;

  const maj = new Date(entree.chargeA).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  document.getElementById('actuMaj').textContent = `Mis à jour à ${maj}`;

  if (entree.articles.length === 0) {
    liste.innerHTML = '<div class="actu-empty">Aucune actualité récupérée (connexion internet ?).</div>';
    return;
  }

  liste.innerHTML = '';
  entree.articles.forEach(article => {
    const carte = document.createElement('div');
    carte.className = 'actu-article';
    const quand = actuFormaterDate(article.date);
    const meta = [article.source, quand].filter(Boolean).join(' · ');
    carte.innerHTML = `
      <div class="actu-article-titre">${actuEchapper(article.titre)}</div>
      ${article.resume ? `<div class="actu-article-resume">${actuEchapper(article.resume)}</div>` : ''}
      ${meta ? `<div class="actu-article-date">${actuEchapper(meta)}</div>` : ''}
    `;
    carte.addEventListener('click', () => {
      if (article.lien) window.pywebview.api.ouvrir_lien(article.lien);
    });
    liste.appendChild(carte);
  });
}

async function chargerActualites(categorie, forcer = false) {
  const liste = document.getElementById('actuList');
  const refreshBtn = document.getElementById('actuRefreshBtn');

  const enCache = actuCache[categorie];
  if (!forcer && enCache && Date.now() - enCache.chargeA < ACTU_VALIDITE_MS) {
    actuAfficher(categorie);
    return;
  }

  liste.innerHTML = '<div class="actu-empty">Chargement des actualités…</div>';
  refreshBtn.classList.add('loading');

  if (!window.pywebview || !window.pywebview.api) {
    liste.innerHTML = '<div class="actu-empty">Le pont Python n\'est pas disponible.</div>';
    refreshBtn.classList.remove('loading');
    return;
  }

  try {
    const articles = await window.pywebview.api.get_actualites(categorie);
    actuCache[categorie] = { articles: articles || [], chargeA: Date.now() };
    // L'utilisateur a pu changer d'onglet pendant le chargement
    if (categorie === actuCategorieActive) actuAfficher(categorie);
  } catch (e) {
    liste.innerHTML = '<div class="actu-empty">Erreur lors de la récupération des actualités.</div>';
  }
  refreshBtn.classList.remove('loading');
}

document.querySelectorAll('.actu-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.actu-tab').forEach(t => t.classList.toggle('active', t === tab));
    actuCategorieActive = tab.dataset.actuCat;
    chargerActualites(actuCategorieActive);
  });
});

document.getElementById('actuRefreshBtn').addEventListener('click', () => {
  chargerActualites(actuCategorieActive, true);
});

// À chaque ouverture de l'onglet : recharge si les données sont périmées.
document.addEventListener('tab:opened', (e) => {
  if (e.detail !== 'actualites') return;
  chargerActualites(actuCategorieActive);
});
