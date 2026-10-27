// --- Module Calcul ---
// Toute la logique de calcul est côté Python (calcul.py). Ce fichier ne fait
// que : lire la barre de calcul, gérer la photo, construire les formulaires
// de formules et afficher les résultats. Tout est affiché via textContent
// (jamais innerHTML) : la réponse d'une IA ne peut donc pas injecter de code.

(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const panel = document.querySelector('[data-panel="calcul"]');
  if (!panel) return;

  const el = {
    bar: $('calcBar'), input: $('calcInput'), go: $('calcGo'),
    photoBtn: $('calcPhotoBtn'), file: $('calcFile'), photo: $('calcPhoto'),
    photoImg: $('calcPhotoImg'), photoRetirer: $('calcPhotoRetirer'),
    result: $('calcResult'), detail: $('calcDetail'),
    iaPill: $('calcIaPill'), iaConfig: $('calcIaConfig'), iaCle: $('calcIaCle'),
    iaModele: $('calcIaModele'), iaSave: $('calcIaSave'), iaRetirer: $('calcIaRetirer'), iaEtat: $('calcIaEtat'),
    chips: $('calcChips'), search: $('calcSearch'), flist: $('calcFList'), form: $('calcForm'),
    histo: $('calcHisto'), histoVider: $('calcHistoVider'),
  };

  let photo = null;          // { dataUrl }
  let catalogue = null;      // { categories, formules }
  let formuleCourante = null;
  let catFiltre = 'Tout';
  let dernier = null;        // dernière demande de la barre, pour la relancer si besoin
  let minuteur = null;

  // --- Petits utilitaires ---
  function api() {
    return new Promise((resolve) => {
      const essayer = () => (window.pywebview && window.pywebview.api)
        ? resolve(window.pywebview.api) : setTimeout(essayer, 150);
      essayer();
    });
  }
  function h(tag, cls, texte) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (texte != null) n.textContent = texte;
    return n;
  }
  function vider(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function normaliser(s) {
    return (s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  }

  async function copier(ligne, texte) {
    const brut = texte.replace(/\u202f/g, '');   // sans les espaces de milliers : prêt à recoller
    try {
      await navigator.clipboard.writeText(brut);
    } catch (e) {
      const t = document.createElement('textarea');
      t.value = brut; document.body.appendChild(t); t.select();
      try { document.execCommand('copy'); } catch (e2) { /* tant pis */ }
      document.body.removeChild(t);
    }
    if (ligne) {
      ligne.classList.add('copie');
      setTimeout(() => ligne.classList.remove('copie'), 700);
    }
  }

  // --- Affichage d'un résultat (barre principale ou formulaire) ---
  function afficher(conteneur, res) {
    vider(conteneur);
    conteneur.classList.remove('erreur');
    conteneur.classList.toggle('avec-details', el.detail.checked);
    if (!res || (!res.ok && !res.message)) { conteneur.classList.add('hidden'); return; }
    conteneur.classList.remove('hidden');

    if (!res.ok) {
      conteneur.classList.add('erreur');
      conteneur.appendChild(h('div', 'calc-erreur', res.message));
      return;
    }
    const seule = res.lignes.length === 1 && !res.lignes[0].label;
    res.lignes.forEach((l) => {
      const ligne = h('div', 'calc-ligne' + (seule ? ' seule' : ''));
      if (l.label) ligne.appendChild(h('span', 'lab', l.label));
      ligne.appendChild(h('span', 'val', l.valeur));
      if (l.formule) ligne.appendChild(h('div', 'calc-formule', l.formule));
      ligne.title = 'Cliquer pour copier';
      ligne.addEventListener('click', () => copier(ligne, l.valeur));
      conteneur.appendChild(ligne);
    });
    if (res.explication) conteneur.appendChild(h('div', 'calc-explication', res.explication));
    if (res.note) conteneur.appendChild(h('div', 'calc-explication', res.note));
  }

  // --- Barre de calcul ---
  async function executer(texte, photoJointe) {
    el.go.disabled = true;
    const delai = setTimeout(() => {
      vider(el.result);
      el.result.classList.remove('hidden', 'erreur');
      el.result.appendChild(h('div', 'calc-chargement', photoJointe ? 'Lecture de la photo…' : 'Calcul…'));
    }, 350);
    try {
      const a = await api();
      const res = await a.calcul_demander(texte, photoJointe ? photoJointe.dataUrl : null, el.detail.checked);
      dernier = { texte, photo: photoJointe, res };
      clearTimeout(delai);
      afficher(el.result, res);
      if (res.ok) chargerHistorique();
    } catch (e) {
      clearTimeout(delai);
      afficher(el.result, { ok: false, message: 'Erreur interne' });
    } finally {
      el.go.disabled = false;
    }
  }

  function lancer() {
    const texte = el.input.value.trim();
    if (!texte && !photo) return;
    executer(texte, photo);
  }

  el.go.addEventListener('click', lancer);
  el.input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') lancer();
    if (e.key === 'Escape') { el.input.value = ''; afficher(el.result, null); }
  });

  // Interrupteur Détails : bascule l'affichage, et relance une réponse IA pour obtenir ses explications
  el.detail.addEventListener('change', () => {
    panel.querySelectorAll('.calc-result').forEach((c) => c.classList.toggle('avec-details', el.detail.checked));
    if (el.detail.checked && dernier && dernier.res && dernier.res.ok
        && dernier.res.type === 'ia' && !dernier.res.explication) {
      executer(dernier.texte, dernier.photo);
    }
  });

  // --- Photo : bouton, glisser-déposer, collage (Ctrl+V) ---
  function definirPhoto(dataUrl) {
    photo = { dataUrl };
    el.photoImg.src = dataUrl;
    el.photo.classList.remove('hidden');
    el.input.focus();
  }
  function retirerPhoto() {
    photo = null;
    el.photoImg.removeAttribute('src');
    el.photo.classList.add('hidden');
    el.file.value = '';
  }
  function chargerImage(fichier) {
    if (!fichier || !fichier.type || !fichier.type.startsWith('image/')) {
      afficher(el.result, { ok: false, message: 'Fichier image attendu (png, jpg…)' });
      return;
    }
    const lecteur = new FileReader();
    lecteur.onload = () => {
      const img = new Image();
      img.onload = () => {
        // Réduction côté interface : transfert plus léger vers Python, lecture tout aussi nette pour l'IA
        const echelle = Math.min(1, 1600 / Math.max(img.naturalWidth, img.naturalHeight));
        const w = Math.round(img.naturalWidth * echelle), hh = Math.round(img.naturalHeight * echelle);
        const c = document.createElement('canvas');
        c.width = w; c.height = hh;
        const ctx = c.getContext('2d');
        ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, w, hh);
        ctx.drawImage(img, 0, 0, w, hh);
        definirPhoto(c.toDataURL('image/jpeg', 0.9));
      };
      img.onerror = () => definirPhoto(lecteur.result);
      img.src = lecteur.result;
    };
    lecteur.readAsDataURL(fichier);
  }

  el.photoBtn.addEventListener('click', () => el.file.click());
  el.file.addEventListener('change', () => { if (el.file.files[0]) chargerImage(el.file.files[0]); });
  el.photoRetirer.addEventListener('click', retirerPhoto);

  document.addEventListener('paste', (e) => {
    if (panel.classList.contains('hidden')) return;
    const items = (e.clipboardData && e.clipboardData.items) || [];
    for (const it of items) {
      if (it.type && it.type.startsWith('image/')) {
        e.preventDefault();
        chargerImage(it.getAsFile());
        return;
      }
    }
  });
  panel.addEventListener('dragover', (e) => {
    if (e.dataTransfer && [...e.dataTransfer.types].includes('Files')) {
      e.preventDefault();
      el.bar.classList.add('drop');
    }
  });
  panel.addEventListener('dragleave', (e) => {
    if (!panel.contains(e.relatedTarget)) el.bar.classList.remove('drop');
  });
  panel.addEventListener('drop', (e) => {
    el.bar.classList.remove('drop');
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) {
      e.preventDefault();
      chargerImage(e.dataTransfer.files[0]);
    }
  });

  // --- Onglets internes (Formules / Historique) ---
  panel.querySelectorAll('[data-calc-tab]').forEach((b) => {
    b.addEventListener('click', () => {
      panel.querySelectorAll('[data-calc-tab]').forEach((x) => x.classList.toggle('active', x === b));
      panel.querySelectorAll('[data-calc-section]').forEach((s) =>
        s.classList.toggle('hidden', s.dataset.calcSection !== b.dataset.calcTab));
      if (b.dataset.calcTab === 'historique') chargerHistorique();
    });
  });

  // --- Catalogue de formules ---
  async function chargerCatalogue() {
    if (catalogue) return;
    try {
      const a = await api();
      catalogue = await a.calcul_catalogue();
      dessinerChips();
      dessinerListe();
    } catch (e) {
      vider(el.flist);
      el.flist.appendChild(h('div', 'calc-vide', 'Catalogue indisponible.'));
    }
  }

  function dessinerChips() {
    vider(el.chips);
    ['Tout', ...catalogue.categories].forEach((c) => {
      const b = h('button', 'calc-chip' + (c === catFiltre ? ' active' : ''), c);
      b.type = 'button';
      b.addEventListener('click', () => { catFiltre = c; dessinerChips(); dessinerListe(); });
      el.chips.appendChild(b);
    });
  }

  function dessinerListe() {
    vider(el.flist);
    const q = normaliser(el.search.value);
    const liste = catalogue.formules.filter((f) =>
      (catFiltre === 'Tout' || f.cat === catFiltre) &&
      (!q || normaliser(f.nom + ' ' + f.mots + ' ' + f.cat).includes(q)));
    if (liste.length === 0) {
      el.flist.appendChild(h('div', 'calc-vide', 'Aucune formule. Essaie la barre ci-dessus.'));
      return;
    }
    liste.forEach((f) => {
      const b = h('button', 'calc-fitem' + (formuleCourante && formuleCourante.id === f.id ? ' actif' : ''));
      b.type = 'button';
      b.appendChild(h('span', 'cat', f.cat));
      b.appendChild(h('span', null, f.nom));
      b.addEventListener('click', () => ouvrirFormule(f));
      el.flist.appendChild(b);
    });
  }
  el.search.addEventListener('input', () => { if (catalogue) dessinerListe(); });

  // --- Formulaire d'une formule ---
  function ouvrirFormule(f) {
    formuleCourante = f;
    dessinerListe();
    vider(el.form);
    el.form.classList.remove('hidden');

    const tete = h('div', 'calc-form-head');
    tete.appendChild(h('div', 'calc-form-title', f.nom));
    if (f.choix) {
      const sel = h('select', 'calc-select');
      sel.setAttribute('aria-label', f.choix.l);
      const defauts = {};
      f.entrees.forEach((e) => { defauts[e.k] = e.d; });
      let idx = f.choix.o.findIndex((o) => Object.keys(o.set).every((k) => defauts[k] === o.set[k]));
      if (idx === -1) {
        const perso = h('option', null, f.choix.l + ' : personnalisé');
        perso.value = '-1';
        sel.appendChild(perso);
      }
      f.choix.o.forEach((o, i) => {
        const opt = h('option', null, o.nom);
        opt.value = String(i);
        sel.appendChild(opt);
      });
      sel.value = String(idx);
      sel.addEventListener('change', () => {
        const o = f.choix.o[parseInt(sel.value, 10)];
        if (!o) return;
        Object.entries(o.set).forEach(([k, v]) => {
          const champ = el.form.querySelector(`[data-k="${k}"]`);
          if (champ) champ.value = v;
        });
        calculerFormule(false);
      });
      tete.appendChild(sel);
    }
    el.form.appendChild(tete);

    const grille = h('div', 'calc-fields');
    f.entrees.forEach((e) => {
      const champ = h('div', 'calc-field');
      champ.appendChild(h('label', null, e.l + (e.opt ? ' (optionnel)' : '')));
      const boite = h('div', 'box');
      let inp;
      if (e.t === 'bool') {
        inp = document.createElement('input');
        inp.type = 'checkbox';
        inp.checked = e.d === '1';
        inp.addEventListener('change', planifier);
      } else {
        inp = document.createElement('input');
        inp.type = 'text';
        inp.value = e.d;
        inp.autocomplete = 'off';
        inp.spellcheck = false;
        if (e.t === 'liste') inp.placeholder = 'ex. 100 220 330';
        inp.addEventListener('input', planifier);
        inp.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') calculerFormule(true); });
      }
      inp.dataset.k = e.k;
      boite.appendChild(inp);
      if (e.u && e.t !== 'bool') boite.appendChild(h('span', 'u', e.u));
      champ.appendChild(boite);
      grille.appendChild(champ);
    });
    el.form.appendChild(grille);

    const res = h('div', 'calc-result hidden');
    res.id = 'calcFormRes';
    el.form.appendChild(res);

    const actions = h('div', 'calc-form-actions');
    const bCalc = h('button', 'calc-btn', 'Calculer et mémoriser');
    bCalc.type = 'button';
    bCalc.addEventListener('click', () => calculerFormule(true));
    const bFermer = h('button', 'calc-btn secondaire', 'Fermer');
    bFermer.type = 'button';
    bFermer.addEventListener('click', () => {
      formuleCourante = null;
      el.form.classList.add('hidden');
      dessinerListe();
    });
    actions.appendChild(bCalc);
    actions.appendChild(bFermer);
    el.form.appendChild(actions);

    calculerFormule(false);
    el.form.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function planifier() {
    clearTimeout(minuteur);
    minuteur = setTimeout(() => calculerFormule(false), 220);
  }

  async function calculerFormule(enregistrer) {
    const f = formuleCourante;
    if (!f) return;
    const valeurs = {};
    el.form.querySelectorAll('[data-k]').forEach((i) => {
      valeurs[i.dataset.k] = i.type === 'checkbox' ? (i.checked ? '1' : '0') : i.value;
    });
    try {
      const a = await api();
      const res = await a.calcul_formule(f.id, valeurs, !!enregistrer);
      if (formuleCourante !== f) return;           // une autre formule a été ouverte entre-temps
      afficher($('calcFormRes'), res);
      if (enregistrer && res.ok) chargerHistorique();
    } catch (e) {
      afficher($('calcFormRes'), { ok: false, message: 'Erreur interne' });
    }
  }

  // --- Historique ---
  async function chargerHistorique() {
    try {
      const a = await api();
      const items = await a.calcul_historique_lister();
      vider(el.histo);
      if (!items.length) {
        el.histo.appendChild(h('div', 'calc-vide', 'Aucun calcul pour l’instant.'));
        return;
      }
      items.forEach((it) => {
        const ligne = h('div', 'calc-hrow');
        const corps = h('div', 'corps');
        corps.appendChild(h('div', 'e', it.entree));
        corps.appendChild(h('div', 'r', it.resultat));
        const x = h('button', 'x', '✕');
        x.type = 'button';
        x.title = 'Supprimer';
        x.addEventListener('click', async (ev) => {
          ev.stopPropagation();
          await a.calcul_historique_supprimer(it.id);
          chargerHistorique();
        });
        ligne.title = ['expression', 'conversion', 'maths'].includes(it.type)
          ? 'Reprendre ce calcul' : 'Copier le résultat';
        ligne.addEventListener('click', () => {
          if (['expression', 'conversion', 'maths'].includes(it.type)) {
            el.input.value = it.entree;
            el.input.focus();
            window.scrollTo(0, 0);
          } else {
            copier(ligne, it.resultat.split(' ; ')[0].replace(/^.*? = /, ''));
          }
        });
        ligne.appendChild(corps);
        ligne.appendChild(x);
        el.histo.appendChild(ligne);
      });
    } catch (e) { /* l'historique est un confort */ }
  }
  el.histoVider.addEventListener('click', async () => {
    const a = await api();
    await a.calcul_historique_vider();
    chargerHistorique();
  });

  // --- Configuration de l'IA (clé API) ---
  async function majStatutIA() {
    try {
      const a = await api();
      const s = await a.calcul_ia_statut();
      el.iaPill.classList.toggle('actif', s.actif);
      el.iaPill.title = s.actif ? `IA prête · ${s.modele}` : 'IA non configurée (nécessaire pour les photos)';
      el.iaEtat.textContent = s.actif
        ? `Active · clé ${s.source} (${s.apercu})`
        : 'Inactive : sans clé, les photos et les demandes en langage naturel ne fonctionnent pas.';
      if (document.activeElement !== el.iaModele) el.iaModele.value = s.modele;
    } catch (e) { /* ignoré */ }
  }
  el.iaPill.addEventListener('click', () => {
    el.iaConfig.classList.toggle('hidden');
    if (!el.iaConfig.classList.contains('hidden')) el.iaCle.focus();
  });
  el.iaSave.addEventListener('click', async () => {
    const a = await api();
    await a.calcul_ia_configurer(el.iaCle.value, el.iaModele.value);
    el.iaCle.value = '';
    majStatutIA();
  });
  el.iaRetirer.addEventListener('click', async () => {
    const a = await api();
    await a.calcul_ia_retirer_cle();
    majStatutIA();
  });

  // --- Ouverture de l'onglet ---
  document.addEventListener('tab:opened', (e) => {
    if (e.detail !== 'calcul') return;
    chargerCatalogue();
    chargerHistorique();
    majStatutIA();
    setTimeout(() => el.input.focus(), 60);
  });
})();
