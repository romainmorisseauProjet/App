"""
Module actualités.

Récupère les news par catégorie via des flux RSS publics (gratuit, pas de
clé API, pas besoin d'IA). Pour chaque catégorie, on interroge PLUSIEURS
sources en parallèle, on fusionne, on retire les doublons et on trie du plus
récent au plus ancien : même si un flux est en panne ou publie rarement,
les autres compensent. Isolé dans ce fichier, comme les autres modules.
"""

import re
import time
from calendar import timegm
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import feedparser
import requests

# Chaque catégorie = une liste de (nom de la source, URL du flux RSS).
# Si une URL ne répond plus, elle est simplement ignorée.
FLUX_PAR_CATEGORIE = {
    "politique_france": [
        ("Franceinfo", "https://www.francetvinfo.fr/politique.rss"),
        ("Le Monde", "https://www.lemonde.fr/politique/rss_full.xml"),
        ("Brut", "https://www.brut.media/rss/fr/france.xml"),
    ],
    "international": [
        ("Franceinfo", "https://www.francetvinfo.fr/monde.rss"),
        ("Le Monde", "https://www.lemonde.fr/international/rss_full.xml"),
        ("Brut", "https://www.brut.media/rss/fr/international.xml"),
    ],
    "faits_divers": [
        ("Franceinfo", "https://www.francetvinfo.fr/faits-divers.rss"),
    ],
    "technologie": [
        ("Le Monde", "https://www.lemonde.fr/pixels/rss_full.xml"),
        ("Brut", "https://www.brut.media/rss/fr/sciences-technologies.xml"),
    ],
    "economie": [
        ("Franceinfo", "https://www.francetvinfo.fr/economie.rss"),
        ("Le Monde", "https://www.lemonde.fr/economie/rss_full.xml"),
        ("Brut", "https://www.brut.media/rss/fr/economie.xml"),
    ],
    "sport": [
        ("Franceinfo", "https://www.francetvinfo.fr/sports.rss"),
        ("Le Monde", "https://www.lemonde.fr/sport/rss_full.xml"),
        ("Brut", "https://www.brut.media/rss/fr/sport.xml"),
    ],
    "culture": [
        ("Franceinfo", "https://www.francetvinfo.fr/culture.rss"),
        ("Le Monde", "https://www.lemonde.fr/culture/rss_full.xml"),
    ],
    "sante": [
        ("Franceinfo", "https://www.francetvinfo.fr/sante.rss"),
        ("Le Monde", "https://www.lemonde.fr/sante/rss_full.xml"),
        ("Brut", "https://www.brut.media/rss/fr/sante.xml"),
    ],
    "environnement": [
        ("Le Monde", "https://www.lemonde.fr/planete/rss_full.xml"),
        ("Brut", "https://www.brut.media/rss/fr/environnement.xml"),
    ],
}

# En-têtes qui demandent explicitement un contenu frais (pas de cache
# intermédiaire) + un vrai User-Agent, certains sites refusent les requêtes anonymes.
ENTETES = {
    "User-Agent": "Mozilla/5.0 (compatible; AssistantPerso/1.0)",
    "Cache-Control": "no-cache, no-store, max-age=0",
    "Pragma": "no-cache",
}


def _nettoyer_html(texte):
    if not texte:
        return ""
    texte = re.sub(r"<[^>]+>", "", texte)
    texte = re.sub(r"\s+", " ", texte)
    return texte.strip()


def _timestamp(entree):
    """Date de publication en secondes (UTC), ou None si le flux n'en donne pas."""
    for champ in ("published_parsed", "updated_parsed"):
        valeur = entree.get(champ)
        if valeur:
            try:
                return timegm(valeur)
            except (TypeError, ValueError, OverflowError):
                pass
    return None


def _lire_flux(source, url):
    """Télécharge un flux et renvoie la liste de ses articles. Liste vide en cas d'échec."""
    try:
        # Le paramètre "_" change à chaque appel : il empêche un cache (CDN,
        # proxy) de nous resservir une ancienne version du flux.
        reponse = requests.get(url, headers=ENTETES, params={"_": int(time.time())}, timeout=8)
        reponse.raise_for_status()
        flux = feedparser.parse(reponse.content)
    except Exception:
        return []

    articles = []
    for entree in flux.entries:
        ts = _timestamp(entree)
        articles.append({
            "titre": _nettoyer_html(entree.get("title", "")) or "(sans titre)",
            "resume": _nettoyer_html(entree.get("summary", "")),
            "lien": entree.get("link", ""),
            "timestamp": ts,
            "date": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else "",
            "source": source,
        })
    return articles


def recuperer_articles(categorie, limite=15):
    """Articles les plus récents de la catégorie, toutes sources confondues."""
    sources = FLUX_PAR_CATEGORIE.get(categorie)
    if not sources:
        return []

    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        resultats = list(pool.map(lambda s: _lire_flux(s[0], s[1]), sources))

    fusion, vus = [], set()
    for liste in resultats:
        for article in liste:
            cle = article["lien"] or article["titre"]
            if cle in vus:
                continue
            vus.add(cle)
            fusion.append(article)

    # Plus récent d'abord ; les articles sans date passent en dernier.
    fusion.sort(key=lambda a: a["timestamp"] or 0, reverse=True)
    for a in fusion:
        a.pop("timestamp", None)
    return fusion[:limite]
