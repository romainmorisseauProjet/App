"""
Module voix.

Tout ce qui concerne la commande vocale vit dans ce fichier, séparé du
reste de l'appli : main.py vient piocher dedans, mais toute la logique
(reconnaissance vocale, puis plus tard la décision d'action) est ici.

Étape 1 (celle-ci) : juste charger le modèle de reconnaissance vocale
et vérifier qu'il fonctionne. On ne s'occupe pas encore du micro.
"""

# Le modèle est lourd à charger (plusieurs centaines de Mo) : on ne le
# charge qu'une seule fois, à la première utilisation, plutôt qu'à
# chaque appel. C'est ce qu'on appelle un "chargement paresseux".
_modele = None


def _get_modele():
    global _modele
    if _modele is None:
        # Import ici (et non en haut du fichier) : l'appli démarre même si
        # faster-whisper n'est pas installé ; seule la voix en a besoin.
        from faster_whisper import WhisperModel
        # "small" est un bon compromis vitesse / précision pour du français
        # sur un CPU classique. Si c'est trop lent chez toi, on pourra
        # passer à "base" (plus rapide, un peu moins précis).
        # Le premier appel télécharge le modèle (~500 Mo) : ça peut prendre
        # une minute ou deux selon ta connexion, une seule fois.
        _modele = WhisperModel("small", device="cpu", compute_type="int8")
    return _modele


def test_chargement():
    """Ne fait rien d'utile en soi : sert juste à vérifier que
    faster-whisper est bien installé et que le modèle se charge sans
    erreur, avant qu'on branche le micro dessus."""
    _get_modele()
    return "Modèle vocal chargé avec succès."


def transcrire_fichier(chemin_audio):
    """Transcrit un fichier audio (wav) en texte français.
    Pas encore utilisée à cette étape, elle servira à l'étape 3."""
    modele = _get_modele()
    segments, info = modele.transcribe(chemin_audio, language="fr")
    texte = " ".join(segment.text.strip() for segment in segments)
    return texte.strip()
