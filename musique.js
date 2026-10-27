// --- Module Musique ---

let muzBibliotheque = [];
let muzIndexActuel = -1;
let muzInitialise = false;
let muzUtilisateurEnTrainDeGlisser = false;

// La lecture se fait dans le navigateur : les fichiers viennent du serveur
// (/media/musique/<fichier>), ce qui marche aussi depuis un téléphone.
const muzAudio = new Audio();
muzAudio.preload = 'metadata';

function muzFormaterTemps(secondes) {
  secondes = Math.max(0, Math.floor(secondes || 0));
  const m = Math.floor(secondes / 60);
  const s = secondes % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
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
        <div class="muz-morceau-titre"></div>
        <div class="muz-morceau-artiste"></div>
      </div>
      <div class="muz-morceau-duree">${muzFormaterTemps(morceau.duree)}</div>
    `;
    ligne.querySelector('.muz-morceau-titre').textContent = morceau.titre;
    ligne.querySelector('.muz-morceau-artiste').textContent = morceau.artiste || '';
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
  muzAudio.src = '/media/musique/' + encodeURIComponent(morceau.fichier);
  try {
    await muzAudio.play();
  } catch (e) {
    alert("Impossible de lire ce fichier : " + e.message);
    return;
  }
  muzIndexActuel = index;
  muzMettreAJourSurbrillance();
  document.getElementById('muzPlayerTitre').textContent = morceau.titre;
  document.getElementById('muzPlayerArtiste').textContent = morceau.artiste || '';
  document.getElementById('muzTempsTotal').textContent = muzFormaterTemps(morceau.duree);
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
  if (muzAudio.paused) muzAudio.play(); else muzAudio.pause();
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
muzProgress.addEventListener('touchstart', () => { muzUtilisateurEnTrainDeGlisser = true; }, { passive: true });
muzProgress.addEventListener('change', () => {
  if (muzAudio.duration) muzAudio.currentTime = (muzProgress.value / 100) * muzAudio.duration;
  muzUtilisateurEnTrainDeGlisser = false;
});

document.getElementById('muzVolume').addEventListener('input', (e) => {
  muzAudio.volume = Math.max(0, Math.min(1, parseInt(e.target.value) / 100));
});

// Le lecteur du navigateur nous prévient lui-même : plus besoin d'interroger le serveur.
muzAudio.addEventListener('play', () => muzDefinirIconePlayPause(true));
muzAudio.addEventListener('pause', () => muzDefinirIconePlayPause(false));
muzAudio.addEventListener('loadedmetadata', () => {
  document.getElementById('muzTempsTotal').textContent = muzFormaterTemps(muzAudio.duration);
});
muzAudio.addEventListener('timeupdate', () => {
  document.getElementById('muzTempsActuel').textContent = muzFormaterTemps(muzAudio.currentTime);
  if (!muzUtilisateurEnTrainDeGlisser && muzAudio.duration) {
    muzProgress.value = (muzAudio.currentTime / muzAudio.duration) * 100;
  }
});
muzAudio.addEventListener('ended', () => document.getElementById('muzNextBtn').click());

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
    muzChargerBibliotheque();
  }
});
