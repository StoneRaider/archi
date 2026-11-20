# mail_commande.py — mails sur commande d'Archi : chercher, lire, contacts, preparer, envoyer
# Regle : un mail n'est envoye qu'apres un apercu valide par J (deux appels distincts).
import base64
import hashlib
import html
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta
from email.header import Header
from email.mime.text import MIMEText
from email.utils import getaddresses

from gmail_tool import get_service
from outlook_tool import _call, GRAPH

from reglages import chemin
EN_ATTENTE = chemin("mail_en_attente.json")
ADRESSE_OK = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[a-zA-Z]{2,}$")
DUREE_VALIDITE = timedelta(hours=2)


# ---------- outils ----------
def _qui():
    """« , Camille » : le prenom du profil (ARCHI_UTILISATEUR, regle a l'installation) ; rien s'il manque."""
    p = " ".join((os.environ.get("ARCHI_UTILISATEUR") or "").split())[:30]
    return (", " + p) if p else ""


def _norm(t):
    t = unicodedata.normalize("NFD", str(t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _boites(boite):
    b = _norm(boite).strip()
    if b in ("gmail", "google"):
        return ["gmail"]
    if b in ("outlook", "hotmail", "microsoft"):
        return ["outlook"]
    return ["gmail", "outlook"]


def _html_en_texte(h):
    h = re.sub(r"(?is)<(script|style).*?</\1>", " ", h or "")
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", h)
    h = re.sub(r"<[^>]+>", " ", h)
    h = html.unescape(h)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", h)).strip()


def _destinataires(a):
    liste = [x.strip() for x in re.split(r"[,;]", str(a or "")) if x.strip()]
    if not liste:
        raise ValueError("aucun destinataire")
    mauvais = [x for x in liste if not ADRESSE_OK.match(x)]
    if mauvais:
        raise ValueError("adresse invalide : " + ", ".join(mauvais) +
                         " (utilise chercher_contact pour trouver l'adresse)")
    return liste


# ---------- recherche ----------
def _chercher_gmail(texte, date, maxi):
    service = get_service()
    q = texte or ""
    if date:
        j = datetime.strptime(date, "%Y-%m-%d")
        q += f" after:{j:%Y/%m/%d} before:{j + timedelta(days=1):%Y/%m/%d}"
    res = service.users().messages().list(userId="me", q=q.strip(), maxResults=maxi).execute()
    mails = []
    for m in res.get("messages", []):
        d = service.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"]).execute()
        h = {x["name"]: x["value"] for x in d["payload"]["headers"]}
        quand = datetime.fromtimestamp(int(d.get("internalDate", "0")) / 1000)
        mails.append({
            "boite": "gmail", "id": m["id"],
            "de": getaddresses([h.get("From", "")])[0][1] if h.get("From") else "",
            "date": f"{quand:%Y-%m-%d %H:%M}", "sujet": h.get("Subject", ""),
            "extrait": html.unescape(d.get("snippet", ""))[:200],
        })
    return mails


def _chercher_outlook(texte, date, maxi):
    champs = "&$select=id,subject,from,receivedDateTime,bodyPreview,hasAttachments"
    trouves = {}
    mot = _norm(texte)
    url = f"{GRAPH}/me/messages?$top=50&$orderby=receivedDateTime desc" + champs
    if date:
        url += (f"&$filter=receivedDateTime ge {date}T00:00:00Z "
                f"and receivedDateTime lt {date}T23:59:59Z")
    for m in _call("GET", url).json().get("value", []):
        exp = m.get("from", {}).get("emailAddress", {})
        botte = _norm(" ".join([exp.get("address", ""), exp.get("name", ""),
                                m.get("subject", ""), m.get("bodyPreview", "")]))
        if not mot or mot in botte:
            trouves[m["id"]] = m
    if texte:
        url = f'{GRAPH}/me/messages?$top=25&$search="{texte}"' + champs
        for m in _call("GET", url).json().get("value", []):
            if date and not m["receivedDateTime"].startswith(date):
                continue
            trouves.setdefault(m["id"], m)
    return [{
        "boite": "outlook", "id": m["id"],
        "de": m.get("from", {}).get("emailAddress", {}).get("address", ""),
        "date": m["receivedDateTime"][:16].replace("T", " "),
        "sujet": m.get("subject", ""), "extrait": m.get("bodyPreview", "")[:200],
    } for m in trouves.values()]


def chercher(texte="", date="", boite="toutes", maxi=10):
    mails, erreurs = [], []
    for b in _boites(boite):
        try:
            mails += _chercher_gmail(texte, date, maxi) if b == "gmail" else _chercher_outlook(texte, date, maxi)
        except Exception as e:
            erreurs.append(f"{b} : {e}")
    mails.sort(key=lambda m: m["date"], reverse=True)
    return {"ok": not (erreurs and not mails), "nombre": len(mails[:maxi]), "mails": mails[:maxi], "erreurs": erreurs}


# ---------- lecture ----------
def _texte_gmail(payload):
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "ignore")
    html_trouve = ""
    for p in payload.get("parts", []) or []:
        t = _texte_gmail(p)
        if t and p.get("mimeType") == "text/plain":
            return t
        if t and not html_trouve:
            html_trouve = t
    if payload.get("mimeType") == "text/html" and payload.get("body", {}).get("data"):
        return _html_en_texte(base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "ignore"))
    return html_trouve


def lire(id, boite):
    if _boites(boite) == ["gmail"]:
        d = get_service().users().messages().get(userId="me", id=id, format="full").execute()
        h = {x["name"]: x["value"] for x in d["payload"]["headers"]}
        return {"ok": True, "boite": "gmail", "de": h.get("From", ""), "date": h.get("Date", ""),
                "sujet": h.get("Subject", ""), "contenu": _texte_gmail(d["payload"])[:4000]}
    m = _call("GET", f"{GRAPH}/me/messages/{id}?$select=subject,from,receivedDateTime,body").json()
    corps = m["body"]["content"]
    if m["body"].get("contentType", "").lower() == "html":
        corps = _html_en_texte(corps)
    return {"ok": True, "boite": "outlook",
            "de": m.get("from", {}).get("emailAddress", {}).get("address", ""),
            "date": m["receivedDateTime"][:16].replace("T", " "),
            "sujet": m.get("subject", ""), "contenu": corps[:4000]}


# ---------- contacts ----------
def chercher_contact(nom):
    mots = [w for w in _norm(nom).split() if len(w) > 1]
    if not mots:
        raise ValueError("nom vide")
    vus = {}

    def noter(nom_aff, adresse, boite):
        adresse = (adresse or "").strip().lower()
        if not adresse or "@" not in adresse:
            return
        botte = _norm(nom_aff) + " " + _norm(adresse)
        if all(w in botte for w in mots):
            c = vus.setdefault(adresse, {"adresse": adresse, "nom": nom_aff or "", "vu": 0, "boites": set()})
            c["vu"] += 1
            c["boites"].add(boite)
            if nom_aff and not c["nom"]:
                c["nom"] = nom_aff

    try:
        s = get_service()
        q = " OR ".join([f'from:"{nom}"', f'to:"{nom}"'])
        for m in s.users().messages().list(userId="me", q=q, maxResults=25).execute().get("messages", []):
            d = s.users().messages().get(userId="me", id=m["id"], format="metadata",
                                         metadataHeaders=["From", "To", "Cc"]).execute()
            for x in d["payload"]["headers"]:
                for n, a in getaddresses([x["value"]]):
                    noter(n, a, "gmail")
    except Exception:
        pass
    try:
        url = f'{GRAPH}/me/messages?$top=25&$search="{nom}"&$select=from,toRecipients,ccRecipients'
        for m in _call("GET", url).json().get("value", []):
            for r in [m.get("from")] + m.get("toRecipients", []) + m.get("ccRecipients", []):
                e = (r or {}).get("emailAddress", {})
                noter(e.get("name", ""), e.get("address", ""), "outlook")
    except Exception:
        pass
    contacts = sorted(vus.values(), key=lambda c: -c["vu"])[:5]
    for c in contacts:
        c["boites"] = sorted(c["boites"])
    return {"ok": True, "nombre": len(contacts), "contacts": contacts}


# ---------- preparer / envoyer ----------
def _epeler(adresse):
    """camille@example.com -> 'c, a, m, i, l, l, e, arobase, example, point, com' (lisible a voix haute)."""
    local, _, domaine = adresse.partition("@")
    noms = {".": "point", "-": "tiret", "_": "tiret bas", "+": "plus"}
    lettres = [noms.get(c, c) for c in local]
    dom = [noms.get(p, p) for p in re.split(r"([.\-])", domaine) if p]
    return ", ".join(lettres + ["arobase"] + dom)


def _adresse_connue(adresse):
    """Vrai si l'adresse apparait deja dans les mails echanges (Gmail ou Outlook)."""
    try:
        r = get_service().users().messages().list(
            userId="me", q=f"from:{adresse} OR to:{adresse} OR cc:{adresse}", maxResults=1).execute()
        if r.get("messages"):
            return True
    except Exception:
        pass
    try:
        r = _call("GET", f'{GRAPH}/me/messages?$top=1&$search="{adresse}"&$select=id').json()
        if r.get("value"):
            return True
    except Exception:
        pass
    return False


def _jeter_ancien_apercu():
    """Si un apercu precedent n'a pas ete envoye (J a demande une correction), on supprime son brouillon."""
    if not os.path.exists(EN_ATTENTE):
        return
    try:
        with open(EN_ATTENTE, encoding="utf-8") as f:
            old = json.load(f)
        if old["boite"] == "gmail":
            get_service().users().drafts().delete(userId="me", id=old["id_brouillon"]).execute()
        else:
            _call("DELETE", f"{GRAPH}/me/messages/{old['id_brouillon']}")
    except Exception:
        pass
    try:
        os.remove(EN_ATTENTE)
    except OSError:
        pass


def empreinte_de(boite, dest, sujet, corps):
    """Ce qui identifie UN apercu : sa boite d'envoi, ses destinataires, son objet, son texte. L'envoi doit la presenter.
    Chaque champ est precede de sa longueur (en caracteres) : deux apercus differents n'ont jamais la meme ecriture.
    Le meme calcul est refait dans outils/mails/mails.py et dans core/apercu_mail.js."""
    champs = (str(boite), ",".join(dest), str(sujet), str(corps))
    return hashlib.sha256("".join("%d:%s" % (len(x), x) for x in champs).encode("utf-8")).hexdigest()[:32]


def preparer(a, sujet, corps, boite="gmail"):
    dest = _destinataires(a)
    b = _boites(boite or "gmail")
    if len(b) != 1:
        b = ["gmail"]
    b = b[0]
    sujet = (sujet or "").strip() or "(sans objet)"
    corps = (corps or "").strip()
    if not corps:
        raise ValueError("le texte du mail est vide")

    if b == "gmail":
        msg = MIMEText(corps, "plain", "utf-8")
        msg["to"] = ", ".join(dest)
        msg["subject"] = Header(sujet, "utf-8")
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        d = get_service().users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
        id_brouillon = d["id"]
    else:
        m = _call("POST", f"{GRAPH}/me/messages", json={
            "subject": sujet,
            "body": {"contentType": "Text", "content": corps},
            "toRecipients": [{"emailAddress": {"address": x}} for x in dest],
        }).json()
        id_brouillon = m["id"]

    _jeter_ancien_apercu()
    empreinte = empreinte_de(b, dest, sujet, corps)
    attente = {"boite": b, "id_brouillon": id_brouillon, "a": dest, "sujet": sujet, "empreinte": empreinte,
               "corps": corps, "cree_le": datetime.now().isoformat(timespec="seconds")}
    with open(EN_ATTENTE, "w", encoding="utf-8") as f:
        json.dump(attente, f, ensure_ascii=False, indent=2)

    nom_boite = "Gmail" if b == "gmail" else "Outlook"
    inconnues = [x for x in dest if not _adresse_connue(x)]
    alerte = ""
    if inconnues:
        alerte = (" ATTENTION : je n'ai jamais vu " + ("ces adresses" if len(inconnues) > 1 else "cette adresse")
                  + " dans tes mails, vérifie l'orthographe : "
                  + " ; ".join(_epeler(x) for x in inconnues) + ".")
    phrase = (f"Voici le mail prêt{_qui()}, depuis ta boîte {nom_boite}, pour {', '.join(dest)}.{alerte} "
              f"Objet : {sujet}. Texte : {corps} Je l'envoie ?")
    return {"ok": True, "statut": "APERCU", "boite": b, "a": dest, "sujet": sujet, "corps": corps, "empreinte": empreinte,
            "adresses_inconnues": inconnues, "phrase_pour_utilisateur": phrase}


def envoyer(empreinte=None):
    if not os.path.exists(EN_ATTENTE):
        raise ValueError("aucun mail en attente : prepare d'abord le mail et montre l'apercu")
    with open(EN_ATTENTE, encoding="utf-8") as f:
        att = json.load(f)
    if datetime.now() - datetime.fromisoformat(att["cree_le"]) > DUREE_VALIDITE:
        os.remove(EN_ATTENTE)
        raise ValueError("l'apercu a plus de deux heures : prepare-le a nouveau")
    # l'envoi nomme l'apercu qu'il envoie : si un autre brouillon a ete prepare entre-temps, rien ne part
    if not att.get("empreinte") or empreinte != att["empreinte"]:
        raise ValueError("l'apercu a change : montre le nouvel apercu avant d'envoyer")

    if att["boite"] == "gmail":
        get_service().users().drafts().send(userId="me", body={"id": att["id_brouillon"]}).execute()
    else:
        _call("POST", f"{GRAPH}/me/messages/{att['id_brouillon']}/send")

    try:                      # le mail est parti : une erreur de fichier ne doit pas faire dire le contraire
        os.remove(EN_ATTENTE)
    except OSError:
        pass
    nom_boite = "Gmail" if att["boite"] == "gmail" else "Outlook"
    return {"ok": True, "statut": "ENVOYE", "boite": att["boite"], "a": att["a"], "sujet": att["sujet"],
            "phrase_pour_utilisateur": f"C'est envoyé{_qui()}, depuis ta boîte {nom_boite}, à {', '.join(att['a'])}."}
