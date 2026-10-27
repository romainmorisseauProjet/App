// --- Module Domotique ---
// Les appareils sont mémorisés en base (data/assistant.db, table
// domotique_appareils) via main.py. Pour l'instant l'allumage/extinction
// et les réglages sont simulés localement : c'est une base propre sur
// laquelle brancher plus tard un vrai protocole par type d'appareil
// (Tuya, Philips Hue, MQTT/Zigbee2MQTT…) dans main.py sans toucher à
// cette interface.

const DOMO_TYPES = {
  lampe: {
    label: 'Lampe',
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.2 1 2.05V17h6v-.25c0-.85.4-1.55 1-2.05A7 7 0 0 0 12 2z"/></svg>',
    slider: { min: 1, max: 100, unit: '%', label: 'Luminosité' },
  },
  prise: {
    label: 'Prise connectée',
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 2v4"/><path d="M15 2v4"/><path d="M7 6h10v4a5 5 0 0 1-10 0V6z"/><path d="M12 15v7"/></svg>',
    slider: null,
  },
  thermostat: {
    label: 'Thermostat',
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 14.76V4a2 2 0 0 0-4 0v10.76a4 4 0 1 0 4 0z"/></svg>',
    slider: { min: 10, max: 30, unit: '°C', label: 'Température' },
  },
  volet: {
    label: 'Volet roulant',
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="1.5"/><line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="14" x2="20" y2="14"/></svg>',
    slider: { min: 0, max: 100, unit: '%', label: 'Ouverture' },
  },
  autre: {
    label: 'Autre',
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="12" cy="12" r="3"/></svg>',
    slider: null,
  },
};

let domoAppareils = [];
let domoInitialisee = false;

function domoTypeConfig(type) {
  return DOMO_TYPES[type] || DOMO_TYPES.autre;
}

async function chargerAppareils() {
  if (!window.pywebview || !window.pywebview.api) {
    setTimeout(chargerAppareils, 200);
    return;
  }
  domoAppareils = await window.pywebview.api.get_appareils();
  render_domoGrid();
}

function render_domoGrid() {
  const grid = document.getElementById('domoGrid');
  grid.innerHTML = '';

  if (domoAppareils.length === 0) {
    grid.innerHTML = '<div class="domo-empty" id="domoEmpty">Aucun appareil pour l\'instant — ajoute ta première lampe ou prise connectée.</div>';
    return;
  }

  domoAppareils.forEach(a => grid.appendChild(creer_carteAppareil(a)));
}

function creer_carteAppareil(appareil) {
  const cfg = domoTypeConfig(appareil.type);
  const allume = !!appareil.etat;

  const card = document.createElement('div');
  card.className = `domo-card${allume ? ' on' : ''}`;
  card.dataset.id = appareil.id;

  let sliderHtml = '';
  if (cfg.slider) {
    sliderHtml = `
      <div class="domo-slider-row">
        <div class="domo-slider-labels">
          <span>${cfg.slider.label}</span>
          <span data-slider-value>${appareil.valeur}${cfg.slider.unit}</span>
        </div>
        <input type="range" min="${cfg.slider.min}" max="${cfg.slider.max}" value="${appareil.valeur}"
               data-slider ${allume ? '' : 'disabled'}>
      </div>`;
  }

  card.innerHTML = `
    <div class="domo-card-top">
      <div class="domo-card-icon">${cfg.icon}</div>
      <button class="domo-remove" data-remove aria-label="Supprimer l'appareil" type="button">✕</button>
    </div>
    <div>
      <div class="domo-card-name">${escapeHtml(appareil.nom)}</div>
      <div class="domo-card-room">${escapeHtml(appareil.piece) || cfg.label}</div>
    </div>
    ${sliderHtml}
    <div class="domo-card-control">
      <span class="domo-state-label" data-state-label>${allume ? 'Allumé' : 'Éteint'}</span>
      <label class="domo-switch">
        <input type="checkbox" data-toggle ${allume ? 'checked' : ''}>
        <span class="domo-switch-track"><span class="domo-switch-thumb"></span></span>
      </label>
    </div>
  `;

  // Interrupteur
  card.querySelector('[data-toggle]').addEventListener('change', async (e) => {
    const resultat = await window.pywebview.api.toggle_appareil(appareil.id);
    if (!resultat || !resultat.ok) return;
    appareil.etat = resultat.etat;
    const on = !!appareil.etat;
    card.classList.toggle('on', on);
    card.querySelector('[data-state-label]').textContent = on ? 'Allumé' : 'Éteint';
    const slider = card.querySelector('[data-slider]');
    if (slider) slider.disabled = !on;
  });

  // Curseur (luminosité / température / ouverture)
  const slider = card.querySelector('[data-slider]');
  if (slider) {
    let debounce = null;
    slider.addEventListener('input', () => {
      card.querySelector('[data-slider-value]').textContent = `${slider.value}${cfg.slider.unit}`;
    });
    slider.addEventListener('change', () => {
      clearTimeout(debounce);
      debounce = setTimeout(async () => {
        const valeur = parseInt(slider.value, 10);
        await window.pywebview.api.set_valeur_appareil(appareil.id, valeur);
        appareil.valeur = valeur;
        appareil.etat = 1;
        card.classList.add('on');
        card.querySelector('[data-state-label]').textContent = 'Allumé';
        card.querySelector('[data-toggle]').checked = true;
        slider.disabled = false;
      }, 150);
    });
  }

  // Suppression
  card.querySelector('[data-remove]').addEventListener('click', async () => {
    await window.pywebview.api.remove_appareil(appareil.id);
    domoAppareils = domoAppareils.filter(a => a.id !== appareil.id);
    render_domoGrid();
  });

  return card;
}

function escapeHtml(texte) {
  const div = document.createElement('div');
  div.textContent = texte || '';
  return div.innerHTML;
}

// --- Modale d'ajout ---
const domoModalBackdrop = document.getElementById('domoModalBackdrop');
const domoNomInput = document.getElementById('domoNomInput');
const domoTypeInput = document.getElementById('domoTypeInput');
const domoPieceInput = document.getElementById('domoPieceInput');
const domoModalError = document.getElementById('domoModalError');

function ouvrir_domoModal() {
  domoNomInput.value = '';
  domoTypeInput.value = 'lampe';
  domoPieceInput.value = '';
  domoModalError.classList.add('hidden');
  domoModalBackdrop.classList.remove('hidden');
  domoNomInput.focus();
}

function fermer_domoModal() {
  domoModalBackdrop.classList.add('hidden');
}

document.getElementById('domoAddBtn').addEventListener('click', ouvrir_domoModal);
document.getElementById('domoCancelBtn').addEventListener('click', fermer_domoModal);
domoModalBackdrop.addEventListener('click', (e) => {
  if (e.target === domoModalBackdrop) fermer_domoModal();
});

document.getElementById('domoConfirmBtn').addEventListener('click', async () => {
  const nom = domoNomInput.value.trim();
  if (!nom) {
    domoModalError.textContent = 'Donne un nom à l\'appareil.';
    domoModalError.classList.remove('hidden');
    return;
  }
  const resultat = await window.pywebview.api.add_appareil(
    nom, domoTypeInput.value, domoPieceInput.value.trim()
  );
  if (!resultat || !resultat.ok) {
    domoModalError.textContent = (resultat && resultat.message) || 'Impossible d\'ajouter cet appareil.';
    domoModalError.classList.remove('hidden');
    return;
  }
  domoAppareils.push(resultat.appareil);
  render_domoGrid();
  fermer_domoModal();
});

domoNomInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') document.getElementById('domoConfirmBtn').click();
});

// Chargement au premier passage sur l'onglet Domotique
document.addEventListener('tab:opened', (e) => {
  if (e.detail === 'domotique' && !domoInitialisee) {
    domoInitialisee = true;
    const grid = document.getElementById('domoGrid');
    grid.innerHTML = '';
    grid.appendChild(creerBlocChargement('Chargement des appareils…'));
    chargerAppareils();
  }
});
