# archi_env.py - lit le fichier .env d'Archi (a la racine du depot) et le met dans l'environnement.
# Sans bibliotheque. Une variable deja definie dans l'environnement n'est JAMAIS ecrasee.
# Les valeurs ne sont jamais affichees.
#   import archi_env; archi_env.charger()            # dans un script Python
#   python archi_env.py --verifier                    # dit quelles sections sont remplies (sans les valeurs)
import os
import re
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
LIGNE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def lire(chemin):
    """{nom: valeur} ; ignore les commentaires et les lignes vides ; accepte "..." ou '...' autour des valeurs"""
    valeurs = {}
    try:
        with open(chemin, encoding="utf-8-sig") as f:
            for brut in f:
                if not brut.strip() or brut.lstrip().startswith("#"):
                    continue
                m = LIGNE.match(brut)
                if not m:
                    continue
                nom, v = m.group(1), m.group(2)
                if len(v) >= 2 and v[0] in "\"'" and v.find(v[0], 1) > 0:
                    v = v[1:v.find(v[0], 1)]   # "valeur" ou 'valeur', un commentaire peut suivre
                elif " #" in v:
                    v = v.split(" #", 1)[0].rstrip()   # commentaire en fin de ligne
                valeurs[nom] = v
    except FileNotFoundError:
        pass
    return valeurs


def charger(chemin=None):
    """met le .env dans os.environ (sans ecraser) ; rend le nombre de variables ajoutees"""
    chemin = chemin or os.environ.get("ARCHI_ENV") or os.path.join(ICI, ".env")
    n = 0
    for nom, v in lire(chemin).items():
        if v != "" and nom not in os.environ:
            os.environ[nom] = v
            n += 1
    return n


SECTIONS = {
    "Telegram": ["TELEGRAM_BOT_TOKEN", "ARCHI_TELEGRAM_CHAT_ID", "WEBHOOK_URL"],
    "Appli Android": ["ARCHI_CLE_TELEPHONE"],
    "Depot": ["ARCHI_DEPOT"],
}

if __name__ == "__main__":
    v = lire(os.environ.get("ARCHI_ENV") or os.path.join(ICI, ".env"))
    if not v:
        print("Pas de .env : copie .env.example en .env puis remplis-le.")
        sys.exit(1)
    for sec, noms in SECTIONS.items():
        manque = [n for n in noms if not v.get(n)]
        print(f"{sec:16} : " + ("OK" if not manque else "a remplir : " + ", ".join(manque)))
    FAC = {"Outlook": "ARCHI_OUTLOOK_CLIENT_ID", "Oeil (porte)": "ARCHI_CLE_OEIL", "Imprimante 3D": "ARCHI_IMPRIMANTE_IP"}
    print("Facultatif      : " + ", ".join(k + (" OK" if v.get(n) else " (vide)") for k, n in FAC.items())
          + " ; Gmail/agenda : fichier serveur/donnees/google_client.json ou ARCHI_GOOGLE_CLIENT")
    courte = [n for n in ("ARCHI_CLE_TELEPHONE", "ARCHI_CLE_OEIL") if v.get(n) and len(v[n]) < 16]
    if courte:
        print("ATTENTION, cle trop courte (16 caracteres minimum) : " + ", ".join(courte))
