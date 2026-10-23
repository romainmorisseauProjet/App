"""
Module carburants.

Utilise l'open data officiel du Ministère de l'Économie (gratuit, pas de
clé API) pour trouver les stations-service les moins chères autour d'un
point (une ville choisie dans les suggestions). Isolé dans ce fichier,
comme les autres modules.
"""

import math
import requests

URL_RECORDS = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/prix-des-carburants-en-france-flux-instantane-v2/records"

CARBURANTS_VALIDES = {"gazole", "sp95", "sp98", "e10", "e85", "gplc"}


def _distance_km(lat1, lon1, lat2, lon2):
    """Distance à vol d'oiseau entre deux points (formule de haversine)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def rechercher_stations(latitude, longitude, carburant="gazole", rayon_km=10, limite=20):
    """Renvoie {"ok": bool, "stations": [...], "message": str}.
    Les stations sont triées du prix le moins cher au plus cher pour le
    carburant choisi, dans un rayon autour du point donné."""
    if carburant not in CARBURANTS_VALIDES:
        return {"ok": False, "stations": [], "message": "Carburant inconnu."}

    champ_prix = f"{carburant}_prix"
    champ_maj = f"{carburant}_maj"

    # L'API filtre par "boîte" rectangulaire ; on la calcule à partir du
    # rayon demandé, puis on affine avec la vraie distance ci-dessous.
    delta_lat = rayon_km / 111.0
    delta_lon = rayon_km / (111.0 * max(0.1, math.cos(math.radians(latitude))))
    lat_min, lat_max = latitude - delta_lat, latitude + delta_lat
    lon_min, lon_max = longitude - delta_lon, longitude + delta_lon

    parametres = {
        "where": f"in_bbox(geom, {lat_min}, {lon_min}, {lat_max}, {lon_max}) and {champ_prix} is not null",
        "order_by": f"{champ_prix} asc",
        "limit": 100,  # maximum autorisé par l'API
    }

    try:
        reponse = requests.get(URL_RECORDS, params=parametres, timeout=10)
        if reponse.status_code != 200:
            return {
                "ok": False,
                "stations": [],
                "message": f"L'API a répondu une erreur ({reponse.status_code}) : {reponse.text[:200]}",
            }
        donnees = reponse.json()
    except Exception as e:
        return {"ok": False, "stations": [], "message": f"Connexion impossible : {e}"}

    stations = []
    for enr in donnees.get("results", []):
        geom = enr.get("geom") or {}
        lat_s, lon_s = geom.get("lat"), geom.get("lon")
        prix = enr.get(champ_prix)
        if lat_s is None or lon_s is None or prix in (None, ""):
            continue
        try:
            prix = float(prix)
        except (TypeError, ValueError):
            continue

        distance = _distance_km(latitude, longitude, lat_s, lon_s)
        if distance > rayon_km:
            continue

        stations.append({
            "adresse": enr.get("adresse", ""),
            "ville": enr.get("ville", ""),
            "cp": enr.get("cp", ""),
            "prix": round(prix, 3),
            "maj": enr.get(champ_maj) or "",
            "distance_km": round(distance, 1),
            "latitude": lat_s,
            "longitude": lon_s,
        })

    stations.sort(key=lambda s: (s["prix"], s["distance_km"]))
    return {"ok": True, "stations": stations[:limite], "message": ""}
