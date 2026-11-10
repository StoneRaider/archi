# Tests de l'import des workflows (hors ligne, sans n8n) :
#   python n8n/test_importer.py
# Sans bot Telegram, le workflow principal doit rester activable : ses noeuds Telegram sont importes desactives.
import copy
import json
import os
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
import importer_workflows as imp  # noqa: E402
import creer_identifiants as ident  # noqa: E402

echecs = 0


def verifier(nom, condition):
    global echecs
    print(("ok   " if condition else "ECHEC") + " " + nom)
    if not condition:
        echecs += 1


with open(os.path.join(ICI, imp.PRINCIPAL), encoding="utf-8") as h:
    ORIGINAL = json.load(h)

verifier("le workflow principal porte l'identifiant attendu", ORIGINAL.get("id") == imp.ID_PRINCIPAL)
telegram = [n for n in ORIGINAL["nodes"] if n["type"] in imp.TYPES_TELEGRAM]
verifier("le workflow principal a un declencheur et deux envois Telegram", len(telegram) == 3)

sans = imp.adapter(copy.deepcopy(ORIGINAL), avec_telegram=False)
verifier("sans bot : tous les noeuds Telegram sont desactives",
         all(n.get("disabled") is True for n in sans["nodes"] if n["type"] in imp.TYPES_TELEGRAM))
verifier("sans bot : aucun autre noeud n'est touche",
         all(not n.get("disabled") for n in sans["nodes"] if n["type"] not in imp.TYPES_TELEGRAM))
verifier("sans bot : les webhooks de l'appli et le reveil du planificateur restent la",
         {"Appli telephone", "Boite appli", "Chaque minute"} <= {n["name"] for n in sans["nodes"] if not n.get("disabled")})

avec = imp.adapter(copy.deepcopy(sans), avec_telegram=True)
verifier("avec bot : les noeuds Telegram sont rallumes",
         all("disabled" not in n for n in avec["nodes"] if n["type"] in imp.TYPES_TELEGRAM))
declencheur = [n for n in avec["nodes"] if n["type"] == "n8n-nodes-base.telegramTrigger"][0]
verifier("le declencheur Telegram garde son adresse", bool(declencheur.get("webhookId"))
         and declencheur["webhookId"] == [n for n in ORIGINAL["nodes"] if n["type"] == "n8n-nodes-base.telegramTrigger"][0].get("webhookId"))
# sans webhookId, n8n sert /webhook/<workflow>/<noeud>/telephone-archi au lieu de /webhook/telephone-archi (404 pour l'appli)
verifier("chaque webhook du workflow principal a un webhookId (sinon l'appli recoit un 404)",
         all(n.get("webhookId") for n in ORIGINAL["nodes"] if n["type"] in imp.TYPES_WEBHOOK))
ancien = copy.deepcopy(ORIGINAL)
for n in ancien["nodes"]:
    n.pop("webhookId", None)
repare = imp.adapter(ancien, avec_telegram=False)
verifier("un vieux fichier sans webhookId est repare a l'import",
         all(n.get("webhookId") for n in repare["nodes"] if n["type"] in imp.TYPES_WEBHOOK))
for f in sorted(os.listdir(os.path.join(ICI, "optionnels"))):
    if f.endswith(".json"):
        w = json.load(open(os.path.join(ICI, "optionnels", f), encoding="utf-8"))
        verifier("optionnels/%s : pas de webhook sans webhookId" % f,
                 all(n.get("webhookId") for n in w["nodes"] if n["type"] in imp.TYPES_WEBHOOK))
verifier("le fichier d'origine n'est pas modifie", '"disabled"' not in json.dumps(ORIGINAL))

verifier("Telegram branche = jeton ET numero de chat",
         imp.telegram_branche({"TELEGRAM_BOT_TOKEN": "x", "ARCHI_TELEGRAM_CHAT_ID": "1"})
         and not imp.telegram_branche({"TELEGRAM_BOT_TOKEN": "x"})
         and not imp.telegram_branche({"ARCHI_TELEGRAM_CHAT_ID": "1"}))

brief = json.load(open(os.path.join(ICI, "optionnels", "brief.json"), encoding="utf-8"))
verifier("le brief du jour porte l'identifiant attendu", brief.get("id") == imp.ID_BRIEF)

# identifiants : LM Studio toujours, Telegram seulement avec un jeton ; l'empreinte change avec eux
base = ident.identifiants({})
verifier("sans .env : seul l'identifiant LM Studio est cree", [c["id"] for c in base] == [ident.ID_LM])
avec_tg = ident.identifiants({"TELEGRAM_BOT_TOKEN": "jeton-de-test"})
verifier("avec jeton : l'identifiant Telegram s'ajoute", [c["id"] for c in avec_tg] == [ident.ID_LM, ident.ID_TELEGRAM])
verifier("l'empreinte change quand les identifiants changent", ident.empreinte(base) != ident.empreinte(avec_tg))
verifier("l'empreinte ne contient pas le jeton", "jeton-de-test" not in ident.empreinte(avec_tg))

print("%d echec(s)" % echecs)
sys.exit(1 if echecs else 0)
