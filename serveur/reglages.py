# reglages.py - les reglages du serveur Python d'Archi, en un seul endroit (variables d'environnement).
# Les connexions (jetons Google/Microsoft) et les donnees de travail vont dans DONNEES, jamais dans le depot.
import os
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
# le .env a la racine du depot (sans ecraser ce qui est deja dans l'environnement)
sys.path.insert(0, os.path.dirname(ICI))
try:
    import archi_env
    archi_env.charger()
except ImportError:
    pass
DONNEES = os.environ.get("ARCHI_SERVEUR_DONNEES") or os.path.join(ICI, "donnees")
os.makedirs(DONNEES, exist_ok=True)


def chemin(*morceaux):
    """un fichier dans le dossier de donnees du serveur (jetons, journaux, memoire des expediteurs)"""
    p = os.path.join(DONNEES, *morceaux)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


LM_URL = os.environ.get("ARCHI_LM_URL", "http://127.0.0.1:1234/v1").rstrip("/") + "/chat/completions"
MODELE = os.environ.get("ARCHI_MODELE", "openai/gpt-oss-20b")
UTILISATEUR = os.environ.get("ARCHI_UTILISATEUR", "l'utilisateur")
FUSEAU = os.environ.get("ARCHI_FUSEAU", "Europe/Paris")
# Google : fichier OAuth « application de bureau » telecharge depuis Google Cloud (voir LISEZMOI.md)
GOOGLE_CLIENT = os.environ.get("ARCHI_GOOGLE_CLIENT") or chemin("google_client.json")
# Microsoft (Outlook / Hotmail) : application inscrite dans Azure (voir LISEZMOI.md)
OUTLOOK_CLIENT_ID = os.environ.get("ARCHI_OUTLOOK_CLIENT_ID", "")
OUTLOOK_TENANT = os.environ.get("ARCHI_OUTLOOK_TENANT", "consumers")   # consumers = comptes personnels Outlook/Hotmail
PORT = int(os.environ.get("ARCHI_SERVEUR_PORT", "8765"))
