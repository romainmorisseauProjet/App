// --- Étape 2 : bouton micro + enregistrement ---
// À ce stade, on enregistre le micro et on envoie l'audio à Python,
// mais Python ne fait encore rien avec (pas de transcription).
// Le but est juste de vérifier que le son arrive bien côté Python.

const micBtn = document.getElementById('micBtn');
const voiceStatus = document.getElementById('voiceStatus');
const coreCenter = document.getElementById('coreCenter');
const coreRing3 = document.getElementById('coreRing3');
const coreState = document.getElementById('coreState');
const transcriptionText = document.getElementById('transcriptionText');

let enregistreur = null;
let morceauxAudio = [];
let enregistrementEnCours = false;

// --- Analyse du volume du micro en direct, pour faire réagir le cœur ---
let audioCtx = null;
let analyser = null;
let dataArray = null;
let idAnimation = null;

function demarrerAnalyseVolume(flux) {
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const source = audioCtx.createMediaStreamSource(flux);
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 512;
  source.connect(analyser);
  dataArray = new Uint8Array(analyser.frequencyBinCount);

  coreCenter.classList.add('listening');
  coreRing3.classList.add('listening');

  const boucle = () => {
    analyser.getByteTimeDomainData(dataArray);
    // Calcul RMS (une mesure classique du "volume" d'un signal audio)
    let somme = 0;
    for (let i = 0; i < dataArray.length; i++) {
      const echantillon = (dataArray[i] - 128) / 128;
      somme += echantillon * echantillon;
    }
    const volume = Math.sqrt(somme / dataArray.length);
    // On amplifie un peu, une voix normale ne sature pas facilement le signal
    const intensite = Math.min(1, volume * 5);
    document.documentElement.style.setProperty('--mic-volume', intensite.toFixed(3));
    idAnimation = requestAnimationFrame(boucle);
  };
  boucle();
}

function arreterAnalyseVolume() {
  if (idAnimation) cancelAnimationFrame(idAnimation);
  if (audioCtx) { audioCtx.close(); audioCtx = null; }
  document.documentElement.style.setProperty('--mic-volume', 0);
  coreCenter.classList.remove('listening');
  coreRing3.classList.remove('listening');
}

function afficherStatutVoix(texte, estErreur = false) {
  voiceStatus.textContent = texte;
  voiceStatus.classList.remove('hidden');
  voiceStatus.classList.toggle('error', estErreur);
}

async function demarrerEnregistrement() {
  try {
    const flux = await navigator.mediaDevices.getUserMedia({ audio: true });
    morceauxAudio = [];
    enregistreur = new MediaRecorder(flux);

    enregistreur.ondataavailable = (e) => {
      if (e.data.size > 0) morceauxAudio.push(e.data);
    };

    enregistreur.onstop = () => {
      flux.getTracks().forEach(piste => piste.stop());
      arreterAnalyseVolume();
      envoyerAudioAuBackend();
    };

    enregistreur.start();
    enregistrementEnCours = true;
    micBtn.classList.add('recording');
    coreState.textContent = 'Écoute…';
    afficherStatutVoix('Écoute en cours… reclique pour arrêter');
    demarrerAnalyseVolume(flux);
  } catch (err) {
    afficherStatutVoix("Impossible d'accéder au micro (permission refusée ?)", true);
  }
}

function arreterEnregistrement() {
  if (enregistreur && enregistrementEnCours) {
    enregistreur.stop();
    enregistrementEnCours = false;
    micBtn.classList.remove('recording');
    coreState.textContent = 'Traitement…';
    afficherStatutVoix('Envoi au backend…');
  }
}

async function envoyerAudioAuBackend() {
  const blob = new Blob(morceauxAudio, { type: 'audio/webm' });

  const base64 = await new Promise((resolve, reject) => {
    const lecteur = new FileReader();
    lecteur.onloadend = () => resolve(lecteur.result.split(',')[1]);
    lecteur.onerror = reject;
    lecteur.readAsDataURL(blob);
  });

  if (!window.pywebview || !window.pywebview.api) {
    afficherStatutVoix('Le pont Python n\'est pas disponible.', true);
    coreState.textContent = 'En attente';
    return;
  }

  try {
    const resultat = await window.pywebview.api.recevoir_audio(base64);
    afficherStatutVoix('');
    voiceStatus.classList.add('hidden');
    // La vraie transcription arrivera à l'étape 3 ; pour l'instant on
    // affiche juste la confirmation que l'audio est bien arrivé.
    transcriptionText.textContent = resultat;
    transcriptionText.classList.remove('placeholder');
    coreState.textContent = 'En attente';
  } catch (err) {
    afficherStatutVoix("Erreur lors de l'envoi au backend.", true);
    coreState.textContent = 'En attente';
  }
}

micBtn.addEventListener('click', () => {
  if (enregistrementEnCours) {
    arreterEnregistrement();
  } else {
    demarrerEnregistrement();
  }
});
