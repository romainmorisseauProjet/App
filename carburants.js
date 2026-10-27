// --- Module Carburants ---

let carbLieuChoisi = null;   // { nom, lat, lon } une fois une ville sélectionnée
let carbTimeoutSuggestions = null;

const carbInput = document.getElementById('carbRecherche');
const carbSuggestions = document.getElementById('carbSuggestions');
const carbTypeSelect = document.getElementById('carbType');
const carbRayonSelect = document.getElementById('carbRayon');

// --- Suggestions de villes pendant la frappe (même service que la météo,
// limité à la France) ---
carbInput.addEventListener('input', () => {
  clearTimeout(carbTimeoutSuggestions);
  // Dès qu'on retape, l'ancien choix n'est plus valable
  carbLieuChoisi = null;
  const q = carbInput.value.trim();
  if (q.length < 2) { carbSuggestions.classList.add('hidden'); return; }
  carbTimeoutSuggestions = setTimeout(() => carbChercherVilles(q), 350);
});

document.addEventListener('click', (e) => {
  if (!e.target.closest('.carb-search')) carbSuggestions.classList.add('hidden');
});

async function carbChercherVilles(q) {
  try {
    const r = await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(q)}&count=6&language=fr&format=json&countryCode=FR`);
    const d = await r.json();
    const villes = d.results || [];
    carbSuggestions.innerHTML = '';

    if (villes.length === 0) {
      carbSuggestions.innerHTML = '<div class="carb-suggestion-vide">Aucune ville trouvée</div>';
    } else {
      villes.forEach(v => {
        const div = document.createElement('div');
        div.className = 'carb-suggestion';
        const sousTitre = [v.admin2, v.admin1].filter(Boolean).join(', ');
        div.innerHTML = `<div>${v.name}</div><div class="sub">${sousTitre}</div>`;
        div.addEventListener('click', () => {
          carbLieuChoisi = { nom: v.name, lat: v.latitude, lon: v.longitude };
          carbInput.value = v.name;
          carbSuggestions.classList.add('hidden');
          carbChercherStations();
        });
        carbSuggestions.appendChild(div);
      });
    }
    carbSuggestions.classList.remove('hidden');
  } catch (e) {
    carbSuggestions.innerHTML = '<div class="carb-suggestion-vide">Erreur de recherche (connexion ?)</div>';
    carbSuggestions.classList.remove('hidden');
  }
}

// --- Âge du prix, affiché de façon lisible ("il y a 3 h") ---
function carbAgePrix(dateBrute) {
  if (!dateBrute) return '';
  const d = new Date(dateBrute);
  if (isNaN(d)) return '';
  const minutes = Math.round((Date.now() - d.getTime()) / 60000);
  if (minutes < 60) return `il y a ${Math.max(minutes, 1)} min`;
  const heures = Math.round(minutes / 60);
  if (heures < 24) return `il y a ${heures} h`;
  return `il y a ${Math.round(heures / 24)} j`;
}

// --- Recherche des stations autour de la ville choisie ---
async function carbChercherStations() {
  if (!carbLieuChoisi) return;

  const liste = document.getElementById('carbListe');
  const lieu = document.getElementById('carbLieu');
  const type = carbTypeSelect.value;
  const rayon = parseInt(carbRayonSelect.value);

  lieu.textContent = `Stations autour de ${carbLieuChoisi.nom} (${rayon} km)`;
  liste.innerHTML = '<div class="carb-empty">Recherche en cours…</div>';

  try {
    const res = await window.pywebview.api.get_stations_carburant(
      carbLieuChoisi.lat, carbLieuChoisi.lon, type, rayon
    );

    if (!res.ok) {
      liste.innerHTML = `<div class="carb-empty erreur">${res.message}</div>`;
      return;
    }
    if (res.stations.length === 0) {
      liste.innerHTML = '<div class="carb-empty">Aucune station avec ce carburant dans ce rayon. Essaie un rayon plus grand.</div>';
      return;
    }

    liste.innerHTML = '';
    res.stations.forEach((station, index) => {
      const carte = document.createElement('div');
      carte.className = 'carb-station' + (index === 0 ? ' moins-cher' : '');
      carte.title = "Ouvrir dans Google Maps";
      const age = carbAgePrix(station.maj);
      carte.innerHTML = `
        <div class="carb-station-infos">
          <div class="carb-station-adresse">${station.adresse || 'Adresse inconnue'}</div>
          <div class="carb-station-detail">${station.cp || ''} ${station.ville || ''} · ${station.distance_km} km</div>
        </div>
        <div class="carb-station-droite">
          <div class="carb-station-prix">${station.prix.toFixed(3)} €</div>
          ${age ? `<div class="carb-station-age">${age}</div>` : ''}
        </div>
      `;
      carte.addEventListener('click', () => {
        window.pywebview.api.ouvrir_lien(
          `https://www.google.com/maps/search/?api=1&query=${station.latitude},${station.longitude}`
        );
      });
      liste.appendChild(carte);
    });
  } catch (e) {
    liste.innerHTML = '<div class="carb-empty erreur">Erreur lors de la recherche.</div>';
  }
}

// Changer de carburant ou de rayon relance la recherche si une ville est choisie
carbTypeSelect.addEventListener('change', carbChercherStations);
carbRayonSelect.addEventListener('change', carbChercherStations);
