# archi_env.py - lit le fichier .env d'Archi (a la racine du depot) et le met dans l'environnement.
# Sans bibliotheque. Une variable deja definie dans l'environnement n'est JAMAIS ecrasee.
# Les valeurs ne sont jamais affichees.
#   import archi_env; archi_env.charger()            # dans un script Python
#   python archi_env.py                               # dit quelles sections sont remplies (sans les valeurs)
#   python archi_env.py --brancher                    # CE Python chargera le .env a chaque demarrage (voir brancher)
#   python archi_env.py --debrancher                  # l'inverse
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


NOM_AUTO = "archi_env_auto"
MODELE_AUTO = '''# Pose par « python archi_env.py --brancher » (installation.bat le fait). Supprimer : python archi_env.py --debrancher
# Charge le fichier .env d'Archi au demarrage de CE Python, sans ecraser une variable deja definie.
# Pourquoi : n8n lance le code des workflows dans un processus a part, qui ne transmet pas les reglages d'Archi
# aux outils qu'il demarre. Sans ce fichier, un outil retomberait en silence sur les dossiers par defaut.
# Rien n'est charge pour un test (script test*.py) ni avec ARCHI_SANS_ENV=1 : un test ne travaille jamais dans le vrai chateau.
# Il cache aussi les fenetres noires des programmes lances par un Python sans fenetre (voir _sans_fenetre).
import os
import sys

DEPOT = %r


def _sans_fenetre():
    # Pas de fenetre noire devant l'utilisateur (13/11/2026). n8n lance ce Python SANS fenetre ; chaque programme qu'il
    # lance ensuite (ffmpeg, whisper, un autre Python...) recevait alors une console visible, qui passait devant la page.
    # Dans ce cas-la seulement (aucune console du tout), ils sont lances sans fenetre. Lance depuis un terminal, rien ne change. Un programme qui
    # demande expres sa console (CREATE_NEW_CONSOLE) ou se detache (DETACHED_PROCESS) est laisse tel quel.
    # Pour le couper le temps d'un essai : ARCHI_FENETRES=1.
    if sys.platform != "win32" or os.environ.get("ARCHI_FENETRES") == "1":
        return
    import ctypes
    k = ctypes.windll.kernel32
    fen = k.GetConsoleWindow()
    liste = (ctypes.c_uint * 4)()
    n = k.GetConsoleProcessList(liste, 4)
    if fen:
        # un venv lance en arriere-plan : son lanceur a pu creer une console visible rien que pour ce Python
        # (personne d'autre dessus, pas de terminal) : on la cache. Ses programmes partagent cette console cachee.
        if sys.prefix != sys.base_prefix and n == 1:
            ctypes.windll.user32.ShowWindow(fen, 0)
        return
    if n:
        # une console invisible (lance « sans fenetre ») : ses programmes en heritent, aucune fenetre. On n'y touche
        # pas : l'option « sans fenetre » ferait perdre la sortie d'un programme qui ecrit directement dessus.
        return
    import _winapi
    sans = getattr(_winapi, "CREATE_NO_WINDOW", 0x08000000)
    laisser = getattr(_winapi, "CREATE_NEW_CONSOLE", 0x10) | getattr(_winapi, "DETACHED_PROCESS", 0x08)
    creer = _winapi.CreateProcess
    if getattr(creer, "_archi_sans_fenetre", False):
        return

    def creer_sans_fenetre(app, ligne, attr_p, attr_t, heriter, drapeaux, env, dossier, demarrage):
        if not drapeaux & laisser:
            drapeaux |= sans
        return creer(app, ligne, attr_p, attr_t, heriter, drapeaux, env, dossier, demarrage)

    creer_sans_fenetre._archi_sans_fenetre = True
    _winapi.CreateProcess = creer_sans_fenetre


try:
    _sans_fenetre()
except Exception:   # jamais une raison d'empecher Python de demarrer
    pass


def _charger():
    if os.environ.get("ARCHI_SANS_ENV") == "1":
        return
    script = os.path.basename((getattr(sys, "argv", None) or [""])[0]).lower()
    if script.startswith("test"):
        return
    sys.path.insert(0, DEPOT)
    try:
        import archi_env
        archi_env.charger(os.path.join(DEPOT, ".env"))
    finally:
        try:
            sys.path.remove(DEPOT)
        except ValueError:
            pass


try:
    _charger()
except Exception:   # un .env illisible ne doit jamais empecher Python de demarrer
    pass
'''


def _dossier_site():
    import sysconfig
    return sysconfig.get_paths()["purelib"]


def brancher(dossier=None):
    """Fait charger le .env par CE Python a chaque demarrage (un fichier .pth dans son site-packages).
    A reserver a un Python prive d'Archi (venv) : tous ses scripts recevront les reglages. Rend le dossier utilise."""
    dossier = dossier or _dossier_site()
    with open(os.path.join(dossier, NOM_AUTO + ".py"), "w", encoding="utf-8") as f:
        f.write(MODELE_AUTO % ICI)
    with open(os.path.join(dossier, NOM_AUTO + ".pth"), "w", encoding="utf-8") as f:
        f.write("import %s\n" % NOM_AUTO)
    return dossier


def debrancher(dossier=None):
    dossier = dossier or _dossier_site()
    for nom in (NOM_AUTO + ".pth", NOM_AUTO + ".py"):
        try:
            os.remove(os.path.join(dossier, nom))
        except OSError:
            pass
    return dossier


SECTIONS = {
    "Telegram": ["TELEGRAM_BOT_TOKEN", "ARCHI_TELEGRAM_CHAT_ID", "WEBHOOK_URL"],
    "Appli Android": ["ARCHI_CLE_TELEPHONE"],
    "Depot": ["ARCHI_DEPOT"],
}

if __name__ == "__main__":
    if "--brancher" in sys.argv:
        print("Ce Python chargera le .env d'Archi a chaque demarrage (%s)." % brancher())
        sys.exit(0)
    if "--debrancher" in sys.argv:
        print("Ce Python ne charge plus le .env d'Archi (%s)." % debrancher())
        sys.exit(0)
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
