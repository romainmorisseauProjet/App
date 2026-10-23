"""
Module ISS (Station Spatiale Internationale).

Position en direct, trajectoire, équipage à bord, et prédiction des
prochains passages VISIBLES au-dessus d'un lieu. Données gratuites, sans clé
API : wheretheiss.at (position + éléments orbitaux) et Open Notify (équipage).
Isolé dans ce fichier, comme les autres modules.
"""

import math
import time
from datetime import datetime, timezone

import requests

API = "https://api.wheretheiss.at/v1"
ID_ISS = 25544
ENTETES = {"User-Agent": "AssistantPerso/1.0"}

R_TERRE = 6378.137          # rayon équatorial (km)
F_TERRE = 1 / 298.257223563  # aplatissement WGS84

# Cache du TLE (éléments orbitaux) : il ne change que toutes les quelques heures.
_cache_tle = {"valeur": None, "t": 0}
# Cache des passages calculés : clé = (lat, lon arrondis)
_cache_passages = {}


# ---------------------------------------------------------------- données live

def position_actuelle():
    """Position et télémétrie de l'ISS à l'instant présent."""
    try:
        r = requests.get(f"{API}/satellites/{ID_ISS}", headers=ENTETES, timeout=8)
        r.raise_for_status()
        d = r.json()
        return {"ok": True, **{k: d.get(k) for k in (
            "latitude", "longitude", "altitude", "velocity", "visibility",
            "footprint", "solar_lat", "solar_lon", "timestamp")}}
    except Exception as e:
        return {"ok": False, "message": f"Position indisponible : {e}"}


def pays_survole(latitude, longitude):
    """Code pays (ISO) survolé, ou None au-dessus de l'océan."""
    try:
        r = requests.get(f"{API}/coordinates/{latitude},{longitude}", headers=ENTETES, timeout=6)
        r.raise_for_status()
        code = r.json().get("country_code")
        return None if code in (None, "", "??") else code
    except Exception:
        return None


def trace_orbite(minutes_avant=45, minutes_apres=135, pas_minutes=4):
    """Points (lat, lon) de la trajectoire autour de l'instant présent,
    en séparant le passé du futur. L'API accepte 10 horodatages par requête."""
    maintenant = int(time.time())
    horodatages = list(range(maintenant - minutes_avant * 60,
                             maintenant + minutes_apres * 60 + 1, pas_minutes * 60))
    points = []
    try:
        for i in range(0, len(horodatages), 10):
            lot = horodatages[i:i + 10]
            r = requests.get(
                f"{API}/satellites/{ID_ISS}/positions",
                params={"timestamps": ",".join(map(str, lot)), "units": "kilometers"},
                headers=ENTETES, timeout=10,
            )
            r.raise_for_status()
            for p in r.json():
                points.append({"t": p["timestamp"], "lat": p["latitude"], "lon": p["longitude"]})
            time.sleep(1.0)  # l'API demande de rester sous ~1 requête/seconde
    except Exception as e:
        return {"ok": False, "points": [], "message": f"Trajectoire indisponible : {e}"}
    return {"ok": True, "points": points, "maintenant": maintenant}


def equipage():
    """Humains actuellement dans l'espace (Open Notify). Liste vide si indisponible."""
    try:
        r = requests.get("http://api.open-notify.org/astros.json", headers=ENTETES, timeout=6)
        r.raise_for_status()
        gens = r.json().get("people", [])
        return {"ok": True, "total": len(gens), "personnes": gens}
    except Exception:
        return {"ok": False, "total": 0, "personnes": []}


# ------------------------------------------------------- prédiction de passages

def _tle():
    """Éléments orbitaux de l'ISS (mis en cache 3 h)."""
    if _cache_tle["valeur"] and time.time() - _cache_tle["t"] < 3 * 3600:
        return _cache_tle["valeur"]
    r = requests.get(f"{API}/satellites/{ID_ISS}/tles", headers=ENTETES, timeout=8)
    r.raise_for_status()
    d = r.json()
    _cache_tle["valeur"] = (d["line1"], d["line2"])
    _cache_tle["t"] = time.time()
    return _cache_tle["valeur"]


def _jd_depuis_unix(ts):
    return ts / 86400.0 + 2440587.5


def _position_soleil_eci(jd):
    """Vecteur unitaire Terre→Soleil (formule astronomique basse précision,
    ~0,01° : largement suffisant pour savoir s'il fait nuit)."""
    n = jd - 2451545.0
    L = math.radians((280.460 + 0.9856474 * n) % 360)
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = L + math.radians(1.915) * math.sin(g) + math.radians(0.020) * math.sin(2 * g)
    eps = math.radians(23.439 - 0.0000004 * n)
    return (math.cos(lam), math.cos(eps) * math.sin(lam), math.sin(eps) * math.sin(lam))


def _gmst(jd):
    return math.radians((280.46061837 + 360.98564736629 * (jd - 2451545.0)) % 360)


def _eci_vers_ecef(v, theta):
    c, s = math.cos(theta), math.sin(theta)
    return (v[0] * c + v[1] * s, -v[0] * s + v[1] * c, v[2])


def _observateur(lat_deg, lon_deg, alt_km=0.0):
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    e2 = F_TERRE * (2 - F_TERRE)
    N = R_TERRE / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    pos = ((N + alt_km) * math.cos(lat) * math.cos(lon),
           (N + alt_km) * math.cos(lat) * math.sin(lon),
           (N * (1 - e2) + alt_km) * math.sin(lat))
    est = (-math.sin(lon), math.cos(lon), 0.0)
    nord = (-math.sin(lat) * math.cos(lon), -math.sin(lat) * math.sin(lon), math.cos(lat))
    haut = (math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat))
    return pos, est, nord, haut


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _point_cardinal(azimut_deg):
    noms = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]
    return noms[int((azimut_deg + 22.5) // 45) % 8]


def calculer_passages(tle, lat_deg, lon_deg, debut_unix, jours=4, nb_max=6,
                      elevation_min=10.0, soleil_max=-6.0):
    """Passages VISIBLES de l'ISS : au-dessus de `elevation_min` degrés,
    éclairée par le Soleil, pendant que le ciel de l'observateur est assez
    sombre (Soleil à moins de `soleil_max` degrés sous l'horizon).
    Renvoie une liste de dicts (début, durée, élévation max, directions)."""
    from sgp4.api import Satrec

    sat = Satrec.twoline2rv(tle[0], tle[1])
    obs_pos, est, nord, haut = _observateur(lat_deg, lon_deg)

    pas = 15  # secondes
    passages, courant = [], None

    for i in range(int(jours * 86400 / pas)):
        ts = debut_unix + i * pas
        jd = _jd_depuis_unix(ts)
        jd_ent = math.floor(jd - 0.5) + 0.5
        err, r_eci, _v = sat.sgp4(jd_ent, jd - jd_ent)
        if err != 0:
            continue

        theta = _gmst(jd)
        r_ecef = _eci_vers_ecef(r_eci, theta)
        rho = (r_ecef[0] - obs_pos[0], r_ecef[1] - obs_pos[1], r_ecef[2] - obs_pos[2])
        dist = math.sqrt(_dot(rho, rho))
        elevation = math.degrees(math.asin(_dot(rho, haut) / dist))

        visible = False
        if elevation >= elevation_min:
            s_eci = _position_soleil_eci(jd)
            s_ecef = _eci_vers_ecef(s_eci, theta)
            soleil_alt = math.degrees(math.asin(_dot(s_ecef, haut)))
            # ISS éclairée ? (ombre cylindrique de la Terre)
            proj = _dot(r_eci, s_eci)
            dans_ombre = proj < 0 and math.sqrt(max(0.0, _dot(r_eci, r_eci) - proj ** 2)) < R_TERRE
            visible = (soleil_alt <= soleil_max) and not dans_ombre

        if visible:
            azimut = math.degrees(math.atan2(_dot(rho, est), _dot(rho, nord))) % 360
            if courant is None:
                courant = {"debut": ts, "fin": ts, "max_el": elevation, "az_debut": azimut,
                           "az_max": azimut, "az_fin": azimut}
            else:
                courant["fin"] = ts
                courant["az_fin"] = azimut
                if elevation > courant["max_el"]:
                    courant["max_el"] = elevation
                    courant["az_max"] = azimut
        elif courant is not None:
            passages.append(courant)
            courant = None
            if len(passages) >= nb_max:
                break
    if courant is not None and len(passages) < nb_max:
        passages.append(courant)

    return [{
        "debut": p["debut"],
        "duree_s": p["fin"] - p["debut"] + pas,
        "elevation_max": round(p["max_el"]),
        "depart": _point_cardinal(p["az_debut"]),
        "culmine": _point_cardinal(p["az_max"]),
        "arrivee": _point_cardinal(p["az_fin"]),
    } for p in passages]


def prochains_passages(latitude, longitude):
    """Prochains passages visibles pour un lieu (mis en cache 30 min)."""
    cle = (round(latitude, 2), round(longitude, 2))
    en_cache = _cache_passages.get(cle)
    if en_cache and time.time() - en_cache["t"] < 1800:
        return en_cache["resultat"]
    try:
        tle = _tle()
        passages = calculer_passages(tle, latitude, longitude, int(time.time()))
        resultat = {"ok": True, "passages": passages}
    except Exception as e:
        resultat = {"ok": False, "passages": [], "message": f"Calcul impossible : {e}"}
    if resultat["ok"]:
        _cache_passages[cle] = {"t": time.time(), "resultat": resultat}
    return resultat
