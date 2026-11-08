"""Tests des regles dures du navigateur (sans navigateur) : adresses interdites, boutons finaux, touches."""
import os, re, sys
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "navigateur.py"), encoding="utf-8").read()
ns = {"re": re}
for nom in ("INTERDITS", "CHAMP_SENSIBLE", "BOUTON_FINAL", "TOUCHES_PERMISES"):
    i = src.index(nom + " = ")
    j = src.index("\n", src.index(")" if nom != "TOUCHES_PERMISES" else "}", i)) if nom == "TOUCHES_PERMISES" else src.index(", re.I)", i) + 7
    exec(src[i:j], ns)
ok = ko = 0
def verif(nom, cond):
    global ok, ko
    ok, ko = (ok + 1, ko) if cond else (ok, ko + 1)
    if not cond:
        print("ECHEC", nom)
for u in ("http://localhost:5678", "http://192.168.1.1", "http://x@127.0.0.1", "https://imprimante.local/", "javascript:alert(1)",
          "http://10.0.0.2", "https://172.20.1.1", "http://169.254.169.254/", "file:///C:/", "http://[::1]/"):
    verif("interdit " + u, bool(ns["INTERDITS"].search(u)))
for u in ("https://exemple.fr", "https://www.service-public.fr/demarche"):
    verif("permis " + u, not ns["INTERDITS"].search(u))
for b in ("Payer", "Commander", "Send", "Place order", "Supprimer le compte", "Confirmer", "Réserver", "Finaliser ma commande", "Envoyer"):
    verif("bouton final " + b, bool(ns["BOUTON_FINAL"].search(b)))
for b in ("Suivant", "Voir le panier", "Rechercher", "Fermer"):
    verif("bouton normal " + b, not ns["BOUTON_FINAL"].search(b))
verif("Entree non permise par defaut", "Enter" not in ns["TOUCHES_PERMISES"] and "Space" not in ns["TOUCHES_PERMISES"])
verif("champ mot de passe sensible", bool(ns["CHAMP_SENSIBLE"].search("input password Mot de passe")))
# hote_public : toutes les requetes de la page passent par lui
import functools, ipaddress, socket
i = src.index("@functools.lru_cache(maxsize=512)\ndef hote_public")
j = src.index("\n\n\ndef proteger", i)
exec(src[i:j], ns.update({"functools": functools, "ipaddress": ipaddress, "socket": socket}) or ns)
for h in ("localhost", "127.0.0.1", "2130706433", "0x7f.0.0.1", "0", "192.168.1.1", "10.0.0.1", "169.254.169.254", "", "::1"):
    verif("hote prive bloque " + repr(h), not ns["hote_public"](h))
seul = "SEUL_DANS_SON_FORMULAIRE" in src and "champ.evaluate(SEUL_DANS_SON_FORMULAIRE)" in src
verif("Entree dans chercher : seulement un champ seul dans son formulaire", seul)
verif("telecharger controle les boutons finaux", 'if action == "telecharger":' in src and src.index("BOUTON_FINAL.search(desc) or el.evaluate", src.index('if action == "telecharger":')) > 0)
verif("retirer sans cible refuse", "Quelle page dois-je retirer" in src)
print(f"{ok} OK, {ko} ECHEC")
sys.exit(1 if ko else 0)
