# importer_workflows.py - importe dans n8n le workflow principal et les workflows optionnels, avec leurs ID FIXES :
# ainsi les liens entre eux (Hunter -> outils OSINT, vision...) et les identifiants (.env) marchent sans rien regler.
# Puis il ACTIVE le workflow principal (et le brief du jour si Telegram est branche).
#   python n8n/importer_workflows.py            (lance par installation.bat et par lancer_archi.bat)
#   python n8n/importer_workflows.py --forcer   (reimporte tout : tes modifications dans n8n seront ECRASEES)
# n8n doit etre arrete pendant l'import (la commande ecrit directement dans sa base).
#
# Sans bot Telegram (TELEGRAM_BOT_TOKEN ou ARCHI_TELEGRAM_CHAT_ID vide), les noeuds Telegram du workflow principal
# sont importes DESACTIVES : sinon n8n refuse d'activer le workflow, et l'appli comme la page d'accueil resteraient
# sans reponse. Quand Telegram est branche plus tard (brancher_telegram.bat), le workflow principal est reimporte.
import glob
import hashlib
import json
import os
import sys
import tempfile
import uuid

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
sys.path.insert(0, os.path.dirname(ICI))
import archi_env  # noqa: E402
import _n8n  # noqa: E402

PRINCIPAL = "archi_demo.json"
ID_PRINCIPAL = "ArchiDemo0000001"
ID_BRIEF = "ArchiBrief000001"
TYPES_TELEGRAM = ("n8n-nodes-base.telegramTrigger", "n8n-nodes-base.telegram")
TYPES_WEBHOOK = ("n8n-nodes-base.webhook", "n8n-nodes-base.telegramTrigger")


def telegram_branche(env):
    return bool(env.get("TELEGRAM_BOT_TOKEN") and env.get("ARCHI_TELEGRAM_CHAT_ID"))


def identite_telegram(dossier, creer=True):
    """{node_id, webhook_id, workflow_id} du declencheur Telegram de CETTE installation, tires au hasard une fois.
    Pourquoi : n8n donne a Telegram le jeton secret « <workflow>_<noeud> ». Avec les identifiants du depot, ce jeton
    serait le meme pour tout le monde : quiconque connaitrait l'adresse du tunnel pourrait se faire passer pour Telegram.
    Le portail lit ce fichier et n'accepte que ce chemin et ce jeton."""
    f = os.path.join(dossier, "telegram.json")
    try:
        with open(f, encoding="utf-8") as h:
            d = json.load(h)
        if all(isinstance(d.get(k), str) and len(d[k]) >= 8 for k in ("node_id", "webhook_id")):
            d["workflow_id"] = ID_PRINCIPAL
            return d
    except (OSError, ValueError):
        pass
    if not creer:
        return None
    d = {"workflow_id": ID_PRINCIPAL, "node_id": str(uuid.uuid4()), "webhook_id": str(uuid.uuid4())}
    os.makedirs(dossier, exist_ok=True)
    with open(f, "w", encoding="utf-8") as h:
        json.dump(d, h)
    return d


def adapter(workflow, avec_telegram, identite=None):
    """le workflow principal tel qu'il sera importe : noeuds Telegram desactives s'il n'y a pas de bot,
    et declencheur Telegram aux identifiants de cette installation (voir identite_telegram)"""
    for n in workflow.get("nodes", []):
        if identite and n.get("type") == "n8n-nodes-base.telegramTrigger":
            n["id"] = identite["node_id"]
            n["webhookId"] = identite["webhook_id"]
        if n.get("type") in TYPES_TELEGRAM:
            if avec_telegram:
                n.pop("disabled", None)
            else:
                n["disabled"] = True
        if n.get("type") in TYPES_WEBHOOK and not n.get("webhookId"):
            # sans webhookId, n8n range le webhook sous /webhook/<workflow>/<noeud>/<chemin> : l'appli recevrait un 404
            n["webhookId"] = "archi-" + hashlib.sha256(n.get("name", "").encode("utf-8")).hexdigest()[:24]
    return workflow


def empreinte(fichier):
    """empreinte du fichier du depot : un workflow est reimporte quand une nouvelle version d'Archi le change"""
    with open(fichier, "rb") as h:
        return hashlib.sha256(h.read()).hexdigest()[:16]


def importer(fichier):
    code, _ = _n8n.lancer(["import:workflow", "--input=" + fichier], delai=600)
    return code == 0


def main():
    archi_env.charger()
    base = os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files")
    os.makedirs(base, exist_ok=True)
    dossier_temoins = os.path.join(base, ".workflows_archi_importes")
    os.makedirs(dossier_temoins, exist_ok=True)
    forcer = "--forcer" in sys.argv
    avec_telegram = telegram_branche(os.environ)
    identite = identite_telegram(dossier_temoins)
    # le principal est reimporte si Telegram change d'etat, ou si l'identite du declencheur vient d'etre tiree
    etat_voulu = ("ok telegram" if avec_telegram else "ok sans_telegram") + " " + identite["webhook_id"][:8]

    def temoin(f):
        return os.path.join(dossier_temoins, os.path.basename(f))

    def marque(f):
        # le principal depend aussi de Telegram : il est reimporte quand le bot vient d'etre branche (ou debranche)
        return (etat_voulu if os.path.basename(f) == PRINCIPAL else "ok") + " " + empreinte(f)

    def deja(f):
        try:
            return open(temoin(f), encoding="utf-8").read().strip() == marque(f)
        except OSError:
            return False

    tous = [os.path.join(ICI, PRINCIPAL)] + sorted(glob.glob(os.path.join(ICI, "optionnels", "*.json")))
    # un temoin par fichier : ce qui a deja ete importe n'est reimporte que si le fichier du depot a change
    # (nouvelle version d'Archi) ; sinon tes modifications dans n8n restent
    fichiers = [f for f in tous if forcer or not deja(f)]
    if not fichiers:
        print("Workflows deja importes (python n8n/importer_workflows.py --forcer pour tout reimporter et ECRASER).")
        return 0
    ok = 0
    for f in fichiers:
        a_importer, temporaire = f, None
        if os.path.basename(f) == PRINCIPAL:
            with open(f, encoding="utf-8") as h:
                w = adapter(json.load(h), avec_telegram, identite)
            fd, temporaire = tempfile.mkstemp(prefix="archi_wf_", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as h:
                json.dump(w, h, ensure_ascii=False)
            a_importer = temporaire
        try:
            if importer(a_importer):
                ok += 1
                with open(temoin(f), "w", encoding="utf-8") as h:
                    h.write(marque(f) + "\n")
            else:
                print("Echec de l'import : %s" % os.path.basename(f))
        finally:
            if temporaire:
                try:
                    os.remove(temporaire)
                except OSError:
                    pass
    print("Workflows importes dans n8n : %d sur %d." % (ok, len(fichiers)))
    if ok != len(fichiers):
        print("Les autres : importe-les a la main dans n8n (Workflows > Import from file).")

    # un import laisse toujours le workflow inactif : on rallume ce qui doit tourner
    a_activer = [(ID_PRINCIPAL, "Archi (principal)")] + ([(ID_BRIEF, "brief du jour")] if avec_telegram else [])
    for ident, nom in a_activer:
        code, _ = _n8n.lancer(["update:workflow", "--id=" + ident, "--active=true"], delai=300)
        print(("Workflow active : %s" if code == 0 else "Workflow PAS active (%s) : active-le dans n8n, bouton en haut a droite.") % nom)
    if not avec_telegram:
        print("Telegram n'est pas branche : Archi repond sur la page d'accueil et dans l'appli. (brancher_telegram.bat pour l'ajouter)")
    return 0 if ok == len(fichiers) else 1


if __name__ == "__main__":
    sys.exit(main())
