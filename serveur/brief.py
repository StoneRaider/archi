# brief.py - le brief quotidien d'Archi, en ecrit (Telegram). Version generique, reglee dans le .env.
#   python brief.py            -> une ligne JSON {"ok": ..., "texte": "..."}
# Rubriques (chacune a 60 s au plus : si un service ne repond pas, elle est sautee et le brief part quand meme) :
#   alertes (catastrophes GDACS rouges, signaux de guerre dans les regions suivies), agenda Google du jour,
#   meteo des lieux choisis, mails importants des dernieres 24 h (Gmail / Outlook), anniversaires (fiches du chateau),
#   relances (memoire/projets/relances.txt), Polymarket (s'il y a eu un gros mouvement), actualite (flux RSS choisis).
# Reglages (.env) :
#   ARCHI_BRIEF_LIEUX   = Maison:48.85,2.35 ; Travail:45.76,4.84      (vide = la derniere position connue)
#   ARCHI_BRIEF_FLUX    = ReliefWeb|https://reliefweb.int/disasters/rss.xml|3 ; Le Monde|https://www.lemonde.fr/rss/une.xml|2
#   ARCHI_REGIONS_ALERTE= france,europe   (mots qui rendent une alerte « proche »)
#   ARCHI_UTILISATEUR, ARCHI_FUSEAU
import concurrent.futures as cf
import html
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reglages import chemin, UTILISATEUR, FUSEAU  # noqa: E402

BASE = os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files")
CHATEAU = os.path.join(BASE, "memoire")
UA = {"User-Agent": "Mozilla/5.0 (Archi, assistant personnel)"}
MAINTENANT = datetime.now()
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _get(url, timeout=20):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def _norm(t):
    t = unicodedata.normalize("NFD", str(t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _liste(env, defaut):
    return [x.strip() for x in (os.environ.get(env) or defaut).split(";") if x.strip()]


# ---------- agenda Google (sans fenetre de connexion : jeton mort = rubrique sautee) ----------
def _google(nom):
    import pickle
    from google.auth.transport.requests import Request
    f = chemin(nom)
    if not os.path.exists(f):
        raise RuntimeError("Google pas encore connecte")
    creds = pickle.load(open(f, "rb"))
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            pickle.dump(creds, open(f, "wb"))
        else:
            raise RuntimeError("connexion Google a refaire")
    return creds


def agenda():
    from googleapiclient.discovery import build
    svc = build("calendar", "v3", credentials=_google("google_agenda.pickle"), cache_discovery=False)
    debut = MAINTENANT.replace(hour=0, minute=0, second=0, microsecond=0)
    items = svc.events().list(calendarId="primary", timeMin=debut.astimezone().isoformat(),
                              timeMax=(debut + timedelta(days=1)).astimezone().isoformat(), singleEvents=True,
                              orderBy="startTime").execute().get("items", [])
    rdv = []
    for e in items:
        s = e["start"].get("dateTime")
        titre = e.get("summary", "(sans titre)")
        if not s:
            rdv.append(("journée", titre))
        elif datetime.fromisoformat(e["end"]["dateTime"]).replace(tzinfo=None) > MAINTENANT:
            rdv.append((f"{datetime.fromisoformat(s):%H:%M}", titre))
    return rdv


# ---------- meteo (Open-Meteo, gratuit, sans cle) ----------
METEO = {0: "grand soleil", 1: "plutôt beau", 2: "nuageux par moments", 3: "couvert", 45: "brouillard", 48: "brouillard givrant",
         51: "bruine", 53: "bruine", 55: "bruine", 61: "pluie faible", 63: "pluie", 65: "forte pluie", 71: "neige faible",
         73: "neige", 75: "forte neige", 80: "averses", 81: "averses", 82: "grosses averses", 85: "averses de neige",
         95: "orages", 96: "orages et grêle", 99: "orages et grêle"}


def lieux_meteo():
    L = []
    for x in _liste("ARCHI_BRIEF_LIEUX", ""):
        m = re.match(r"^(.+?)\s*:\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$", x)
        if m:
            L.append((m.group(1), float(m.group(2)), float(m.group(3))))
    if not L:
        try:
            p = json.load(open(os.path.join(CHATEAU, "position.json"), encoding="utf-8"))
            L.append(("Ici", float(p["lat"]), float(p["lon"])))
        except Exception:
            pass
    return L[:4]


def meteo(lieu, lat, lon):
    u = ("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "timezone": FUSEAU, "forecast_days": 1,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"}))
    d = json.loads(_get(u))["daily"]
    ciel = METEO.get(int(d["weather_code"][0]), "temps variable")
    return (f"• {lieu} : {ciel}, {round(d['temperature_2m_min'][0])} à {round(d['temperature_2m_max'][0])} °C"
            f", pluie {d['precipitation_probability_max'][0]} %")


# ---------- mails importants ----------
GARDER = re.compile(r"commande|livr|exp[ée]di|colis|factur|paiement|virement|rendez-vous|rdv|imp[oô]t|banque|notaire|"
                    r"urssaf|caf\b|assurance|contrat|r[ée]servation|billet|vol |rappel|[ée]ch[ée]ance|urgent|convocation", re.I)
JETER = re.compile(r"newsletter|promo|offre|soldes|% de r[ée]duction|d[ée]couvrez|nouveaut[ée]|recommand|on a trouv[ée]|"
                   r"pour vous|webinar|abonnez|derni[eè]re chance|black friday", re.I)
ROBOT = re.compile(r"no-?reply|ne-?pas-?repondre|notification|newsletter|news@|info@|marketing|mailer", re.I)


def _important(de, sujet, extrait):
    if JETER.search(f"{sujet} {extrait}") and not GARDER.search(sujet):
        return False
    return bool(GARDER.search(sujet)) if ROBOT.search(de) else True


def mails():
    from email.utils import getaddresses
    trouves, erreurs = [], []
    try:
        from googleapiclient.discovery import build
        svc = build("gmail", "v1", credentials=_google("google_gmail.pickle"), cache_discovery=False)
        q = "newer_than:1d -category:promotions -category:social -category:forums -in:sent"
        for m in svc.users().messages().list(userId="me", q=q, maxResults=25).execute().get("messages", []):
            d = svc.users().messages().get(userId="me", id=m["id"], format="metadata", metadataHeaders=["From", "Subject"]).execute()
            h = {x["name"]: x["value"] for x in d["payload"]["headers"]}
            nom, adr = getaddresses([h.get("From", "")])[0]
            trouves.append((nom or adr, adr, h.get("Subject", "(sans objet)"), html.unescape(d.get("snippet", ""))))
    except Exception as e:
        erreurs.append("Gmail : " + str(e)[:80])
    if os.environ.get("ARCHI_OUTLOOK_CLIENT_ID"):
        try:
            from outlook_tool import _call, GRAPH
            depuis = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            url = (f"{GRAPH}/me/mailFolders/inbox/messages?$top=25&$orderby=receivedDateTime desc"
                   f"&$filter=receivedDateTime ge {depuis}&$select=subject,from,bodyPreview")
            for m in _call("GET", url).json().get("value", []):
                e = m.get("from", {}).get("emailAddress", {})
                trouves.append((e.get("name") or e.get("address", ""), e.get("address", ""), m.get("subject", ""), m.get("bodyPreview", "")))
        except Exception as e:
            erreurs.append("Outlook : " + str(e)[:80])
    bons = [t for t in trouves if _important(t[1], t[2], t[3])]
    return {"mails": [f"{nom} — {sujet[:90]}" for nom, _, sujet, _ in bons[:5]], "en_plus": max(0, len(bons) - 5), "erreurs": erreurs}


# ---------- actualite et alertes ----------
def flux_choisis():
    L = []
    for x in _liste("ARCHI_BRIEF_FLUX", "ReliefWeb|https://reliefweb.int/disasters/rss.xml|3"):
        p = [y.strip() for y in x.split("|")]
        if len(p) >= 2 and p[1].startswith("https://"):
            L.append((p[0], p[1], int(p[2]) if len(p) > 2 and p[2].isdigit() else 2))
    return L[:8]


def flux(nom, url, n):
    racine = ET.fromstring(_get(url))
    titres = [re.sub(r"\s+", " ", it.findtext("title") or "").strip() for it in racine.iter("item")]
    if not titres:
        ns = "{http://www.w3.org/2005/Atom}"
        titres = [re.sub(r"\s+", " ", e.findtext(ns + "title") or "").strip() for e in racine.iter(ns + "entry")]
    return [(nom, t) for t in titres if t][:n]


GUERRE = re.compile(r"guerre|mobilisation|frappes?|missiles?|invasion|attaque militaire|nucl[ée]aire|conscription|"
                    r"[ée]tat d'urgence|loi martiale|escalade", re.I)


def alertes():
    sortie = []
    racine = ET.fromstring(_get("https://www.gdacs.org/xml/rss.xml", timeout=30))
    ns = {"gdacs": "http://www.gdacs.org"}
    for it in racine.iter("item"):
        if (it.findtext("gdacs:alertlevel", default="", namespaces=ns) or "").lower() == "red":
            sortie.append("🔴 " + re.sub(r"\s+", " ", it.findtext("title") or "").strip())
    regions = [r.strip().lower() for r in (os.environ.get("ARCHI_REGIONS_ALERTE") or "europe").split(",") if r.strip()]
    proche = re.compile("|".join(re.escape(r) for r in regions), re.I)
    for nom, url, _ in flux_choisis():
        try:
            for _, t in flux(nom, url, 40):
                if GUERRE.search(t) and proche.search(t):
                    sortie.append(f"⚔️ {t} ({nom})")
        except Exception:
            pass
    return list(dict.fromkeys(sortie))[:5]


# ---------- anniversaires (fiches du chateau : « ne le 12 mars » / « date de naissance : 12 mars ») ----------
MOIS_N = {_norm(m): i + 1 for i, m in enumerate(MOIS)}
DATE_RE = re.compile(r"(?:n[ée]e?\s+le|date de naissance\s*:)\s*(?:le\s+)?(\d{1,2}|premier)\s+(" + "|".join(MOIS_N) + r")")


def anniversaires():
    sortie, aujourd = [], MAINTENANT.date()
    dossier = os.path.join(CHATEAU, "personnes")
    if not os.path.isdir(dossier):
        return sortie
    for f in os.listdir(dossier):
        if not f.endswith(".md") or f[0].isupper():
            continue
        texte = _norm(open(os.path.join(dossier, f), encoding="utf-8").read())
        m = DATE_RE.search(texte)
        if not m:
            continue
        jour = 1 if m.group(1) == "premier" else int(m.group(1))
        try:
            prochain = date(aujourd.year, MOIS_N[m.group(2)], jour)
        except ValueError:
            continue
        if prochain < aujourd:
            prochain = date(aujourd.year + 1, prochain.month, prochain.day)
        nom = f[:-3].replace("_", " ").title()
        ecart = (prochain - aujourd).days
        if ecart == 0:
            sortie.append(f"🎂 C'est l'anniversaire de {nom} aujourd'hui !")
        elif ecart == 7:
            sortie.append(f"🎁 Anniversaire de {nom} dans une semaine ({prochain.day} {MOIS[prochain.month - 1]}) : une idée de cadeau ?")
    return sortie


# ---------- relances (une ligne = une relance ; lundi = lignes « lundi: », 1er du mois = « mois: », sinon tous les jours) ----------
def relances():
    r = []
    try:
        with open(os.path.join(CHATEAU, "projets", "relances.txt"), encoding="utf-8-sig") as f:
            for l in f:
                l = l.strip()
                if not l or l.startswith("#"):
                    continue
                if l.lower().startswith("lundi:"):
                    if MAINTENANT.weekday() == 0:
                        r.append("📌 " + l[6:].strip())
                elif l.lower().startswith("mois:"):
                    if MAINTENANT.day == 1:
                        r.append("📌 " + l[5:].strip())
                else:
                    r.append("📌 " + l)
    except OSError:
        pass
    return r[:6]


def polymarket():
    try:
        import subprocess
        outil = os.path.join(BASE, "outils", "indicateur_polymarket", "indicateur_polymarket.py")
        if not os.path.isfile(outil):
            return None
        r = subprocess.run([sys.executable, outil, "--brief"], capture_output=True, timeout=20, encoding="utf-8", errors="replace")
        return json.loads(r.stdout.strip().splitlines()[-1]).get("lignes") or None
    except Exception:
        return None


def main():
    taches = {"agenda": agenda, "mails": mails, "anniv": anniversaires, "alertes": alertes}
    for i, (lieu, lat, lon) in enumerate(lieux_meteo()):
        taches[f"meteo_{i}"] = (lambda lieu=lieu, lat=lat, lon=lon: meteo(lieu, lat, lon))
    for nom, url, n in flux_choisis():
        taches["flux_" + nom] = (lambda nom=nom, url=url, n=n: flux(nom, url, n))
    res, rates = {}, []
    ex = cf.ThreadPoolExecutor(max_workers=len(taches))
    futurs = {k: ex.submit(f) for k, f in taches.items()}
    for k, fu in futurs.items():
        try:
            res[k] = fu.result(timeout=60)
        except Exception:
            rates.append(k)
            res[k] = None
    qui = "" if UTILISATEUR == "l'utilisateur" else f", {UTILISATEUR}"
    L = [f"☀️ Brief du {JOURS[MAINTENANT.weekday()]} {MAINTENANT.day} {MOIS[MAINTENANT.month - 1]}{qui}"]
    if res.get("alertes"):
        L.append("\n🚨 Alertes\n" + "\n".join(res["alertes"]))
    met = [res[k] for k in sorted(res) if k.startswith("meteo_") and res[k]]
    if met:
        L.append("\n🌦️ Météo\n" + "\n".join(met))
    if res.get("agenda"):
        L.append("\n📅 Agenda\n" + "\n".join(f"• {h} — {t}" for h, t in res["agenda"]))
    m = res.get("mails")
    if m and (m["mails"] or m["erreurs"]):
        bloc = [f"• {x}" for x in m["mails"]] + ([f"(+ {m['en_plus']} autres)"] if m["en_plus"] else []) \
            + (["⚠️ " + " ; ".join(m["erreurs"])] if m["erreurs"] else [])
        L.append("\n✉️ Mails importants des dernières 24 h\n" + "\n".join(bloc))
    for bloc in (res.get("anniv") or [], relances()):
        if bloc:
            L.append("\n" + "\n".join(bloc))
    po = polymarket()
    if po:
        L.append("\n🔮 Polymarket\n" + "\n".join(po))
    actu = [f"• {t} ({s})" for nom, _, _ in flux_choisis() for s, t in (res.get("flux_" + nom) or [])]
    if actu:
        L.append("\n🌍 Actualité\n" + "\n".join(actu))
    if rates:
        L.append("\n(rubriques sautées faute de réponse : " + ", ".join(rates) + ")")
    print(json.dumps({"ok": True, "texte": "\n".join(L)[:4000]}, ensure_ascii=False))
    sys.stdout.flush()
    os._exit(0)  # coupe net les rubriques restees bloquees


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print(json.dumps({"ok": False, "texte": f"Le brief a planté : {str(err)[:200]}"}, ensure_ascii=False))
        sys.stdout.flush()
        os._exit(0)
