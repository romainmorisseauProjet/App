// --- Module Projets ---
// Bloc-notes par projet : pages de notes + tâches, et une jauge d'avancement
// qui se calcule à partir des tâches cochées (ou d'un curseur manuel s'il n'y
// a aucune tâche). Les données vivent en base, côté Python (projets.py).

const prjEtat = {
  projets: [],            // résumés de tous les projets (liste de gauche)
  courantId: null,        // projet ouvert
  details: null,          // { projet, taches, pages } du projet ouvert
  pageId: null,           // page affichée dans l'éditeur
  pageParProjet: {},      // dernière page ouverte pour chaque projet
  sale: false,            // true = la page a des modifications non enregistrées
  minuteur: null,         // minuteur de sauvegarde automatique
  pctAffiche: 0,
  initialise: false,
};

const prjEl = id => document.getElementById(id);
const prjApi = () => (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;

function prjEchapper(texte) {
  const d = document.createElement('div');
  d.textContent = texte == null ? '' : String(texte);
  return d.innerHTML;
}

// ------------------------------------------------------- nettoyage du HTML
// Les notes sont stockées en HTML. On n'accepte que quelques balises de mise
// en forme : tout le reste (scripts, attributs, styles, images…) est retiré,
// à l'enregistrement comme à la lecture.
const PRJ_BALISES = new Set(['B', 'STRONG', 'I', 'EM', 'U', 'H2', 'H3', 'P', 'DIV', 'BR', 'UL', 'OL', 'LI']);

function prjNettoyer(html) {
  const doc = new DOMParser().parseFromString(html || '', 'text/html');
  const sortie = document.createElement('div');
  const copier = (source, dest) => {
    source.childNodes.forEach(n => {
      if (n.nodeType === 3) {
        dest.appendChild(document.createTextNode(n.textContent));
      } else if (n.nodeType === 1) {
        if (n.tagName === 'SCRIPT' || n.tagName === 'STYLE') return;
        if (PRJ_BALISES.has(n.tagName)) {
          const el = document.createElement(n.tagName.toLowerCase());   // sans aucun attribut
          copier(n, el);
          dest.appendChild(el);
        } else {
          copier(n, dest);   // balise inconnue : on garde seulement son texte
        }
      }
    });
  };
  copier(doc.body, sortie);
  return sortie.innerHTML;
}

// ----------------------------------------------------------- petits outils

// Compte de façon fluide d'un nombre à un autre (la jauge "monte petit à petit").
function prjAnimerNombre(el, de, vers, duree) {
  if (el._anim) cancelAnimationFrame(el._anim);
  if (!duree || de === vers) { el.textContent = vers + '%'; return; }
  const debut = performance.now();
  const pas = (t) => {
    const k = Math.min(1, (t - debut) / duree);
    const ease = 1 - Math.pow(1 - k, 3);
    el.textContent = Math.round(de + (vers - de) * ease) + '%';
    if (k < 1) el._anim = requestAnimationFrame(pas);
  };
  el._anim = requestAnimationFrame(pas);
}

function prjHeure() {
  return new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
}

// Bouton à double clic : le 1er clic demande confirmation, le 2e exécute.
function prjDoubleClic(bouton, texteConfirm, action) {
  const texteInitial = bouton.textContent;
  let minuteur = null;
  bouton.addEventListener('click', () => {
    if (bouton.classList.contains('confirme')) {
      clearTimeout(minuteur);
      bouton.classList.remove('confirme');
      bouton.textContent = texteInitial;
      action();
    } else {
      bouton.classList.add('confirme');
      bouton.textContent = texteConfirm;
      minuteur = setTimeout(() => { bouton.classList.remove('confirme'); bouton.textContent = texteInitial; }, 3000);
    }
  });
}

// --------------------------------------------------------- liste de gauche

function prjRendreListe() {
  const zone = prjEl('prjListe');
  zone.innerHTML = '';
  prjEtat.projets.forEach(p => {
    const item = document.createElement('div');
    item.className = 'prj-item';
    item.dataset.id = p.id;
    item.style.setProperty('--c', p.couleur);
    item.innerHTML = `
      <div class="prj-item-ligne">
        <span class="prj-point"></span>
        <span class="prj-item-nom">${prjEchapper(p.nom)}</span>
        <span class="prj-item-pct">${p.progression}%</span>
      </div>
      <div class="prj-mini"><i style="width:${p.progression}%"></i></div>`;
    item.classList.toggle('fini', p.progression >= 100);
    item.classList.toggle('actif', p.id === prjEtat.courantId);
    item.addEventListener('click', () => { if (p.id !== prjEtat.courantId) prjOuvrir(p.id); });
    zone.appendChild(item);
  });
}

function prjMajItem(resume) {
  const item = prjEl('prjListe').querySelector(`.prj-item[data-id="${resume.id}"]`);
  if (!item) return;
  item.querySelector('.prj-item-nom').textContent = resume.nom;
  item.querySelector('.prj-item-pct').textContent = resume.progression + '%';
  item.querySelector('.prj-mini i').style.width = resume.progression + '%';
  item.classList.toggle('fini', resume.progression >= 100);
}

function prjMarquerActif() {
  prjEl('prjListe').querySelectorAll('.prj-item').forEach(el => {
    el.classList.toggle('actif', parseInt(el.dataset.id) === prjEtat.courantId);
  });
}

// ------------------------------------------------------------ la jauge

// mode : 'ouverture' (la jauge se remplit depuis 0) ou 'maj' (elle monte/descend
// depuis sa valeur actuelle).
function prjRendreAvancement(r, mode) {
  const contenu = prjEl('prjContenu');
  const barre = prjEl('prjBarre');
  const etaitFini = contenu.classList.contains('fini');
  const depart = mode === 'ouverture' ? 0 : prjEtat.pctAffiche;

  if (mode === 'ouverture') {
    barre.style.transition = 'none';
    barre.style.width = '0%';
    void barre.offsetWidth;            // force le navigateur à prendre en compte le 0 avant d'animer
    barre.style.transition = '';
  }
  barre.style.width = r.progression + '%';
  prjAnimerNombre(prjEl('prjPct'), depart, r.progression, 800);
  prjEtat.pctAffiche = r.progression;

  // Texte sous le pourcentage + curseur manuel
  const manuel = prjEl('prjManuel');
  if (r.mode === 'taches') {
    const s = r.nb_taches > 1 ? 's' : '';
    prjEl('prjAvDetail').textContent = `${r.nb_faites} sur ${r.nb_taches} tâche${s} terminée${r.nb_faites > 1 ? 's' : ''}`;
    manuel.classList.add('hidden');
  } else {
    prjEl('prjAvDetail').textContent = 'Avancement réglé à la main';
    manuel.classList.remove('hidden');
    prjEl('prjSlider').value = r.progression;
  }
  prjEl('prjCompteTaches').textContent = r.nb_taches ? `${r.nb_faites}/${r.nb_taches}` : '';

  // Passage à 100 % : petite célébration (seulement quand on y arrive, pas à l'ouverture)
  const fini = r.progression >= 100;
  contenu.classList.toggle('fini', fini);
  if (fini && !etaitFini && mode === 'maj') {
    const fond = prjEl('prjBarreFond');
    fond.classList.remove('celebre');
    void fond.offsetWidth;
    fond.classList.add('celebre');
  }
}

// Applique un résumé reçu de Python (après une tâche cochée, etc.)
function prjAppliquerResume(resume) {
  if (!resume) return;
  prjEtat.details.projet = resume;
  const i = prjEtat.projets.findIndex(p => p.id === resume.id);
  if (i >= 0) prjEtat.projets[i] = resume;
  prjRendreAvancement(resume, 'maj');
  prjMajItem(resume);
}

// -------------------------------------------------------- ouverture projet

function prjAfficherVide() {
  prjEl('prjVide').classList.remove('hidden');
  prjEl('prjContenu').classList.add('hidden');
  prjEtat.courantId = null; prjEtat.details = null; prjEtat.pageId = null;
}

async function prjChargerListe(selectionId) {
  const api = prjApi();
  if (!api) return;
  const liste = await api.projets_lister();
  prjEtat.projets = Array.isArray(liste) ? liste : [];
  if (prjEtat.projets.length === 0) { prjRendreListe(); prjAfficherVide(); return; }
  const cible = selectionId != null ? selectionId : prjEtat.courantId;
  const existe = prjEtat.projets.some(p => p.id === cible);
  prjEtat.courantId = existe ? cible : prjEtat.projets[0].id;
  prjRendreListe();
  await prjOuvrir(prjEtat.courantId, true);
}

async function prjOuvrir(id, forcer = false) {
  const api = prjApi();
  if (!api) return;
  if (!forcer) await prjFlush();            // on enregistre la page en cours avant de changer de projet

  const d = await api.projets_details(id);
  if (!d || !d.ok) { await prjChargerListe(); return; }

  prjEtat.courantId = id;
  prjEtat.details = d;
  prjEl('prjVide').classList.add('hidden');
  prjEl('prjContenu').classList.remove('hidden');
  prjEl('prjContenu').style.setProperty('--prj-couleur', d.projet.couleur);
  prjEl('prjNom').value = d.projet.nom;
  prjMarquerActif();
  prjRendreAvancement(d.projet, 'ouverture');
  prjRendreTaches();
  prjRendrePages();

  const memo = prjEtat.pageParProjet[id];
  const pageId = d.pages.some(p => p.id === memo) ? memo : d.pages[0].id;
  await prjOuvrirPage(pageId, true);
}

// ----------------------------------------------------------- nom / suppression

async function prjRenommer() {
  const api = prjApi(); const d = prjEtat.details;
  if (!api || !d) return;
  const nom = prjEl('prjNom').value.trim();
  if (nom === d.projet.nom) return;
  const res = await api.projets_renommer(d.projet.id, nom);
  if (res && res.ok) {
    d.projet = res.projet;
    const i = prjEtat.projets.findIndex(p => p.id === res.projet.id);
    if (i >= 0) prjEtat.projets[i] = res.projet;
    prjMajItem(res.projet);
  } else {
    prjEl('prjNom').value = d.projet.nom;   // nom vide refusé : on remet l'ancien
  }
}
prjEl('prjNom').addEventListener('change', prjRenommer);
prjEl('prjNom').addEventListener('keydown', e => { if (e.key === 'Enter') e.target.blur(); });

prjDoubleClic(prjEl('prjSupprimerBtn'), 'Confirmer la suppression ?', async () => {
  const api = prjApi(); const d = prjEtat.details;
  if (!api || !d) return;
  clearTimeout(prjEtat.minuteur); prjEtat.sale = false; prjEtat.pageId = null;   // inutile d'enregistrer une page qu'on supprime
  await api.projets_supprimer(d.projet.id);
  prjEtat.courantId = null;
  await prjChargerListe();
});

// ---------------------------------------------------------- nouveau projet

const prjNouveauForm = prjEl('prjNouveauForm');
const prjNouveauInput = prjEl('prjNouveauInput');

prjEl('prjNouveauBtn').addEventListener('click', () => {
  const visible = !prjNouveauForm.classList.toggle('hidden');
  if (visible) prjNouveauInput.focus();
});

prjNouveauInput.addEventListener('keydown', async (e) => {
  if (e.key === 'Escape') { prjNouveauForm.classList.add('hidden'); prjNouveauInput.value = ''; return; }
  if (e.key !== 'Enter') return;
  const api = prjApi();
  const nom = prjNouveauInput.value.trim();
  if (!api || !nom) return;
  const res = await api.projets_creer(nom);
  if (!res || !res.ok) return;
  prjNouveauInput.value = '';
  prjNouveauForm.classList.add('hidden');
  await prjFlush();
  await prjChargerListe(res.id);
  prjOnglet('notes');
  prjEl('prjEditeur').focus();
});

// -------------------------------------------------------- onglets Notes/Tâches

function prjOnglet(nom) {
  prjEl('prjOngletNotes').classList.toggle('active', nom === 'notes');
  prjEl('prjOngletTaches').classList.toggle('active', nom === 'taches');
  prjEl('prjVueNotes').classList.toggle('hidden', nom !== 'notes');
  prjEl('prjVueTaches').classList.toggle('hidden', nom !== 'taches');
  if (nom === 'taches') prjFlush();
}
prjEl('prjOngletNotes').addEventListener('click', () => prjOnglet('notes'));
prjEl('prjOngletTaches').addEventListener('click', () => prjOnglet('taches'));

// ----------------------------------------------------------------- tâches

const PRJ_ICONE_COCHE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';

function prjLigneTache(tache) {
  const ligne = document.createElement('div');
  ligne.className = 'prj-tache' + (tache.fait ? ' fait' : '');

  const coche = document.createElement('button');
  coche.type = 'button'; coche.className = 'prj-check'; coche.setAttribute('aria-label', 'Terminer / rouvrir la tâche');
  coche.innerHTML = PRJ_ICONE_COCHE;
  coche.addEventListener('click', async () => {
    const res = await prjApi().projets_tache_basculer(tache.id);
    if (!res || !res.ok) return;
    tache.fait = res.fait;
    ligne.classList.toggle('fait', tache.fait);
    prjAppliquerResume(res.projet);
  });

  const texte = document.createElement('input');
  texte.type = 'text'; texte.className = 'prj-tache-texte'; texte.value = tache.texte; texte.maxLength = 300;
  texte.addEventListener('change', async () => {
    const res = await prjApi().projets_tache_modifier(tache.id, texte.value);
    if (res && res.ok) { tache.texte = res.texte; texte.value = res.texte; }
    else texte.value = tache.texte;
  });
  texte.addEventListener('keydown', e => { if (e.key === 'Enter') texte.blur(); });

  const suppr = document.createElement('button');
  suppr.type = 'button'; suppr.className = 'prj-tache-suppr'; suppr.textContent = '×'; suppr.setAttribute('aria-label', 'Supprimer la tâche');
  suppr.addEventListener('click', async () => {
    const res = await prjApi().projets_tache_supprimer(tache.id);
    if (!res || !res.ok) return;
    prjEtat.details.taches = prjEtat.details.taches.filter(t => t.id !== tache.id);
    prjRendreTaches();
    prjAppliquerResume(res.projet);
  });

  ligne.append(coche, texte, suppr);
  return ligne;
}

function prjRendreTaches() {
  const zone = prjEl('prjListeTaches');
  zone.innerHTML = '';
  const taches = prjEtat.details.taches;
  if (taches.length === 0) {
    zone.innerHTML = '<div class="prj-vide-liste">Aucune tâche pour l\'instant.<br>Dès la première, la jauge se calcule toute seule : chaque tâche cochée la fait monter.</div>';
    return;
  }
  taches.forEach(t => zone.appendChild(prjLigneTache(t)));
}

prjEl('prjTacheInput').addEventListener('keydown', async (e) => {
  if (e.key !== 'Enter') return;
  const api = prjApi(); const d = prjEtat.details;
  const texte = e.target.value.trim();
  if (!api || !d || !texte) return;
  const res = await api.projets_tache_ajouter(d.projet.id, texte);
  if (!res || !res.ok) return;
  e.target.value = '';
  d.taches.push(res.tache);
  prjRendreTaches();
  prjAppliquerResume(res.projet);
});

// ----------------------------------------------------------- pages et notes

function prjRendrePages() {
  const zone = prjEl('prjPages');
  zone.innerHTML = '';
  prjEtat.details.pages.forEach(p => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'prj-page-tab' + (p.id === prjEtat.pageId ? ' actif' : '');
    b.dataset.id = p.id;
    b.textContent = p.titre;
    b.addEventListener('click', () => { if (p.id !== prjEtat.pageId) prjOuvrirPage(p.id); });
    zone.appendChild(b);
  });
  const plus = document.createElement('button');
  plus.type = 'button'; plus.className = 'prj-page-tab prj-page-ajout'; plus.textContent = '+';
  plus.title = 'Nouvelle page'; plus.setAttribute('aria-label', 'Nouvelle page');
  plus.addEventListener('click', prjNouvellePage);
  zone.appendChild(plus);
}

function prjMajPlaceholder() {
  const ed = prjEl('prjEditeur');
  const vide = ed.textContent.trim() === '' && !ed.querySelector('li, h2, h3');
  ed.dataset.vide = vide ? '1' : '0';
}

async function prjOuvrirPage(pageId, sansFlush = false) {
  const api = prjApi();
  if (!api) return;
  if (!sansFlush) await prjFlush();
  const p = await api.projets_page_lire(pageId);
  if (!p || !p.ok) return;
  prjEtat.pageId = pageId;
  prjEtat.pageParProjet[prjEtat.courantId] = pageId;
  prjEtat.sale = false;
  prjEl('prjPageTitre').value = p.titre;
  prjEl('prjEditeur').innerHTML = prjNettoyer(p.contenu);
  prjMajPlaceholder();
  prjEl('prjSauvegarde').textContent = '';
  prjEl('prjSauvegarde').classList.remove('erreur');
  prjRendrePages();
}

async function prjNouvellePage() {
  const api = prjApi(); const d = prjEtat.details;
  if (!api || !d) return;
  await prjFlush();
  const res = await api.projets_page_creer(d.projet.id, 'Nouvelle page');
  if (!res || !res.ok) return;
  d.pages.push({ id: res.id, titre: res.titre, maj_le: '' });
  await prjOuvrirPage(res.id, true);
  const titre = prjEl('prjPageTitre');
  titre.focus(); titre.select();
}

prjDoubleClic(prjEl('prjPageSupprBtn'), 'Confirmer ?', async () => {
  const api = prjApi(); const d = prjEtat.details;
  if (!api || !d || !prjEtat.pageId) return;
  const res = await api.projets_page_supprimer(prjEtat.pageId);
  const ind = prjEl('prjSauvegarde');
  if (!res || !res.ok) {
    ind.textContent = (res && res.message) || 'Suppression impossible';
    ind.classList.add('erreur');
    return;
  }
  clearTimeout(prjEtat.minuteur); prjEtat.sale = false;
  const supprimee = prjEtat.pageId;
  const restantes = d.pages.filter(p => p.id !== supprimee);
  d.pages = restantes;
  await prjOuvrirPage(restantes[0].id, true);
});

// ---- sauvegarde automatique

async function prjSauverPage() {
  const api = prjApi();
  const pageId = prjEtat.pageId;
  if (!api || !pageId) return;
  const titre = prjEl('prjPageTitre').value;
  const contenu = prjNettoyer(prjEl('prjEditeur').innerHTML);
  const ind = prjEl('prjSauvegarde');
  prjEtat.sale = false;
  ind.classList.remove('erreur');
  ind.textContent = 'Enregistrement…';
  const res = await api.projets_page_sauver(pageId, titre, contenu);
  if (res && res.ok) {
    const p = prjEtat.details && prjEtat.details.pages.find(x => x.id === pageId);
    if (p) p.titre = res.titre;
    ind.textContent = 'Enregistré à ' + prjHeure();
  } else {
    prjEtat.sale = true;      // on réessaiera
    ind.classList.add('erreur');
    ind.textContent = (res && res.message) || 'Échec de l\'enregistrement';
  }
}

function prjProgrammerSauvegarde() {
  prjEtat.sale = true;
  prjEl('prjSauvegarde').classList.remove('erreur');
  prjEl('prjSauvegarde').textContent = 'Modifications…';
  clearTimeout(prjEtat.minuteur);
  prjEtat.minuteur = setTimeout(prjSauverPage, 800);
}

// Enregistre tout de suite s'il y a des modifications en attente.
async function prjFlush() {
  clearTimeout(prjEtat.minuteur);
  prjEtat.minuteur = null;
  if (prjEtat.sale && prjEtat.pageId) await prjSauverPage();
}

// ---- éditeur

const prjEditeur = prjEl('prjEditeur');

prjEditeur.addEventListener('input', () => { prjMajPlaceholder(); prjProgrammerSauvegarde(); });

// Collage en texte brut : évite d'importer la mise en page (et le code) d'un autre site ou de Word.
prjEditeur.addEventListener('paste', (e) => {
  e.preventDefault();
  const texte = (e.clipboardData || window.clipboardData).getData('text/plain');
  document.execCommand('insertText', false, texte);
});

prjEditeur.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); prjFlush(); }
});

prjEl('prjPageTitre').addEventListener('input', (e) => {
  const tab = prjEl('prjPages').querySelector(`.prj-page-tab[data-id="${prjEtat.pageId}"]`);
  if (tab) tab.textContent = e.target.value.trim() || 'Sans titre';
  prjProgrammerSauvegarde();
});
prjEl('prjPageTitre').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); prjEditeur.focus(); } });

// Barre d'outils : mousedown ne doit pas retirer la sélection du texte.
prjEl('prjOutils').addEventListener('mousedown', e => { if (e.target.closest('.prj-tb')) e.preventDefault(); });
prjEl('prjOutils').addEventListener('click', (e) => {
  const bouton = e.target.closest('.prj-tb');
  if (!bouton) return;
  prjEditeur.focus();
  const cmd = bouton.dataset.cmd;
  if (cmd === 'titre') {
    const courant = (document.queryCommandValue('formatBlock') || '').toLowerCase();
    document.execCommand('formatBlock', false, courant === 'h2' ? 'p' : 'h2');
  } else if (cmd === 'ul') {
    document.execCommand('insertUnorderedList');
  } else if (cmd === 'ol') {
    document.execCommand('insertOrderedList');
  } else {
    document.execCommand(cmd);
  }
  prjMajPlaceholder();
  prjProgrammerSauvegarde();
});

try { document.execCommand('defaultParagraphSeparator', false, 'p'); } catch (e) { /* non bloquant */ }

// ---- curseur d'avancement manuel (quand le projet n'a aucune tâche)

const prjSlider = prjEl('prjSlider');
prjSlider.addEventListener('input', () => {
  const v = parseInt(prjSlider.value);
  prjEl('prjBarre').style.width = v + '%';
  prjEl('prjPct').textContent = v + '%';
  prjEtat.pctAffiche = v;
});
prjSlider.addEventListener('change', async () => {
  const api = prjApi(); const d = prjEtat.details;
  if (!api || !d) return;
  const res = await api.projets_definir_progression(d.projet.id, parseInt(prjSlider.value));
  if (res && res.ok) {
    d.projet = res.projet;
    const i = prjEtat.projets.findIndex(p => p.id === res.projet.id);
    if (i >= 0) prjEtat.projets[i] = res.projet;
    prjMajItem(res.projet);
    const fini = res.projet.progression >= 100;
    const etaitFini = prjEl('prjContenu').classList.contains('fini');
    prjEl('prjContenu').classList.toggle('fini', fini);
    if (fini && !etaitFini) {
      const fond = prjEl('prjBarreFond'); fond.classList.remove('celebre'); void fond.offsetWidth; fond.classList.add('celebre');
    }
  }
});

// ------------------------------------------------------------ cycle de vie

document.addEventListener('tab:opened', (e) => {
  if (e.detail === 'projets') {
    if (!prjEtat.initialise) { prjEtat.initialise = true; prjChargerListe(); }
  } else {
    prjFlush();     // on quitte l'onglet : rien ne doit rester non enregistré
  }
});
window.addEventListener('beforeunload', () => { prjFlush(); });
