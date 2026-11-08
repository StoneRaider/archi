"""Tests de liasse_fiscale.py sur l'entreprise fictive de historique.exemple.json (faux dossier, rien de reel)."""
import json, os, shutil, subprocess, sys, tempfile
ICI = os.path.dirname(os.path.abspath(__file__))
D = tempfile.mkdtemp(prefix="liasse_")
shutil.copy(os.path.join(ICI, "historique.exemple.json"), os.path.join(D, "historique.json"))
ENV = dict(os.environ, ARCHI_LIASSE_HISTO=os.path.join(D, "historique.json"), ARCHI_BASE=D, ARCHI_PY="")
ok = ko = 0


def appel(**d):
    f = os.path.join(D, "demande.json")
    json.dump(d, open(f, "w", encoding="utf-8"))
    out = subprocess.run([sys.executable, os.path.join(ICI, "liasse_fiscale.py"), "--fichier", f], capture_output=True, env=ENV)
    return json.loads(out.stdout.decode("utf-8").strip().splitlines()[-1])


def verif(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
    else:
        ko += 1
        print("ECHEC", nom, str(detail)[:300])


r = appel(action="preparer", annee=2026, recettes=5400, assurance=250, honoraires=600)
verif("preparer 2026", r["ok"] and r["resultat"] == 3070.0, r)
verif("case 5NC dans la phrase", "5NC" in r["phrase_pour_utilisateur"], r)
verif("montants estimes signales", any("tva" in e for e in r["estimes"]), r)
verif("fiche ecrite dans le faux dossier", os.path.isfile(r["fiche_md"]) and r["fiche_md"].startswith(D), r)
r = appel(action="preparer", annee=2028, recettes=1)
verif("annee non enchainee refusee", not r["ok"] and "clôturer" in r["phrase_pour_utilisateur"], r)
r = appel(action="cloturer", annee=2026)
verif("cloturer sans confirmer : essai a blanc", "Essai" in r["phrase_pour_utilisateur"] and "2026" not in json.load(open(os.path.join(D, "historique.json"), encoding="utf-8"))["annees"], r)
r = appel(action="synthese")
verif("synthese", r["ok"] and "2025" in r["phrase_pour_utilisateur"], r)
r = appel(action="n_importe_quoi")
verif("action inconnue", not r["ok"], r)
print(f"{ok} OK, {ko} ECHEC")
sys.exit(1 if ko else 0)
