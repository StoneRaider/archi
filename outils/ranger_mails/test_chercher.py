# Tests sans Internet de l'action « chercher » (lecture seule), avec une fausse boite. 05/11/2026.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ranger_mails as rm  # noqa: E402

ok = ko = 0


def verifier(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print("OK  ", nom)
    else:
        ko += 1
        print("ECHEC", nom, detail)


class FausseBoite:
    nom = "Outlook"
    MAILS = {"envoyes": [{"id": "1", "de": "camille@example.com", "a": "Cabinet Exemple <compta@example.com>",
                          "sujet": "Comptes 2026", "date": "2026-11-02T17:00:00Z"},
                         {"id": "2", "de": "camille@example.com", "a": "Famille <famille@example.org>", "sujet": "Noel", "date": "2026-11-01"}],
             "": [{"id": "3", "de": "factures@example.net", "a": "camille@example.com", "sujet": "Facture", "date": "2026-11-03"}]}

    def __init__(self):
        self.bouge = 0

    def lister(self, dans, c, limite):
        liste = self.MAILS.get(rm.dossier_special(dans), self.MAILS[""] if rm.est_reception(dans) else [])
        res = [m for m in liste if (not c["destinataire"] or c["destinataire"].lower() in m["a"].lower())
               and (not c["sujet"] or c["sujet"].lower() in m["sujet"].lower())]
        return res[:limite]

    def deplacer(self, *_a):
        self.bouge += 1

    def creer(self, *_a):
        self.bouge += 1


boites = []


def fab():
    b = FausseBoite()
    boites.append(b)
    return b


phrase, extra = rm.executer({"compte": "outlook", "action": "chercher", "dans": "Éléments envoyés",
                             "destinataire": "compta@example"}, fab)
verifier("envoyes + destinataire : 1 mail trouve", extra["nombre"] == 1 and "compta@example" in extra["mails"][0]["a"], phrase)
verifier("rien n'a bouge", "rien n'a bouge" in phrase and boites[-1].bouge == 0, phrase)
phrase, extra = rm.executer({"compte": "outlook", "action": "rechercher", "dans": "sent"}, fab)
verifier("alias rechercher + sent", extra["nombre"] == 2, phrase)
phrase, extra = rm.executer({"compte": "outlook", "action": "chercher"}, fab)
verifier("sans dossier = boite de reception", extra["nombre"] == 1 and extra["mails"][0]["id"] == "3", phrase)
phrase, extra = rm.executer({"compte": "outlook", "action": "chercher", "dans": "envoyes", "sujet": "rien du tout"}, fab)
verifier("aucun resultat dit clairement", extra["nombre"] == 0 and "aucun" in phrase, phrase)
for nom, attendu in (("Éléments envoyés", "envoyes"), ("Brouillons", "brouillons"), ("Courrier indésirable", "indesirables"),
                     ("Éléments supprimés", "corbeille"), ("Comptes annuels", "")):
    verifier(f"dossier special {nom} -> {attendu or 'ordinaire'}", rm.dossier_special(nom) == attendu)
try:
    rm.executer({"compte": "outlook", "action": "chercher", "apres": "pas une date"}, fab)
    verifier("date illisible refusee", False)
except rm.Erreur:
    verifier("date illisible refusee", True)
print(f"\n{ok} OK, {ko} echec(s)")
sys.exit(1 if ko else 0)
