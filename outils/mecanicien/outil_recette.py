# outil_recette.py - un outil fabrique par le mecanicien d'Archi. Il ne contient pas de programme : sa recette
# (recette.json, a cote) est suivie par le moteur du mecanicien (outils/mecanicien/recette.py), le seul exemplaire.
import os
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(ICI), "mecanicien"))
import recette  # noqa: E402

if __name__ == "__main__":
    recette.main(os.path.join(ICI, "recette.json"))
