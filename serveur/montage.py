# montage.py - le monteur video d'Archi.
#   python montage.py --fichier demande.json   (lance en arriere-plan par n8n)
#   python montage.py etat | stop | lister
# demande : {"mode": "event"|"souvenirs", "date": "2026-05-21" | "fichiers": [...] | rien (= dossier « A monter »),
#            "duree_min": 10, "titre": "...", "participants": ["..."], "ambiance": "epique|calme|energique"}
# Mode event : temps forts d'une soiree (jeu en ligne, match, fete) : marqueurs « Archi, clip », pics de son, voix excitees.
# Mode souvenirs : balade, vacances, sortie : meilleurs plans, coupes regulieres sur la musique.
# Sorties dans Videos\Montages : la video (MP4), les sous-titres (SRT, a part) et le projet DaVinci (FCPXML).

import glob
import html
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import wave
from datetime import datetime, timedelta

import numpy as np

ACCUEIL = os.path.expanduser("~")
VIDEOS = os.path.join(ACCUEIL, "Videos")
A_MONTER = os.path.join(VIDEOS, "À monter")
MONTAGES = os.path.join(VIDEOS, "Montages")
MUSIQUE = os.path.join(VIDEOS, "Musique libre")
BASE = os.path.join(os.environ.get("ARCHI_BASE") or os.path.join(ACCUEIL, ".n8n-files"), "montage")
ETAT = os.path.join(BASE, "etat.json")
_WH = os.environ.get("ARCHI_WHISPER_DIR") or os.path.join(os.path.expanduser("~"), "whisper")   # dossier de ffmpeg + whisper.cpp (ARCHI_WHISPER_DIR)
FFMPEG = os.path.join(_WH, "ffmpeg.exe")
WHISPER = os.environ.get("ARCHI_WHISPER") or os.path.join(_WH, "whisper-bin-x64", "Release", "whisper-cli.exe")
WHISPER_MODELE = os.path.join(_WH, "ggml-small.bin")
LM = os.environ.get("ARCHI_LM_URL", "http://127.0.0.1:1234/v1").rstrip("/") + "/chat/completions"
RETOUR = os.environ.get("ARCHI_WEBHOOK_ALERTE", "")   # webhook n8n LOCAL qui previent l'utilisateur (facultatif)
POLICE = "C\\:/Windows/Fonts/arialbd.ttf"
POLICE_TITRE = "C\\:/Windows/Fonts/impact.ttf" if os.path.exists(r"C:\Windows\Fonts\impact.ttf") else POLICE
FPS = 30
W, H = 1920, 1080
EXT_VIDEO = (".mp4", ".mkv", ".mov", ".avi", ".m4v", ".webm")
EXT_PHOTO = (".jpg", ".jpeg", ".png", ".webp")
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
CREATION = 0x08000000  # pas de fenetre noire

for d in (A_MONTER, MONTAGES, BASE, os.path.join(MUSIQUE, "epique"), os.path.join(MUSIQUE, "calme"), os.path.join(MUSIQUE, "energique")):
    os.makedirs(d, exist_ok=True)


# ---------- outils ----------
def ffprobe_exe():
    c = sorted(glob.glob(os.path.join(_WH, "ffmpeg-*", "bin", "ffprobe.exe")))
    return c[-1] if c else "ffprobe"


FFPROBE = ffprobe_exe()


def lancer(cmd, timeout=None):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=timeout, creationflags=CREATION)
    if r.returncode != 0:
        raise RuntimeError(" ".join(str(c) for c in cmd[:3]) + " : " + (r.stderr or "")[-400:])
    return r.stdout


def lire_etat():
    try:
        with open(ETAT, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def etat(**k):
    e = lire_etat()
    e.update(k)
    e["maj"] = datetime.now().isoformat(timespec="seconds")
    with open(ETAT, "w", encoding="utf-8") as f:
        json.dump(e, f, ensure_ascii=False, indent=1)
    if lire_etat().get("stop_demande") and k.get("en_cours", True):
        raise InterruptedError("arrêté par l'utilisateur")


def renvoyer(texte, vocal):
    if not RETOUR:
        return
    try:
        req = urllib.request.Request(RETOUR, data=json.dumps({"type": "REPONSE", "canal": "montage", "texte": texte, "vocal": vocal}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=30).read()
    except Exception:
        pass


def sans_accents(t):
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


def hms(s):
    s = max(0, s)
    return f"{int(s // 3600):02d}:{int(s % 3600 // 60):02d}:{s % 60:06.3f}".replace(".", ",")


def court(s):
    return f"{int(s // 3600)}h{int(s % 3600 // 60):02d}" if s >= 3600 else f"{int(s // 60)} min {int(s % 60):02d}"


def jeu_ouvert():
    try:
        # le jeu a surveiller (ARCHI_MONTAGE_JEU, ex. MonJeu.exe) : pas de montage lourd pendant une partie
        jeu = os.environ.get("ARCHI_MONTAGE_JEU", "").strip()
        if not jeu:
            return False
        r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {jeu}"], capture_output=True, text=True, creationflags=CREATION)
        return jeu.lower() in r.stdout.lower()
    except Exception:
        return False


def sonder(f):
    d = json.loads(lancer([FFPROBE, "-v", "error", "-show_entries", "format=duration:stream=index,codec_type,width,height",
                           "-show_chapters", "-of", "json", f], 60))
    audios = [s for s in d.get("streams", []) if s.get("codec_type") == "audio"]
    videos = [s for s in d.get("streams", []) if s.get("codec_type") == "video"]
    return {"fichier": f, "duree": float(d.get("format", {}).get("duration") or 0), "pistes": len(audios),
            "video": bool(videos), "chapitres": [float(c.get("start_time", 0)) for c in d.get("chapters", [])]}


# ---------- choix des fichiers ----------
def date_du_nom(f):
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})[ _](\d{2})-(\d{2})-(\d{2})", os.path.basename(f))
    if m:
        return datetime(*map(int, m.groups()))
    return datetime.fromtimestamp(os.path.getmtime(f))


def choisir_fichiers(d):
    if d.get("fichiers"):
        L = [f if os.path.isabs(f) else os.path.join(VIDEOS, f) for f in d["fichiers"]]
    elif d.get("date"):
        jour = datetime.strptime(d["date"][:10], "%Y-%m-%d")
        debut, fin = jour + timedelta(hours=12), jour + timedelta(days=1, hours=10)   # une soiree deborde apres minuit
        if d.get("mode") == "souvenirs":
            debut, fin = jour, jour + timedelta(days=1)
        tous = [f for dos in (VIDEOS, A_MONTER) for f in glob.glob(os.path.join(dos, "*")) if f.lower().endswith(EXT_VIDEO + EXT_PHOTO)]
        L = [f for f in tous if debut <= date_du_nom(f) < fin]
        if not L:      # rien le soir de ce jour : on prend tout ce qui a ete enregistre ce jour-la (ex : une soiree commencee a 0 h 06)
            L = [f for f in tous if jour <= date_du_nom(f) < jour + timedelta(days=1)]
    else:
        L = [f for f in glob.glob(os.path.join(A_MONTER, "**", "*"), recursive=True) if f.lower().endswith(EXT_VIDEO + EXT_PHOTO)]
    L = [f for f in L if os.path.exists(f)]
    return sorted(set(L), key=date_du_nom)


# ---------- analyse du son ----------
def extraire_son(src, piste, sortie):
    lancer([FFMPEG, "-y", "-v", "error", "-i", src, "-map", f"0:a:{piste}", "-ac", "1", "-ar", "16000", sortie], 3 * 3600)


def volume_par_seconde(wav, avec_coups=False):
    """Volume moyen par seconde ; avec_coups : aussi les COUPS (tir, explosion) = pic bref au-dessus du bruit ambiant."""
    with wave.open(wav) as w:
        sr = w.getframerate()
        q = sr // 8                       # tranches de 1/8 s
        moy, pic = [], []
        while True:
            b = w.readframes(sr * 60)
            if not b:
                break
            x = np.frombuffer(b, dtype=np.int16).astype(np.float32)
            n = len(x) // sr
            if n == 0:
                break
            x = x[: n * sr]
            moy.append(20 * np.log10(np.sqrt((x.reshape(n, sr) ** 2).mean(axis=1)) + 1.0))
            t = 20 * np.log10(np.sqrt((x.reshape(n * 8, q) ** 2).mean(axis=1)) + 1.0)
            pic.append(t.reshape(n, 8).max(axis=1))
    if not moy:
        return (np.zeros(1), np.zeros(1)) if avec_coups else np.zeros(1)
    moy, pic = np.concatenate(moy), np.concatenate(pic)
    if not avec_coups:
        return moy
    # fond sonore = mediane glissante sur 21 s ; un coup = pic qui depasse nettement ce fond
    pad = np.pad(moy, 10, mode="edge")
    fond = np.median(np.lib.stride_tricks.sliding_window_view(pad, 21), axis=1)[: len(moy)]
    coups = np.clip(pic - fond - 6, 0, None)
    return moy, coups


def transcrire(wav, base):
    lancer([WHISPER, "-m", WHISPER_MODELE, "-l", "fr", "-t", "12", "-f", wav, "-osrt", "-of", base, "-np", "-ml", "70", "-sow"], 4 * 3600)
    segs = []
    try:
        txt = open(base + ".srt", encoding="utf-8", errors="ignore").read()
    except Exception:
        return segs
    for m in re.finditer(r"(\d\d):(\d\d):(\d\d)[,.](\d{3}) --> (\d\d):(\d\d):(\d\d)[,.](\d{3})\s*\n(.+?)(?:\n\n|\Z)", txt, re.S):
        g = list(map(int, m.groups()[:8]))
        a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        t = " ".join(m.group(9).split()).strip()
        if t and not re.fullmatch(r"[\[\(].*[\]\)]|\W*", t):
            segs.append((a, b, t))
    return segs


MARQUEUR = re.compile(r"\b(archi|archie|archy|arche|arshi|archi\w*)\W{0,4}\s*(clip|clips|clipe|clippe|klip|clic)\b")
EXCITATION = re.compile(r"putain|merde|bordel|oh p|ah p|vas[- ]?y|go go|allez|feu|tire|tirez|contact|il est l|on l.a eu|on les a|boom|explos|cours|attention|derri.re toi|a l.aide|au secours|j.suis mort|je suis mort|on a perdu|incroyable|mdr|ptdr|haha|hahaha|ouais+|yes+|wow|ouf|enorme|abuse|chaud", re.I)


def z(v):
    v = np.asarray(v, dtype=np.float32)
    s = v.std()
    return (v - v.mean()) / s if s > 0 else v * 0


def lisser(v, n=8):
    if len(v) < n:
        return v
    return np.convolve(v, np.ones(n) / n, mode="same")


# ---------- modele local ----------
def llm(systeme, contenu, jetons=2500):
    corps = {"model": os.environ.get("ARCHI_MODELE", "openai/gpt-oss-20b"), "temperature": 0.3, "max_tokens": jetons,
             "messages": [{"role": "system", "content": systeme}, {"role": "user", "content": contenu}]}
    req = urllib.request.Request(LM, data=json.dumps(corps).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=600) as r:
        txt = json.loads(r.read().decode("utf-8"))["choices"][0]["message"].get("content") or ""
    return re.sub(r"(?s)<think>.*?</think>", "", txt).strip()


# ---------- les yeux : le modele d'image regarde une image toutes les 10 s ----------
MODELE_IMAGE = os.environ.get("ARCHI_MODELE_VISION", "google/gemma-3-12b")
PAS_IMAGES = 10
PAR_LOT = 4


def image(src, t, sortie):
    lancer([FFMPEG, "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", src, "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "5", sortie], 60)


def regarder(src, duree, travail, i_src, n_src):
    """Note d'action (0-10) par seconde, d'apres ce que voit le modele d'image. Renvoie (notes, descriptions)."""
    import base64
    temps = list(np.arange(PAS_IMAGES / 2, max(duree - 1, PAS_IMAGES / 2 + 0.1), PAS_IMAGES))
    notes = np.zeros(int(math.ceil(duree)) + 1, dtype=np.float32)
    quoi = {}
    vus = []
    for k in range(0, len(temps), PAR_LOT):
        etat(etape=f"Archi regarde la vidéo ({i_src + 1}/{n_src}) : image {min(k + PAR_LOT, len(temps))}/{len(temps)}")
        lot = temps[k: k + PAR_LOT]
        contenu = [{"type": "text", "text": (
            f"Voici {len(lot)} images tirées d'une partie de jeu en ligne (vue du joueur), une toutes les {PAS_IMAGES} secondes. "
            "Note l'ACTION de chaque image de 0 à 10 : 0-2 = menu, écran de chargement, inventaire, couloir vide, attente ; "
            "3-5 = déplacement, vol calme, paysage ; 6-8 = combat, tir, ennemi visible, viseur ou lunette de sniper sur une cible, "
            "véhicule ou tank en action ; 9-10 = explosion, vaisseau ou véhicule en feu, débris, gros combat. "
            "Réponds UNIQUEMENT par un JSON : {\"notes\": [une note par image, dans l'ordre], \"quoi\": [2 à 5 mots en français par image]}")}]
        for j, t in enumerate(lot):
            f = os.path.join(travail, f"img_{j}.jpg")
            try:
                image(src, t, f)
                b64 = base64.b64encode(open(f, "rb").read()).decode()
                contenu.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}})
            except Exception:
                pass
        try:
            corps = {"model": MODELE_IMAGE, "temperature": 0, "max_tokens": 600, "messages": [{"role": "user", "content": contenu}],
                     "chat_template_kwargs": {"enable_thinking": False}, "reasoning_effort": "none"}   # pas de longue reflexion : une note, vite
            req = urllib.request.Request(LM, data=json.dumps(corps).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=300) as r:
                m = json.loads(r.read().decode("utf-8"))["choices"][0]["message"]
            txt = re.sub(r"(?s)<think>.*?</think>", "", m.get("content") or m.get("reasoning_content") or "")
            d = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
            for j, t in enumerate(lot):
                n = float((d.get("notes") or [])[j]) if j < len(d.get("notes") or []) else 0.0
                a, b = int(max(0, t - PAS_IMAGES / 2)), int(min(len(notes), t + PAS_IMAGES / 2))
                notes[a:b] = n
                if j < len(d.get("quoi") or []) and n >= 6:
                    quoi[int(t)] = str(d["quoi"][j])[:40]
            vus.append(len(lot))
        except InterruptedError:
            raise
        except Exception:
            continue
    return notes, quoi, sum(vus)


# ---------- mode event ----------
def tirs_au_ralenti(sources, travail, n_max=80):
    """A chaque tir ou explosion entendu, le modele d'image compare l'image juste avant et juste apres :
    ennemi dans le viseur ? le tir touche / tue / fait exploser ? Renvoie [(temps global, touche, cible, quoi)]."""
    import base64
    coups_t, decal = [], 0.0
    for i, s in enumerate(sources):
        if not s["video"] or s["pistes"] == 0:
            decal += s["duree"]
            continue
        etat(etape=f"repérage des tirs ({i + 1}/{len(sources)})")
        w = os.path.join(travail, f"tirs_{i}.wav")
        extraire_son(s["fichier"], 1 if s["pistes"] >= 3 else 0, w)
        _m, c = volume_par_seconde(w, True)
        os.remove(w)
        # un tir = maximum local (les rafales comptent pour un)
        for t in range(1, len(c) - 1):
            if c[t] > 0 and c[t] >= c[max(0, t - 3): t + 4].max():
                coups_t.append((float(c[t]), decal + t, s, t))
        decal += s["duree"]
    coups_t = sorted(coups_t, key=lambda x: -x[0])[:n_max]
    coups_t.sort(key=lambda x: x[1])
    res = []
    for k in range(0, len(coups_t), 2):
        lot = coups_t[k: k + 2]
        etat(etape=f"Archi regarde les tirs au ralenti : {min(k + 2, len(coups_t))}/{len(coups_t)}")
        contenu = [{"type": "text", "text": (
            f"jeu en ligne, vue du joueur. Voici {len(lot)} paire(s) d'images : pour chaque paire, l'image AVANT un tir ou une explosion "
            "entendue, puis l'image 1 à 2 secondes APRÈS. Pour chaque paire, dis : cible = un ennemi (joueur, soldat, véhicule, vaisseau) "
            "est-il visible dans le viseur ou devant l'arme ? touche = le tir touche, tue ou détruit quelque chose (ennemi qui tombe, "
            "marqueur de touche, véhicule ou vaisseau qui explose, gros impact) ? "
            "Réponds UNIQUEMENT par un JSON : {\"paires\": [{\"cible\": true/false, \"touche\": true/false, \"quoi\": \"3 à 6 mots en français\"}]}")}]
        for j, (_v, tg, s, tl) in enumerate(lot):
            for nom, t in (("avant", tl - 0.6), ("apres", tl + 1.6)):
                f = os.path.join(travail, f"tir_{j}_{nom}.jpg")
                try:
                    image(s["fichier"], max(0, t), f)
                    contenu.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(open(f, "rb").read()).decode()}})
                except Exception:
                    pass
        try:
            corps = {"model": MODELE_IMAGE, "temperature": 0, "max_tokens": 500, "messages": [{"role": "user", "content": contenu}],
                     "chat_template_kwargs": {"enable_thinking": False}, "reasoning_effort": "none"}
            req = urllib.request.Request(LM, data=json.dumps(corps).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=300) as r:
                m = json.loads(r.read().decode("utf-8"))["choices"][0]["message"]
            txt = re.sub(r"(?s)<think>.*?</think>", "", m.get("content") or m.get("reasoning_content") or "")
            pa = json.loads(re.search(r"\{.*\}", txt, re.S).group(0)).get("paires") or []
            for j, (_v, tg, _s, _t) in enumerate(lot):
                if j < len(pa):
                    x = pa[j]
                    res.append((tg, bool(x.get("touche")), bool(x.get("cible")), str(x.get("quoi") or "")[:40]))
        except InterruptedError:
            raise
        except Exception:
            continue
    return res


def cle_analyse(sources, yeux):
    import hashlib
    h = hashlib.sha1()
    for s in sources:
        st = os.stat(s["fichier"])
        h.update(f"{s['fichier']}|{st.st_size}|{int(st.st_mtime)}|".encode("utf-8"))
    h.update(f"yeux={bool(yeux)}|v2".encode())
    return h.hexdigest()[:16]


def analyser_event(sources, travail, yeux=True):
    """Analyse (son, voix, image) d'un event, gardee en memoire : un 2e montage du meme event ne refait pas l'analyse."""
    dos = os.path.join(BASE, "analyses")
    os.makedirs(dos, exist_ok=True)
    f = os.path.join(dos, cle_analyse(sources, yeux) + ".json")
    if os.path.exists(f):
        etat(etape="analyse déjà faite, je la réutilise")
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        score = np.array(d["score"], dtype=np.float32)
        segs = [tuple(x) for x in d["segs"]]
        vues = {float(k): v for k, v in d["vues"].items()}
        marqueurs = d["marqueurs"]
    else:
        marqueurs, score, segs, vues = analyser_event_complet(sources, travail, yeux)
        d = {"score": [round(float(x), 3) for x in score], "segs": segs, "vues": {str(k): v for k, v in vues.items()},
             "marqueurs": marqueurs, "fichiers": [s["fichier"] for s in sources]}
        with open(f, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
    if yeux and "tirs" not in d:
        d["tirs"] = tirs_au_ralenti(sources, travail)
        with open(f, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
    # les tirs qui touchent (kill, vehicule detruit) deviennent des temps forts majeurs
    score = score.copy()
    touches = sorted(float(tg) for tg, touche, _c, _q in d.get("tirs", []) if touche)
    tirs_tous = sorted(float(x[0]) for x in d.get("tirs", []) if x[1] or x[2])   # seulement les vrais tirs : ennemi vise ou touche
    for tg, touche, cible, quoi in d.get("tirs", []):
        t = int(tg)
        if touche:
            score[max(0, t - 4): t + 6] += 4.0
            vues[float(t)] = quoi or "tir qui touche"
        elif cible:
            score[max(0, t - 3): t + 4] += 1.2
    return marqueurs, score, segs, vues, touches, tirs_tous


def fenetres(score, total, n_max=60, ecart=45):
    """Les pics d'action, avec pour chacun le DEBUT de l'action (on remonte tant que ca chauffe) et sa FIN."""
    seuil = float(np.percentile(score, 55))
    res, s2 = [], score.copy()
    for _ in range(n_max):
        p = int(np.argmax(s2))
        if s2[p] < -1e8 or s2[p] <= seuil + 0.2:
            break
        a = p
        while a > 0 and p - a < 40 and score[a - 1] > seuil:
            a -= 1
        b = p
        while b < len(score) - 1 and b - p < 25 and score[b + 1] > seuil:
            b += 1
        # l'action continue ? (poursuite, recharge, nouveau tir dans les 15 s) : on suit jusqu'au bout, 90 s apres le pic au plus
        bas = float(np.percentile(score, 50))
        while b < len(score) - 16 and b - p < 90 and score[b + 1: b + 16].max() > bas:
            b += 1
        debut = max(0, min(a, p - 22) - 8)           # au moins 30 s avant le pic : on voit l'action monter
        fin = min(total, max(b, p + 15) + 6)          # et la suite : le resultat (explosion, mort)
        res.append((p, float(s2[p]), debut, fin))
        s2[max(0, p - ecart): p + ecart] = -1e9
    return res


def analyser_event_complet(sources, travail, yeux=True):
    """Renvoie (marqueurs, score par seconde, segments_texte, vues) en temps GLOBAL (sources mises bout a bout)."""
    decal = 0.0
    score_global, segs_global, marqueurs = [], [], []
    vues = {}
    for i, s in enumerate(sources):
        etat(etape=f"analyse du son ({i + 1}/{len(sources)})", fichier=os.path.basename(s["fichier"]))
        voix_piste = 2 if s["pistes"] >= 3 else 0
        jeu_piste = 1 if s["pistes"] >= 3 else None
        wv = os.path.join(travail, f"voix_{i}.wav")
        extraire_son(s["fichier"], voix_piste, wv)
        v, coups_voix = volume_par_seconde(wv, True)
        sc = 0.6 * z(lisser(v, 6))
        coups = coups_voix
        if jeu_piste is not None:
            wj = os.path.join(travail, f"jeu_{i}.wav")
            extraire_son(s["fichier"], jeu_piste, wj)
            j, coups = volume_par_seconde(wj, True)
            n = min(len(j), len(sc))
            sc = sc[:n] + 0.5 * z(lisser(j, 6))[:n]
            os.remove(wj)
        # tirs et explosions : les coups brefs comptent beaucoup, et ce qui suit (le resultat) aussi
        n = min(len(sc), len(coups))
        cp_ = np.convolve(coups[:n], np.ones(6), mode="full")[:n]      # un coup « rayonne » sur les 6 s suivantes
        sc = sc[:n] + 1.4 * z(cp_)
        attendu = int(math.ceil(s["duree"]))
        sc = np.pad(sc, (0, max(0, attendu - len(sc))))[:attendu]
        if yeux and s["video"]:
            notes, quoi, nb = regarder(s["fichier"], s["duree"], travail, i, len(sources))
            if nb:
                nt = np.pad(notes, (0, max(0, attendu - len(notes))))[:attendu]
                sc = sc + 1.6 * z(nt) + np.where(nt >= 8, 1.5, 0)      # ce qui SE VOIT compte fort
                vues.update({decal + t: q for t, q in quoi.items()})
        # tes marqueurs OBS (chapitres), s'il y en a
        marqueurs += [decal + c for c in s["chapitres"]]
        etat(etape=f"transcription des voix ({i + 1}/{len(sources)}, la plus longue étape)")
        segs = transcrire(wv, os.path.join(travail, f"voix_{i}"))
        os.remove(wv)
        for a, b, t in segs:
            tt = sans_accents(t)
            if MARQUEUR.search(tt):
                marqueurs.append(decal + a)
            if EXCITATION.search(tt):
                sc[int(a): int(b) + 1] += 1.5
            segs_global.append((decal + a, decal + b, t))
        score_global.append(sc)
        decal += s["duree"]
    score = np.concatenate(score_global) if score_global else np.zeros(1)
    score = lisser(score, 10)
    return sorted(set(round(m, 1) for m in marqueurs)), score, segs_global, vues


def texte_entre(segs, a, b, maxi=400):
    return " ".join(t for x, y, t in segs if y >= a and x <= b)[:maxi]


def vu_pres(vues, p, r=15):
    proches = [(abs(t - p), q) for t, q in vues.items() if abs(t - p) <= r]
    return min(proches)[1] if proches else ""


ACTION_VUE = re.compile(r"explos|combat|feu|tir|impact|d[ée]trui|tank|char|attaque|ennemi|bless|tu[ée]|abattu|crash|missile|roquette|d[ée]bris", re.I)
RIRES = re.compile(r"rire|haha|ahah|hihi|mdr|ptdr|lol", re.I)


def vaut_le_coup(a, b, p, vues, segs, tirs_tous):
    """Un moment garde sa place s'il y a de l'ACTION (tirs entendus, explosion, combat vus), ou un vrai fou rire."""
    if any(a <= t <= b for t in tirs_tous):
        return "action"
    if any(a <= t <= b and ACTION_VUE.search(q) for t, q in vues.items()):
        return "action"
    if len(RIRES.findall(texte_entre(segs, a, b, 5000))) >= 2:
        return "rires"
    return None


def plages(texte):
    """« 26:10-27:00, 41:30-43:00 » ou « 1:02:30-1:04:00 » -> [(debut_s, fin_s)] (temps de l'event)."""
    def sec(x):
        p = [float(v) for v in x.strip().split(":")]
        return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1] if len(p) == 2 else p[0] * 60
    res = []
    for a, b in re.findall(r"(\d+(?::\d{1,2}){0,2})\s*(?:-|à|a|->)\s*(\d+(?::\d{1,2}){0,2})", str(texte or "")):
        x, y = sec(a), sec(b)
        if y > x:
            res.append((x, y))
    return res


def choisir_event(marqueurs, candidats, segs, duree_cible, total, vues=None, touches=None, tirs_tous=None, garder=None, enlever=None):
    vues = vues or {}
    tirs_tous = tirs_tous or []
    enlever = enlever or []
    hors = lambda a, b: not any(a < y and b > x for x, y in enlever)
    candidats = [c for c in candidats if hors(c[2], c[3])]
    marqueurs = [m for m in marqueurs if hors(m - 1, m + 1)]
    touches = [t for t in (touches or []) if hors(t - 1, t + 1)]
    if tirs_tous or vues:          # on a des yeux : on ecarte l'attente et les discussions sans action
        gardes, rires = [], 0
        for c in candidats:
            nature = vaut_le_coup(c[2], c[3], c[0], vues, segs, tirs_tous)
            if nature == "action" or (nature == "rires" and rires < 2):
                rires += nature == "rires"
                gardes.append(c)
        candidats = gardes
    morceaux = [{"debut": x, "fin": min(total, y), "pourquoi": "choisi par toi", "prio": -1} for x, y in (garder or [])]
    # 1) tes marqueurs d'abord : 2 min avant, 20 s apres ; raccourcis si ca deborde
    avant, apres = 120, 20
    if marqueurs and len(marqueurs) * (avant + apres) > duree_cible * 0.85:
        avant = max(30, int(duree_cible * 0.85 / len(marqueurs)) - apres)
    for m in marqueurs:
        morceaux.append({"debut": max(0, m - avant), "fin": min(total, m + apres), "pourquoi": "ton marqueur « Archi, clip »", "prio": 0})
    # 1bis) les tirs qui touchent (kill, vehicule ou vaisseau detruit), vus au ralenti : juste apres tes marqueurs
    for t in (touches or []):
        morceaux.append({"debut": max(0, t - 30), "fin": min(total, t + 12), "pic": t,
                         "pourquoi": vu_pres(vues, t, 3) or "tir qui touche", "prio": 0.5})
    # 2) le modele local classe les pics de son par interet, d'apres ce qui se dit
    ordre = list(range(len(candidats)))
    if candidats:
        liste = "\n".join(f"{k}. vers {court(p)} : à l'image : {vu_pres(vues, p) or '?'} ; paroles : « {texte_entre(segs, p - 25, p + 15) or '(aucune)'} »"
                          for k, (p, sc, _a, _b) in enumerate(candidats[:30]))
        try:
            rep = llm("""Tu montes le best-of d'une soirée de jeu entre amis. On te donne des moments repérés par le volume
du son et de l'image, avec ce qu'on voit à l'écran et ce que disent les joueurs. Ce qui SE VOIT prime : explosion, tir, combat,
élimination, but, victoire. Le montage est fait pour quelqu'un qui n'était PAS là : les discussions
et l'attente l'ennuient, seuls les gros fous rires méritent une place. Classe-les du plus intéressant au moins intéressant : action (combat, poursuite, explosion,
atterrissage raté), fous rires, moments d'équipe, réussites. Écarte les moments vides (attente, réglages, silence, discussions
hors-jeu). Donne à chaque moment un titre court EN FRANÇAIS (3 à 5 mots, ex : « Duel final », « Le grand fou rire »).
Réponds UNIQUEMENT par un JSON : {"ordre": [TOUS les numéros, du plus au moins intéressant], "titres": {"numéro": "titre court en français"}}""", liste, 1500)
            d = json.loads(re.search(r"\{.*\}", rep, re.S).group(0))
            vus_k = []
            for k in d.get("ordre", []):
                if str(k).isdigit() and 0 <= int(k) < len(candidats) and int(k) not in vus_k:
                    vus_k.append(int(k))
            ordre = vus_k + [k for k in range(len(candidats)) if k not in vus_k]   # les oublies passent a la fin
            titres = {int(k): v for k, v in (d.get("titres") or {}).items() if str(k).isdigit()}
        except Exception:
            titres = {}
    else:
        titres = {}
    for rang, k in enumerate(ordre):
        p, _sc, a_, b_ = candidats[k]
        morceaux.append({"debut": a_, "fin": b_, "pic": p, "pourquoi": titres.get(k) or vu_pres(vues, p) or "pic d'action (tirs, explosions)", "prio": 1 + rang})
    # 3) on remplit jusqu'a la duree voulue, priorites d'abord, puis on remet dans l'ordre du temps
    garde, cumul = [], 0.0
    for m in sorted(morceaux, key=lambda x: x["prio"]):
        if any(m["debut"] < g["fin"] + 8 and m["fin"] > g["debut"] - 8 for g in garde):   # moments qui se touchent : on les relie (90 s max)
            for g in garde:
                if m["debut"] < g["fin"] + 8 and m["fin"] > g["debut"] - 8 and max(g["fin"], m["fin"]) - min(g["debut"], m["debut"]) <= 130:
                    avant_l = g["fin"] - g["debut"]
                    g["debut"], g["fin"] = min(g["debut"], m["debut"]), max(g["fin"], m["fin"])
                    cumul += (g["fin"] - g["debut"]) - avant_l
            continue
        reste = duree_cible - cumul
        if (m["fin"] - m["debut"]) > reste and m["prio"] >= 1:
            if reste < 10:
                continue
            pic_ = m.get("pic", m["debut"] + 30)      # on raccourcit en gardant la montee de l'action ET son resultat
            m = dict(m, debut=max(0, pic_ - reste * 0.65), fin=pic_ + reste * 0.35)
        garde.append(dict(m))
        cumul += m["fin"] - m["debut"]
        if cumul >= duree_cible:
            break
    # 4) trop court ? on elargit chaque moment (plus de contexte avant, un peu apres)
    if garde and cumul < duree_cible * 0.85:
        manque = duree_cible - cumul
        par = min(15.0, manque / len(garde))
        for g in garde:
            if g["prio"] > 0:
                g["debut"] = max(0, g["debut"] - par * 0.5)
                g["fin"] = min(total, g["fin"] + par * 0.5)
        garde.sort(key=lambda x: x["debut"])
        fusion = [garde[0]]
        for g in garde[1:]:
            if g["debut"] <= fusion[-1]["fin"] and g["fin"] - fusion[-1]["debut"] <= 140:
                fusion[-1]["fin"] = max(fusion[-1]["fin"], g["fin"])
                fusion[-1]["pourquoi"] += " + " + g["pourquoi"]
            elif g["debut"] < fusion[-1]["fin"]:
                g["debut"] = fusion[-1]["fin"]          # pas de doublon, on coupe juste le chevauchement
                if g["fin"] - g["debut"] > 8:
                    fusion.append(g)
            else:
                fusion.append(g)
        garde = fusion
    return sorted(garde, key=lambda x: x["debut"])


# ---------- mode souvenirs ----------
def choisir_souvenirs(sources, duree_cible):
    vids = [s for s in sources if s["video"] and s["duree"] >= 2]
    photos = [s for s in sources if not s["video"]]
    n = len(vids) + len(photos)
    if not n:
        return []
    part = max(3.0, min(12.0, duree_cible / n))
    part = round(part / 2) * 2 or 2          # coupes sur des multiples de 2 s : ca tombe sur le temps fort des musiques
    morceaux, decal = [], 0.0
    for s in sources:
        if s["video"] and s["duree"] >= 2:
            d = min(part, s["duree"] - 0.5)
            milieu = s["duree"] * 0.45
            debut = max(0.3, min(milieu - d / 2, s["duree"] - d - 0.2))
            morceaux.append({"debut": decal + debut, "fin": decal + debut + d, "pourquoi": "plan", "prio": 1})
        elif not s["video"]:
            morceaux.append({"debut": decal, "fin": decal + min(part, 4), "pourquoi": "photo", "prio": 1, "photo": True})
        decal += s["duree"]
    return morceaux


# ---------- rendu ----------
def local(sources, t):
    """temps global -> (source, temps dans la source)"""
    for s in sources:
        if t < s["debut_global"] + s["duree"] - 0.05:
            return s, max(0.0, t - s["debut_global"])
    s = sources[-1]
    return s, max(0.0, t - s["debut_global"])


ENC = ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "20", "-qp_p", "22", "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
ENC_SECOURS = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]


def encoder(args_entree, filtres_v, filtres_a, sortie, duree, cartes=None):
    base = [FFMPEG, "-y", "-v", "error"] + args_entree
    cmd_f = ["-filter_complex", f"{filtres_v};{filtres_a}", "-map", "[v]", "-map", "[a]"] if cartes is None else cartes
    for enc in (ENC, ENC_SECOURS):
        try:
            lancer(base + cmd_f + ["-t", f"{duree:.3f}", "-r", str(FPS)] + enc + [sortie], 3600)
            return
        except RuntimeError:
            if enc is ENC_SECOURS:
                raise


CADRE = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS},format=yuv420p"


def effet_transition(nom, d, x=0.35):
    """Effet au debut (entree) et a la fin (sortie) d'un passage : glitch, secousse, flou, flash."""
    e_in, e_out = f"lt(t,{x})", f"gt(t,{max(0, d - x):.2f})"
    both = f"({e_in}+{e_out})"
    if nom == "glitch":
        return (f"rgbashift=rh=-14:bh=14:gv=6:enable='{both}',noise=alls=45:allf=t:enable='{both}',"
                f"hue=s=0:enable='between(t,0.08,0.16)+between(t,{max(0, d - 0.2):.2f},{max(0, d - 0.12):.2f})'")
    if nom == "secousse":
        return (f"crop=iw-48:ih-48:x='24+if({both},20*sin(t*95),0)':y='24+if({both},16*cos(t*83),0)',scale={W}:{H},setsar=1")
    if nom == "flou":
        return (f"gblur=sigma=22:enable='lt(t,0.14)+gt(t,{max(0, d - 0.14):.2f})',"
                f"gblur=sigma=9:enable='between(t,0.14,0.3)+between(t,{max(0, d - 0.3):.2f},{max(0, d - 0.14):.2f})'")
    # flash blanc
    return f"fade=t=in:st=0:d=0.22:color=white,fade=t=out:st={max(0, d - 0.18):.2f}:d=0.18:color=white"


EFFETS = ["glitch", "secousse", "flou", "flash"]


def rendre_morceau(m, sources, sortie, mode, effet=None):
    s, t0 = local(sources, m["debut"])
    d = m["fin"] - m["debut"]
    f = 0.3
    if m.get("photo"):
        vf = (f"[0:v]scale=3840:-2,zoompan=z='min(zoom+0.0008,1.12)':d={int(d * FPS)}:s={W}x{H}:fps={FPS},"
              f"format=yuv420p,fade=t=in:st=0:d={f},fade=t=out:st={d - f:.2f}:d={f}[v]")
        encoder(["-i", s["fichier"], "-f", "lavfi", "-t", f"{d:.2f}", "-i", "anullsrc=r=48000:cl=stereo"],
                vf, "[1:a]anull[a]", sortie, d)
        return
    if effet:
        f = 0.12
        vf = f"[0:v:0]{CADRE},{effet_transition(effet, d)},format=yuv420p[v]"
    else:
        vf = f"[0:v:0]{CADRE},fade=t=in:st=0:d={f},fade=t=out:st={max(0, d - f):.2f}:d={f}[v]"
    if s["pistes"] == 0:
        encoder(["-ss", f"{t0:.3f}", "-i", s["fichier"], "-f", "lavfi", "-t", f"{d:.2f}", "-i", "anullsrc=r=48000:cl=stereo"],
                vf, "[1:a]anull[a]", sortie, d)
        return
    vol = 1.0 if mode == "event" else 0.35
    af = f"[0:a:0]aresample=48000,volume={vol},afade=t=in:st=0:d={f},afade=t=out:st={max(0, d - f):.2f}:d={f}[a]"
    encoder(["-ss", f"{t0:.3f}", "-i", s["fichier"]], vf, af, sortie, d)


def echapper(t):
    # texte sans caracteres pieges pour ffmpeg
    return re.sub(r"[\\:'%;,\[\]=]", lambda m: {"'": "\u2019", ":": " -", "%": " pct"}.get(m.group(0), " "), t).strip() if t != "[REDACTED]" else t


def carton_titre(sortie, titre, sous_titre, cache, d=5.0):
    """titre : gros texte ; cache : mot ecrit puis barre d'un bandeau rouge [REDACTED] (illisible)."""
    v = [f"color=c=black:s={W}x{H}:r={FPS}:d={d}"]
    filtres = f"drawtext=fontfile='{POLICE_TITRE}':text='{echapper(titre)}':fontsize=150:fontcolor=white:x=(w-tw)/2:y=h*0.30"
    if cache:
        filtres += (f",drawtext=fontfile='{POLICE_TITRE}':text='{echapper(cache)}':fontsize=110:fontcolor=white:x=(w-tw)/2:y=h*0.50"
                    f",drawbox=x=iw*0.30:y=ih*0.485:w=iw*0.40:h=150:color=0xC0141C@1:t=fill"
                    f",drawtext=fontfile='{POLICE}':text='[REDACTED]':fontsize=72:fontcolor=white:x=(w-tw)/2:y=h*0.53")
    if sous_titre:
        filtres += f",drawtext=fontfile='{POLICE}':text='{echapper(sous_titre)}':fontsize=54:fontcolor=0xDDDDDD:x=(w-tw)/2:y=h*0.72"
    filtres += f",fade=t=in:st=0:d=0.6,fade=t=out:st={d - 0.6}:d=0.6,format=yuv420p"
    encoder(["-f", "lavfi", "-i", v[0], "-f", "lavfi", "-t", str(d), "-i", "anullsrc=r=48000:cl=stereo"],
            f"[0:v]{filtres}[v]", "[1:a]anull[a]", sortie, d)


def carton_fin(sortie, participants, d=7.0):
    lignes = ["MERCI À"] + [p.upper() for p in participants[:12]]
    haut = 110 + (len(lignes) - 1) * 66
    y0 = max(60, (H - haut) // 2)
    filtres = ",".join(f"drawtext=fontfile='{POLICE_TITRE if i == 0 else POLICE}':text='{echapper(l)}':fontsize={84 if i == 0 else 48}"
                       f":fontcolor={'white' if i == 0 else '0xDDDDDD'}:x=(w-tw)/2:y={y0 if i == 0 else y0 + 110 + (i - 1) * 66}"
                       for i, l in enumerate(lignes))
    filtres += f",fade=t=in:st=0:d=0.6,fade=t=out:st={d - 0.8}:d=0.8,format=yuv420p"
    encoder(["-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}:d={d}", "-f", "lavfi", "-t", str(d), "-i", "anullsrc=r=48000:cl=stereo"],
            f"[0:v]{filtres}[v]", "[1:a]anull[a]", sortie, d)


def choisir_musique(ambiance):
    dos = os.path.join(MUSIQUE, ambiance or "epique")
    L = [f for f in glob.glob(os.path.join(dos, "*")) + glob.glob(os.path.join(MUSIQUE, "*"))
         if f.lower().endswith((".mp3", ".wav", ".ogg", ".flac", ".m4a"))]
    return random.choice(L) if L else None


def mixer_musique(corps, musique, sortie, duree, mode):
    if mode == "event":
        # la musique baisse toute seule quand les joueurs parlent (compresseur declenche par les voix)
        fa = ("[1:a]aresample=48000,volume=0.30,afade=t=out:st={fo:.2f}:d=3[m];[0:a]asplit=2[o][sc];"
              "[m][sc]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=600[md];"
              "[o][md]amix=inputs=2:duration=first:normalize=0[a]").format(fo=max(0, duree - 3))
    else:
        fa = "[1:a]aresample=48000,volume=0.9,afade=t=out:st={fo:.2f}:d=3[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]".format(fo=max(0, duree - 3))
    lancer([FFMPEG, "-y", "-v", "error", "-i", corps, "-stream_loop", "-1", "-i", musique, "-filter_complex", fa,
            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{duree:.3f}", sortie], 3600)


def ecrire_srt(chemin, morceaux, segs, decalage_titre):
    out, n, pos = [], 1, decalage_titre
    for m in morceaux:
        for a, b, t in segs:
            if b > m["debut"] and a < m["fin"]:
                x, y = max(a, m["debut"]) - m["debut"] + pos, min(b, m["fin"]) - m["debut"] + pos
                if y - x > 0.3:
                    out.append(f"{n}\n{hms(x)} --> {hms(y)}\n{t}\n")
                    n += 1
        pos += m["fin"] - m["debut"]
    with open(chemin, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return n - 1


def ecrire_fcpxml(chemin, morceaux, sources, nom, musique, duree_totale):
    """Projet pour DaVinci Resolve (Fichier > Importer > Timeline) : chaque coupe a sa place, modifiable."""
    r = lambda s: f"{int(round(s * FPS))}/{FPS}s"
    def uri(p):
        return "file:///" + urllib.parse.quote(p.replace("\\", "/"), safe="/:")
    assets, vus = [], {}
    for s in sources:
        if s["fichier"] not in vus:
            k = f"r{len(vus) + 2}"
            vus[s["fichier"]] = k
            assets.append(f'<asset id="{k}" name="{html.escape(os.path.basename(s["fichier"]), quote=True)}" start="0s" duration="{r(s["duree"])}" hasVideo="1" hasAudio="{1 if s["pistes"] else 0}" format="r1">'
                          f'<media-rep kind="original-media" src="{uri(s["fichier"])}"/></asset>')
    if musique:
        assets.append(f'<asset id="rm" name="{html.escape(os.path.basename(musique), quote=True)}" start="0s" duration="{r(duree_totale)}" hasAudio="1"><media-rep kind="original-media" src="{uri(musique)}"/></asset>')
    clips, pos = [], 0.0
    for i, m in enumerate(morceaux):
        s, t0 = local(sources, m["debut"])
        d = m["fin"] - m["debut"]
        lien = f'<asset-clip ref="rm" lane="-1" offset="{r(t0)}" start="0s" duration="{r(duree_totale)}" audioRole="music"/>' if (musique and i == 0) else ""
        clips.append(f'<asset-clip ref="{vus[s["fichier"]]}" offset="{r(pos)}" start="{r(t0)}" duration="{r(d)}" name="{i + 1:02d} - {html.escape(m["pourquoi"][:40], quote=True)}">{lien}</asset-clip>')
        pos += d
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.10">
 <resources>
  <format id="r1" frameDuration="1/{FPS}s" width="{W}" height="{H}"/>
  {"".join(assets)}
 </resources>
 <library><event name="{html.escape(nom)}"><project name="{html.escape(nom)}"><sequence format="r1" duration="{r(pos)}" tcStart="0s" tcFormat="NDF">
  <spine>{"".join(clips)}</spine>
 </sequence></project></event></library>
</fcpxml>'''
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(xml)


# ---------- programme ----------
def monter(d):
    mode = d.get("mode", "event")
    if jeu_ouvert() and not d.get("forcer"):
        raise RuntimeError("jeu est ouvert : je ne monte pas pendant que tu joues (ça mangerait ta carte graphique).")
    fichiers = choisir_fichiers(d)
    if not fichiers:
        raise RuntimeError("aucune vidéo trouvée" + (f" pour le {d.get('date')}" if d.get("date") else " dans Vidéos\\À monter"))
    etat(en_cours=True, debut=datetime.now().isoformat(timespec="seconds"), mode=mode, etape="lecture des fichiers", stop_demande=False,
         erreur=None, resultat=None, marqueurs=None, pics=None,
         fichiers=[os.path.basename(f) for f in fichiers])
    sources, t = [], 0.0
    for f in fichiers:
        if f.lower().endswith(EXT_PHOTO):
            s = {"fichier": f, "duree": 4.0, "pistes": 0, "video": False, "chapitres": []}
        else:
            s = sonder(f)
        s["debut_global"] = t
        t += s["duree"]
        sources.append(s)
    total = t
    duree_cible = float(d.get("duree_min") or (10 if mode == "event" else 3)) * 60
    travail = os.path.join(BASE, "travail_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(travail, exist_ok=True)
    segs, marqueurs = [], []
    try:
        if mode == "event":
            marqueurs, score, segs, vues, touches, tirs_tous = analyser_event(sources, travail, d.get("yeux", True))
            candidats = fenetres(score, total)
            etat(etape="choix des temps forts", marqueurs=len(marqueurs), pics=len(candidats))
            morceaux = choisir_event(marqueurs, candidats, segs, duree_cible, total, vues, touches, tirs_tous,
                                     plages(d.get("garder")), plages(d.get("enlever")))
        else:
            morceaux = choisir_souvenirs(sources, duree_cible)
        if not morceaux:
            raise RuntimeError("je n'ai trouvé aucun moment exploitable")
        jour = date_du_nom(fichiers[0])
        date_txt = f"{jour.day} {MOIS[jour.month - 1]} {jour.year}".upper()
        nom = d.get("nom") or (f"Event {jour:%Y-%m-%d}" if mode == "event" else f"Souvenirs {jour:%Y-%m-%d}")
        nom_fichier = re.sub(r"[^\w\- ]+", "", nom).strip().replace(" ", "_")
        parts = []
        etat(etape="titre")
        titre = os.path.join(travail, "000_titre.mp4")
        if mode == "event":
            carton_titre(titre, d.get("titre") or "EVENT", date_txt, d.get("cache") or os.environ.get("ARCHI_MONTAGE_GROUPE") or None)
        else:
            carton_titre(titre, (d.get("titre") or "SOUVENIRS").upper(), date_txt, None)
        parts.append(titre)
        for i, m in enumerate(morceaux):
            etat(etape=f"rendu des moments ({i + 1}/{len(morceaux)})")
            p = os.path.join(travail, f"{i + 1:03d}.mp4")
            rendre_morceau(m, sources, p, mode, EFFETS[(i + random.randint(0, 3)) % 4] if mode == "event" and d.get("effets", True) else None)
            parts.append(p)
        if d.get("participants"):
            fin = os.path.join(travail, "999_fin.mp4")
            carton_fin(fin, d["participants"])
            parts.append(fin)
        etat(etape="assemblage")
        liste = os.path.join(travail, "liste.txt")
        with open(liste, "w", encoding="utf-8") as f:
            f.write("".join(f"file '{p.replace(os.sep, '/')}'\n" for p in parts))
        corps = os.path.join(travail, "corps.mp4")
        lancer([FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", liste, "-c", "copy", corps], 3600)
        duree_finale = float(json.loads(lancer([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "json", corps]))["format"]["duration"])
        sortie = os.path.join(MONTAGES, f"{nom_fichier}.mp4")
        k = 2
        while os.path.exists(sortie):
            sortie = os.path.join(MONTAGES, f"{nom_fichier}_v{k}.mp4")
            k += 1
        musique = choisir_musique(d.get("ambiance") or ("epique" if mode == "event" else "calme"))
        if musique:
            etat(etape="musique")
            mixer_musique(corps, musique, sortie, duree_finale, mode)
        else:
            shutil.move(corps, sortie)
        base = os.path.splitext(sortie)[0]
        n_srt = ecrire_srt(base + ".srt", morceaux, segs, 5.0) if (segs and d.get("sous_titres")) else 0
        ecrire_fcpxml(base + "_DaVinci.fcpxml", morceaux, sources, os.path.basename(base), musique, duree_finale)
        with open(base + "_moments.txt", "w", encoding="utf-8") as f:
            pos = 5.0
            for m in morceaux:
                s, t0 = local(sources, m["debut"])
                f.write(f"{court(pos)} dans le montage  <-  {os.path.basename(s['fichier'])} à {court(t0)} ({int(m['fin'] - m['debut'])} s) : {m['pourquoi']}\n")
                pos += m["fin"] - m["debut"]
        res = {"ok": True, "video": sortie, "duree": court(duree_finale), "moments": len(morceaux), "marqueurs": len(marqueurs),
               "musique": os.path.basename(musique) if musique else None, "sous_titres": n_srt, "source": court(total)}
        etat(en_cours=False, etape="terminé", resultat=res)
        lignes = [f"🎬 MONTAGE PRÊT : {os.path.basename(sortie)}",
                  f"Durée : {res['duree']} (tiré de {res['source']} de rushes), {res['moments']} moments"
                  + (f", dont {len(marqueurs)} marqués par toi" if mode == "event" else "") + ".",
                  f"Musique : {res['musique']}" if musique else "⚠️ Pas de musique : le dossier Vidéos\\Musique libre est vide.",
                  f"Dossier : Vidéos\\Montages (vidéo, projet DaVinci .fcpxml, liste des moments)."]
        renvoyer("\n".join(lignes), f"BOSS, ton montage est prêt : {res['duree']}, {res['moments']} moments. Il t'attend dans Vidéos, Montages.")
        return res
    finally:
        shutil.rmtree(travail, ignore_errors=True)


def lister():
    L = []
    for dos in (VIDEOS, A_MONTER):
        for f in sorted(glob.glob(os.path.join(dos, "*"))):
            if f.lower().endswith(EXT_VIDEO):
                L.append(f"{date_du_nom(f):%Y-%m-%d %H:%M}  {round(os.path.getsize(f) / 1e9, 1)} Go  {os.path.relpath(f, VIDEOS)}")
    return L


def main():
    a = sys.argv[1] if len(sys.argv) > 1 else ""
    if a == "--fichier":
        with open(sys.argv[2], encoding="utf-8") as f:
            d = json.load(f)
        try:
            os.remove(sys.argv[2])
        except Exception:
            pass
        try:
            print(json.dumps(monter(d), ensure_ascii=False))
        except InterruptedError:
            etat(en_cours=False, etape="arrêté par l'utilisateur")
            renvoyer("🎬 Montage arrêté.", "C'est arrêté BOSS, j'ai abandonné le montage.")
        except Exception as e:
            etat(en_cours=False, etape="échec", erreur=str(e)[:300])
            renvoyer(f"🎬 Montage impossible : {str(e)[:300]}", "Désolé BOSS, le montage a échoué : " + str(e)[:150])
    elif a == "etat":
        e = lire_etat()
        if e.get("en_cours"):
            ph = f"Je suis en plein montage BOSS : {e.get('etape')}."
        elif e.get("resultat"):
            ph = f"Dernier montage terminé : {os.path.basename(e['resultat'].get('video', ''))}, {e['resultat'].get('duree')}."
        else:
            ph = "Aucun montage en cours." + (f" Le dernier a échoué : {e.get('erreur')}" if e.get("erreur") else "")
        print(json.dumps({"ok": True, "etat": e, "phrase_pour_utilisateur": ph}, ensure_ascii=False))
    elif a == "stop":
        e = lire_etat()
        e["stop_demande"] = True
        with open(ETAT, "w", encoding="utf-8") as f:
            json.dump(e, f, ensure_ascii=False)
        print(json.dumps({"ok": True, "phrase_pour_utilisateur": "Je demande l'arrêt du montage, il s'arrête à la fin de l'étape en cours."}, ensure_ascii=False))
    elif a == "lister":
        print(json.dumps({"ok": True, "videos": lister()}, ensure_ascii=False))
    else:
        print(json.dumps({"ok": False, "erreur": "action inconnue"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
