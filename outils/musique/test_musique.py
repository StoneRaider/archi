"""Tests de musique.py sur une petite bibliotheque inventee (faux chateau)."""
import json, os, subprocess, sys, tempfile
ICI = os.path.dirname(os.path.abspath(__file__))
D = tempfile.mkdtemp(prefix="musique_")
P = os.path.join(D, "memoire", "passions")
os.makedirs(P)
open(os.path.join(P, "musique_index.tsv"), "w", encoding="utf-8").write(
    "artiste\ttitre\talbum\tgenre\tannee\tchemin\nBob Marley\tIs This Love\tKaya\tReggae\t1978\tx\n"
    "Daft Punk\tAround the World\tHomework\tElectronic\t1997\tx\nNirvana\tLithium\tNevermind\tRock\t1991\tx\n"
    "Groupe Maison\tTitre\t\t\t\tx\n")
json.dump({"Groupe Maison": "dub"}, open(os.path.join(P, "musique_artistes.json"), "w", encoding="utf-8"))
ok = ko = 0


def appel(**d):
    f = os.path.join(D, "d.json")
    json.dump(d, open(f, "w", encoding="utf-8"))
    r = subprocess.run([sys.executable, os.path.join(ICI, "musique.py"), "--fichier", f], capture_output=True,
                       env=dict(os.environ, ARCHI_BASE=D, PYTHONIOENCODING="utf-8"))
    return json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])


def verif(nom, cond, detail=""):
    global ok, ko
    ok, ko = (ok + 1, ko) if cond else (ok, ko + 1)
    if not cond:
        print("ECHEC", nom, str(detail)[:300])


r = appel(action="proposer", ambiance="calme", nombre=2)
verif("proposer", r["ok"] and len(r["propositions"]) == 2 and all(p.get("recherche_youtube") for p in r["propositions"]), r)
r = appel(action="chercher", q="daft")
verif("chercher", r["ok"] and r["trouve"] == 1, r)
r = appel(action="gouts")
verif("table perso lue", r["ok"] and r["familles"].get("dub") == 1, r)
verif("4 morceaux", r["morceaux"] == 4, r)
print(f"{ok} OK, {ko} ECHEC")
sys.exit(1 if ko else 0)
