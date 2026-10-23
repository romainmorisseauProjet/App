// --- Module Conversion de fichiers ---
// Chaque outil (img2pdf, pdf2img, doc2pdf, pdf2docx, pdf2pptx, merge) partage
// la même mécanique : choisir des fichiers via le sélecteur natif, les afficher en
// liste, puis lancer l'appel Python correspondant. Les résultats sont écrits
// dans data/conversions/ et jamais sur les fichiers d'origine.

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
document.querySelectorAll('[data-pick]').forEach(bouton => {
  bouton.addEventListener('click', async () => {
    if (!window.pywebview || !window.pywebview.api) return;
    const outil = bouton.dataset.pick;
    const multiple = bouton.dataset.multiple === 'true';
    const chemins = await window.pywebview.api.choisir_fichiers(bouton.dataset.filtre, multiple);
    if (!chemins || chemins.length === 0) return;

    if (multiple) {
      // On ajoute aux fichiers déjà choisis, sans doublons (utile pour la fusion)
      chemins.forEach(c => { if (!convFichiers[outil].includes(c)) convFichiers[outil].push(c); });
    } else {
      convFichiers[outil] = chemins.slice(0, 1);
    }
    render_convFileList(outil);
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
      <span class="name">${nomDeFichier(chemin)}</span>
      <button class="remove-btn" data-remove type="button" aria-label="Retirer">✕</button>
    `;

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
  resultDiv.innerHTML = `<span>✅ ${resultat.message}</span>`;
  const ouvrirBtn = document.createElement('button');
  ouvrirBtn.className = 'conv-open-folder-btn';
  ouvrirBtn.type = 'button';
  ouvrirBtn.textContent = 'Ouvrir le dossier des résultats';
  ouvrirBtn.addEventListener('click', () => window.pywebview.api.ouvrir_dossier(resultat.dossier));
  resultDiv.appendChild(ouvrirBtn);
}

document.querySelectorAll('.conv-action-btn').forEach(bouton => {
  bouton.addEventListener('click', async () => {
    const outil = bouton.dataset.action;
    if (!window.pywebview || !window.pywebview.api) return;

    // On demande où enregistrer AVANT de lancer la conversion, plutôt que
    // d'écrire automatiquement dans un dossier fixe du projet.
    const dossierSortie = await window.pywebview.api.choisir_dossier_sortie();
    if (!dossierSortie) return; // l'utilisateur a annulé le sélecteur

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
