# test_prenom.py - Archi appelle l'utilisateur par le prenom du profil (ARCHI_UTILISATEUR), jamais par un surnom en dur.
#   python outils_depot/test_prenom.py
# 1. plus aucun « BOSS » dans le code du depot ;
# 2. l'aide _qui() de chaque fichier donne « , Camille » avec un prenom, et rien sans.
import glob, json, os, re, sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HORS = ("node_modules", ".git", ".local", "donnees", "venv", "__pycache__", os.path.join("appli", "app", "build"))
OK = KO = 0


def verif(nom, cond, detail=""):
    global OK, KO
    if cond:
        OK += 1
    else:
        KO += 1
        print("ECHEC", nom, detail)


def fichiers():
    for dossier, sous, noms in os.walk(RACINE):
        sous[:] = [s for s in sous if s not in HORS and os.path.relpath(os.path.join(dossier, s), RACINE) not in HORS]
        for n in noms:
            if n.endswith((".py", ".js", ".json", ".ps1", ".kt", ".html")):
                yield os.path.join(dossier, n)


moi = os.path.abspath(__file__)
restes = []
for f in fichiers():
    if os.path.abspath(f) == moi or os.path.basename(f) == "test_planificateur.py":
        continue
    try:
        texte = open(f, encoding="utf-8", errors="replace").read()
    except OSError:
        continue
    if "BOSS" in texte:
        restes.append(os.path.relpath(f, RACINE))
verif("plus de BOSS dans le code", not restes, restes)

# l'aide _qui() : la meme dans chaque fichier Python qui s'adresse a l'utilisateur
avec = []
for f in fichiers():
    if not f.endswith(".py") or os.path.abspath(f) == moi:
        continue
    texte = open(f, encoding="utf-8", errors="replace").read()
    m = re.search(r'^def _qui\(\):\n(?:    .*\n)+', texte.replace("\r\n", "\n"), re.M)
    if not m:
        continue
    avec.append(os.path.relpath(f, RACINE))
    espace = {"os": os}
    exec(m.group(0), espace)
    os.environ["ARCHI_UTILISATEUR"] = "  Camille "
    verif("avec prenom : " + avec[-1], espace["_qui"]() == ", Camille", espace["_qui"]())
    os.environ["ARCHI_UTILISATEUR"] = ""
    verif("sans prenom : " + avec[-1], espace["_qui"]() == "")
    os.environ.pop("ARCHI_UTILISATEUR", None)
    verif("sans la variable : " + avec[-1], espace["_qui"]() == "")
verif("l'aide est presente dans les fichiers attendus", len(avec) >= 14, avec)

# les workflows optionnels : le prenom se lit dans un try, un n8n sans acces a l'environnement ne casse rien
for f in glob.glob(os.path.join(RACINE, "n8n", "optionnels", "*.json")):
    for n in json.load(open(f, encoding="utf-8")).get("nodes", []):
        js = n.get("parameters", {}).get("jsCode") or ""
        if re.search(r"\bQUI\b", js):
            verif("QUI defini avant usage : %s / %s" % (os.path.basename(f), n["name"]),
                  js.find("let QUI = ''; try {") != -1 and js.find("let QUI = ''; try {") < js.find("QUI", js.find("catch (e) {}")))

print(f"{OK} OK, {KO} ECHEC")
sys.exit(1 if KO else 0)
