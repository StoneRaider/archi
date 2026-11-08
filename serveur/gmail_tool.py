# gmail_tool.py

import os
import base64
import pickle
from reglages import chemin, GOOGLE_CLIENT
from email.mime.text import MIMEText
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose"
]


def get_service():
    creds = None

    JETON = chemin("google_gmail.pickle")
    if os.path.exists(JETON):
        with open(JETON, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                # Jeton expire ou revoque : on redemande la connexion Google
                print("[Google] Jeton expire, nouvelle connexion dans le navigateur...")
                creds = None
        if not creds or not creds.valid:
            if not os.path.exists(GOOGLE_CLIENT):
                raise RuntimeError("Gmail non branche : il manque le fichier OAuth Google (voir serveur/LISEZMOI.md)")
            flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CLIENT, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(JETON, "wb") as token:
            pickle.dump(creds, token)

    return build("gmail", "v1", credentials=creds)


def get_unread_emails(max_results=10):
    service = get_service()

    results = service.users().messages().list(
        userId="me",
        labelIds=["UNREAD"],
        maxResults=max_results
    ).execute()

    messages = results.get("messages", [])
    emails = []

    for msg in messages:
        msg_data = service.users().messages().get(
            userId="me",
            id=msg["id"],
            format="metadata",
            metadataHeaders=["From", "Subject"]
        ).execute()

        headers = msg_data["payload"]["headers"]

        subject = next((h["value"] for h in headers if h["name"] == "Subject"), "")
        sender = next((h["value"] for h in headers if h["name"] == "From"), "")

        emails.append({
            "id": msg["id"],
            "from": sender,
            "subject": subject,
            "snippet": msg_data.get("snippet", ""),
            "source": "Gmail"
        })

    return emails


def create_draft_gmail(to, subject, body):
    service = get_service()

    body = f"{body}\n\nGénéré par Archi"
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    service.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw}}
    ).execute()


def mark_as_read(message_id):
    service = get_service()

    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"removeLabelIds": ["UNREAD"]}
    ).execute()


def delete_email(message_id):
    service = get_service()

    service.users().messages().trash(
        userId="me",
        id=message_id
    ).execute()


def delete_archi_drafts():
    service = get_service()

    drafts = service.users().drafts().list(userId="me").execute()
    draft_list = drafts.get("drafts", [])

    for draft in draft_list:
        draft_id = draft["id"]

        full = service.users().drafts().get(
            userId="me",
            id=draft_id
        ).execute()

        payload = full["message"]["payload"]
        body_data = ""

        if "body" in payload and payload["body"].get("data"):
            body_data = base64.urlsafe_b64decode(
                payload["body"]["data"]
            ).decode(errors="ignore")

        if "Généré par Archi" in body_data or "Généré par Archie" in body_data:
            service.users().drafts().delete(
                userId="me",
                id=draft_id
            ).execute()


delete_archie_drafts = delete_archi_drafts

def move_to_tri_auto(message_id):
    service = get_service()
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    label = next((l for l in labels if l["name"] == "Tri auto"), None)
    if not label:
        label = service.users().labels().create(userId="me", body={"name": "Tri auto"}).execute()
    service.users().messages().modify(
        userId="me", id=message_id,
        body={"addLabelIds": [label["id"]], "removeLabelIds": ["INBOX"]}
    ).execute()