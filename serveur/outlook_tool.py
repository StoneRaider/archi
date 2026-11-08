# outlook_tool.py - Outlook / Hotmail par Microsoft Graph (jeton garde dans le dossier de donnees)
import os
import msal
import requests

from reglages import chemin, OUTLOOK_CLIENT_ID as CLIENT_ID, OUTLOOK_TENANT as TENANT_ID
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["Mail.ReadWrite", "Mail.Send"]
CACHE_FILE = chemin("outlook_jeton.bin")
GRAPH = "https://graph.microsoft.com/v1.0"

_cache = msal.SerializableTokenCache()
if os.path.exists(CACHE_FILE):
    _cache.deserialize(open(CACHE_FILE, "r").read())

_app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=_cache) if CLIENT_ID else None


def _save_cache():
    if _cache.has_state_changed:
        with open(CACHE_FILE, "w") as f:
            f.write(_cache.serialize())


def get_token():
    if _app is None:   # Outlook facultatif : le serveur demarre sans, seul Outlook repond « non branche »
        raise RuntimeError("Outlook non branche : mets ARCHI_OUTLOOK_CLIENT_ID dans le .env (voir serveur/LISEZMOI.md)")
    result = None
    accounts = _app.get_accounts()
    if accounts:
        result = _app.acquire_token_silent(SCOPES, account=accounts[0])
    if not result:
        print("[Outlook] Connexion requise, ouverture du navigateur...")
        result = _app.acquire_token_interactive(scopes=SCOPES)
    if "access_token" not in result:
        raise RuntimeError(f"[Outlook] Échec connexion : {result.get('error_description', result)}")
    _save_cache()
    return result["access_token"]


def _call(method, url, **kwargs):
    headers = {"Authorization": f"Bearer {get_token()}"}
    resp = requests.request(method, url, headers=headers, **kwargs)
    if not resp.ok:
        raise RuntimeError(f"[Outlook] Erreur {resp.status_code} : {resp.text[:300]}")
    return resp


def get_unread_emails_outlook(max_results=10):
    url = (f"{GRAPH}/me/mailFolders/inbox/messages?$filter=isRead eq false"
           f"&$top={max_results}&$select=subject,from,bodyPreview,id")
    mails = _call("GET", url).json().get("value", [])
    print(f"[Outlook] {len(mails)} mails non lus récupérés")
    return [{
        "id": m["id"],
        "from": m.get("from", {}).get("emailAddress", {}).get("address", ""),
        "subject": m.get("subject", ""),
        "snippet": m.get("bodyPreview", ""),
        "source": "Outlook",
    } for m in mails]


def create_draft_outlook(to, subject, body):
    body = f"{body}\n\nGénéré par Archi"
    draft = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "toRecipients": [{"emailAddress": {"address": to}}],
    }
    _call("POST", f"{GRAPH}/me/messages", json=draft)
    print(f"[Outlook] Brouillon créé pour {to}")


def mark_as_read_outlook(message_id):
    _call("PATCH", f"{GRAPH}/me/messages/{message_id}", json={"isRead": True})


def delete_email_outlook(message_id):
    _call("DELETE", f"{GRAPH}/me/messages/{message_id}")

def move_to_tri_auto_outlook(message_id):
    folders = _call("GET", f"{GRAPH}/me/mailFolders?$top=100").json().get("value", [])
    folder = next((f for f in folders if f["displayName"] == "Tri auto"), None)
    if not folder:
        folder = _call("POST", f"{GRAPH}/me/mailFolders", json={"displayName": "Tri auto"}).json()
    _call("POST", f"{GRAPH}/me/messages/{message_id}/move", json={"destinationId": folder["id"]})

import base64

def get_planning_pdfs(expediteur, deja_traites, top=25):
    """Mails de l'expéditeur avec un PDF joint, pas encore traités. Du plus ancien au plus récent."""
    url = (f"{GRAPH}/me/mailFolders/inbox/messages?$filter=hasAttachments eq true"
           f"&$top={top}&$select=id,subject,from,receivedDateTime")
    mails = _call("GET", url).json().get("value", [])
    resultats = []
    for m in mails:
        adresse = m.get("from", {}).get("emailAddress", {}).get("address", "").lower()
        if expediteur.lower() not in adresse or m["id"] in deja_traites:
            continue
        pj = _call("GET", f"{GRAPH}/me/messages/{m['id']}/attachments").json().get("value", [])
        for a in pj:
            if a.get("name", "").lower().endswith(".pdf") and a.get("contentBytes"):
                resultats.append({
                    "id": m["id"], "date": m["receivedDateTime"][:10],
                    "nom": a["name"], "contenu": base64.b64decode(a["contentBytes"]),
                })
    return sorted(resultats, key=lambda r: r["date"])