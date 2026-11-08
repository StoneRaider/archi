"""Tests hors ligne de imprimante_3d.py : imprimante simulee, aucun reseau."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imprimante_3d as I  # noqa: E402
ok = ko = 0


def verif(nom, cond, detail=""):
    global ok, ko
    ok, ko = (ok + 1, ko) if cond else (ok, ko + 1)
    if not cond:
        print("ECHEC", nom, str(detail)[:200])


class Fausse:
    def __init__(self, etat="standby"):
        self.e, self.vu = etat, []
    def etat(self):
        return {"etat": self.e, "fichier": "cube.gcode" if self.e == "printing" else "", "progression": 42, "buse": 210, "plateau": 60}
    def fichiers(self):
        return ["cube.gcode", "support.3mf"]
    def envoyer(self, nom, contenu):
        self.vu.append(("envoyer", nom, len(contenu)))
    def lancer(self, nom):
        self.vu.append(("lancer", nom))
    def pause(self):
        self.vu.append(("pause",))
    def reprendre(self):
        self.vu.append(("reprendre",))
    def annuler(self):
        self.vu.append(("annuler",))


def essai(d, imp):
    try:
        return I.agir(d, imp)
    except I.Erreur as e:
        return ("ERREUR " + str(e), {})


p = Fausse()
verif("etat", "standby" in essai({"action": "etat"}, p)[0])
verif("fichiers", "cube.gcode" in essai({"action": "fichiers"}, p)[0])
r = essai({"action": "lancer", "fichier": "cube.gcode"}, p)
verif("lancer sans confirmer = essai a blanc", r[1].get("essai") and p.vu == [], r)
r = essai({"action": "imprimer", "fichier": "cube.gcode", "confirmer": "oui"}, p)
verif("lancer confirme (alias imprimer)", p.vu == [("lancer", "cube.gcode")], r)
verif("mauvaise extension refusee", essai({"action": "lancer", "fichier": "virus.exe", "confirmer": "oui"}, p)[0].startswith("ERREUR"))
verif("chemin nettoye", I.nom_sur("../../etc/cube.gcode") == "cube.gcode")
occupee = Fausse("printing")
verif("deja occupee : refuse", essai({"action": "lancer", "fichier": "a.gcode", "confirmer": "oui"}, occupee)[0].startswith("ERREUR") and occupee.vu == [])
f = os.path.join(tempfile.mkdtemp(), "piece.gcode"); open(f, "wb").write(b"G28\n" * 10)
r = essai({"action": "envoyer", "fichier": f}, p)
verif("envoyer sans confirmer = essai", r[1].get("essai"), r)
essai({"action": "envoyer", "fichier": f, "confirmer": "oui"}, p)
verif("envoyer confirme", p.vu[-1] == ("envoyer", "piece.gcode", 40), p.vu)
verif("annuler sans confirmer = essai", essai({"action": "annuler"}, p)[1].get("essai") and p.vu[-1][0] != "annuler")
essai({"action": "pause"}, p)
verif("pause directe", p.vu[-1] == ("pause",))
verif("action inconnue", essai({"action": "chauffer"}, p)[0].startswith("ERREUR"))
# reglages : reseau local seulement
for ip, attendu in (("8.8.8.8", "local"), ("127.0.0.1", "local"), ("abc", "valable"), ("", "adresse")):
    os.environ["ARCHI_IMPRIMANTE_IP"] = ip
    try:
        I.reglages(); verif("reglages " + ip, False)
    except I.Erreur as e:
        verif("reglages " + (ip or "vide"), attendu in str(e), e)
os.environ.update(ARCHI_IMPRIMANTE_IP="192.168.1.50", ARCHI_IMPRIMANTE_TYPE="octoprint", ARCHI_IMPRIMANTE_CLE="")
try:
    t, b, c = I.reglages(); I.ADAPTATEURS[t](b, c); verif("octoprint sans cle refuse", False)
except I.Erreur as e:
    verif("octoprint sans cle refuse", "cle API" in str(e))
os.environ["ARCHI_IMPRIMANTE_TYPE"] = "moonraker"
verif("moonraker port 7125", I.reglages()[1] == "http://192.168.1.50:7125")
import json as _j
si = set(_j.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "outil.json"), encoding="utf-8"))["sensible_si"]["action"])
manquants = [a for a, v in I.ALIAS.items() if v in ("envoyer", "lancer", "annuler") and a not in si] + [a for a in ("envoyer", "lancer", "annuler") if a not in si]
verif("tous les alias dangereux exigent l'accord", not manquants, manquants)
print(f"{ok} OK, {ko} ECHEC")
sys.exit(1 if ko else 0)
