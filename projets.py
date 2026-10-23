"""
Module Projets.

Un bloc-notes façon OneNote : chaque projet contient des PAGES de notes et
une liste de TÂCHES. L'avancement du projet (0 → 100 %) se calcule tout seul
à partir des tâches cochées ; sans tâche, c'est un curseur réglé à la main.
Isolé dans ce fichier, comme les autres modules : main.py vient piocher dedans.

Toutes les fonctions reçoivent le chemin de la base de données en premier
argument et renvoient des dictionnaires simples (faciles à lire côté JS).
"""

import functools
import sqlite3
from datetime import datetime, timezone

# Couleurs attribuées à tour de rôle aux nouveaux projets.
COULEURS = ["#5fd9ff", "#a855f7", "#2f7fff", "#ffd25f", "#ff7aa8", "#4ade80"]

LONGUEUR_MAX_NOM = 80
LONGUEUR_MAX_TACHE = 300
TAILLE_MAX_PAGE = 2_000_000  # caractères : largement assez pour des notes


def _maintenant():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connexion(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # supprimer un projet supprime ses pages et tâches
    return conn


def _protege(fonction):
    """Évite qu'une erreur de base de données ne fasse planter l'appel côté
    interface : on renvoie un message lisible à la place."""
    @functools.wraps(fonction)
    def enveloppe(*args, **kwargs):
        try:
            return fonction(*args, **kwargs)
        except sqlite3.Error as e:
            return {"ok": False, "message": f"Erreur de base de données : {e}"}
    return enveloppe


def creer_tables(db_path):
    conn = _connexion(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            couleur TEXT NOT NULL,
            progression_manuelle INTEGER NOT NULL DEFAULT 0,
            ordre INTEGER NOT NULL,
            cree_le TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projet_taches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            projet_id INTEGER NOT NULL REFERENCES projets(id) ON DELETE CASCADE,
            texte TEXT NOT NULL,
            fait INTEGER NOT NULL DEFAULT 0,
            ordre INTEGER NOT NULL,
            fait_le TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projet_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            projet_id INTEGER NOT NULL REFERENCES projets(id) ON DELETE CASCADE,
            titre TEXT NOT NULL,
            contenu TEXT NOT NULL DEFAULT '',
            ordre INTEGER NOT NULL,
            maj_le TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


# ------------------------------------------------------------- avancement

def _calculer_progression(total_taches, taches_faites, progression_manuelle):
    """Renvoie (pourcentage, mode). Avec des tâches : proportion de tâches
    faites. Sans tâche : valeur du curseur manuel.
    Règle importante : on n'affiche 100 % que si TOUT est fait (199 tâches
    sur 200 donnent 99 %, pas 100 %)."""
    if total_taches > 0:
        pct = int(100 * taches_faites / total_taches + 0.5)
        if taches_faites < total_taches:
            pct = min(pct, 99)
        return pct, "taches"
    return max(0, min(100, int(progression_manuelle))), "manuel"


def _resume(conn, projet_id):
    """Fiche résumée d'un projet (utilisée pour la liste et la jauge)."""
    p = conn.execute("SELECT * FROM projets WHERE id = ?", (projet_id,)).fetchone()
    if p is None:
        return None
    total, faites = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(fait), 0) FROM projet_taches WHERE projet_id = ?", (projet_id,)
    ).fetchone()
    nb_pages = conn.execute("SELECT COUNT(*) FROM projet_pages WHERE projet_id = ?", (projet_id,)).fetchone()[0]
    progression, mode = _calculer_progression(total, faites, p["progression_manuelle"])
    return {
        "id": p["id"], "nom": p["nom"], "couleur": p["couleur"],
        "progression": progression, "mode": mode,
        "nb_taches": total, "nb_faites": faites, "nb_pages": nb_pages,
    }


# ----------------------------------------------------------------- projets

@_protege
def lister(db_path):
    conn = _connexion(db_path)
    ids = [r["id"] for r in conn.execute("SELECT id FROM projets ORDER BY ordre, id")]
    projets = [_resume(conn, i) for i in ids]
    conn.close()
    return projets


@_protege
def creer(db_path, nom):
    nom = (nom or "").strip()[:LONGUEUR_MAX_NOM]
    if not nom:
        return {"ok": False, "message": "Donne un nom au projet."}
    conn = _connexion(db_path)
    nb = conn.execute("SELECT COUNT(*) FROM projets").fetchone()[0]
    ordre = conn.execute("SELECT COALESCE(MAX(ordre), -1) + 1 FROM projets").fetchone()[0]
    cur = conn.execute(
        "INSERT INTO projets (nom, couleur, ordre, cree_le) VALUES (?, ?, ?, ?)",
        (nom, COULEURS[nb % len(COULEURS)], ordre, _maintenant()),
    )
    projet_id = cur.lastrowid
    # Un projet démarre toujours avec une première page, prête à écrire dedans.
    conn.execute(
        "INSERT INTO projet_pages (projet_id, titre, contenu, ordre, maj_le) VALUES (?, 'Notes', '', 0, ?)",
        (projet_id, _maintenant()),
    )
    conn.commit()
    resume = _resume(conn, projet_id)
    conn.close()
    return {"ok": True, "id": projet_id, "projet": resume}


@_protege
def renommer(db_path, projet_id, nom):
    nom = (nom or "").strip()[:LONGUEUR_MAX_NOM]
    if not nom:
        return {"ok": False, "message": "Le nom ne peut pas être vide."}
    conn = _connexion(db_path)
    conn.execute("UPDATE projets SET nom = ? WHERE id = ?", (nom, projet_id))
    conn.commit()
    resume = _resume(conn, projet_id)
    conn.close()
    return {"ok": resume is not None, "projet": resume}


@_protege
def supprimer(db_path, projet_id):
    conn = _connexion(db_path)
    conn.execute("DELETE FROM projets WHERE id = ?", (projet_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@_protege
def definir_progression_manuelle(db_path, projet_id, valeur):
    try:
        valeur = max(0, min(100, int(valeur)))
    except (TypeError, ValueError):
        return {"ok": False, "message": "Valeur invalide."}
    conn = _connexion(db_path)
    conn.execute("UPDATE projets SET progression_manuelle = ? WHERE id = ?", (valeur, projet_id))
    conn.commit()
    resume = _resume(conn, projet_id)
    conn.close()
    return {"ok": resume is not None, "projet": resume}


@_protege
def details(db_path, projet_id):
    """Tout ce qu'il faut pour afficher un projet : résumé, tâches, liste des
    pages (sans leur contenu, chargé à la demande pour rester léger)."""
    conn = _connexion(db_path)
    resume = _resume(conn, projet_id)
    if resume is None:
        conn.close()
        return {"ok": False, "message": "Projet introuvable."}
    taches = [dict(r) for r in conn.execute(
        "SELECT id, texte, fait FROM projet_taches WHERE projet_id = ? ORDER BY ordre, id", (projet_id,))]
    pages = [dict(r) for r in conn.execute(
        "SELECT id, titre, maj_le FROM projet_pages WHERE projet_id = ? ORDER BY ordre, id", (projet_id,))]
    conn.close()
    for t in taches:
        t["fait"] = bool(t["fait"])
    return {"ok": True, "projet": resume, "taches": taches, "pages": pages}


# ------------------------------------------------------------------- pages

@_protege
def page_lire(db_path, page_id):
    conn = _connexion(db_path)
    p = conn.execute("SELECT id, projet_id, titre, contenu, maj_le FROM projet_pages WHERE id = ?", (page_id,)).fetchone()
    conn.close()
    if p is None:
        return {"ok": False, "message": "Page introuvable."}
    return {"ok": True, **dict(p)}


@_protege
def page_creer(db_path, projet_id, titre="Nouvelle page"):
    titre = (titre or "").strip()[:LONGUEUR_MAX_NOM] or "Nouvelle page"
    conn = _connexion(db_path)
    if conn.execute("SELECT 1 FROM projets WHERE id = ?", (projet_id,)).fetchone() is None:
        conn.close()
        return {"ok": False, "message": "Projet introuvable."}
    ordre = conn.execute(
        "SELECT COALESCE(MAX(ordre), -1) + 1 FROM projet_pages WHERE projet_id = ?", (projet_id,)).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO projet_pages (projet_id, titre, contenu, ordre, maj_le) VALUES (?, ?, '', ?, ?)",
        (projet_id, titre, ordre, _maintenant()),
    )
    conn.commit()
    page_id = cur.lastrowid
    conn.close()
    return {"ok": True, "id": page_id, "titre": titre}


@_protege
def page_sauver(db_path, page_id, titre, contenu):
    titre = (titre or "").strip()[:LONGUEUR_MAX_NOM] or "Sans titre"
    contenu = contenu or ""
    if len(contenu) > TAILLE_MAX_PAGE:
        return {"ok": False, "message": "Cette page est trop volumineuse : crée une nouvelle page."}
    maj = _maintenant()
    conn = _connexion(db_path)
    cur = conn.execute(
        "UPDATE projet_pages SET titre = ?, contenu = ?, maj_le = ? WHERE id = ?", (titre, contenu, maj, page_id))
    conn.commit()
    conn.close()
    return {"ok": cur.rowcount > 0, "titre": titre, "maj_le": maj}


@_protege
def page_supprimer(db_path, page_id):
    conn = _connexion(db_path)
    p = conn.execute("SELECT projet_id FROM projet_pages WHERE id = ?", (page_id,)).fetchone()
    if p is None:
        conn.close()
        return {"ok": False, "message": "Page introuvable."}
    nb = conn.execute("SELECT COUNT(*) FROM projet_pages WHERE projet_id = ?", (p["projet_id"],)).fetchone()[0]
    if nb <= 1:
        conn.close()
        return {"ok": False, "message": "Un projet garde toujours au moins une page."}
    conn.execute("DELETE FROM projet_pages WHERE id = ?", (page_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ----------------------------------------------------------------- tâches
# Chaque modification de tâche renvoie le résumé à jour du projet : l'interface
# peut ainsi faire monter la jauge immédiatement, sans second appel.

@_protege
def tache_ajouter(db_path, projet_id, texte):
    texte = (texte or "").strip()[:LONGUEUR_MAX_TACHE]
    if not texte:
        return {"ok": False, "message": "Écris le texte de la tâche."}
    conn = _connexion(db_path)
    if conn.execute("SELECT 1 FROM projets WHERE id = ?", (projet_id,)).fetchone() is None:
        conn.close()
        return {"ok": False, "message": "Projet introuvable."}
    ordre = conn.execute(
        "SELECT COALESCE(MAX(ordre), -1) + 1 FROM projet_taches WHERE projet_id = ?", (projet_id,)).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO projet_taches (projet_id, texte, ordre) VALUES (?, ?, ?)", (projet_id, texte, ordre))
    conn.commit()
    resume = _resume(conn, projet_id)
    conn.close()
    return {"ok": True, "tache": {"id": cur.lastrowid, "texte": texte, "fait": False}, "projet": resume}


@_protege
def tache_basculer(db_path, tache_id):
    conn = _connexion(db_path)
    t = conn.execute("SELECT projet_id, fait FROM projet_taches WHERE id = ?", (tache_id,)).fetchone()
    if t is None:
        conn.close()
        return {"ok": False, "message": "Tâche introuvable."}
    nouveau = 0 if t["fait"] else 1
    conn.execute(
        "UPDATE projet_taches SET fait = ?, fait_le = ? WHERE id = ?",
        (nouveau, _maintenant() if nouveau else None, tache_id))
    conn.commit()
    resume = _resume(conn, t["projet_id"])
    conn.close()
    return {"ok": True, "fait": bool(nouveau), "projet": resume}


@_protege
def tache_modifier(db_path, tache_id, texte):
    texte = (texte or "").strip()[:LONGUEUR_MAX_TACHE]
    if not texte:
        return {"ok": False, "message": "Le texte ne peut pas être vide."}
    conn = _connexion(db_path)
    cur = conn.execute("UPDATE projet_taches SET texte = ? WHERE id = ?", (texte, tache_id))
    conn.commit()
    conn.close()
    return {"ok": cur.rowcount > 0, "texte": texte}


@_protege
def tache_supprimer(db_path, tache_id):
    conn = _connexion(db_path)
    t = conn.execute("SELECT projet_id FROM projet_taches WHERE id = ?", (tache_id,)).fetchone()
    if t is None:
        conn.close()
        return {"ok": False, "message": "Tâche introuvable."}
    conn.execute("DELETE FROM projet_taches WHERE id = ?", (tache_id,))
    conn.commit()
    resume = _resume(conn, t["projet_id"])
    conn.close()
    return {"ok": True, "projet": resume}
