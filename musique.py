"""
Module musique.

Reprend le principe de ton lecteur Tkinter existant (pygame pour la
lecture, yt-dlp pour récupérer des morceaux depuis YouTube), mais intégré
à l'appli plutôt qu'en fenêtre séparée. Isolé dans ce fichier, comme les
autres modules : main.py vient piocher dedans.
"""

import os
import shutil
import time

import pygame
from mutagen import File as MutagenFile

try:
    pygame.mixer.init()
except Exception as e:
    print("Mode silencieux activé (aucun périphérique audio sur le serveur) :", e)

EXTENSIONS_AUDIO = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
EXTENSIONS_VIDEO = {".mp4", ".mkv", ".webm"}

# État de lecture en mémoire. pygame.mixer.music ne donne pas directement
# "où on en est" dans le morceau, donc on calcule la position nous-mêmes
# à partir de l'heure de démarrage.
_etat = {
    "chemin": None,
    "duree": 0,
    "debut": None,      # timestamp epoch du démarrage de la lecture en cours
    "position_pause": 0,
    "en_lecture": False,
}


def _duree_fichier(chemin):
    try:
        audio = MutagenFile(chemin)
        if audio and audio.info:
            return audio.info.length
    except Exception:
        pass
    return 0


def scanner_dossier(dossier):
    """Liste les morceaux (audio et vidéo) trouvés dans le dossier de
    bibliothèque, avec titre / artiste / durée quand disponibles."""
    morceaux = []
    if not dossier or not os.path.isdir(dossier):
        return morceaux

    for nom in sorted(os.listdir(dossier)):
        ext = os.path.splitext(nom)[1].lower()
        if ext not in EXTENSIONS_AUDIO and ext not in EXTENSIONS_VIDEO:
            continue
        chemin = os.path.join(dossier, nom)
        titre_defaut = os.path.splitext(nom)[0]
        titre, artiste, duree = titre_defaut, "", 0

        try:
            audio = MutagenFile(chemin)
            if audio is not None:
                duree = audio.info.length if audio.info else 0
                if audio.tags:
                    if audio.tags.get("TIT2"):
                        titre = str(audio.tags.get("TIT2"))
                    if audio.tags.get("TPE1"):
                        artiste = str(audio.tags.get("TPE1"))
        except Exception:
            pass

        morceaux.append({
            "chemin": chemin,
            "titre": titre,
            "artiste": artiste,
            "duree": round(duree),
            "type": "video" if ext in EXTENSIONS_VIDEO else "audio",
        })
    return morceaux


def jouer(chemin):
    if not os.path.isfile(chemin):
        return {"ok": False, "message": "Fichier introuvable."}
    try:
        pygame.mixer.music.load(chemin)
        pygame.mixer.music.play()
        _etat["chemin"] = chemin
        _etat["debut"] = time.time()
        _etat["position_pause"] = 0
        _etat["en_lecture"] = True
        _etat["duree"] = _duree_fichier(chemin)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "message": f"Impossible de lire ce fichier : {e}"}


def basculer_pause():
    if not _etat["chemin"]:
        return
    if _etat["en_lecture"]:
        _etat["position_pause"] = position_actuelle()
        pygame.mixer.music.pause()
        _etat["en_lecture"] = False
    else:
        pygame.mixer.music.unpause()
        _etat["debut"] = time.time() - _etat["position_pause"]
        _etat["en_lecture"] = True


def definir_position(secondes):
    """Saute à une position donnée (utilisé quand on clique sur la barre
    de progression). Fonctionne pour mp3/ogg via pygame."""
    if not _etat["chemin"]:
        return
    try:
        pygame.mixer.music.play(start=secondes)
        _etat["debut"] = time.time() - secondes
        _etat["en_lecture"] = True
    except Exception:
        pass  # certains formats ne supportent pas le saut direct


def definir_volume(volume_0_a_100):
    v = max(0, min(100, volume_0_a_100))
    pygame.mixer.music.set_volume(v / 100)


def position_actuelle():
    if not _etat["chemin"]:
        return 0
    if _etat["en_lecture"]:
        return max(0, time.time() - _etat["debut"])
    return _etat["position_pause"]


def obtenir_etat():
    return {
        "chemin": _etat["chemin"],
        "en_lecture": bool(_etat["en_lecture"] and pygame.mixer.music.get_busy()),
        "position": round(position_actuelle(), 1),
        "duree": round(_etat["duree"], 1),
    }


def telecharger(url, format_cible, dossier_destination):
    """Télécharge une vidéo YouTube en mp3 (audio seul) ou mp4 (vidéo
    complète) dans le dossier de bibliothèque."""
    if not shutil.which("ffmpeg"):
        return {
            "ok": False,
            "message": "ffmpeg est requis pour le téléchargement et n'a pas été trouvé. "
                       "Installe-le (ffmpeg.org) puis réessaie.",
        }

    try:
        import yt_dlp
    except ImportError:
        return {"ok": False, "message": "yt-dlp n'est pas installé."}

    os.makedirs(dossier_destination, exist_ok=True)
    modele_nom = os.path.join(dossier_destination, "%(title)s.%(ext)s")

    if format_cible == "mp3":
        options = {
            "format": "bestaudio/best",
            "outtmpl": modele_nom,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "noplaylist": True,
            "quiet": True,
        }
    else:
        options = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4",
            "outtmpl": modele_nom,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
        }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            titre = info.get("title", "Le fichier")
        return {"ok": True, "message": f"« {titre} » ajouté à la bibliothèque."}
    except Exception as e:
        return {"ok": False, "message": f"Échec du téléchargement : {e}"}
