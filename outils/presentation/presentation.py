# -*- coding: utf-8 -*-
"""presentation.py - Archi fabrique une presentation (PowerPoint + PDF) avec Presenton (Docker, 127.0.0.1:5001),
qui ecrit avec le modele local d'Archi (LM Studio). Rien ne sort du PC, a part les photos d'illustration (Pexels).
Usage : python presentation.py --fichier demande.json   (outil maison d'Archi)
  {"sujet": "...", "contenu": "notes, plan ou texte (facultatif)", "diapos": 8, "ton": "professionnel",
   "langue": "French", "theme": "professional-blue"}
  python presentation.py --test   -> petit essai de 3 diapos
Repond UNE ligne JSON {"ok", "document" (PDF par defaut, PowerPoint si "format":"pptx" ou si J dit PowerPoint), "phrase_pour_utilisateur"}.
"""
import json
import os
import re
import shutil
import sys
import time
import unicodedata
import urllib.error
import base64
import urllib.request
from datetime import datetime

API = os.environ.get("PRESENTON_URL", "http://127.0.0.1:5001")
ICI = os.path.dirname(os.path.abspath(__file__))
BASE = os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files")
BOITE = os.environ.get("ARCHI_BOITE_OUTILS") or (os.path.join(os.environ["ARCHI_DEPOT"], "boite_outils")
                                              if os.environ.get("ARCHI_DEPOT") else os.path.join(BASE, "pc", "boite_outils"))
DATA = os.path.join(BOITE, "presenton_data")   # monte dans le conteneur en /app_data
SORTIE = os.path.join(BASE, "documents", "presentations")
ACCES = os.path.join(ICI, "acces_presenton.txt")   # une ligne « identifiant:motdepasse » (compte admin cree par J)
TONS = {"pro": "professional", "professionnel": "professional", "professionnelle": "professional", "serieux": "professional",
        "detendu": "casual", "decontracte": "casual", "simple": "casual", "drole": "funny", "humour": "funny", "amusant": "funny",
        "pedagogique": "educational", "cours": "educational", "explicatif": "educational", "vente": "sales_pitch",
        "commercial": "sales_pitch", "pitch": "sales_pitch", "normal": "default"}


def _qui():
    """« , Camille » : le prenom du profil (ARCHI_UTILISATEUR, regle a l'installation) ; rien s'il manque."""
    p = " ".join((os.environ.get("ARCHI_UTILISATEUR") or "").split())[:30]
    return (", " + p) if p else ""


def sortir(d):
    print(json.dumps(d, ensure_ascii=False))
    sys.exit(0)


def sans_accents(s):
    return unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode().lower().strip()


JETON = {"valeur": None, "mode": "basic"}


def lire_acces():
    try:
        acces = open(ACCES, encoding="utf-8-sig").read().strip()
        return acces if ":" in acces else ""
    except Exception:
        return ""


def connexion():
    """POST /api/v1/auth/login -> access_token (ou cookie de session) ; utilise si l'identification simple est refusee."""
    acces = lire_acces()
    if not acces:
        return False
    u, _, mdp = acces.partition(":")
    req = urllib.request.Request(API + "/api/v1/auth/login", data=json.dumps({"username": u, "password": mdp}).encode("utf-8"),
                                 method="POST", headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            corps = r.read().decode("utf-8", "replace")
            cookie = "; ".join(c.split(";", 1)[0] for c in r.headers.get_all("Set-Cookie") or [])
        d = json.loads(corps) if corps.strip().startswith("{") else {}
        jeton = d.get("access_token") or d.get("token") or (d.get("data") or {}).get("access_token")
        if jeton:
            JETON.update(valeur=jeton, mode="bearer", cookie=cookie)
            return True
        if cookie:
            JETON.update(valeur=None, mode="cookie", cookie=cookie)
            return True
    except Exception:
        pass
    return False


def entetes():
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    acces = lire_acces()
    if JETON["mode"] == "bearer" and JETON["valeur"]:
        h["Authorization"] = "Bearer " + JETON["valeur"]
    elif acces and JETON["mode"] == "basic":
        h["Authorization"] = "Basic " + base64.b64encode(acces.encode("utf-8")).decode("ascii")
    if JETON.get("cookie"):
        h["Cookie"] = JETON["cookie"]
    return h


def appel(chemin, corps=None, timeout=600, methode=None):
    code, r = appel_brut(chemin, corps, timeout, methode)
    if code == 401 and JETON["mode"] == "basic" and connexion():
        code, r = appel_brut(chemin, corps, timeout, methode)
    return code, r


def appel_brut(chemin, corps=None, timeout=600, methode=None):
    data = json.dumps(corps).encode("utf-8") if corps is not None else None
    req = urllib.request.Request(API + chemin, data=data, method=methode or ("POST" if data else "GET"), headers=entetes())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            t = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(t) if t.strip().startswith(("{", "[")) else t)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400]
    except Exception as e:
        return 0, repr(e)[:200]


def fichier_local(chemin):
    """Le conteneur renvoie /app_data/exports/x.pptx (ou /static/...) : on retrouve le fichier dans presenton_data."""
    p = str(chemin or "").replace("\\", "/")
    for prefixe in ("/app_data/", "app_data/"):
        if prefixe in p:
            return os.path.join(DATA, *p.split(prefixe, 1)[1].split("/"))
    nom = os.path.basename(p)
    for racine, _, fichiers in os.walk(os.path.join(DATA, "exports")):
        if nom in fichiers:
            return os.path.join(racine, nom)
    return None


def nom_propre(sujet):
    s = re.sub(r"[^A-Za-z0-9 _-]+", "", sans_accents(sujet)).strip().replace(" ", "_")[:50] or "presentation"
    return f"{datetime.now():%Y-%m-%d_%Hh%M}_{s}"


def generer(sujet, contenu, n, ton, langue, theme, format_):
    corps = {"content": (sujet + ("\n\n" + contenu if contenu else "")).strip(), "n_slides": n, "language": langue,
             "tone": ton, "verbosity": "standard", "image_type": "stock", "include_title_slide": True,
             "include_table_of_contents": n >= 10, "export_as": format_, "template": "general"}
    if theme:
        corps["theme"] = theme
    return appel("/api/v1/ppt/presentation/generate", corps, timeout=900)


def main():
    args = sys.argv[1:]
    if "--test" in args:
        d = {"sujet": "Un assistant IA local pour une petite entreprise", "diapos": 3, "ton": "professionnel"}
    elif "--fichier" in args:
        d = json.load(open(args[args.index("--fichier") + 1], encoding="utf-8"))
    else:
        d = json.loads(args[0]) if args else {}
    if isinstance(d.get("parametres"), dict):
        d = {**d, **d["parametres"]}
    sujet = str(d.get("sujet") or d.get("titre") or d.get("theme_sujet") or "").strip()
    contenu = str(d.get("contenu") or d.get("notes") or d.get("plan") or d.get("texte") or "").strip()
    if not sujet and not contenu:
        sortir({"ok": False, "phrase_pour_utilisateur": "Sur quel sujet veux-tu la présentation" + _qui() + " ?"})
    try:
        n = int(str(d.get("diapos") or d.get("n_slides") or d.get("pages") or 8))
    except Exception:
        n = 8
    n = max(3, min(20, n))
    ton = TONS.get(sans_accents(str(d.get("ton") or "")), "default")
    langue = str(d.get("langue") or "French")
    theme = str(d.get("theme") or "").strip() or None
    fmt = sans_accents(str(d.get("format") or d.get("type") or ""))
    format_ = "pptx" if re.search(r"pptx|powerpoint|ppt|modifiable", fmt + " " + sans_accents(sujet + " " + contenu[:200])) else "pdf"

    # Presenton repond ?
    code, _ = appel("/api/v1/ppt/presentation/all", timeout=15)
    if code == 0 or (isinstance(code, int) and code >= 500):
        sortir({"ok": False, "phrase_pour_utilisateur": "Presenton ne répond pas (Docker est-il lancé ?)."})

    t0 = time.time()
    code, r = generer(sujet, contenu, n, ton, langue, theme, format_)
    if code == 428:
        sortir({"ok": False, "phrase_pour_utilisateur": "Presenton attend que tu crées son compte : ouvre http://127.0.0.1:5001 sur le PC."})
    if code == 401:
        sortir({"ok": False, "phrase_pour_utilisateur": "Presenton refuse l'accès : vérifie outils\\presentation\\acces_presenton.txt (identifiant:motdepasse)."})
    if code != 200 or not isinstance(r, dict) or not r.get("path"):
        sortir({"ok": False, "phrase_pour_utilisateur": "Presenton n'a pas réussi à faire la présentation.",
                "erreur": f"{code} {str(r)[:300]}"})
    src = fichier_local(r["path"])
    pid = r.get("presentation_id")
    os.makedirs(SORTIE, exist_ok=True)
    base = nom_propre(sujet or contenu[:40])
    res = {"ok": True, "presentation_id": pid, "diapos": n, "format": format_, "duree_s": round(time.time() - t0),
           "edition": API + str(r.get("edit_path") or "")}
    if src and os.path.isfile(src):
        res["document"] = os.path.join(SORTIE, base + "." + format_)
        shutil.copyfile(src, res["document"])
    if not res.get("document"):
        sortir({"ok": False, "phrase_pour_utilisateur": "La présentation est faite mais je ne retrouve pas le fichier.",
                "erreur": f"path={r.get('path')}"})
    res["phrase_pour_utilisateur"] = (f"Ta présentation de {n} diapositives sur « {sujet or 'tes notes'} » est prête, je te l'envoie"
                                 + (" en PowerPoint." if format_ == "pptx" else " en PDF. Si tu veux la retoucher, demande-la en PowerPoint."))
    sortir(res)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        sortir({"ok": False, "phrase_pour_utilisateur": "L'outil présentation a eu un problème.", "erreur": repr(e)[:200]})
