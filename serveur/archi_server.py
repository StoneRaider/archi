# archi_server.py - serveur local (127.0.0.1) qui expose les mails a n8n : chercher, lire, contacts, preparer puis envoyer, tri
import threading
import traceback
from datetime import datetime

import uvicorn
from fastapi import FastAPI, Query
from outlook_tool import _call, GRAPH
from email_orchestrator import nettoyage_complet
import mail_commande
from reglages import PORT
from pydantic import BaseModel

app = FastAPI(title="Archi - serveur local")

HOTES_PERMIS = {"127.0.0.1", "localhost", "[::1]"}


@app.middleware("http")
async def seulement_n8n(request, call_next):
    """Anti-CSRF / anti-rebinding : une page web ouverte dans un navigateur ne doit pas pouvoir appeler le serveur
    (ex. envoyer le mail deja prepare). Un navigateur envoie Origin / Sec-Fetch-Site ; n8n, non. Et l'hote doit
    etre local (une adresse web qui pointerait vers 127.0.0.1 est refusee)."""
    from fastapi.responses import JSONResponse
    hote = (request.headers.get("host") or "").rsplit(":", 1)[0].lower()
    site = (request.headers.get("sec-fetch-site") or "").lower()
    directe = request.method == "GET" and request.url.path == "/sante" and site in ("", "none")
    if hote not in HOTES_PERMIS or (not directe and (request.headers.get("origin") or site)):
        return JSONResponse({"ok": False, "resultat": "refuse : appel depuis un navigateur ou une adresse non locale"}, status_code=403)
    return await call_next(request)

# Empêche deux traitements de tourner en même temps
verrou = threading.Lock()
etat_tri = {"en_cours": False, "dernier_lancement": None, "dernier_bilan": None}


@app.get("/sante")
def sante():
    return {"ok": True, "message": "Serveur Archi en ligne"}



def _traiter_en_fond():
    """Lance le tri complet en arrière-plan (peut durer plusieurs minutes)."""
    etat_tri["en_cours"] = True
    etat_tri["dernier_lancement"] = datetime.now().strftime("%d/%m %H:%M")
    try:
        bilan = nettoyage_complet(pause_secondes=10, max_passages=10)
        etat_tri["dernier_bilan"] = bilan
    except Exception as e:
        etat_tri["dernier_bilan"] = f"Erreur : {e}"
    finally:
        etat_tri["en_cours"] = False
        verrou.release()


@app.post("/mails/traiter")
def mails_traiter():
    if not verrou.acquire(blocking=False):
        return {"ok": True, "resultat": "Le traitement des mails est déjà en cours."}
    threading.Thread(target=_traiter_en_fond, daemon=True).start()
    return {"ok": True, "resultat": "Traitement des mails non lus lancé."}


@app.get("/mails/etat")
def mails_etat():
    return {"ok": True, **etat_tri}


@app.get("/mails/chercher")
def mails_chercher(
    texte: str = Query("", description="Mot-clé, expéditeur ou sujet"),
    date: str = Query("", description="Date AAAA-MM-JJ, optionnelle"),
    boite: str = Query("toutes", description="gmail, outlook ou toutes"),
    max: int = 10,
):
    try:
        return mail_commande.chercher(texte, date, boite, max)
    except Exception as e:
        return {"ok": False, "resultat": f"Erreur recherche : {e}"}


@app.get("/mails/lire")
def mails_lire(id: str, boite: str = "outlook"):
    try:
        return mail_commande.lire(id, boite)
    except Exception as e:
        return {"ok": False, "resultat": f"Erreur lecture : {e}"}


@app.get("/contacts/chercher")
def contacts_chercher(nom: str = Query(..., description="Nom ou prénom du contact")):
    try:
        return mail_commande.chercher_contact(nom)
    except Exception as e:
        return {"ok": False, "resultat": f"Erreur contact : {e}"}


class MailAPreparer(BaseModel):
    a: str
    sujet: str = ""
    corps: str = ""
    boite: str = "gmail"


@app.post("/mails/preparer")
def mails_preparer(m: MailAPreparer):
    try:
        return mail_commande.preparer(m.a, m.sujet, m.corps, m.boite)
    except Exception as e:
        return {"ok": False, "statut": "ERREUR", "phrase_pour_utilisateur": f"Je n'ai pas pu préparer le mail BOSS : {e}"}


@app.post("/mails/envoyer")
def mails_envoyer():
    try:
        return mail_commande.envoyer()
    except Exception as e:
        return {"ok": False, "statut": "ERREUR", "phrase_pour_utilisateur": f"Le mail n'est PAS parti BOSS : {e}"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)   # jamais expose hors du PC