# creer_pdf.py - outil maison d'Archi : fabriquer un PDF propre (compte rendu, fiche, carte avec des lieux)
# et le rendre a Archi, qui l'envoie a J sur Telegram.
#   python creer_pdf.py --fichier demande.json
#   demande.json : {"titre": "...", "contenu": "texte facon markdown", "lieux": [...], "sous_titre": "..."}
#     contenu : # Titre, ## Sous-titre, - puce, 1. liste, | a | b | (tableau), **gras**, lignes vides = paragraphes
#     lieux   : liste de lieux a mettre sur une carte (OpenStreetMap). Chaque lieu : {"nom": "...", "lat": 47.6, "lon": 1.5,
#               "note": "..."} ; sans lat/lon, le lieu est cherche par son nom (ajouter la ville dans le nom).
#               Accepte aussi une chaine "Chateau de Chambord ; Chateau de Blois ; ..." ou du JSON en texte.
# Le PDF va dans .n8n-files\documents\. Ne modifie et ne supprime aucun autre fichier.

import argparse
import io
import json
import math
import os
import re
import subprocess
SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # pas de fenetre noire devant l utilisateur (13/11)
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

ICI = os.path.dirname(os.path.abspath(__file__))
SORTIE = os.path.join(os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files"), "documents")
VENV = os.environ.get("ARCHI_PY", "")
UA = {"User-Agent": "Archi-assistant-personnel/1.0 (usage prive)"}
TUILES = os.environ.get("CREER_PDF_TUILES", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
NOMINATIM = os.environ.get("CREER_PDF_NOMINATIM", "https://nominatim.openstreetmap.org/search")
MAX_LIEUX = 30


def repondre(ok, phrase, **extra):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(dict(ok=ok, phrase_pour_utilisateur=phrase, **extra), ensure_ascii=False))


try:
    import reportlab  # noqa: F401
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    if os.path.isfile(VENV) and os.path.abspath(sys.executable).lower() != os.path.abspath(VENV).lower():
        r = subprocess.run([VENV, os.path.abspath(__file__)] + sys.argv[1:], capture_output=True, timeout=280, creationflags=SANS_FENETRE)
        sys.stdout.buffer.write(r.stdout)
        sys.exit(r.returncode)
    repondre(False, "Il manque les bibliothèques pour fabriquer un PDF (reportlab et Pillow).")
    sys.exit(0)

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image as RLImage, KeepTogether, ListFlowable, ListItem, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)


class Erreur(Exception):
    pass


# ---------- polices : Arial de Windows (accents, euro, guillemets) sinon Helvetica ----------
def polices():
    for nom, fic in (("Corps", "arial.ttf"), ("CorpsGras", "arialbd.ttf")):
        for d in (r"C:\Windows\Fonts", "/usr/share/fonts/truetype/dejavu"):
            chemin = os.path.join(d, fic if d.startswith("C:") else ("DejaVuSans-Bold.ttf" if "bd" in fic else "DejaVuSans.ttf"))
            if os.path.isfile(chemin):
                try:
                    pdfmetrics.registerFont(TTFont(nom, chemin))
                    break
                except Exception:
                    pass
    noms = pdfmetrics.getRegisteredFontNames()
    return ("Corps" if "Corps" in noms else "Helvetica", "CorpsGras" if "CorpsGras" in noms else "Helvetica-Bold")


F, FB = polices()
ENCRE = colors.HexColor("#1f2a24")
VERT = colors.HexColor("#2f6b4f")
GRIS = colors.HexColor("#e8ece9")
S = {
    "titre": ParagraphStyle("titre", fontName=FB, fontSize=20, leading=24, textColor=ENCRE, spaceAfter=4),
    "sous": ParagraphStyle("sous", fontName=F, fontSize=10, leading=13, textColor=colors.HexColor("#5e6b63"), spaceAfter=10),
    "h1": ParagraphStyle("h1", fontName=FB, fontSize=15, leading=19, textColor=VERT, spaceBefore=10, spaceAfter=4),
    "h2": ParagraphStyle("h2", fontName=FB, fontSize=12.5, leading=16, textColor=ENCRE, spaceBefore=8, spaceAfter=3),
    "p": ParagraphStyle("p", fontName=F, fontSize=10.5, leading=15, textColor=ENCRE, spaceAfter=6, alignment=TA_LEFT),
    "cel": ParagraphStyle("cel", fontName=F, fontSize=9.5, leading=12, textColor=ENCRE),
    "celb": ParagraphStyle("celb", fontName=FB, fontSize=9.5, leading=12, textColor=ENCRE),
    "pied": ParagraphStyle("pied", fontName=F, fontSize=8, leading=10, textColor=colors.HexColor("#777777")),
}


def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def enrichi(t):
    """**gras** et *italique* -> balises reportlab, le reste echappe"""
    t = esc(t)
    t = re.sub(r"\*\*(.+?)\*\*", lambda m: f'<font name="{FB}">{m.group(1)}</font>', t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
    return t


# ---------- texte facon markdown -> blocs PDF ----------
def blocs_texte(contenu, largeur):
    out, puces, numeros, tableau, para = [], [], [], [], []

    def vider():
        nonlocal puces, numeros, tableau, para
        if para:
            out.append(Paragraph(enrichi(" ".join(para)), S["p"]))
            para = []
        if puces:
            out.append(ListFlowable([ListItem(Paragraph(enrichi(x), S["p"]), leftIndent=12) for x in puces],
                                    bulletType="bullet", start="•", leftIndent=12, bulletFontName=F))
            puces = []
        if numeros:
            out.append(ListFlowable([ListItem(Paragraph(enrichi(x), S["p"]), leftIndent=14) for x in numeros],
                                    bulletType="1", bulletFormat="%s.", leftIndent=14, bulletFontName=F))
            numeros = []
        if tableau:
            lignes = [r for r in tableau if not re.fullmatch(r"\|?\s*:?-{2,}.*", "|".join(r))]
            n = max(len(r) for r in lignes)
            data = [[Paragraph(enrichi(c), S["celb"] if i == 0 else S["cel"]) for c in r + [""] * (n - len(r))]
                    for i, r in enumerate(lignes)]
            t = Table(data, colWidths=[largeur / n] * n, repeatRows=1)
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), GRIS), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#a9b4ad")),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            out.append(t)
            out.append(Spacer(1, 6))
            tableau = []

    for brut in str(contenu or "").replace("\r\n", "\n").split("\n"):
        l = brut.strip()
        if not l:
            vider()
            continue
        if l.startswith("|"):
            if not tableau:
                vider()
            tableau.append([c.strip() for c in l.strip("|").split("|")])
            continue
        if tableau:
            vider()
        m = re.match(r"^(#{1,3})\s+(.*)$", l)
        if m:
            vider()
            out.append(Paragraph(enrichi(m.group(2)), S["h1"] if len(m.group(1)) <= 1 else S["h2"]))
            continue
        m = re.match(r"^[-•*]\s+(.*)$", l)
        if m:
            if para or numeros:
                p, n = para, numeros
                para, numeros = [], []
                if p:
                    out.append(Paragraph(enrichi(" ".join(p)), S["p"]))
                if n:
                    numeros = n
                    vider()
            puces.append(m.group(1))
            continue
        m = re.match(r"^\d+[.)]\s+(.*)$", l)
        if m:
            if para:
                out.append(Paragraph(enrichi(" ".join(para)), S["p"]))
                para = []
            if puces:
                vider()
            numeros.append(m.group(1))
            continue
        if puces or numeros:
            vider()
        para.append(l)
    vider()
    return out


# ---------- lieux et carte ----------
def lire_lieux(v):
    if not v:
        return []
    if isinstance(v, str):
        v = v.strip()
        try:
            v = json.loads(v)
        except ValueError:
            v = [{"nom": x.strip()} for x in re.split(r"[;\n]+", v) if x.strip()]
    if isinstance(v, dict):
        v = [v]
    lieux = []
    for x in v[:MAX_LIEUX]:
        if isinstance(x, str):
            x = {"nom": x}
        if not isinstance(x, dict):
            continue
        nom = str(x.get("nom") or x.get("name") or x.get("titre") or "").strip()
        try:
            lat = float(str(x.get("lat", x.get("latitude", ""))).replace(",", "."))
            lon = float(str(x.get("lon", x.get("lng", x.get("longitude", "")))).replace(",", "."))
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError
        except (TypeError, ValueError):
            lat = lon = None
        if nom or lat is not None:
            lieux.append({"nom": nom or f"{lat:.4f}, {lon:.4f}", "lat": lat, "lon": lon, "note": str(x.get("note") or x.get("description") or "").strip()})
    return lieux


def geocoder(lieux):
    rates = []
    for l in lieux:
        if l["lat"] is not None:
            continue
        q = urllib.parse.urlencode({"q": l["nom"], "format": "jsonv2", "limit": 1, "accept-language": "fr"})
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{NOMINATIM}?{q}", headers=UA), timeout=10) as r:
                d = json.loads(r.read().decode("utf-8"))
            if d:
                l["lat"], l["lon"] = float(d[0]["lat"]), float(d[0]["lon"])
            else:
                rates.append(l["nom"])
        except Exception:
            rates.append(l["nom"])
        time.sleep(1.1)  # regle d'OpenStreetMap : une recherche par seconde
    return rates


def tuile_xy(lat, lon, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def faire_carte(lieux, w=1400, h=1000):
    pts = [l for l in lieux if l["lat"] is not None]
    if not pts:
        return None
    lats = [p["lat"] for p in pts]
    lons = [p["lon"] for p in pts]
    z = 16
    while z > 2:
        x0, y0 = tuile_xy(max(lats), min(lons), z)
        x1, y1 = tuile_xy(min(lats), max(lons), z)
        if (x1 - x0) * 256 <= w * 0.8 and (y1 - y0) * 256 <= h * 0.8:
            break
        z -= 1
    if len(pts) == 1:
        z = min(z, 13)
    cx, cy = tuile_xy(sum(lats) / len(lats), sum(lons) / len(lons), z)
    gx, gy = cx * 256 - w / 2, cy * 256 - h / 2
    carte = Image.new("RGB", (w, h), (232, 236, 233))
    tx0, ty0 = int(gx // 256), int(gy // 256)
    tx1, ty1 = int((gx + w) // 256), int((gy + h) // 256)
    tuiles_ok = 0
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            if not (0 <= ty < 2 ** z):
                continue
            url = TUILES.format(z=z, x=tx % (2 ** z), y=ty)
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=10) as r:
                    t = Image.open(io.BytesIO(r.read())).convert("RGB")
                carte.paste(t, (int(tx * 256 - gx), int(ty * 256 - gy)))
                tuiles_ok += 1
            except Exception:
                pass
    d = ImageDraw.Draw(carte)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 22)
    except Exception:
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", 22)
        except Exception:
            font = ImageFont.load_default()
    for i, p in enumerate(lieux, 1):
        if p["lat"] is None:
            continue
        x, y = tuile_xy(p["lat"], p["lon"], z)
        x, y = x * 256 - gx, y * 256 - gy
        r_ = 17
        d.ellipse([x - r_, y - r_, x + r_, y + r_], fill=(47, 107, 79), outline=(255, 255, 255), width=3)
        s = str(i)
        bb = d.textbbox((0, 0), s, font=font)
        d.text((x - (bb[2] - bb[0]) / 2 - bb[0], y - (bb[3] - bb[1]) / 2 - bb[1]), s, fill=(255, 255, 255), font=font)
    d.rectangle([w - 330, h - 28, w, h], fill=(255, 255, 255))
    d.text((w - 322, h - 24), "© les contributeurs d'OpenStreetMap", fill=(60, 60, 60),
           font=ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 16) if os.path.isfile(r"C:\Windows\Fonts\arial.ttf") else ImageFont.load_default())
    buf = io.BytesIO()
    carte.save(buf, format="JPEG", quality=88)
    buf.seek(0)
    return buf, tuiles_ok


# ---------- assemblage ----------
def nom_de_fichier(titre):
    import unicodedata
    t = unicodedata.normalize("NFD", titre)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_")[:60] or "document"
    return f"{datetime.now():%Y-%m-%d_%H%M}_{t}.pdf"


def creer(d):
    titre = str(d.get("titre") or d.get("title") or "").strip()
    contenu = d.get("contenu") or d.get("texte") or d.get("content") or ""
    if isinstance(contenu, list):
        contenu = "\n".join("- " + str(x) for x in contenu)
    lieux = lire_lieux(d.get("lieux") or d.get("places"))
    if not titre:
        titre = "Carte" if lieux and not contenu else "Document"
    if not str(contenu).strip() and not lieux:
        raise Erreur("Il me faut un contenu (le texte du compte rendu ou de la fiche) ou des lieux à mettre sur une carte.")
    os.makedirs(SORTIE, exist_ok=True)
    chemin = os.path.join(SORTIE, nom_de_fichier(titre))
    largeur = A4[0] - 36 * mm
    h = [Paragraph(enrichi(titre), S["titre"]),
         Paragraph(esc(d.get("sous_titre") or f"Préparé par Archi le {datetime.now():%d/%m/%Y à %H:%M}"), S["sous"])]
    notes = []
    rates = geocoder(lieux) if lieux else []
    if lieux:
        res = faire_carte(lieux)
        if res:
            img, n_tuiles = res
            hauteur = largeur * 1000 / 1400
            h.append(RLImage(img, width=largeur, height=hauteur))
            if n_tuiles == 0:
                notes.append("le fond de carte n'a pas pu être téléchargé (pas d'Internet ?), seuls les points sont placés")
            h.append(Spacer(1, 6))
        data = [[Paragraph("N°", S["celb"]), Paragraph("Lieu", S["celb"]), Paragraph("À savoir", S["celb"])]]
        for i, l in enumerate(lieux, 1):
            data.append([Paragraph(str(i), S["cel"]), Paragraph(enrichi(l["nom"]), S["cel"]),
                         Paragraph(enrichi(l["note"] or ("position introuvable" if l["lat"] is None else "")), S["cel"])])
        t = Table(data, colWidths=[12 * mm, largeur * 0.38, largeur - 12 * mm - largeur * 0.38], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), GRIS), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#a9b4ad")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        h.append(t)
        h.append(Spacer(1, 8))
    h += blocs_texte(contenu, largeur)

    def pied(c, doc):
        c.saveState()
        c.setFont(F, 8)
        c.setFillColor(colors.HexColor("#777777"))
        c.drawString(18 * mm, 10 * mm, titre[:90])
        c.drawRightString(A4[0] - 18 * mm, 10 * mm, f"page {doc.page}")
        c.restoreState()

    doc = SimpleDocTemplate(chemin, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=titre, author="Archi")
    doc.build(h, onFirstPage=pied, onLaterPages=pied)
    phrase = f"C'est fait : le PDF « {titre} » est prêt" + (f", avec une carte de {len(lieux) - len(rates)} lieu(x)" if lieux else "") + "."
    if rates:
        phrase += f" Je n'ai pas trouvé la position de : {', '.join(rates[:6])}."
    if notes:
        phrase += " Attention : " + " ; ".join(notes) + "."
    return repondre(True, phrase, document=chemin, lieux_places=len(lieux) - len(rates))


def main():
    pa = argparse.ArgumentParser()
    pa.add_argument("--fichier", required=True)
    a = pa.parse_args()
    try:
        with open(a.fichier, encoding="utf-8-sig") as f:
            d = json.load(f)
    except Exception:
        return repondre(False, "La demande est illisible.")
    try:
        return creer(d if isinstance(d, dict) else {"contenu": str(d)})
    except Erreur as e:
        return repondre(False, str(e))
    except Exception as e:
        return repondre(False, f"Le PDF n'a pas pu être fabriqué ({type(e).__name__} : {str(e)[:150]}).")


if __name__ == "__main__":
    main()
