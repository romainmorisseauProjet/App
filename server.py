"""
Serveur web de MON_IA.

Remplace la fenêtre pywebview : l'interface (dossier ui/) est servie en HTTP
et chaque appel JavaScript `window.pywebview.api.methode(...)` devient une
requête `POST /api/methode` (voir ui/bridge.js) que ce fichier redirige vers
la méthode du même nom de la classe Api (main.py).

Lancement local :   APP_PASSWORD=monmotdepasse python server.py
Lancement Render :  gunicorn server:app --workers 1 --threads 4 --timeout 120

Variables d'environnement :
  APP_PASSWORD  (obligatoire) mot de passe pour entrer dans l'appli
  SECRET_KEY    (conseillé)   chaîne aléatoire longue, signe les cookies de session
  DATA_DIR      (conseillé)   dossier des données ; sur Render, le point de montage du disque
"""

import hmac
import io
import os
import secrets
import shutil
import time
import zipfile

from flask import (
    Flask, abort, jsonify, redirect, request, send_file,
    send_from_directory, session,
)
from werkzeug.middleware.proxy_fix import ProxyFix

import main

app = Flask(__name__, static_folder=None)
# Render place l'appli derrière un proxy HTTPS : on lit la vraie IP et le vrai schéma.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),  # HTTPS uniquement en ligne
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,          # reste connecté 30 jours
    MAX_CONTENT_LENGTH=60 * 1024 * 1024,                    # 60 Mo max par requête
)

APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

# Mode local : activé par lancer.py (fenêtre de bureau) ou par « python server.py »
# sans mot de passe. Le serveur n'écoute alors que sur 127.0.0.1 (ton PC), donc
# aucun mot de passe n'est demandé. En ligne (gunicorn / Render), ce mode n'existe
# pas : sans APP_PASSWORD, l'accès reste bloqué.
LOCAL = os.environ.get("MON_IA_LOCAL") == "1" and not os.environ.get("RENDER")
if not LOCAL:
    if not APP_PASSWORD:
        print("ATTENTION : APP_PASSWORD absent, l'acces est BLOQUE tant que tu ne l'as pas defini.")
    if not os.environ.get("SECRET_KEY"):
        print("ATTENTION : SECRET_KEY absente, tu seras deconnecte a chaque redemarrage du serveur.")

main.init_db()
for dossier in (main.UPLOADS_DIR, main.CONVERSIONS_DIR, main.MUSIQUE_DIR):
    os.makedirs(dossier, exist_ok=True)

api = main.Api()

# Méthodes appelables depuis le navigateur : toutes les méthodes publiques de Api.
METHODES = {
    nom for nom in dir(api)
    if not nom.startswith("_") and callable(getattr(api, nom))
}


# --------------------------------------------------------------------------
# Authentification
# --------------------------------------------------------------------------

_echecs = {}  # ip -> (nombre d'échecs, instant du dernier échec)
MAX_ECHECS = 5
BLOCAGE_SECONDES = 300


def _bloque(ip):
    nb, dernier = _echecs.get(ip, (0, 0))
    if nb >= MAX_ECHECS and time.time() - dernier < BLOCAGE_SECONDES:
        return True
    if nb >= MAX_ECHECS:
        _echecs.pop(ip, None)
    return False


PAGE_LOGIN = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Assistant — Connexion</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       background:#050810;color:#cfe3ff;font-family:system-ui,Segoe UI,sans-serif}
  form{width:min(92vw,360px);padding:32px 28px;border:1px solid #1d4ed8;border-radius:14px;
       background:rgba(10,16,32,.85);box-shadow:0 0 28px rgba(37,99,235,.35)}
  h1{margin:0 0 6px;font-size:1.25rem;letter-spacing:.12em;text-transform:uppercase;
     color:#7db4ff;text-shadow:0 0 12px rgba(80,150,255,.7)}
  p{margin:0 0 20px;font-size:.85rem;color:#7f93b5}
  input{width:100%;padding:12px 14px;border-radius:8px;border:1px solid #1e3a8a;
        background:#050a18;color:#e6f0ff;font-size:1rem;outline:none}
  input:focus{border-color:#3b82f6;box-shadow:0 0 10px rgba(59,130,246,.5)}
  button{width:100%;margin-top:14px;padding:12px;border:0;border-radius:8px;cursor:pointer;
         background:#2563eb;color:#fff;font-size:1rem;font-weight:600}
  button:hover{background:#3b82f6}
  .err{margin-top:12px;color:#ff7b7b;font-size:.85rem;min-height:1.2em}
</style></head><body>
<form method="post" action="/login">
  <h1>Assistant</h1><p>Accès privé</p>
  <input type="password" name="mot_de_passe" placeholder="Mot de passe" autofocus required>
  <button type="submit">Entrer</button>
  <div class="err">__ERREUR__</div>
</form></body></html>"""


def _page_login(erreur="", code=200):
    return PAGE_LOGIN.replace("__ERREUR__", erreur), code


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return _page_login()

    ip = request.remote_addr or "?"
    if not APP_PASSWORD:
        return _page_login("Serveur non configuré : APP_PASSWORD manquant.", 503)
    if _bloque(ip):
        return _page_login("Trop d'essais. Réessaie dans quelques minutes.", 429)

    saisi = request.form.get("mot_de_passe", "")
    if hmac.compare_digest(saisi.encode(), APP_PASSWORD.encode()):
        _echecs.pop(ip, None)
        session.clear()
        session["ok"] = True
        session.permanent = True
        return redirect("/")

    nb, _ = _echecs.get(ip, (0, 0))
    _echecs[ip] = (nb + 1, time.time())
    time.sleep(1)  # ralentit les essais en rafale
    return _page_login("Mot de passe incorrect.", 401)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/healthz")
def healthz():
    # Pour le « Health Check Path » de Render : aucune donnée, pas d'authentification.
    return "ok"


@app.before_request
def exiger_connexion():
    if request.endpoint in ("login", "healthz"):
        return None
    if LOCAL or (session.get("ok") and APP_PASSWORD):
        return None
    if request.path.startswith(("/api/", "/upload", "/download", "/media/")):
        return jsonify({"error": "non connecté"}), 401
    return redirect("/login")


@app.after_request
def entetes_securite(reponse):
    reponse.headers["X-Content-Type-Options"] = "nosniff"
    reponse.headers["Referrer-Policy"] = "same-origin"
    reponse.headers["X-Frame-Options"] = "DENY"
    if request.path.startswith("/api/") or request.path in ("/", "/index.html"):
        reponse.headers["Cache-Control"] = "no-store"
    return reponse


# --------------------------------------------------------------------------
# Pont /api/<methode>
# --------------------------------------------------------------------------

def _preparer_resultat(res):
    """Ne jamais envoyer de chemin du serveur au navigateur : un dossier de
    résultats devient un identifiant + la liste des fichiers à télécharger."""
    if isinstance(res, dict) and res.get("dossier"):
        dossier = res.pop("dossier")
        res["dossier_id"] = os.path.basename(dossier)
        res["fichiers"] = sorted(
            f for f in os.listdir(dossier) if os.path.isfile(os.path.join(dossier, f))
        )
    return res


@app.route("/api/<nom>", methods=["POST"])
def appeler_api(nom):
    if nom not in METHODES:
        abort(404)
    if not request.is_json:  # protège contre les envois depuis un autre site
        abort(415)
    args = (request.get_json(silent=True) or {}).get("args", [])
    if not isinstance(args, list):
        abort(400)
    try:
        resultat = getattr(api, nom)(*args)
    except TypeError as e:
        return jsonify({"error": f"Arguments invalides : {e}"}), 400
    except Exception as e:  # une erreur dans un module ne doit pas faire tomber le serveur
        app.logger.exception("Erreur dans %s", nom)
        return jsonify({"error": str(e)}), 500
    return jsonify(_preparer_resultat(resultat))


# --------------------------------------------------------------------------
# Envoi / téléchargement de fichiers (module Conversion)
# --------------------------------------------------------------------------

EXTENSIONS_UPLOAD = {
    ".jpg", ".jpeg", ".png", ".pdf", ".docx", ".doc", ".odt", ".rtf", ".txt",
    ".pptx", ".ppt", ".odp", ".xlsx", ".xls", ".ods", ".csv",
}


def _nettoyer_anciens(dossier, age_max_secondes=24 * 3600):
    """Supprime les envois et résultats vieux de plus de 24 h (disque limité)."""
    limite = time.time() - age_max_secondes
    try:
        for nom in os.listdir(dossier):
            chemin = os.path.join(dossier, nom)
            if os.path.getmtime(chemin) < limite:
                shutil.rmtree(chemin, ignore_errors=True)
    except OSError:
        pass


def _nom_sur(nom):
    nom = os.path.basename(nom or "").replace("\x00", "")
    nom = "".join(c if (c.isalnum() or c in " ._-()") else "_" for c in nom).strip(" .")
    return nom or "fichier"


@app.route("/upload", methods=["POST"])
def upload():
    _nettoyer_anciens(main.UPLOADS_DIR)
    _nettoyer_anciens(main.CONVERSIONS_DIR)
    envoyes = []
    for fichier in request.files.getlist("fichiers"):
        nom = _nom_sur(fichier.filename)
        if os.path.splitext(nom)[1].lower() not in EXTENSIONS_UPLOAD:
            return jsonify({"ok": False, "message": f"Type de fichier non accepté : {nom}"}), 400
        identifiant = secrets.token_hex(8)
        dossier = os.path.join(main.UPLOADS_DIR, identifiant)
        os.makedirs(dossier)
        fichier.save(os.path.join(dossier, nom))
        envoyes.append(f"{identifiant}/{nom}")
    if not envoyes:
        return jsonify({"ok": False, "message": "Aucun fichier reçu."}), 400
    return jsonify({"ok": True, "chemins": envoyes})


def _dossier_resultat(dossier_id):
    racine = os.path.realpath(main.CONVERSIONS_DIR)
    complet = os.path.realpath(os.path.join(racine, dossier_id))
    if os.path.dirname(complet) != racine or not os.path.isdir(complet):
        abort(404)
    return complet


@app.route("/download/<dossier_id>/<path:fichier>")
def telecharger_fichier(dossier_id, fichier):
    return send_from_directory(_dossier_resultat(dossier_id), fichier, as_attachment=True)


@app.route("/download-zip/<dossier_id>")
def telecharger_zip(dossier_id):
    dossier = _dossier_resultat(dossier_id)
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(dossier)):
            chemin = os.path.join(dossier, f)
            if os.path.isfile(chemin):
                z.write(chemin, f)
    tampon.seek(0)
    return send_file(tampon, mimetype="application/zip", as_attachment=True,
                     download_name="resultats.zip")


# --------------------------------------------------------------------------
# Musique : le navigateur lit directement les fichiers du serveur
# --------------------------------------------------------------------------

@app.route("/media/musique/<path:fichier>")
def media_musique(fichier):
    # conditional=True : gère les requêtes « Range » (avance rapide dans le morceau)
    return send_from_directory(main.MUSIQUE_DIR, fichier, conditional=True)


# --------------------------------------------------------------------------
# Interface (dossier ui/)
# --------------------------------------------------------------------------

@app.route("/")
def accueil():
    return send_from_directory(main.UI_DIR, "index.html")


@app.route("/<path:fichier>")
def statique(fichier):
    return send_from_directory(main.UI_DIR, fichier)


if __name__ == "__main__":
    # « python server.py » : serveur local dans le navigateur (http://127.0.0.1:5000).
    if not APP_PASSWORD and not os.environ.get("RENDER"):
        LOCAL = True
    port = int(os.environ.get("PORT", 5000))
    print(f"Ouvre http://127.0.0.1:{port} dans ton navigateur ou dans VS Code (Simple Browser).")
    app.run(host="127.0.0.1", port=port, debug=False)
