import os
import sqlite3
import base64
import shutil
import subprocess
import platform
from datetime import datetime
from bottle import route, run, static_file
import voice
import actualites
import musique
import carburants
import iss
import projets
import calcul

AUDIO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "audio")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "assistant.db")
HTML_PATH = os.path.join(BASE_DIR, "ui", "index.html")
CONVERSIONS_DIR = os.path.join(BASE_DIR, "data", "conversions")
MUSIQUE_DIR_DEFAUT = os.path.join(BASE_DIR, "data", "musique")

# Référence vers la fenêtre principale, nécessaire pour ouvrir les
# sélecteurs de fichiers natifs depuis les méthodes de l'Api (uniquement en local).
window = None


def init_db():
    """Crée le fichier de base de données et les tables nécessaires
    si elles n'existent pas encore."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meteo_favoris (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            region TEXT,
            pays TEXT,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            ordre INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS domotique_appareils (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            type TEXT NOT NULL,
            piece TEXT,
            etat INTEGER NOT NULL DEFAULT 0,
            valeur INTEGER NOT NULL DEFAULT 0,
            ordre INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS modules_ordre (
            cle TEXT PRIMARY KEY,
            ordre INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS parametres (
            cle TEXT PRIMARY KEY,
            valeur TEXT
        )
    """)
    conn.commit()
    conn.close()
    projets.creer_tables(DB_PATH)
    calcul.creer_tables(DB_PATH)


class Api:
    """Pont entre le JavaScript de l'interface et le code Python."""

    def ping(self):
        return "Connexion Python OK — la fenêtre parle bien avec le backend."

    def test_voix(self):
        return voice.test_chargement()

    def recevoir_audio(self, audio_base64):
        os.makedirs(AUDIO_PATH, exist_ok=True)
        donnees = base64.b64decode(audio_base64)
        chemin = os.path.join(AUDIO_PATH, "dernier_enregistrement.webm")
        with open(chemin, "wb") as f:
            f.write(donnees)
        taille_ko = round(len(donnees) / 1024, 1)
        return f"Audio reçu : {taille_ko} Ko, enregistré dans data/audio/"

    # --- Favoris météo ---

    def get_favoris(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, nom, region, pays, latitude, longitude FROM meteo_favoris ORDER BY ordre"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_favori(self, nom, region, pays, latitude, longitude):
        conn = sqlite3.connect(DB_PATH)
        existe = conn.execute(
            "SELECT 1 FROM meteo_favoris WHERE nom = ? AND latitude = ? AND longitude = ?",
            (nom, latitude, longitude),
        ).fetchone()
        if existe:
            conn.close()
            return {"ok": False, "message": "Déjà dans les favoris"}
        ordre = conn.execute("SELECT COALESCE(MAX(ordre), -1) + 1 FROM meteo_favoris").fetchone()[0]
        conn.execute(
            "INSERT INTO meteo_favoris (nom, region, pays, latitude, longitude, ordre) VALUES (?, ?, ?, ?, ?, ?)",
            (nom, region, pays, latitude, longitude, ordre),
        )
        conn.commit()
        conn.close()
        return {"ok": True}

    def remove_favori(self, favori_id):
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM meteo_favoris WHERE id = ?", (favori_id,))
        conn.commit()
        conn.close()
        return {"ok": True}

    # --- Domotique ---

    VALEURS_DEFAUT_PAR_TYPE = {"lampe": 100, "volet": 100, "thermostat": 20}

    def get_appareils(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, nom, type, piece, etat, valeur FROM domotique_appareils ORDER BY ordre"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_appareil(self, nom, type_appareil, piece):
        nom = (nom or "").strip()
        piece = (piece or "").strip()
        if not nom:
            return {"ok": False, "message": "Le nom est obligatoire"}
        valeur = self.VALEURS_DEFAUT_PAR_TYPE.get(type_appareil, 0)
        conn = sqlite3.connect(DB_PATH)
        ordre = conn.execute(
            "SELECT COALESCE(MAX(ordre), -1) + 1 FROM domotique_appareils"
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO domotique_appareils (nom, type, piece, etat, valeur, ordre) "
            "VALUES (?, ?, ?, 0, ?, ?)",
            (nom, type_appareil, piece, valeur, ordre),
        )
        conn.commit()
        nouvel_id = cur.lastrowid
        conn.close()
        return {
            "ok": True,
            "appareil": {
                "id": nouvel_id, "nom": nom, "type": type_appareil,
                "piece": piece, "etat": 0, "valeur": valeur,
            },
        }

    def remove_appareil(self, appareil_id):
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM domotique_appareils WHERE id = ?", (appareil_id,))
        conn.commit()
        conn.close()
        return {"ok": True}

    def toggle_appareil(self, appareil_id):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT etat FROM domotique_appareils WHERE id = ?", (appareil_id,)
        ).fetchone()
        if row is None:
            conn.close()
            return {"ok": False}
        nouvel_etat = 0 if row[0] else 1
        conn.execute(
            "UPDATE domotique_appareils SET etat = ? WHERE id = ?",
            (nouvel_etat, appareil_id),
        )
        conn.commit()
        conn.close()
        return {"ok": True, "etat": nouvel_etat}

    def set_valeur_appareil(self, appareil_id, valeur):
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE domotique_appareils SET valeur = ?, etat = 1 WHERE id = ?",
            (valeur, appareil_id),
        )
        conn.commit()
        conn.close()
        return {"ok": True}

    # --- Ordre des modules ---

    def get_ordre_modules(self):
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("SELECT cle FROM modules_ordre ORDER BY ordre").fetchall()
        conn.close()
        return [r[0] for r in rows]

    def set_ordre_modules(self, cles):
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM modules_ordre")
        conn.executemany(
            "INSERT INTO modules_ordre (cle, ordre) VALUES (?, ?)",
            [(cle, i) for i, cle in enumerate(cles)],
        )
        conn.commit()
        conn.close()
        return {"ok": True}

    # --- Conversion de fichiers ---

    FILTRES_DIALOGUE = {
        "images": ("Images (*.jpg;*.jpeg;*.png)",),
        "pdf": ("Documents PDF (*.pdf)",),
        "document": (
            "Documents bureautiques (*.docx;*.doc;*.odt;*.rtf;*.txt;"
            "*.pptx;*.ppt;*.odp;*.xlsx;*.xls;*.ods;*.csv)",
        ),
    }

    def choisir_fichiers(self, filtre, multiple):
        if window is None:
            return []
        import webview
        types = self.FILTRES_DIALOGUE.get(filtre, ())
        resultat = window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=bool(multiple), file_types=types
        )
        return list(resultat) if resultat else []

    def ouvrir_dossier(self, chemin):
        try:
            systeme = platform.system()
            if systeme == "Windows":
                os.startfile(chemin)
            elif systeme == "Darwin":
                subprocess.run(["open", chemin], check=True)
            else:
                subprocess.run(["xdg-open", chemin], check=True)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def choisir_dossier_sortie(self):
        if window is None:
            return None
        import webview
        resultat = window.create_file_dialog(webview.FOLDER_DIALOG)
        return resultat[0] if resultat else None

    def _nouveau_dossier_sortie(self, prefixe, dossier_parent=None):
        parent = dossier_parent or CONVERSIONS_DIR
        os.makedirs(parent, exist_ok=True)
        horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
        dossier = os.path.join(parent, f"{horodatage}_{prefixe}")
        os.makedirs(dossier, exist_ok=True)
        return dossier

    def images_vers_pdf(self, chemins, dossier_sortie=None):
        if not chemins:
            return {"ok": False, "message": "Choisis au moins une image."}
        try:
            from PIL import Image
            images = [Image.open(c).convert("RGB") for c in chemins]
            dossier = self._nouveau_dossier_sortie("images-vers-pdf", dossier_sortie)
            sortie = os.path.join(dossier, "images.pdf")
            images[0].save(sortie, save_all=True, append_images=images[1:])
            return {"ok": True, "dossier": dossier, "message": f"{len(images)} image(s) rassemblée(s) dans un PDF."}
        except Exception as e:
            return {"ok": False, "message": f"Échec de la conversion : {e}"}

    def pdf_vers_images(self, chemin_pdf, format_image, dossier_sortie=None):
        if not chemin_pdf:
            return {"ok": False, "message": "Choisis un fichier PDF."}
        try:
            import pymupdf
            dossier = self._nouveau_dossier_sortie("pdf-vers-images", dossier_sortie)
            doc = pymupdf.open(chemin_pdf)
            for i, page in enumerate(doc):
                pix = page.get_pixmap(dpi=200)
                pix.save(os.path.join(dossier, f"page-{i + 1}.{format_image}"))
            nb_pages = doc.page_count
            doc.close()
            return {"ok": True, "dossier": dossier, "message": f"{nb_pages} page(s) exportée(s) en image."}
        except Exception as e:
            return {"ok": False, "message": f"Échec de la conversion : {e}"}

    def document_vers_pdf(self, chemin_document, dossier_sortie=None):
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if not soffice:
            return {
                "ok": False,
                "message": "LibreOffice est requis pour cette conversion et n'a pas été trouvé.",
            }
        try:
            dossier = self._nouveau_dossier_sortie("document-vers-pdf", dossier_sortie)
            subprocess.run(
                [soffice, "--headless", "--norestore", "--convert-to", "pdf", "--outdir", dossier, chemin_document],
                check=True, timeout=120,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return {"ok": True, "dossier": dossier, "message": "Document converti en PDF."}
        except Exception as e:
            return {"ok": False, "message": f"Échec de la conversion : {e}"}

    def pdf_vers_docx(self, chemin_pdf, dossier_sortie=None):
        if not chemin_pdf:
            return {"ok": False, "message": "Choisis un fichier PDF."}
        try:
            from pdf2docx import Converter
            dossier = self._nouveau_dossier_sortie("pdf-vers-word", dossier_sortie)
            nom = os.path.splitext(os.path.basename(chemin_pdf))[0]
            sortie = os.path.join(dossier, f"{nom}.docx")
            convertisseur = Converter(chemin_pdf)
            convertisseur.convert(sortie)
            convertisseur.close()
            return {"ok": True, "dossier": dossier, "message": "PDF converti en document Word."}
        except Exception as e:
            return {"ok": False, "message": f"Échec de la conversion : {e}"}

    def pdf_vers_pptx(self, chemin_pdf, dossier_sortie=None):
        if not chemin_pdf:
            return {"ok": False, "message": "Choisis un fichier PDF."}
        try:
            import pymupdf
            from pptx import Presentation
            from pptx.util import Emu

            dossier = self._nouveau_dossier_sortie("pdf-vers-powerpoint", dossier_sortie)
            doc = pymupdf.open(chemin_pdf)
            nb_pages = doc.page_count
            if nb_pages == 0:
                doc.close()
                return {"ok": False, "message": "Ce PDF ne contient aucune page."}

            dpi = 150
            presentation = Presentation()
            diapo_vierge = presentation.slide_layouts[6]

            for i, page in enumerate(doc):
                pix = page.get_pixmap(dpi=dpi)
                chemin_image = os.path.join(dossier, f"_page-{i + 1}.png")
                pix.save(chemin_image)
                if i == 0:
                    presentation.slide_width = Emu(int(pix.width / dpi * 914400))
                    presentation.slide_height = Emu(int(pix.height / dpi * 914400))
                diapositive = presentation.slides.add_slide(diapo_vierge)
                diapositive.shapes.add_picture(
                    chemin_image, 0, 0,
                    width=presentation.slide_width, height=presentation.slide_height,
                )
                os.remove(chemin_image)
            doc.close()

            nom = os.path.splitext(os.path.basename(chemin_pdf))[0]
            sortie = os.path.join(dossier, f"{nom}.pptx")
            presentation.save(sortie)
            return {"ok": True, "dossier": dossier, "message": f"{nb_pages} page(s) transformée(s) en diapositives."}
        except Exception as e:
            return {"ok": False, "message": f"Échec de la conversion : {e}"}

    def fusionner_pdf(self, chemins, dossier_sortie=None):
        if not chemins or len(chemins) < 2:
            return {"ok": False, "message": "Choisis au moins deux fichiers PDF."}
        try:
            from pypdf import PdfReader, PdfWriter
            writer = PdfWriter()
            for chemin in chemins:
                reader = PdfReader(chemin)
                for page in reader.pages:
                    writer.add_page(page)
            dossier = self._nouveau_dossier_sortie("pdf-fusionnes", dossier_sortie)
            sortie = os.path.join(dossier, "fusion.pdf")
            with open(sortie, "wb") as f:
                writer.write(f)
            return {"ok": True, "dossier": dossier, "message": f"{len(chemins)} PDF fusionnés en un seul fichier."}
        except Exception as e:
            return {"ok": False, "message": f"Échec de la fusion : {e}"}

    # --- Actualités ---

    def get_actualites(self, categorie):
        return actualites.recuperer_articles(categorie)

    def ouvrir_lien(self, url):
        import webbrowser
        webbrowser.open(url)
        return {"ok": True}

    # --- Musique ---

    def _lire_parametre(self, cle, defaut=None):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT valeur FROM parametres WHERE cle = ?", (cle,)).fetchone()
        conn.close()
        return row[0] if row else defaut

    def _ecrire_parametre(self, cle, valeur):
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO parametres (cle, valeur) VALUES (?, ?) "
            "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
            (cle, valeur),
        )
        conn.commit()
        conn.close()

    def get_dossier_musique(self):
        dossier = self._lire_parametre("dossier_musique", MUSIQUE_DIR_DEFAUT)
        os.makedirs(dossier, exist_ok=True)
        return dossier

    def choisir_dossier_musique(self):
        if window is None:
            return None
        import webview
        resultat = window.create_file_dialog(webview.FOLDER_DIALOG)
        if not resultat:
            return None
        self._ecrire_parametre("dossier_musique", resultat[0])
        return resultat[0]

    def get_bibliotheque(self):
        return musique.scanner_dossier(self.get_dossier_musique())

    def telecharger_musique(self, url, format_cible):
        return musique.telecharger(url, format_cible, self.get_dossier_musique())

    def jouer_morceau(self, chemin):
        return musique.jouer(chemin)

    def basculer_pause_musique(self):
        musique.basculer_pause()
        return {"ok": True}

    def definir_position_musique(self, secondes):
        musique.definir_position(secondes)
        return {"ok": True}

    def definir_volume_musique(self, volume):
        musique.definir_volume(volume)
        return {"ok": True}

    def get_etat_musique(self):
        return musique.obtenir_etat()

    # --- Carburants ---

    def get_stations_carburant(self, latitude, longitude, carburant, rayon_km):
        return carburants.rechercher_stations(latitude, longitude, carburant, rayon_km)

    # --- Station spatiale (ISS) ---

    def get_iss_etat(self):
        pos = iss.position_actuelle()
        if pos.get("ok"):
            pos["pays"] = iss.pays_survole(pos["latitude"], pos["longitude"])
        return pos

    def get_iss_trace(self):
        return iss.trace_orbite()

    def get_iss_equipage(self):
        return iss.equipage()

    def get_iss_passages(self, latitude, longitude):
        return iss.prochains_passages(latitude, longitude)

    def get_iss_lieu(self):
        import json
        brut = self._lire_parametre("iss_lieu")
        return json.loads(brut) if brut else None

    def set_iss_lieu(self, nom, latitude, longitude):
        import json
        self._ecrire_parametre("iss_lieu", json.dumps({"nom": nom, "lat": latitude, "lon": longitude}))
        return {"ok": True}

    # --- Projets ---

    def projets_lister(self):
        return projets.lister(DB_PATH)

    def projets_creer(self, nom):
        return projets.creer(DB_PATH, nom)

    def projets_renommer(self, projet_id, nom):
        return projets.renommer(DB_PATH, projet_id, nom)

    def projets_supprimer(self, projet_id):
        return projets.supprimer(DB_PATH, projet_id)

    def projets_definir_progression(self, projet_id, valeur):
        return projets.definir_progression_manuelle(DB_PATH, projet_id, valeur)

    def projets_details(self, projet_id):
        return projets.details(DB_PATH, projet_id)

    def projets_page_lire(self, page_id):
        return projets.page_lire(DB_PATH, page_id)

    def projets_page_creer(self, projet_id, titre="Nouvelle page"):
        return projets.page_creer(DB_PATH, projet_id, titre)

    def projets_page_sauver(self, page_id, titre, contenu):
        return projets.page_sauver(DB_PATH, page_id, titre, contenu)

    def projets_page_supprimer(self, page_id):
        return projets.page_supprimer(DB_PATH, page_id)

    def projets_tache_ajouter(self, projet_id, texte):
        return projets.tache_ajouter(DB_PATH, projet_id, texte)

    def projets_tache_basculer(self, tache_id):
        return projets.tache_basculer(DB_PATH, tache_id)

    def projets_tache_modifier(self, tache_id, texte):
        return projets.tache_modifier(DB_PATH, tache_id, texte)

    def projets_tache_supprimer(self, tache_id):
        return projets.tache_supprimer(DB_PATH, tache_id)

    # --- Calcul ---

    def calcul_catalogue(self):
        return calcul.catalogue()

    def calcul_demander(self, texte, image=None, detail=False):
        return calcul.demander(DB_PATH, texte, image, detail)

    def calcul_formule(self, formule_id, valeurs, enregistrer=False):
        return calcul.calculer_formule(DB_PATH, formule_id, valeurs, enregistrer)

    def calcul_historique_lister(self):
        return calcul.historique_lister(DB_PATH)

    def calcul_historique_supprimer(self, entree_id):
        return calcul.historique_supprimer(DB_PATH, entree_id)

    def calcul_historique_vider(self):
        return calcul.historique_vider(DB_PATH)

    def calcul_ia_statut(self):
        return calcul.ia_statut(DB_PATH)

    def calcul_ia_configurer(self, cle, modele):
        return calcul.ia_configurer(DB_PATH, cle, modele)

    def calcul_ia_retirer_cle(self):
        return calcul.ia_retirer_cle(DB_PATH)


# --- Routes du serveur web (pour Render) ---

@route('/')
def index():
    return static_file('index.html', root=os.path.join(BASE_DIR, 'ui'))

@route('/ui/<filepath:path>')
def serve_ui(filepath):
    return static_file(filepath, root=os.path.join(BASE_DIR, 'ui'))


def main():
    global window
    init_db()
    api = Api()
    
    # Render fournit automatiquement une variable d'environnement "PORT"
    port = int(os.environ.get("PORT", 0))
    
    if port > 0:
        # Mode Serveur Web (sur Render)
        print(f"Démarrage du serveur web sur le port {port}...")
        run(host="0.0.0.0", port=port, server="wsgiref")
    else:
        # Mode Bureau classique (sur ton ordinateur personnel)
        import webview
        window = webview.create_window(
            "Assistant",
            HTML_PATH,
            js_api=api,
            width=1200,
            height=800,
            min_size=(800, 560),
            background_color="#050810",
        )
        webview.start()


if __name__ == "__main__":
    main()