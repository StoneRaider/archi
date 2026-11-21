# inscrire_outils.py - recopie la fiche d'un outil (outils/<nom>/outil.json) dans le registre d'exemple du depot
# (chateau_exemple/outils/registre.json), celui qu'une installation neuve recoit et que completer_registre.py ajoute a
# une installation existante.
#   python outils_depot/inscrire_outils.py agenda recherche_web      inscrit ou met a jour ces outils
#   python outils_depot/inscrire_outils.py --verifier                dit quelles fiches different du registre (code 1 s'il y en a)
import json
import os
import sys

DEPOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRE = os.path.join(DEPOT, "chateau_exemple", "outils", "registre.json")


def fiche(nom):
    with open(os.path.join(DEPOT, "outils", nom, "outil.json"), encoding="utf-8") as h:
        f = json.load(h)
    if f.get("nom") != nom:
        raise SystemExit("outils/%s/outil.json : le nom ecrit dedans est « %s »" % (nom, f.get("nom")))
    return f


def main():
    with open(REGISTRE, encoding="utf-8") as h:
        registre = json.load(h)
    if "--verifier" in sys.argv:
        ecarts = [n for n in sorted(os.listdir(os.path.join(DEPOT, "outils")))
                  if os.path.exists(os.path.join(DEPOT, "outils", n, "outil.json")) and registre.get(n) != fiche(n)]
        print("fiches differentes du registre : " + (", ".join(ecarts) or "aucune"))
        return 1 if ecarts else 0
    noms = [a for a in sys.argv[1:] if not a.startswith("--")]
    for nom in noms:
        registre[nom] = fiche(nom)
    with open(REGISTRE, "w", encoding="utf-8", newline="\n") as h:
        json.dump(registre, h, ensure_ascii=False, indent=1)
        h.write("\n")
    print("inscrits : " + ", ".join(noms))
    return 0


if __name__ == "__main__":
    sys.exit(main())
