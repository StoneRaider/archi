"""Tests hors ligne de la recolte YouTube (faux chateau, aucune video telechargee)."""
import json, os, subprocess, sys, tempfile
ICI = os.path.dirname(os.path.abspath(__file__))
D = tempfile.mkdtemp(prefix="recolte_")
os.makedirs(os.path.join(D, "memoire", "bibliotheque"))
ENV = dict(os.environ, ARCHI_BASE=D, PYTHONIOENCODING="utf-8", ARCHI_WEBHOOK_ALERTE="")
ok = ko = 0


def appel(**d):
    f = os.path.join(D, "d.json")
    json.dump(d, open(f, "w", encoding="utf-8"))
    r = subprocess.run([sys.executable, os.path.join(ICI, "recolte_lancer.py"), "--fichier", f], capture_output=True, env=ENV)
    return json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])


def verif(nom, cond, detail=""):
    global ok, ko
    ok, ko = (ok + 1, ko) if cond else (ok, ko + 1)
    if not cond:
        print("ECHEC", nom, str(detail)[:200])


r = appel(cible="etat")
verif("etat", r["ok"] and "Aucune récolte" in r["resultat"], r)
r = appel(cible="suivies")
verif("suivies vide", r["ok"] and "Aucune" in r["resultat"], r)
r = appel(cible="retirer: Chaine Inconnue")
verif("retirer une chaine inconnue", not r["ok"], r)
r = appel(cible="")
verif("cible vide expliquee", not r["ok"] and "nom" in r["phrase_pour_utilisateur"], r)
verif("donnees dans le chateau", os.path.isdir(os.path.join(D, "recolte")))
print(f"{ok} OK, {ko} ECHEC")
sys.exit(1 if ko else 0)
