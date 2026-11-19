# lire_pdf.py - outil maison d'Archi : lire un PDF du PC (facture, contrat, courrier, scan).
#   python lire_pdf.py --fichier demande.json
#   demande.json : {"action": "lire" | "liste", "nom": "facture EDF", "pages": "1-3"}
#     lire  : trouve le PDF (par un bout de son nom, ou son chemin complet), en sort le texte.
#             Pages scannees (sans texte) : le modele d'image d'Archi (LM Studio) les recopie, 6 pages max par appel.
#             Le texte complet est garde dans .n8n-files\admin\lectures\<nom>.txt (relu sans refaire le travail).
#     liste : les PDF trouves sur le PC (les plus recents d'abord).
# Cherche dans : .n8n-files, Telechargements, Documents, Bureau. Ne modifie, ne deplace et ne supprime aucun PDF.

import argparse
import base64
import hashlib
import io
import json
import os
import re
import subprocess
SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # pas de fenetre noire devant l utilisateur (13/11)
import sys
import unicodedata
import urllib.request

ICI = os.path.dirname(os.path.abspath(__file__))
MAISON = os.path.expanduser("~")
BASE = os.environ.get("ARCHI_BASE") or os.path.join(MAISON, ".n8n-files")
RACINES = [BASE, os.path.join(MAISON, "Downloads"),
           os.path.join(MAISON, "Documents"), os.path.join(MAISON, "Desktop")]
LECTURES = os.path.join(BASE, "admin", "lectures")
VENV = os.environ.get("ARCHI_PY", "")
LM = os.environ.get("ARCHI_LM_URL", "http://127.0.0.1:1234/v1").rstrip("/") + "/chat/completions"
MODELE_IMAGE = os.environ.get("ARCHI_MODELE_VISION", "qwythos-9b-claude-mythos-5-1m")
MAX_OCR = 6          # pages scannees recopiees par appel (environ 20 s chacune)
EXTRAIT = 3500       # caracteres rendus a Archi dans la reponse


class Erreur(Exception):
    pass


def repondre(ok, phrase, **extra):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(dict(ok=ok, phrase_pour_utilisateur=phrase, **extra), ensure_ascii=False))


try:
    import pypdfium2 as pdfium
except ImportError:  # lance avec un Python sans la bibliotheque PDF : on passe la main au Python d'Archi
    if os.path.isfile(VENV) and os.path.abspath(sys.executable).lower() != os.path.abspath(VENV).lower():
        r = subprocess.run([VENV, os.path.abspath(__file__)] + sys.argv[1:], capture_output=True, timeout=290, creationflags=SANS_FENETRE)
        sys.stdout.buffer.write(r.stdout)
        sys.exit(r.returncode)
    repondre(False, "Il manque la bibliothèque de lecture PDF (pypdfium2) sur le PC.")
    sys.exit(0)


def norm(s):
    s = unicodedata.normalize("NFD", str(s).lower())
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip()


def tous_les_pdf():
    vus = []
    for r in RACINES:
        if not os.path.isdir(r):
            continue
        for dossier, sous, fichiers in os.walk(r):
            sous[:] = [d for d in sous if not d.startswith(".") and d not in ("node_modules", "venv", "__pycache__", "crypte")]
            for f in fichiers:
                if f.lower().endswith(".pdf"):
                    p = os.path.join(dossier, f)
                    try:
                        vus.append((os.path.getmtime(p), p))
                    except OSError:
                        pass
    return [p for _, p in sorted(vus, reverse=True)]


def trouver(nom):
    nom = str(nom or "").strip().strip('"')
    if not nom:
        raise Erreur("Dis-moi quel PDF lire : un bout de son nom suffit, par exemple « facture EDF ».")
    if nom.startswith("\\\\") or nom.startswith("//"):
        raise Erreur("Je ne lis pas les PDF d'un partage réseau.")
    if os.path.isfile(nom) and nom.lower().endswith(".pdf"):
        vrai = os.path.realpath(nom)
        if not any(os.path.commonpath([vrai, os.path.realpath(r)]) == os.path.realpath(r) for r in RACINES if os.path.isdir(r)):
            raise Erreur("Je ne lis que les PDF de .n8n-files, Téléchargements, Documents et Bureau.")
        return vrai, []
    mots = norm(nom).split()
    trouves = [p for p in tous_les_pdf() if all(m in norm(os.path.basename(p)) for m in mots)]
    if not trouves:  # deuxieme essai : le chemin (dossier) compte aussi
        trouves = [p for p in tous_les_pdf() if all(m in norm(p) for m in mots)]
    if not trouves:
        raise Erreur(f"Je ne trouve aucun PDF qui s'appelle « {nom} » sur le PC (dossiers .n8n-files, Téléchargements, Documents, Bureau).")
    return trouves[0], trouves[1:4]


def pages_voulues(txt, n):
    if not txt:
        return list(range(n))
    out = set()
    for bout in re.split(r"[,;\s]+", str(txt)):
        m = re.match(r"^(\d+)(?:-(\d+))?$", bout)
        if m:
            a, b = int(m.group(1)), min(int(m.group(2) or m.group(1)), n)
            out.update(i - 1 for i in range(a, b + 1) if 1 <= i <= n)
    if not out:
        raise Erreur(f"Je ne comprends pas les pages « {txt} ». Exemple : 1-3 ou 2,5.")
    return sorted(out)


def propre(t):
    """texte sans caracteres de controle (ils font planter le modele) et sans blancs inutiles"""
    t = t.replace("\r\n", "\n").replace("\ufffe", "-").replace("\x02", "-")
    t = re.sub(r"[\x00-\x08\x0b-\x1f\x7f\ufeff\ufffd\ufffe\uffff]", " ", t)
    t = re.sub(r"[ \t\u00a0]+", " ", t)
    t = re.sub(r" *\n[ \n]*", "\n", t)
    return t.strip()


def recopier_image(img_png):
    corps = {"model": MODELE_IMAGE, "temperature": 0, "max_tokens": 3000,
             "chat_template_kwargs": {"enable_thinking": False}, "reasoning_effort": "none",
             "messages": [{"role": "user", "content": [
                 {"type": "text", "text": "Recopie EXACTEMENT tout le texte de cette page de document, ligne par ligne, en gardant "
                                          "tous les chiffres, montants, dates et numéros tels quels. Pour un tableau, une ligne par "
                                          "rangée, cellules séparées par « | ». N'ajoute aucun commentaire."},
                 {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(img_png).decode()}}]}]}
    req = urllib.request.Request(LM, data=json.dumps(corps).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        m = json.loads(r.read().decode("utf-8"))["choices"][0]["message"]
    return re.sub(r"(?s)<think>.*?</think>", "", m.get("content") or "").strip()


def lire(d):
    chemin, autres = trouver(d.get("nom") or d.get("fichier_pdf") or d.get("chemin"))
    with open(chemin, "rb") as f:
        empreinte = hashlib.sha1(f.read()).hexdigest()[:12]
    base = re.sub(r"[^\w\- ]+", "_", os.path.splitext(os.path.basename(chemin))[0]).strip()[:80]
    cache = os.path.join(LECTURES, f"{base}.{empreinte}.json")
    deja = {}
    try:
        with open(cache, encoding="utf-8") as f:
            deja = json.load(f)
    except Exception:
        pass
    doc = pdfium.PdfDocument(chemin)
    n = len(doc)
    voulues = pages_voulues(d.get("pages"), n)
    textes = deja.get("pages", {})
    ocr_faits, ocr_restants, ocr_echecs = [], [], []
    raison = ""
    for i in voulues:
        k = str(i + 1)
        if k in textes:
            continue
        page = doc[i]
        t = propre(page.get_textpage().get_text_range())
        utiles = re.sub(r"[\s\ue000-\uf8ff]", "", t)
        bizarres = len(re.findall(r"[\ue000-\uf8ff]", t))
        if len(utiles) >= 40 and bizarres <= 0.2 * max(1, len(utiles)):
            textes[k] = t
            continue
        if len(ocr_faits) >= MAX_OCR or len(ocr_echecs) >= 2:
            ocr_restants.append(i + 1)
            continue
        img = page.render(scale=150 / 72).to_pil()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        try:
            textes[k] = "[page scannée, recopiée par le modèle d'image]\n" + propre(recopier_image(buf.getvalue()))
            ocr_faits.append(i + 1)
        except Exception as e:
            ocr_echecs.append(i + 1)
            try:
                raison = (e.read().decode("utf-8", "replace") if hasattr(e, "read") else str(e))[:200]
            except Exception:
                raison = str(e)[:200]
    os.makedirs(LECTURES, exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        json.dump({"pdf": chemin, "pages_total": n, "pages": textes}, f, ensure_ascii=False)
    lues = [i + 1 for i in voulues if str(i + 1) in textes]
    complet = "\n\n".join(f"===== Page {p} =====\n{textes[str(p)]}" for p in lues)
    txt_final = os.path.join(LECTURES, f"{base}.txt")
    toutes = "\n\n".join(f"===== Page {p} =====\n{textes[p]}" for p in sorted(textes, key=int))
    with open(txt_final, "w", encoding="utf-8") as f:
        f.write(toutes)
    phrase = f"J'ai lu « {os.path.basename(chemin)} » : {len(lues)} page(s) sur {n}."
    if ocr_faits:
        phrase += f" {len(ocr_faits)} page(s) étaient scannées, je les ai recopiées : vérifie les chiffres importants."
    if ocr_restants and not ocr_echecs:
        phrase += f" Il reste {len(ocr_restants)} page(s) scannée(s) à lire : redemande-moi la suite (pages {', '.join(map(str, ocr_restants[:12]))}{'…' if len(ocr_restants) > 12 else ''})."
    if ocr_echecs:
        phrase += (f" Je n'ai pas pu recopier les pages scannées : le modèle d'image (LM Studio, {MODELE_IMAGE}) a refusé"
                   f" ({re.sub(r'\s+', ' ', raison)[:160]}). Il reste {len(ocr_echecs) + len(ocr_restants)} page(s) scannée(s) non lues.")
    if autres:
        phrase += " Autres PDF au nom proche : " + " ; ".join(os.path.basename(a) for a in autres) + "."
    return repondre(True, phrase, pdf=chemin, pages_total=n, pages_lues=lues, texte_complet_dans=txt_final,
                    texte=complet[:EXTRAIT] + ("\n[... suite dans le fichier texte ...]" if len(complet) > EXTRAIT else ""))


def liste(d):
    filtre = norm(d.get("nom") or "")
    pdfs = [p for p in tous_les_pdf() if not filtre or all(m in norm(p) for m in filtre.split())][:25]
    if not pdfs:
        return repondre(True, "Je ne trouve aucun PDF" + (f" pour « {d.get('nom')} »." if filtre else " sur le PC."), pdfs=[])
    noms = [os.path.basename(p) for p in pdfs]
    return repondre(True, f"{len(pdfs)} PDF trouvé(s), les plus récents d'abord : " + " ; ".join(noms[:10]) + ".", pdfs=pdfs)


RECUS = os.path.join(BASE, "recus")


def main():
    global MAX_OCR
    pa = argparse.ArgumentParser()
    pa.add_argument("--fichier")
    pa.add_argument("--dernier-recu", action="store_true", help="lit le dernier PDF recu sur Telegram (dossier recus)")
    a = pa.parse_args()
    if a.dernier_recu:  # appele par Archi_Telegram quand J envoie un PDF
        MAX_OCR = 3
        try:
            pdfs = sorted((os.path.join(RECUS, f) for f in os.listdir(RECUS) if f.lower().endswith(".pdf")), key=os.path.getmtime)
        except OSError:
            pdfs = []
        if not pdfs:
            return repondre(False, "Je n'ai trouvé aucun PDF reçu dans le dossier recus.")
        try:
            return lire({"nom": pdfs[-1]})
        except Exception as e:
            return repondre(False, f"Le PDF n'a pas pu être lu ({type(e).__name__}).")
    if not a.fichier:
        return repondre(False, "Il manque la demande (--fichier).")
    try:
        with open(a.fichier, encoding="utf-8-sig") as f:
            d = json.load(f)
    except Exception:
        return repondre(False, "La demande est illisible.")
    act = str(d.get("action") or "lire").strip().lower()
    act = {"lecture": "lire", "lis": "lire", "ouvrir": "lire", "chercher": "liste", "lister": "liste"}.get(act, act)
    try:
        if act == "lire":
            return lire(d)
        if act == "liste":
            return liste(d)
        return repondre(False, f"Je ne connais pas « {act} ». Choix : lire ou liste.")
    except Erreur as e:
        return repondre(False, str(e))
    except Exception as e:
        return repondre(False, f"Le PDF n'a pas pu être lu ({type(e).__name__} : {str(e)[:120]}). Il est peut-être protégé ou abîmé.")


if __name__ == "__main__":
    main()
