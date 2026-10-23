// --- Données des régions métropolitaines (ville de référence) ---
const REGIONS = [
  { nom: 'Île-de-France',            ville: 'Paris',      lat: 48.8566, lon: 2.3522 },
  { nom: 'Normandie',                ville: 'Rouen',      lat: 49.4432, lon: 1.0993 },
  { nom: 'Hauts-de-France',          ville: 'Lille',       lat: 50.6292, lon: 3.0573 },
  { nom: 'Grand Est',                ville: 'Strasbourg', lat: 48.5734, lon: 7.7521 },
  { nom: 'Bourgogne-Franche-Comté',  ville: 'Dijon',      lat: 47.3220, lon: 5.0415 },
  { nom: 'Bretagne',                 ville: 'Rennes',     lat: 48.1173, lon: -1.6778 },
  { nom: 'Pays de la Loire',         ville: 'Nantes',     lat: 47.2184, lon: -1.5536 },
  { nom: 'Centre-Val de Loire',      ville: 'Orléans',    lat: 47.9029, lon: 1.9039 },
  { nom: 'Nouvelle-Aquitaine',       ville: 'Bordeaux',   lat: 44.8378, lon: -0.5792 },
  { nom: 'Occitanie',                ville: 'Toulouse',   lat: 43.6047, lon: 1.4442 },
  { nom: 'Auvergne-Rhône-Alpes',     ville: 'Lyon',       lat: 45.7640, lon: 4.8357 },
  { nom: "Provence-Alpes-Côte d'Azur", ville: 'Marseille', lat: 43.2965, lon: 5.3698 },
  { nom: 'Corse',                    ville: 'Ajaccio',    lat: 41.9192, lon: 8.7386 },
];

// Points approximatifs du contour de la France métropolitaine (lat, lon)
const CONTOUR_FRANCE = [
  [51.03, 2.38], [50.75, 4.15], [49.55, 5.85], [49.2, 7.0],
  [48.58, 7.85], [47.6, 7.35], [46.3, 6.2], [45.9, 6.9],
  [43.75, 7.5], [43.3, 5.4], [42.7, 3.0], [42.5, 1.5],
  [43.5, -1.5], [44.85, -1.2], [46.15, -1.2], [47.2, -2.2],
  [48.4, -4.5], [48.65, -2.0], [49.65, -1.6], [49.5, 0.1],
  [51.03, 2.38],
];
// Contour approximatif de la Corse
const CONTOUR_CORSE = [
  [43.0, 9.4], [42.6, 9.55], [41.95, 9.25], [41.55, 8.8],
  [41.9, 8.6], [42.6, 8.7], [43.0, 9.4],
];
const LON_MIN = -5.0, LON_MAX = 9.6, LAT_MIN = 41.2, LAT_MAX = 51.2;
const MAP_W = 520, MAP_H = 580;

function projeter(lat, lon) {
  const x = ((lon - LON_MIN) / (LON_MAX - LON_MIN)) * (MAP_W - 60) + 30;
  const y = ((LAT_MAX - lat) / (LAT_MAX - LAT_MIN)) * (MAP_H - 60) + 20;
  return { x, y };
}

function couleurTemp(t) {
  // -5°C -> bleu, ~15°C -> cyan/jaune, 35°C -> rouge-orangé
  const stops = [
    { t: -5, c: [79, 141, 255] },
    { t: 12, c: [95, 217, 255] },
    { t: 22, c: [255, 210, 95] },
    { t: 35, c: [255, 107, 79] },
  ];
  let lo = stops[0], hi = stops[stops.length - 1];
  for (let i = 0; i < stops.length - 1; i++) {
    if (t >= stops[i].t && t <= stops[i + 1].t) { lo = stops[i]; hi = stops[i + 1]; break; }
  }
  const span = hi.t - lo.t || 1;
  const ratio = Math.min(1, Math.max(0, (t - lo.t) / span));
  const c = lo.c.map((v, i) => Math.round(v + (hi.c[i] - v) * ratio));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

const WEATHER_ICONS = {
  0: '☀️', 1: '🌤️', 2: '⛅', 3: '☁️',
  45: '🌫️', 48: '🌫️',
  51: '🌦️', 53: '🌦️', 55: '🌧️',
  61: '🌧️', 63: '🌧️', 65: '🌧️',
  71: '🌨️', 73: '🌨️', 75: '❄️',
  80: '🌦️', 81: '🌧️', 82: '⛈️',
  95: '⛈️', 96: '⛈️', 99: '⛈️',
};
const WEATHER_LABELS = {
  0: 'Ciel dégagé', 1: 'Plutôt dégagé', 2: 'Partiellement nuageux', 3: 'Couvert',
  45: 'Brouillard', 48: 'Brouillard givrant',
  51: 'Bruine légère', 53: 'Bruine', 55: 'Bruine forte',
  61: 'Pluie légère', 63: 'Pluie', 65: 'Pluie forte',
  71: 'Neige légère', 73: 'Neige', 75: 'Neige forte',
  80: 'Averses', 81: 'Averses fortes', 82: 'Averses violentes',
  95: 'Orages', 96: 'Orages avec grêle', 99: 'Orages violents',
};

let meteoInitialisee = false;
let favoris = [];
let villeCourante = null; // { nom, region, lat, lon }

async function chargerFavoris() {
  if (!window.pywebview || !window.pywebview.api) return;
  favoris = await window.pywebview.api.get_favoris();
  render_favoris();
}

function render_favoris() {
  const row = document.getElementById('favorisRow');
  row.innerHTML = '';
  if (favoris.length === 0) {
    row.innerHTML = '<span class="favoris-empty" id="favorisEmpty">Aucune ville favorite pour l\'instant</span>';
    return;
  }
  favoris.forEach(f => {
    const chip = document.createElement('div');
    chip.className = 'favori-chip';
    chip.innerHTML = `<span>${f.nom}</span><span class="temp" data-fav-temp="${f.id}">…</span><button class="remove" data-remove="${f.id}">✕</button>`;
    chip.addEventListener('click', (e) => {
      if (e.target.closest('.remove')) return;
      afficherVille(f.nom, f.region, f.latitude, f.longitude);
    });
    row.appendChild(chip);
    chargerTempRapide(f.latitude, f.longitude).then(t => {
      const el = chip.querySelector('[data-fav-temp]');
      if (el && t !== null) el.textContent = Math.round(t) + '°';
    });
  });
  row.querySelectorAll('[data-remove]').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      await window.pywebview.api.remove_favori(parseInt(btn.dataset.remove));
      chargerFavoris();
    });
  });
}

async function chargerTempRapide(lat, lon) {
  try {
    const r = await fetch(`https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&current=temperature_2m`);
    const d = await r.json();
    return d.current ? d.current.temperature_2m : null;
  } catch { return null; }
}

// --- Carte de France ---
async function initCarte() {
  const svg = document.getElementById('franceMap');
  svg.innerHTML = '<text x="260" y="290" text-anchor="middle" fill="#7590b3" font-size="13">Chargement…</text>';

  const lats = REGIONS.map(r => r.lat).join(',');
  const lons = REGIONS.map(r => r.lon).join(',');

  let data;
  try {
    const r = await fetch(`https://api.open-meteo.com/v1/forecast?latitude=${lats}&longitude=${lons}&current=temperature_2m,weathercode`);
    data = await r.json();
    if (data && data.error) throw new Error(data.reason || 'Erreur API');
  } catch (err) {
    svg.innerHTML = `<text x="260" y="290" text-anchor="middle" fill="#7590b3" font-size="13">Impossible de charger la météo (vérifie ta connexion)</text>`;
    return;
  }
  const liste = Array.isArray(data) ? data : [data];
  svg.innerHTML = '';

  // Contour de fond (France + Corse)
  [CONTOUR_FRANCE, CONTOUR_CORSE].forEach(contour => {
    const points = contour.map(([lat, lon]) => {
      const p = projeter(lat, lon);
      return `${p.x},${p.y}`;
    }).join(' ');
    const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    poly.setAttribute('points', points);
    poly.setAttribute('class', 'france-outline');
    svg.appendChild(poly);
  });

  REGIONS.forEach((region, i) => {
    const infos = liste[i] || {};
    const temp = infos.current ? infos.current.temperature_2m : null;
    const { x, y } = projeter(region.lat, region.lon);
    const couleur = temp !== null ? couleurTemp(temp) : '#45566f';

    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');

    const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    dot.setAttribute('cx', x); dot.setAttribute('cy', y); dot.setAttribute('r', 14);
    dot.setAttribute('fill', couleur);
    dot.setAttribute('opacity', '0.85');
    dot.setAttribute('class', 'region-dot');
    dot.style.filter = `drop-shadow(0 0 8px ${couleur})`;
    dot.addEventListener('click', () => afficherVille(region.ville, region.nom, region.lat, region.lon));
    g.appendChild(dot);

    const tempText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    tempText.setAttribute('x', x); tempText.setAttribute('y', y + 4);
    tempText.setAttribute('text-anchor', 'middle');
    tempText.setAttribute('class', 'region-temp');
    tempText.textContent = temp !== null ? Math.round(temp) + '°' : '—';
    tempText.style.pointerEvents = 'none';
    g.appendChild(tempText);

    const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    label.setAttribute('x', x); label.setAttribute('y', y + 27);
    label.setAttribute('text-anchor', 'middle');
    label.setAttribute('class', 'region-label');
    label.textContent = region.ville;
    g.appendChild(label);

    svg.appendChild(g);
  });
}

// --- Recherche de ville ---
let rechercheTimeout = null;
const searchInput = document.getElementById('citySearch');
const searchResults = document.getElementById('searchResults');

searchInput.addEventListener('input', () => {
  clearTimeout(rechercheTimeout);
  const q = searchInput.value.trim();
  if (q.length < 2) { searchResults.classList.add('hidden'); return; }
  rechercheTimeout = setTimeout(() => rechercherVille(q), 400);
});

document.addEventListener('click', (e) => {
  if (!e.target.closest('.meteo-search')) searchResults.classList.add('hidden');
});

async function rechercherVille(q) {
  try {
    const r = await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(q)}&count=6&language=fr&format=json`);
    const d = await r.json();
    const items = d.results || [];
    searchResults.innerHTML = '';
    if (items.length === 0) {
      searchResults.innerHTML = '<div class="search-result-empty">Aucun résultat</div>';
    } else {
      items.forEach(it => {
        const div = document.createElement('div');
        div.className = 'search-result-item';
        const sousTitre = [it.admin1, it.country].filter(Boolean).join(', ');
        div.innerHTML = `<div>${it.name}</div><div class="sub">${sousTitre}</div>`;
        div.addEventListener('click', () => {
          afficherVille(it.name, sousTitre, it.latitude, it.longitude);
          searchResults.classList.add('hidden');
          searchInput.value = '';
        });
        searchResults.appendChild(div);
      });
    }
    searchResults.classList.remove('hidden');
  } catch {
    searchResults.innerHTML = '<div class="search-result-empty">Erreur de recherche</div>';
    searchResults.classList.remove('hidden');
  }
}

// --- Panneau de détail ---
async function afficherVille(nom, region, lat, lon) {
  villeCourante = { nom, region, lat, lon };
  document.getElementById('detailEmpty').classList.add('hidden');
  document.getElementById('detailContent').classList.remove('hidden');
  document.getElementById('detailCity').textContent = nom;
  document.getElementById('detailRegion').textContent = region || '';
  document.getElementById('detailTemp').textContent = '…';
  document.getElementById('detailDesc').textContent = '';
  document.getElementById('forecastStrip').innerHTML = '';

  const estFavori = favoris.some(f => f.nom === nom && Math.abs(f.latitude - lat) < 0.01 && Math.abs(f.longitude - lon) < 0.01);
  const favBtn = document.getElementById('favBtn');
  favBtn.classList.toggle('active', estFavori);

  try {
    const r = await fetch(`https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&current=temperature_2m,weathercode&daily=temperature_2m_max,temperature_2m_min,weathercode&timezone=auto&forecast_days=7`);
    const d = await r.json();

    document.getElementById('detailTemp').textContent = Math.round(d.current.temperature_2m) + '°C';
    document.getElementById('detailDesc').textContent = WEATHER_LABELS[d.current.weathercode] || '';

    const strip = document.getElementById('forecastStrip');
    d.daily.time.forEach((date, i) => {
      const jour = new Date(date).toLocaleDateString('fr-FR', { weekday: 'short' });
      const code = d.daily.weathercode[i];
      const card = document.createElement('div');
      card.className = 'forecast-day';
      card.innerHTML = `
        <div class="day-name">${jour}</div>
        <div class="day-icon">${WEATHER_ICONS[code] || '—'}</div>
        <div class="day-max">${Math.round(d.daily.temperature_2m_max[i])}°</div>
        <div class="day-min">${Math.round(d.daily.temperature_2m_min[i])}°</div>
      `;
      strip.appendChild(card);
    });
  } catch {
    document.getElementById('detailDesc').textContent = 'Impossible de charger la météo';
  }
}

document.getElementById('favBtn').addEventListener('click', async () => {
  if (!villeCourante) return;
  const favBtn = document.getElementById('favBtn');
  const estFavori = favoris.some(f => f.nom === villeCourante.nom && Math.abs(f.latitude - villeCourante.lat) < 0.01);
  if (estFavori) {
    const f = favoris.find(f => f.nom === villeCourante.nom && Math.abs(f.latitude - villeCourante.lat) < 0.01);
    await window.pywebview.api.remove_favori(f.id);
  } else {
    await window.pywebview.api.add_favori(villeCourante.nom, villeCourante.region, 'France', villeCourante.lat, villeCourante.lon);
  }
  favBtn.classList.toggle('active');
  chargerFavoris();
});

// --- Initialisation à l'ouverture de l'onglet ---
document.addEventListener('tab:opened', (e) => {
  if (e.detail !== 'meteo' || meteoInitialisee) return;
  meteoInitialisee = true;
  chargerFavoris();
  initCarte();
});
