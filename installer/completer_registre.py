# completer_registre.py - ajoute au registre des outils de l'utilisateur les outils NOUVEAUX de cette version d'Archi.
# Un outil deja inscrit n'est jamais modifie (l'utilisateur a pu le regler) et rien n'est retire.
#   python completer_registre.py <registre d'exemple> <registre de l'utilisateur>
import json
import os
import sys

source, cible = sys.argv[1], sys.argv[2]
with open(source, encoding="utf-8") as h:
    nouveaux = json.load(h)
with open(cible, encoding="utf-8-sig") as h:
    registre = json.load(h)
ajoutes = [nom for nom in nouveaux if nom not in registre]
for nom in ajoutes:
    registre[nom] = nouveaux[nom]
if ajoutes:
    with open(cible + ".tmp", "w", encoding="utf-8", newline="\n") as h:
        json.dump(registre, h, ensure_ascii=False, indent=1)
    os.replace(cible + ".tmp", cible)
print(", ".join(ajoutes))
