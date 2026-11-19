# agenda.py - l'agenda Google de l'utilisateur, pour Archi.
#   python agenda.py --fichier demande.json
#   {"action": "ajouter", "titre": "...", "debut": "2026-11-26T13:00", "fin": "2026-11-26T15:00", "lieu": "", "notes": "", "rappel_min": 30}
#   {"action": "ajouter", "titre": "...", "jour": "2026-11-26"}            -> evenement sur la journee entiere
#   {"action": "lister", "de": "2026-11-26", "a": "2026-11-27"}             -> evenements de la periode
#   {"action": "chercher", "texte": "club"}                           -> evenements a venir qui contiennent ce texte
# Utilise la connexion Google deja en place (calendar_tool.py, meme dossier). Repond une ligne JSON.

import json
import os
import sys
from datetime import datetime, timedelta

ICI = os.path.dirname(os.path.abspath(__file__))
os.chdir(ICI)                       # le jeton Google est range a cote
sys.path.insert(0, ICI)
from calendar_tool import get_calendar_service   # noqa: E402

TZ = os.environ.get("ARCHI_FUSEAU", "Europe/Paris")
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def _qui():
    """« , Camille » : le prenom du profil (ARCHI_UTILISATEUR, regle a l'installation) ; rien s'il manque."""
    p = " ".join((os.environ.get("ARCHI_UTILISATEUR") or "").split())[:30]
    return (", " + p) if p else ""


def _rfc3339(dt):
    """heure locale (fuseau ARCHI_FUSEAU) -> RFC 3339 avec le bon decalage (et non UTC)"""
    if dt.tzinfo is None:
        try:
            from zoneinfo import ZoneInfo
            dt = dt.replace(tzinfo=ZoneInfo(TZ))
        except Exception:
            dt = dt.astimezone()   # fuseau du PC
    return dt.isoformat()


def lisible(dt):
    return f"{JOURS[dt.weekday()]} {dt.day} {MOIS[dt.month - 1]} {dt.year}"


def heure(dt):
    return f"{dt.hour} h {dt.minute:02d}" if dt.minute else f"{dt.hour} h"


def lire_date(t):
    t = str(t).strip().replace(" ", "T")
    for f in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(t[:19] if "T" in t else t[:10], f)
        except ValueError:
            pass
    raise ValueError(f"date illisible : « {t} » (attendu AAAA-MM-JJ ou AAAA-MM-JJTHH:MM)")


def decrire(e):
    s, f = e.get("start", {}), e.get("end", {})
    if "dateTime" in s:
        a = datetime.fromisoformat(s["dateTime"][:19])
        b = datetime.fromisoformat(f["dateTime"][:19])
        quand = f"{lisible(a)}, {heure(a)} - {heure(b)}"
    else:
        quand = f"{lisible(datetime.fromisoformat(s['date']))}, toute la journée"
    return f"{quand} : {e.get('summary', '(sans titre)')}" + (f" ({e['location']})" if e.get("location") else "")


def evenements(service, debut, fin, texte=""):
    r = service.events().list(calendarId="primary", timeMin=_rfc3339(debut),
                              timeMax=_rfc3339(fin),
                              singleEvents=True, orderBy="startTime", q=texte or None, maxResults=50).execute()
    return r.get("items", [])


def ajouter(d):
    titre = str(d.get("titre") or "").strip()
    if not titre:
        return {"ok": False, "phrase_pour_utilisateur": "Il me manque le titre de l'événement" + _qui() + "."}
    service = get_calendar_service()
    corps = {"summary": titre[:200]}
    if d.get("lieu"):
        corps["location"] = str(d["lieu"])[:200]
    if d.get("notes"):
        corps["description"] = str(d["notes"])[:2000]
    if d.get("debut"):
        a = lire_date(d["debut"])
        b = lire_date(d["fin"]) if d.get("fin") else a + timedelta(hours=1)
        if b <= a:
            return {"ok": False, "phrase_pour_utilisateur": "La fin est avant le début, je n'ai rien ajouté" + _qui() + ". Tu me redonnes les heures ?"}
        if a < datetime.now() - timedelta(hours=1):
            return {"ok": False, "phrase_pour_utilisateur": f"Le {lisible(a)} est déjà passé, je n'ai rien ajouté. Tu voulais quelle année ?"}
        corps["start"] = {"dateTime": a.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": TZ}
        corps["end"] = {"dateTime": b.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": TZ}
        quand = f"le {lisible(a)} de {heure(a)} à {heure(b)}"
        conflits = [e for e in evenements(service, a - timedelta(hours=2), b + timedelta(hours=2))
                    if "dateTime" in e.get("start", {}) and datetime.fromisoformat(e["start"]["dateTime"][:19]) < b
                    and datetime.fromisoformat(e["end"]["dateTime"][:19]) > a]
    elif d.get("jour"):
        a = lire_date(d["jour"])
        corps["start"] = {"date": a.strftime("%Y-%m-%d")}
        corps["end"] = {"date": (a + timedelta(days=1)).strftime("%Y-%m-%d")}
        quand = f"le {lisible(a)}, toute la journée"
        conflits = []
    else:
        return {"ok": False, "phrase_pour_utilisateur": "Il me manque la date (et les heures) de l'événement" + _qui() + "."}
    rappel = d.get("rappel_min")
    if rappel not in (None, ""):
        corps["reminders"] = {"useDefault": False, "overrides": [{"method": "popup", "minutes": int(float(rappel))}]}
    e = service.events().insert(calendarId="primary", body=corps).execute()
    # verification : on relit l'evenement dans l'agenda
    verif = service.events().get(calendarId="primary", eventId=e["id"]).execute()
    phrase = f"C'est dans ton agenda{_qui()} : « {verif.get('summary')} » {quand}."
    if conflits:
        phrase += " Attention, ça tombe en même temps que : " + " ; ".join(decrire(c) for c in conflits[:3]) + "."
    return {"ok": True, "verifie": True, "id": e["id"], "lien": e.get("htmlLink"), "phrase_pour_utilisateur": phrase}


def lister(d):
    a = lire_date(d.get("de") or datetime.now().strftime("%Y-%m-%d"))
    b = lire_date(d["a"]) if d.get("a") else a + timedelta(days=1)
    if b <= a:
        b = a + timedelta(days=1)
    L = evenements(get_calendar_service(), a - timedelta(hours=1), b + timedelta(hours=1))
    L = [e for e in L if a <= datetime.fromisoformat((e["start"].get("dateTime") or e["start"]["date"])[:19]) < b]
    return {"ok": True, "evenements": [decrire(e) for e in L],
            "phrase_pour_utilisateur": ("Rien dans ton agenda sur cette période." if not L else f"{len(L)} événement(s) : " + " ; ".join(decrire(e) for e in L[:8]))}


def chercher(d):
    texte = str(d.get("texte") or "").strip()
    a = datetime.now() - timedelta(days=int(d.get("jours_avant") or 30))
    L = evenements(get_calendar_service(), a, datetime.now() + timedelta(days=400), texte)
    return {"ok": True, "evenements": [decrire(e) for e in L],
            "phrase_pour_utilisateur": (f"Rien trouvé pour « {texte} » dans ton agenda." if not L else " ; ".join(decrire(e) for e in L[:8]))}


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--fichier":
        with open(sys.argv[2], encoding="utf-8") as f:
            d = json.load(f)
    else:
        d = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    a = str(d.get("action") or "lister").lower()
    r = ajouter(d) if a.startswith("ajout") else chercher(d) if a.startswith("cherch") else lister(d)
    print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print(json.dumps({"ok": False, "erreur": str(err)[:300],
                          "phrase_pour_utilisateur": "Je n'ai PAS pu toucher à ton agenda" + _qui() + " : " + str(err)[:150]}, ensure_ascii=False))
