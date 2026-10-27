// --- Module Conversion de fichiers ---
// Chaque outil (img2pdf, pdf2img, doc2pdf, pdf2docx, pdf2pptx, merge) partage
// la même mécanique : choisir des fichiers (ils sont envoyés au serveur), les
// afficher en liste, puis lancer l'appel Python correspondant. Le résultat est
// proposé en téléchargement ; les fichiers d'origine ne sont jamais modifiés.

const CONV_OUTILS = {
  img2pdf: { min: 1, reorder: false, actionLabel: 'Conversion en cours…' },
  pdf2img: { min: 1, reorder: false, actionLabel: 'Export en cours…' },
  doc2pdf: { min: 1, reorder: false, actionLabel: 'Conversion en cours…' },
  pdf2docx: { min: 1, reorder: false, actionLabel: 'Conversion en cours…' },
  pdf2pptx: { min: 1, reorder: false, actionLabel: 'Conversion en cours…' },
  merge: { min: 2, reorder: true, actionLabel: 'Fusion en cours…' },
};

const convFichiers = { img2pdf: [], pdf2img: [], doc2pdf: [], pdf2docx: [], pdf2pptx: [], merge: [] };

function nomDeFichier(chemin) {
  return chemin.split(/[\\/]/).pop();
}

// --- Onglets de l'outil actif ---
document.querySelectorAll('.conv-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.conv-tab').forEach(t => t.classList.toggle('active', t === tab));
    const cible = tab.dataset.convTab;
    document.querySelectorAll('.conv-panel').forEach(p => {
      p.classList.toggle('hidden', p.dataset.convPanel !== cible);
    });
  });
});

// --- Sélection de fichiers ---
const CONV_ACCEPT = {
  images: '.jpg,.jpeg,.png',
  pdf: '.pdf',
  document: '.docx,.doc,.odt,.rtf,.txt,.pptx,.ppt,.odp,.xlsx,.xls,.ods,.csv',
};

async function convEnvoyer(fichiersChoisis) {
  const formulaire = new FormData();
  [...fichiersChoisis].forEach(f => formulaire.append('fichiers', f));
  const reponse = await fetch('/upload', { method: 'POST', body: formulaire, credentials: 'same-origin' });
  if (reponse.status === 401) { window.location.href = '/login'; return []; }
  const donnees = await reponse.json().catch(() => ({}));
  if (!reponse.ok || !donnees.ok) throw new Error(donnees.message || "Échec de l'envoi du fichier.");
  return donnees.chemins;
}

document.querySelectorAll('[data-pick]').forEach(bouton => {
  bouton.addEventListener('click', () => {
    const outil = bouton.dataset.pick;
    const multiple = bouton.dataset.multiple === 'true';

    const input = document.createElement('input');
    input.type = 'file';
    input.accept = CONV_ACCEPT[bouton.dataset.filtre] || '';
    input.multiple = multiple;
    input.addEventListener('change', async () => {
      if (!input.files || input.files.length === 0) return;
      const resultDiv = document.querySelector(`[data-result="${outil}"]`);
      try {
        const chemins = await convEnvoyer(input.files);
        if (multiple) {
          // On ajoute aux fichiers déjà choisis, sans doublons (utile pour la fusion)
          chemins.forEach(c => { if (!convFichiers[outil].includes(c)) convFichiers[outil].push(c); });
        } else {
          convFichiers[outil] = chemins.slice(0, 1);
        }
        render_convFileList(outil);
      } catch (e) {
        resultDiv.className = 'conv-result error';
        resultDiv.textContent = e.message;
      }
    });
    input.click();
  });
});

function render_convFileList(outil) {
  const conteneur = document.querySelector(`[data-filelist="${outil}"]`);
  const cfg = CONV_OUTILS[outil];
  const fichiers = convFichiers[outil];
  conteneur.innerHTML = '';

  fichiers.forEach((chemin, index) => {
    const chip = document.createElement('div');
    chip.className = 'conv-file-chip';
    chip.innerHTML = `
      ${cfg.reorder ? `
        <button class="order-btn" data-up ${index === 0 ? 'disabled' : ''} type="button" aria-label="Monter">▲</button>
        <button class="order-btn" data-down ${index === fichiers.length - 1 ? 'disabled' : ''} type="button" aria-label="Descendre">▼</button>
      ` : ''}
      <span class="name"></span>
      <button class="remove-btn" data-remove type="button" aria-label="Retirer">✕</button>
    `;

    chip.querySelector('.name').textContent = nomDeFichier(chemin);

    if (cfg.reorder) {
      chip.querySelector('[data-up]').addEventListener('click', () => {
        if (index === 0) return;
        [fichiers[index - 1], fichiers[index]] = [fichiers[index], fichiers[index - 1]];
        render_convFileList(outil);
      });
      chip.querySelector('[data-down]').addEventListener('click', () => {
        if (index === fichiers.length - 1) return;
        [fichiers[index + 1], fichiers[index]] = [fichiers[index], fichiers[index + 1]];
        render_convFileList(outil);
      });
    }

    chip.querySelector('[data-remove]').addEventListener('click', () => {
      convFichiers[outil].splice(index, 1);
      render_convFileList(outil);
    });

    conteneur.appendChild(chip);
  });

  const actionBtn = document.querySelector(`[data-action="${outil}"]`);
  actionBtn.disabled = fichiers.length < cfg.min;

  const resultDiv = document.querySelector(`[data-result="${outil}"]`);
  resultDiv.className = 'conv-result';
  resultDiv.innerHTML = '';
}

// --- Lancement de la conversion ---
async function afficher_convResultat(outil, resultat) {
  const resultDiv = document.querySelector(`[data-result="${outil}"]`);
  if (!resultat || !resultat.ok) {
    resultDiv.className = 'conv-result error';
    resultDiv.textContent = (resultat && resultat.message) || "Une erreur inattendue s'est produite.";
    return;
  }
  resultDiv.className = 'conv-result ok';
  resultDiv.innerHTML = '';
  const msg = document.createElement('span');
  msg.textContent = '✅ ' + resultat.message;
  resultDiv.appendChild(msg);

  const fichiers = resultat.fichiers || [];
  fichiers.forEach(nom => {
    const lien = document.createElement('a');
    lien.className = 'conv-open-folder-btn';
    lien.href = `/download/${encodeURIComponent(resultat.dossier_id)}/${encodeURIComponent(nom)}`;
    lien.textContent = fichiers.length === 1 ? 'Télécharger' : 'Télécharger ' + nom;
    lien.style.textDecoration = 'none';
    lien.style.display = 'inline-block';
    resultDiv.appendChild(lien);
  });
  if (fichiers.length > 1) {
    const zip = document.createElement('a');
    zip.className = 'conv-open-folder-btn';
    zip.href = `/download-zip/${encodeURIComponent(resultat.dossier_id)}`;
    zip.textContent = 'Tout télécharger (.zip)';
    zip.style.textDecoration = 'none';
    zip.style.display = 'inline-block';
    resultDiv.appendChild(zip);
  }
}

document.querySelectorAll('.conv-action-btn').forEach(bouton => {
  bouton.addEventListener('click', async () => {
    const outil = bouton.dataset.action;
    // Sur le web, le résultat reste sur le serveur le temps du téléchargement.
    const dossierSortie = null;

    bouton.disabled = true;
    bouton.classList.add('loading');
    const contenuOriginal = bouton.innerHTML;
    bouton.innerHTML = '';
    bouton.appendChild(creerMiniEspritLoader());
    bouton.appendChild(document.createTextNode(' ' + CONV_OUTILS[outil].actionLabel));
    const resultDiv = document.querySelector(`[data-result="${outil}"]`);
    resultDiv.className = 'conv-result';
    resultDiv.innerHTML = '';

    let resultat;
    try {
      const fichiers = convFichiers[outil];
      if (outil === 'img2pdf') {
        resultat = await window.pywebview.api.images_vers_pdf(fichiers, dossierSortie);
      } else if (outil === 'pdf2img') {
        const format = document.getElementById('pdf2imgFormat').value;
        resultat = await window.pywebview.api.pdf_vers_images(fichiers[0], format, dossierSortie);
      } else if (outil === 'doc2pdf') {
        resultat = await window.pywebview.api.document_vers_pdf(fichiers[0], dossierSortie);
      } else if (outil === 'pdf2docx') {
        resultat = await window.pywebview.api.pdf_vers_docx(fichiers[0], dossierSortie);
      } else if (outil === 'pdf2pptx') {
        resultat = await window.pywebview.api.pdf_vers_pptx(fichiers[0], dossierSortie);
      } else if (outil === 'merge') {
        resultat = await window.pywebview.api.fusionner_pdf(fichiers, dossierSortie);
      }
    } catch (e) {
      resultat = { ok: false, message: "Une erreur inattendue s'est produite." };
    }

    bouton.classList.remove('loading');
    bouton.innerHTML = contenuOriginal;
    bouton.disabled = convFichiers[outil].length < CONV_OUTILS[outil].min;
    afficher_convResultat(outil, resultat);
  });
});
