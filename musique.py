"""
Module musique (version web).

La lecture se fait maintenant dans le navigateur (balise <audio>) : ce fichier
ne sert plus qu'à lister la bibliothèque stockée sur le serveur et à y
télécharger des morceaux avec yt-dlp.
"""

import os
import shutil

from mutagen import File as MutagenFile

EXTENSIONS_AUDIO = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
EXTENSIONS_VIDEO = {".mp4", ".mkv", ".webm"}

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
            "fichier": nom,
            "titre": titre,
            "artiste": artiste,
            "duree": round(duree),
            "type": "video" if ext in EXTENSIONS_VIDEO else "audio",
        })
    return morceaux


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

    cookies = os.environ.get("YTDLP_COOKIES")  # chemin d'un cookies.txt (facultatif)
    if cookies and os.path.isfile(cookies):
        options["cookiefile"] = cookies

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            titre = info.get("title", "Le fichier")
        return {"ok": True, "message": f"« {titre} » ajouté à la bibliothèque."}
    except Exception as e:
        return {"ok": False, "message": f"Échec du téléchargement : {e}"}
