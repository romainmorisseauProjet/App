// --- Module Station spatiale (ISS) ---
// Dépend de iss-carte.js (constante ISS_TERRES : fond de carte).

const issEtat = {
  position: null,        // dernière télémétrie reçue
  trace: null,           // points de trajectoire
  lieu: null,            // { nom, lat, lon } : l'endroit d'observation
  carteConstruite: false,
  minuteur: null,
  minuteurTrace: 0,      // horodatage du dernier chargement de trajectoire
  passagesCharges: 0,    // horodatage du dernier calcul de passages
  equipageCharge: 0,
  enCours: false,        // évite d'empiler les requêtes si une est lente
};

const issX = lon => (lon + 180) * 2;
const issY = lat => (90 - lat) * 2;
const issRad = d => d * Math.PI / 180;
const issDeg = r => r * 180 / Math.PI;

function issEl(id) { return document.getElementById(id); }

// ---------------------------------------------------------------- géométrie

function issDistanceKm(lat1, lon1, lat2, lon2) {
  const dLat = issRad(lat2 - lat1), dLon = issRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(issRad(lat1)) * Math.cos(issRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(a));
}

// Hauteur du Soleil (en degrés) vu depuis un lieu, à partir du point sous le Soleil.
function issHauteurSoleil(lat, lon, solaireLat, solaireLon) {
  const v = Math.sin(issRad(lat)) * Math.sin(issRad(solaireLat)) +
            Math.cos(issRad(lat)) * Math.cos(issRad(solaireLat)) * Math.cos(issRad(lon - solaireLon));
  return issDeg(Math.asin(Math.max(-1, Math.min(1, v))));
}

// Cercle de visibilité de l'ISS (rayon = moitié de l'empreinte), en points lat/lon.
function issEmpreintePoints(lat, lon, rayonKm) {
  const delta = rayonKm / 6371, phi = issRad(lat), pts = [];
  for (let b = 0; b < 360; b += 6) {
    const th = issRad(b);
    const lat2 = Math.asin(Math.sin(phi) * Math.cos(delta) + Math.cos(phi) * Math.sin(delta) * Math.cos(th));
    const dLon = Math.atan2(Math.sin(th) * Math.sin(delta) * Math.cos(phi), Math.cos(delta) - Math.sin(phi) * Math.sin(lat2));
    pts.push([issDeg(lat2), lon + issDeg(dLon)]);   // longitude "déroulée" : continue autour du centre
  }
  return pts;
}

// Zone de nuit : la courbe du terminateur, fermée vers le pôle côté nuit.
function issCheminNuit(solaireLat, solaireLon) {
  let phiS = solaireLat;
  if (Math.abs(phiS) < 0.05) phiS = phiS < 0 ? -0.05 : 0.05;
  const tan = Math.tan(issRad(phiS));
  let d = '';
  for (let lon = -180; lon <= 180; lon += 2) {
    const lat = issDeg(Math.atan(-Math.cos(issRad(lon - solaireLon)) / tan));
    d += (lon === -180 ? 'M' : 'L') + issX(lon).toFixed(1) + ' ' + issY(lat).toFixed(1);
  }
  const bord = phiS > 0 ? 360 : 0;   // soleil au nord : la nuit est au sud (bas de la carte)
  return d + `L720 ${bord}L0 ${bord}Z`;
}

// Trace en segments, en coupant là où la trajectoire passe de 180° à -180°.
function issCheminTrace(points) {
  let d = '', precedent = null;
  points.forEach(p => {
    const x = issX(p.lon).toFixed(1), y = issY(p.lat).toFixed(1);
    if (precedent === null || Math.abs(p.lon - precedent) > 180) d += `M${x} ${y}`;
    else d += `L${x} ${y}`;
    precedent = p.lon;
  });
  return d;
}

// ------------------------------------------------------------------- carte

function issConstruireCarte() {
  if (issEtat.carteConstruite) return;
  issEtat.carteConstruite = true;

  let grille = '';
  for (let lon = -150; lon <= 150; lon += 30) grille += `<line x1="${issX(lon)}" y1="0" x2="${issX(lon)}" y2="360"/>`;
  for (let lat = -60; lat <= 60; lat += 30) {
    grille += `<line ${lat === 0 ? 'class="iss-grille-equateur"' : ''} x1="0" y1="${issY(lat)}" x2="720" y2="${issY(lat)}"/>`;
  }

  issEl('issSvg').innerHTML = `
    <defs><clipPath id="issClip"><rect width="720" height="360"/></clipPath></defs>
    <g clip-path="url(#issClip)">
      <g class="iss-grille">${grille}</g>
      <path class="iss-terres" d="${ISS_TERRES}"/>
      <path class="iss-nuit" id="issNuit"/>
      <path class="iss-trace-passe" id="issTracePasse"/>
      <path class="iss-trace-futur" id="issTraceFutur"/>
      <g id="issEmpreinte"></g>
      <g id="issLieu"></g>
      <g id="issSonde" style="display:none">
        <circle class="iss-sonde-halo" r="6"/>
        <circle class="iss-sonde-coeur" r="3.6"/>
      </g>
    </g>`;
}

function issDessinerTrace() {
  if (!issEtat.trace || !issEtat.trace.ok) return;
  const maintenant = Date.now() / 1000;
  const passe = issEtat.trace.points.filter(p => p.t <= maintenant);
  const futur = issEtat.trace.points.filter(p => p.t >= maintenant);
  // On accroche le futur à la position actuelle pour que la ligne parte de l'ISS
  if (issEtat.position && issEtat.position.ok) {
    const p = { lat: issEtat.position.latitude, lon: issEtat.position.longitude };
    if (passe.length) passe.push(p);
    futur.unshift(p);
  }
  issEl('issTracePasse').setAttribute('d', issCheminTrace(passe));
  issEl('issTraceFutur').setAttribute('d', issCheminTrace(futur));
}

function issDessinerPosition() {
  const p = issEtat.position;
  if (!p || !p.ok) return;

  issEl('issNuit').setAttribute('d', issCheminNuit(p.solar_lat, p.solar_lon));

  const sonde = issEl('issSonde');
  sonde.style.display = '';
  sonde.setAttribute('transform', `translate(${issX(p.longitude).toFixed(1)} ${issY(p.latitude).toFixed(1)})`);

  // Zone d'où l'ISS est au-dessus de l'horizon (recopiée à gauche/droite pour franchir le bord de la carte)
  const pts = issEmpreintePoints(p.latitude, p.longitude, p.footprint / 2)
    .map(([la, lo]) => `${issX(lo).toFixed(1)},${issY(la).toFixed(1)}`).join(' ');
  issEl('issEmpreinte').innerHTML = [-720, 0, 720]
    .map(dx => `<polygon class="iss-empreinte" transform="translate(${dx} 0)" points="${pts}"/>`).join('');
}

function issDessinerLieu() {
  const g = issEl('issLieu');
  if (!issEtat.lieu) { g.innerHTML = ''; return; }
  const x = issX(issEtat.lieu.lon), y = issY(issEtat.lieu.lat);
  const nom = document.createElement('div'); nom.textContent = issEtat.lieu.nom;   // échappement
  g.innerHTML = `
    <path class="iss-lieu-marque" d="M${x} ${y - 5}L${x + 4} ${y}L${x} ${y + 5}L${x - 4} ${y}Z"/>
    <text class="iss-lieu-contour" x="${x + 7}" y="${y + 3}">${nom.innerHTML}</text>
    <text class="iss-lieu-etiquette" x="${x + 7}" y="${y + 3}">${nom.innerHTML}</text>`;
}

// ------------------------------------------------------------ télémétrie

function issFormaterCoord(valeur, positif, negatif) {
  return `${Math.abs(valeur).toFixed(2)}° ${valeur >= 0 ? positif : negatif}`;
}

function issNomPays(code) {
  if (!code) return 'Océan';
  try { return new Intl.DisplayNames(['fr'], { type: 'region' }).of(code) || code; }
  catch (e) { return code; }
}

function issAfficherTuiles() {
  const p = issEtat.position;
  if (!p || !p.ok) return;
  const nf = new Intl.NumberFormat('fr-FR');
  issEl('issLat').textContent = issFormaterCoord(p.latitude, 'N', 'S');
  issEl('issLon').textContent = issFormaterCoord(p.longitude, 'E', 'O');
  issEl('issAlt').innerHTML = `${nf.format(Math.round(p.altitude))}<small>km</small>`;
  issEl('issVit').innerHTML = `${nf.format(Math.round(p.velocity))}<small>km/h</small>`;
  issEl('issPays').textContent = issNomPays(p.pays);
  issEl('issLumiere').textContent = p.visibility === 'eclipsed' ? 'Dans l\'ombre' : 'Au soleil';
}

function issPastille(etat, texte) {
  const el = issEl('issPastille');
  el.className = 'iss-pill ' + etat;
  issEl('issPastilleTexte').textContent = texte;
}

// ------------------------------------------------- « Chez toi » (statut live)

function issAfficherStatut() {
  const el = issEl('issStatut');
  const p = issEtat.position, lieu = issEtat.lieu;
  el.className = 'iss-statut';

  if (!lieu) {
    el.innerHTML = 'Choisis une ville pour savoir quand l\'ISS passera au-dessus de chez toi.';
    return;
  }
  if (!p || !p.ok) { el.textContent = 'En attente de la position de l\'ISS…'; return; }

  const distance = issDistanceKm(lieu.lat, lieu.lon, p.latitude, p.longitude);
  const auDessus = distance < p.footprint / 2;
  const soleil = issHauteurSoleil(lieu.lat, lieu.lon, p.solar_lat, p.solar_lon);
  const issEclairee = p.visibility !== 'eclipsed';   // l'API renvoie daylight / visible / eclipsed
  const nf = new Intl.NumberFormat('fr-FR');
  const km = nf.format(Math.round(distance));

  if (auDessus && issEclairee && soleil < -6) {
    el.classList.add('visible');
    el.innerHTML = `<strong>Visible maintenant à l'œil nu depuis ${lieu.nom} !</strong><br>Lève les yeux : elle est à ${km} km de toi, éclairée par le Soleil, dans un ciel assez sombre.`;
  } else if (auDessus && soleil >= -6) {
    el.innerHTML = `<strong>Elle est au-dessus de ton horizon</strong> (à ${km} km), mais le ciel est encore trop clair pour la voir.`;
  } else if (auDessus && !issEclairee) {
    el.innerHTML = `<strong>Elle est au-dessus de ton horizon</strong> (à ${km} km), mais plongée dans l'ombre de la Terre : invisible.`;
  } else {
    el.innerHTML = `L'ISS est actuellement à <strong>${km} km</strong> de ${lieu.nom}, sous ton horizon.`;
  }
}

function issDans(ts) {
  const min = Math.round((ts * 1000 - Date.now()) / 60000);
  if (min <= 0) return 'en cours';
  if (min < 60) return `dans ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `dans ${h} h ${String(min % 60).padStart(2, '0')}`;
  return `dans ${Math.round(h / 24)} j`;
}

async function issChargerPassages(forcer = false) {
  const zone = issEl('issPassages');
  if (!issEtat.lieu) { zone.innerHTML = ''; return; }
  if (!forcer && Date.now() - issEtat.passagesCharges < 20 * 60 * 1000 && zone.dataset.lieu === issEtat.lieu.nom) return;

  zone.dataset.lieu = issEtat.lieu.nom;
  zone.innerHTML = '<div class="iss-vide">Calcul des prochains passages…</div>';
  try {
    const res = await window.pywebview.api.get_iss_passages(issEtat.lieu.lat, issEtat.lieu.lon);
    issEtat.passagesCharges = Date.now();
    if (!res.ok) { zone.innerHTML = `<div class="iss-vide">${res.message || 'Calcul impossible.'}</div>`; return; }
    if (res.passages.length === 0) {
      zone.innerHTML = '<div class="iss-vide">Aucun passage visible dans les 4 prochains jours (ciel trop clair ou ISS dans l\'ombre). Réessaie demain.</div>';
      return;
    }
    zone.innerHTML = '<div class="iss-passages-titre">PROCHAINS PASSAGES VISIBLES</div>';
    res.passages.forEach(ps => {
      const quand = new Date(ps.debut * 1000).toLocaleString('fr-FR', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
      const min = Math.floor(ps.duree_s / 60), sec = String(ps.duree_s % 60).padStart(2, '0');
      const ligne = document.createElement('div');
      ligne.className = 'iss-passage';
      ligne.innerHTML = `
        <div><div class="iss-passage-quand">${quand}</div><div class="iss-passage-relatif">${issDans(ps.debut)}</div></div>
        <div class="iss-passage-droite"><b>${ps.elevation_max}°</b> max · ${min}:${sec}<br>${ps.depart} → ${ps.culmine} → ${ps.arrivee}</div>`;
      zone.appendChild(ligne);
    });
  } catch (e) {
    zone.innerHTML = '<div class="iss-vide">Erreur lors du calcul des passages.</div>';
  }
}

// ------------------------------------------------------------- équipage

async function issChargerEquipage() {
  if (Date.now() - issEtat.equipageCharge < 60 * 60 * 1000) return;
  const zone = issEl('issEquipage');
  try {
    const res = await window.pywebview.api.get_iss_equipage();
    issEtat.equipageCharge = Date.now();
    if (!res.ok || res.personnes.length === 0) {
      zone.innerHTML = '<div class="iss-vide">Liste indisponible pour le moment.</div>';
      issEl('issEquipageTitre').textContent = 'Humains dans l\'espace';
      return;
    }
    issEl('issEquipageTitre').textContent = `${res.total} humains dans l'espace en ce moment`;
    zone.innerHTML = '';
    res.personnes.forEach(pers => {
      const initiales = pers.name.split(' ').map(m => m[0]).slice(0, 2).join('').toUpperCase();
      const chip = document.createElement('div');
      chip.className = 'iss-astronaute';
      const ini = document.createElement('span'); ini.className = 'iss-astronaute-ini'; ini.textContent = initiales;
      const nom = document.createElement('span'); nom.textContent = pers.name;
      const vaisseau = document.createElement('small'); vaisseau.textContent = pers.craft;
      chip.append(ini, nom, vaisseau);
      zone.appendChild(chip);
    });
  } catch (e) {
    zone.innerHTML = '<div class="iss-vide">Liste indisponible pour le moment.</div>';
  }
}

// ---------------------------------------------------------- boucle live

async function issRafraichir() {
  if (issEtat.enCours) return;
  issEtat.enCours = true;
  try {
    const etat = await window.pywebview.api.get_iss_etat();
    if (etat.ok) {
      issEtat.position = etat;
      issDessinerPosition();
      issDessinerTrace();
      issAfficherTuiles();
      issAfficherStatut();
      issPastille('live', 'En direct · ' + new Date().toLocaleTimeString('fr-FR'));
    } else {
      issPastille('err', 'Reconnexion…');
    }
  } catch (e) {
    issPastille('err', 'Reconnexion…');
  }
  issEtat.enCours = false;

  // La trajectoire change lentement : on la recharge toutes les 4 minutes seulement
  if (Date.now() - issEtat.minuteurTrace > 4 * 60 * 1000) {
    issEtat.minuteurTrace = Date.now();
    window.pywebview.api.get_iss_trace().then(t => { issEtat.trace = t; issDessinerTrace(); }).catch(() => {});
  }
}

async function issDemarrer() {
  issConstruireCarte();
  if (!issEtat.lieu) {
    try { issEtat.lieu = await window.pywebview.api.get_iss_lieu(); } catch (e) {}
    if (issEtat.lieu) issEl('issLieuInput').value = issEtat.lieu.nom;
    issDessinerLieu();
  }
  issAfficherStatut();
  issRafraichir();
  if (!issEtat.minuteur) issEtat.minuteur = setInterval(issRafraichir, 5000);
  issChargerPassages();
  issChargerEquipage();
}

function issArreter() {
  if (issEtat.minuteur) { clearInterval(issEtat.minuteur); issEtat.minuteur = null; }
}

document.addEventListener('tab:opened', (e) => {
  if (e.detail === 'iss') issDemarrer(); else issArreter();
});

// --------------------------------------------------- choix de la ville

let issTimeoutRecherche = null;
const issInput = issEl('issLieuInput');
const issSuggestions = issEl('issSuggestions');

issInput.addEventListener('input', () => {
  clearTimeout(issTimeoutRecherche);
  const q = issInput.value.trim();
  if (q.length < 2) { issSuggestions.classList.add('hidden'); return; }
  issTimeoutRecherche = setTimeout(() => issChercherVilles(q), 350);
});

document.addEventListener('click', (e) => {
  if (!e.target.closest('.iss-recherche')) issSuggestions.classList.add('hidden');
});

async function issChercherVilles(q) {
  try {
    const r = await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(q)}&count=6&language=fr&format=json`);
    const d = await r.json();
    const villes = d.results || [];
    issSuggestions.innerHTML = '';
    if (villes.length === 0) {
      issSuggestions.innerHTML = '<div class="iss-suggestion-vide">Aucune ville trouvée</div>';
    } else {
      villes.forEach(v => {
        const div = document.createElement('div');
        div.className = 'iss-suggestion';
        const nom = document.createElement('div'); nom.textContent = v.name;
        const sub = document.createElement('div'); sub.className = 'sub';
        sub.textContent = [v.admin1, v.country].filter(Boolean).join(', ');
        div.append(nom, sub);
        div.addEventListener('click', () => issChoisirLieu(v));
        issSuggestions.appendChild(div);
      });
    }
    issSuggestions.classList.remove('hidden');
  } catch (e) {
    issSuggestions.innerHTML = '<div class="iss-suggestion-vide">Erreur de recherche (connexion ?)</div>';
    issSuggestions.classList.remove('hidden');
  }
}

async function issChoisirLieu(ville) {
  issEtat.lieu = { nom: ville.name, lat: ville.latitude, lon: ville.longitude };
  issInput.value = ville.name;
  issSuggestions.classList.add('hidden');
  issDessinerLieu();
  issAfficherStatut();
  try { await window.pywebview.api.set_iss_lieu(ville.name, ville.latitude, ville.longitude); } catch (e) {}
  issChargerPassages(true);
}
