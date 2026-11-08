# -*- coding: utf-8 -*-
"""indexer.py - fabrique l'index de la bibliotheque musicale de l'utilisateur (LECTURE SEULE du dossier Music).
Sortie : memoire/passions/musique_index.tsv  (artiste, titre, album, genre, annee, chemin)
Relancer apres avoir ajoute des morceaux : python indexer.py"""
import os, re, sys, unicodedata
from mutagen import File as MFile

# LE LIEN BIBLIOTHEQUE -> CHATEAU : les dossiers de musique a indexer (lecture seule), separes par ";"
#   ex. ARCHI_MUSIQUE=D:/Musique;//NAS/musique   (par defaut : le dossier Musique de l'utilisateur)
RACINES = [r for r in os.environ.get("ARCHI_MUSIQUE", os.path.join(os.path.expanduser("~"), "Music")).split(";") if r.strip()]
BASE = os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files")
SORTIE = os.path.join(BASE, "memoire", "passions", "musique_index.tsv")
EXT = {".mp3", ".wma", ".m4a", ".wav", ".mpc", ".flac", ".ogg", ".aac", ".opus", ".ape"}

def prem(tags, *cles):
    for k in cles:
        try:
            v = tags.get(k)
        except Exception:
            v = None
        if v is None:
            continue
        if hasattr(v, "text"):
            v = v.text
        if isinstance(v, (list, tuple)):
            v = v[0] if v else ""
        v = str(v).strip()
        if v:
            return v
    return ""

def propre(s):
    return re.sub(r"[\t\r\n]+", " ", s or "").strip()

DOSSIERS = {"compil", "playlist", "playlists", "mp3", "music", "musik", "musika", "musique", "divers", "nouveau dossier"}


def nettoyer(s):
    s = re.sub(r"\[[^\]]*(youtube|mp3|download|www)[^\]]*\]", "", s or "", flags=re.I)
    s = re.sub(r"\s*-\s*copie(\s*\(\d+\))?\s*$", "", s, flags=re.I)
    s = re.sub(r"\s*\(\d\)\s*$", "", s)
    s = s.replace("_", " ")
    return re.sub(r"\s+", " ", s).strip(" -")


def depuis_nom(chemin):
    b = nettoyer(os.path.splitext(os.path.basename(chemin))[0])
    b = re.sub(r"^\s*\d{1,3}\s*[-._)]\s*", "", b)
    if " - " in b:
        a, t = b.split(" - ", 1)
        a = re.sub(r"^\s*\d{1,3}\s*[-._)]?\s*", "", a)
        return a.strip(), t.strip()
    return "", b.strip()

def cle(a, t):
    s = unicodedata.normalize("NFD", (a + "|" + t).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9|]+", "", s)

vus, lignes, n = set(), [], 0
for R in RACINES:
    for dp, dn, fn in os.walk(R):
        for f in fn:
            if os.path.splitext(f)[1].lower() not in EXT:
                continue
            p = os.path.join(dp, f)
            n += 1
            a = t = al = g = an = ""
            try:
                m = MFile(p, easy=True)
                if m is not None and m.tags is not None:
                    tg = m.tags
                    a = prem(tg, "artist", "albumartist", "Author", "WM/AlbumArtist")
                    t = prem(tg, "title", "Title")
                    al = prem(tg, "album", "WM/AlbumTitle")
                    g = prem(tg, "genre", "WM/Genre")
                    an = prem(tg, "date", "WM/Year")[:4]
            except Exception:
                pass
            t = re.sub(r"^\s*\d{1,3}\s*[-._]\s+", "", t or "")
            if not a or not t:
                a2, t2 = depuis_nom(p)
                a2, t2 = nettoyer(a2), nettoyer(t2)
                a = a or a2
                t = t or t2
            if not a:
                dossier = os.path.basename(os.path.dirname(p))
                a = "" if dossier.lower() in DOSSIERS else dossier
            if a.lower() in DOSSIERS or t.lower() == "copie":
                a, t = (a if a.lower() not in DOSSIERS else ""), (t if t.lower() != "copie" else "")
                if not t:
                    continue
            k = cle(a, t)
            if k in vus:
                continue
            vus.add(k)
            lignes.append("\t".join(propre(x) for x in (a, t, al, g, an, p)))
            if n % 2000 == 0:
                print(n, "fichiers lus", file=sys.stderr, flush=True)
with open(SORTIE, "w", encoding="utf-8") as o:
    o.write("artiste\ttitre\talbum\tgenre\tannee\tchemin\n")
    o.write("\n".join(lignes) + "\n")
print(f"{n} fichiers, {len(lignes)} morceaux distincts -> {SORTIE}")
