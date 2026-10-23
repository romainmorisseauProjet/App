// --- Module Musique ---

let muzBibliotheque = [];
let muzIndexActuel = -1;
let muzInitialise = false;
let muzIntervalleEtat = null;
let muzUtilisateurEnTrainDeGlisser = false;

function muzFormaterTemps(secondes) {
  secondes = Math.max(0, Math.floor(secondes || 0));
  const m = Math.floor(secondes / 60);
  const s = secondes % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

async function muzChargerDossier() {
  const dossier = await window.pywebview.api.get_dossier_musique();
  document.getElementById('muzDossierActuel').textContent = 'Bibliothèque : ' + dossier;
}

async function muzChargerBibliotheque() {
  const liste = document.getElementById('muzListe');
  muzBibliotheque = await window.pywebview.api.get_bibliotheque();

  if (!muzBibliotheque || muzBibliotheque.length === 0) {
    liste.innerHTML = '<div class="muz-empty" id="muzEmpty">Bibliothèque vide — télécharge un premier morceau ci-dessus.</div>';
    return;
  }

  liste.innerHTML = '';
  muzBibliotheque.forEach((morceau, index) => {
    const ligne = document.createElement('div');
    ligne.className = 'muz-morceau';
    ligne.dataset.index = index;
    const iconeType = morceau.type === 'video'
      ? '<path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2"/>'
      : '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>';
    ligne.innerHTML = `
      <div class="muz-morceau-icone"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">${iconeType}</svg></div>
      <div class="muz-morceau-infos">
        <div class="muz-morceau-titre">${morceau.titre}</div>
        <div class="muz-morceau-artiste">${morceau.artiste || ''}</div>
      </div>
      <div class="muz-morceau-duree">${muzFormaterTemps(morceau.duree)}</div>
    `;
    ligne.addEventListener('click', () => muzJouerIndex(index));
    liste.appendChild(ligne);
  });

  muzMettreAJourSurbrillance();
}

function muzMettreAJourSurbrillance() {
  document.querySelectorAll('.muz-morceau').forEach(el => {
    el.classList.toggle('actif', parseInt(el.dataset.index) === muzIndexActuel);
  });
}

async function muzJouerIndex(index) {
  if (index < 0 || index >= muzBibliotheque.length) return;
  const morceau = muzBibliotheque[index];
  const resultat = await window.pywebview.api.jouer_morceau(morceau.chemin);
  if (!resultat.ok) {
    alert(resultat.message);
    return;
  }
  muzIndexActuel = index;
  muzMettreAJourSurbrillance();
  document.getElementById('muzPlayerTitre').textContent = morceau.titre;
  document.getElementById('muzPlayerArtiste').textContent = morceau.artiste || '';
  document.getElementById('muzTempsTotal').textContent = muzFormaterTemps(morceau.duree);
  muzDefinirIconePlayPause(true);
}

function muzDefinirIconePlayPause(enLecture) {
  const btn = document.getElementById('muzPlayBtn');
  btn.innerHTML = enLecture
    ? '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/></svg>'
    : '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
}

document.getElementById('muzPlayBtn').addEventListener('click', async () => {
  if (muzIndexActuel === -1) {
    if (muzBibliotheque.length > 0) muzJouerIndex(0);
    return;
  }
  await window.pywebview.api.basculer_pause_musique();
});

document.getElementById('muzPrevBtn').addEventListener('click', () => {
  if (muzBibliotheque.length === 0) return;
  const nouvel_index = muzIndexActuel <= 0 ? muzBibliotheque.length - 1 : muzIndexActuel - 1;
  muzJouerIndex(nouvel_index);
});

document.getElementById('muzNextBtn').addEventListener('click', () => {
  if (muzBibliotheque.length === 0) return;
  const nouvel_index = (muzIndexActuel + 1) % muzBibliotheque.length;
  muzJouerIndex(nouvel_index);
});

// --- Barre de progression, mise à jour en direct ---
const muzProgress = document.getElementById('muzProgress');

muzProgress.addEventListener('mousedown', () => { muzUtilisateurEnTrainDeGlisser = true; });
muzProgress.addEventListener('change', async () => {
  const morceau = muzBibliotheque[muzIndexActuel];
  if (!morceau) { muzUtilisateurEnTrainDeGlisser = false; return; }
  const secondes = (muzProgress.value / 100) * morceau.duree;
  await window.pywebview.api.definir_position_musique(secondes);
  muzUtilisateurEnTrainDeGlisser = false;
});

document.getElementById('muzVolume').addEventListener('input', (e) => {
  window.pywebview.api.definir_volume_musique(parseInt(e.target.value));
});

async function muzRafraichirEtat() {
  if (!window.pywebview || !window.pywebview.api) return;
  const etat = await window.pywebview.api.get_etat_musique();
  muzDefinirIconePlayPause(etat.en_lecture);
  document.getElementById('muzTempsActuel').textContent = muzFormaterTemps(etat.position);
  document.getElementById('muzTempsTotal').textContent = muzFormaterTemps(etat.duree);
  if (!muzUtilisateurEnTrainDeGlisser && etat.duree > 0) {
    muzProgress.value = (etat.position / etat.duree) * 100;
  }
  // Morceau terminé : on enchaîne automatiquement sur le suivant
  if (!etat.en_lecture && etat.duree > 0 && etat.position >= etat.duree - 0.5 && muzIndexActuel !== -1) {
    document.getElementById('muzNextBtn').click();
  }
}

// --- Réglage du dossier de bibliothèque ---
document.getElementById('muzChangerDossierBtn').addEventListener('click', async () => {
  const dossier = await window.pywebview.api.choisir_dossier_musique();
  if (!dossier) return;
  await muzChargerDossier();
  await muzChargerBibliotheque();
});

// --- Téléchargement YouTube ---
let muzFormatChoisi = 'mp3';
document.getElementById('muzFormatMp3').addEventListener('click', () => {
  muzFormatChoisi = 'mp3';
  document.getElementById('muzFormatMp3').classList.add('active');
  document.getElementById('muzFormatMp4').classList.remove('active');
});
document.getElementById('muzFormatMp4').addEventListener('click', () => {
  muzFormatChoisi = 'mp4';
  document.getElementById('muzFormatMp4').classList.add('active');
  document.getElementById('muzFormatMp3').classList.remove('active');
});

document.getElementById('muzTelechargerBtn').addEventListener('click', async () => {
  const input = document.getElementById('muzUrlInput');
  const url = input.value.trim();
  const resultDiv = document.getElementById('muzDownloadResult');
  if (!url) return;

  const bouton = document.getElementById('muzTelechargerBtn');
  bouton.disabled = true;
  bouton.textContent = 'Téléchargement…';
  resultDiv.textContent = '';
  resultDiv.className = 'muz-download-result';

  const resultat = await window.pywebview.api.telecharger_musique(url, muzFormatChoisi);

  bouton.disabled = false;
  bouton.textContent = 'Télécharger';
  resultDiv.textContent = resultat.message;
  resultDiv.classList.add(resultat.ok ? 'ok' : 'error');

  if (resultat.ok) {
    input.value = '';
    muzChargerBibliotheque();
  }
});

// --- Initialisation à la première ouverture de l'onglet ---
document.addEventListener('tab:opened', (e) => {
  if (e.detail !== 'musique') return;
  if (!muzInitialise) {
    muzInitialise = true;
    muzChargerDossier();
    muzChargerBibliotheque();
  }
  if (!muzIntervalleEtat) {
    muzIntervalleEtat = setInterval(muzRafraichirEtat, 1000);
  }
});
