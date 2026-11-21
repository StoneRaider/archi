# calendar_tool.py

import json
import os
import pickle
from reglages import chemin, GOOGLE_CLIENT, FUSEAU
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

SCOPES = ["https://www.googleapis.com/auth/calendar"]

# couleurs d'agenda par mot-cle (facultatif) : donnees/couleurs_agenda.json {"reunion": "2", "sport": "5"}
try:
    SITE_COLORS = {k.lower(): str(v) for k, v in json.load(open(chemin("couleurs_agenda.json"), encoding="utf-8")).items()}
except Exception:
    SITE_COLORS = {}

def get_calendar_service():
    creds = None

    JETON = chemin("google_agenda.pickle")
    if os.path.exists(JETON):
        with open(JETON, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                # Jeton expire ou revoque : on redemande la connexion Google
                creds = None
        if not creds or not creds.valid:
            if not os.path.exists(GOOGLE_CLIENT):
                raise RuntimeError("Agenda non branche : il manque le fichier OAuth Google (voir serveur/LISEZMOI.md)")
            # Appele par l'outil maison (outils/agenda) : jamais de fenetre de connexion ouverte dans le dos de
            # l'utilisateur. La connexion se refait a la main, une fois : python serveur/agenda.py
            if os.environ.get("ARCHI_AGENDA_SANS_NAVIGATEUR") == "1":
                raise RuntimeError("la connexion Google a expire. Pour la refaire, lance une fois « python serveur/agenda.py » sur le PC")
            print("[Google] Connexion dans le navigateur...")
            flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CLIENT, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(JETON, "wb") as token:
            pickle.dump(creds, token)

    return build("calendar", "v3", credentials=creds)


def add_event(summary, start_iso, end_iso, description, site=""):
    service = get_calendar_service()

    color = next((c for mot, c in SITE_COLORS.items() if mot in (site or summary or "").lower()), None)

    event = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_iso, "timeZone": FUSEAU},
        "end": {"dateTime": end_iso, "timeZone": FUSEAU},
    }
    if color:
        event["colorId"] = color

    service.events().insert(calendarId="primary", body=event).execute()


def check_conflict(start_iso, end_iso):
    service = get_calendar_service()

    events = service.events().list(
        calendarId="primary",
        timeMin=start_iso,
        timeMax=end_iso
    ).execute()

    return len(events.get("items", [])) > 0