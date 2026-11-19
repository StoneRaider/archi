# vision_video.py - Archi REGARDE et ECOUTE une video en entier (05/11/2026).
#   python vision_video.py --fichier demande.json
#       {"action": "analyser", "source": "https://youtu.be/..." ou "C:\\...\\video.mp4",
#        "question": "...", "debut": "2:00", "fin": "12:30", "images_max": 60}
#       {"action": "etat"}                  -> ou en est l'analyse en cours / la derniere
#   python vision_video.py --travail <dossier>   (interne : le travail lance en arriere-plan)
#   python vision_video.py --sur-place --fichier demande.json   (tests : tout faire sans arriere-plan)
#
# Etapes (tout en LOCAL, rien ne part sur Internet pour l'analyse, seul le telechargement YouTube y va) :
#  1. recupere la video (yt-dlp, 720p max) ou prend le fichier local ;
#  2. le SON : sous-titres YouTube (avec les heures), sinon Whisper local sur la carte graphique ;
#  3. les IMAGES : changements de plan + une image toutes les X s + les moments ou la voix dit
#     « regarde / ici / comme ca / vous voyez » ; images presque identiques sautees ; 60 max ;
#  4. chaque image est decrite par Gemma 26B (LM Studio, local) avec ce qui est dit a ce moment ;
#  5. gpt-oss-20b croise images + paroles par horodatage -> fiche dans memoire\bibliotheque\
#     (montre, dit, etapes pas a pas, moments cles, 6 captures gardees a cote de la fiche) ;
#  6. la meilleure capture s'affiche dans le panneau Archi ; l'utilisateur est prevenu (Telegram).
# Video plus longue que 30 min : il faut un passage (debut/fin) de 30 min max.
# Repond UNE ligne JSON {"ok", "phrase_pour_utilisateur", ...}.

import base64
import io
import json
import os
import re
import shutil
import subprocess
SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # pas de fenetre noire devant l utilisateur (13/11)
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.request
from datetime import datetime

VENV_PY = os.environ.get("ARCHI_PY", "")
try:
    from PIL import Image
except ImportError:
    if os.path.exists(VENV_PY) and os.path.abspath(sys.executable).lower() != os.path.abspath(VENV_PY).lower():
        sys.exit(subprocess.call([VENV_PY] + sys.argv))   # sans option « sans fenetre » : ce relais ne capture pas la sortie, elle se perdrait
    Image = None

ICI = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
BIBLIO = os.environ.get("VISION_VIDEO_BIBLIO") or os.path.join(os.environ.get("ARCHI_BASE") or os.path.join(HOME, ".n8n-files"), "memoire", "bibliotheque")
AFFICHER = os.path.join(os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files"), "pc", "affichage", "afficher.py")
ETAT = os.environ.get("VISION_VIDEO_ETAT") or os.path.join(ICI, "etat.json")
JOURNAL = os.environ.get("VISION_VIDEO_JOURNAL") or os.path.join(ICI, "journal.txt")
LM = os.environ.get("VISION_VIDEO_LM") or os.environ.get("ARCHI_LM_URL", "http://127.0.0.1:1234/v1").rstrip("/") + "/chat/completions"
MODELE_VUE = os.environ.get("ARCHI_MODELE_VISION", "qwythos-9b-claude-mythos-5-1m")
MODELE_TEXTE = os.environ.get("ARCHI_MODELE", "qwythos-9b-claude-mythos-5-1m")
# webhook n8n LOCAL qui previent l'utilisateur (facultatif ; sans lui, rien n'est envoye)
RETOUR = os.environ.get("ARCHI_WEBHOOK_ALERTE", "")
_WH = os.environ.get("ARCHI_WHISPER_DIR") or os.path.join(os.path.expanduser("~"), "whisper")   # dossier de whisper.cpp (ARCHI_WHISPER_DIR)
FFMPEG = shutil.which("ffmpeg") or os.path.join(_WH, "ffmpeg.exe")
FFPROBE = shutil.which("ffprobe") or os.path.join(os.path.dirname(FFMPEG), "ffprobe.exe")
WHISPER = os.environ.get("ARCHI_WHISPER") or os.path.join(_WH, "vulkan", "whisper-cli.exe")
WHISPER_CPU = os.path.join(_WH, "whisper-bin-x64", "Release", "whisper-cli.exe")
WHISPER_MODELE = os.environ.get("ARCHI_WHISPER_MODELE") or os.path.join(_WH, "ggml-medium-q5_0.bin")

DUREE_MAX = 30 * 60
IMAGES_MAX = 60
CAPTURES_GARDEES = 6
PARALLELE = 3   # images decrites en meme temps par Gemma (LM Studio : 4 places)
MOTS_MONTRES = re.compile(
    r"\b(regarde[zr]?|vous voyez|tu vois|on voit|ici|comme (ça|ca|ceci)|voil[aà]|là|ce bouton|cette pi[eè]ce|"
    r"look|you can see|right here|over here|like this|this one)\b", re.I)
SANS_FENETRE = 0x08000000 if os.name == "nt" else 0


# ---------------------------------------------------------------- petits outils
def _qui():
    """« , Camille » : le prenom du profil (ARCHI_UTILISATEUR, regle a l'installation) ; rien s'il manque."""
    p = " ".join((os.environ.get("ARCHI_UTILISATEUR") or "").split())[:30]
    return (", " + p) if p else ""


def log(t):
    try:
        with open(JOURNAL, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {t}\n")
    except Exception:
        pass


def repondre(d):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(d, ensure_ascii=False))


def slug(t, n=40):
    t = unicodedata.normalize("NFD", str(t).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:n] or "video"


DECALAGE = 0.0   # debut du passage regarde : les heures affichees restent celles de la vraie video


def hms(t):
    return duree_txt(t + DECALAGE)


def duree_txt(s):
    s = int(max(0, s))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def en_secondes(v):
    """'2:30', '1:02:03', '90', '90s', '2 min', '2min30', 150 -> secondes ; None si vide/illisible."""
    if v is None or str(v).strip() == "":
        return None
    t = str(v).strip().lower()
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(min|mn|minutes?|m)", t)
    if m:
        return float(m.group(1).replace(",", ".")) * 60
    t = t.replace(",", ".").replace("h", ":").replace("min", ":").replace("m", ":")
    t = t.replace("sec", "").replace("s", "").replace(" ", "").rstrip(":")
    try:
        parts = [float(p or 0) for p in t.split(":")]
    except ValueError:
        return None
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total if total >= 0 else None


def lire_etat():
    try:
        return json.load(open(ETAT, encoding="utf-8"))
    except Exception:
        return {}


VERROU = threading.Lock()


def ecrire_etat(**kw):
    with VERROU:
        e = lire_etat()
        e.update(kw)
        e["maj"] = datetime.now().isoformat(timespec="seconds")
        tmp = ETAT + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(e, f, ensure_ascii=False, indent=1)
        os.replace(tmp, ETAT)


def pid_vivant(pid):
    if not pid:
        return False
    try:
        if os.name == "nt":
            r = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"], capture_output=True, text=True,
                               creationflags=SANS_FENETRE)
            return str(pid) in r.stdout
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def prevenir(texte, vocal):
    if os.environ.get("VISION_VIDEO_SANS_TELEGRAM"):
        log("TELEGRAM (simule) : " + texte.replace("\n", " | ")[:400])
        return
    if not RETOUR:
        log("pas de webhook ARCHI_WEBHOOK_ALERTE : " + texte.replace("\n", " | ")[:400])
        return
    try:
        corps = json.dumps({"type": "REPONSE", "canal": "recolte", "texte": texte, "vocal": vocal}).encode("utf-8")
        req = urllib.request.Request(RETOUR, data=corps, headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=60).read()
    except Exception as e:
        log(f"message Telegram impossible : {e}")


def lancer(cmd, timeout, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore",
                          timeout=timeout, creationflags=SANS_FENETRE, **kw)


# ---------------------------------------------------------------- la source
def est_url(s):
    return bool(re.match(r"^https?://", s, re.I))


def ytdlp(args, timeout=120):
    base = [VENV_PY if os.path.exists(VENV_PY) else sys.executable, "-m", "yt_dlp", "--no-warnings", "--quiet",
            "--extractor-args", "youtube:lang=fr"]
    node = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
    r = None
    for extra in (["--js-runtimes", "node:" + node], []):
        r = lancer(base + extra + args, timeout)
        if r.returncode == 0 or "js-runtimes" not in (r.stderr or ""):
            return r
    return r


def infos_url(url):
    r = ytdlp(["-J", "--skip-download", "--no-playlist", url], timeout=120)
    if r.returncode != 0:
        raise ErreurSimple("Je n'arrive pas à ouvrir cette vidéo (lien faux, vidéo privée ou YouTube qui bloque).",
                           (r.stderr or "")[-300:])
    d = json.loads(r.stdout)
    return {"titre": d.get("title") or "?", "chaine": d.get("channel") or d.get("uploader") or "?",
            "url": d.get("webpage_url") or url, "duree": float(d.get("duration") or 0), "id": d.get("id") or "video",
            "date": d.get("upload_date") or "", "brut": d}


def infos_fichier(chemin):
    r = lancer([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "json", chemin], 60)
    try:
        duree = float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        raise ErreurSimple("Ce fichier ne ressemble pas à une vidéo que je sais lire.", (r.stderr or "")[-300:])
    nom = os.path.splitext(os.path.basename(chemin))[0]
    return {"titre": nom, "chaine": "fichier local", "url": chemin, "duree": duree, "id": slug(nom, 30),
            "date": datetime.fromtimestamp(os.path.getmtime(chemin)).strftime("%Y%m%d"), "brut": {}}


class ErreurSimple(Exception):
    def __init__(self, phrase, detail=""):
        super().__init__(phrase)
        self.phrase, self.detail = phrase, detail


def telecharger(v, dossier, debut, fin):
    args = ["-f", "bv*[height<=720][ext=mp4]+ba[ext=m4a]/bv*[height<=720]+ba/b[height<=720]/b",
            "--merge-output-format", "mp4", "--ffmpeg-location", os.path.dirname(FFMPEG), "--no-playlist",
            "-o", os.path.join(dossier, "video.%(ext)s")]
    if debut is not None or fin is not None:
        args += ["--download-sections", f"*{debut or 0}-{fin if fin is not None else 'inf'}", "--force-keyframes-at-cuts"]
    r = ytdlp(args + [v["url"]], timeout=1800)
    fichiers = [f for f in os.listdir(dossier) if f.startswith("video.") and not f.endswith((".part", ".ytdl"))]
    if not fichiers:
        raise ErreurSimple("Le téléchargement de la vidéo a échoué.", (r.stderr or "")[-300:])
    return os.path.join(dossier, fichiers[0])


# ---------------------------------------------------------------- le son
def lire_vtt(chemin, decalage=0.0):
    """VTT/SRT -> [(debut_s, fin_s, texte)] sans les repetitions des sous-titres automatiques."""
    segs, derniere, t0, t1 = [], "", None, None
    for l in open(chemin, encoding="utf-8", errors="ignore"):
        l = l.strip()
        m = re.match(r"(\d+:)?(\d+):(\d+)[.,](\d+)\s*-->\s*(\d+:)?(\d+):(\d+)[.,](\d+)", l)
        if m:
            g = m.groups()
            t0 = int((g[0] or "0:")[:-1]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000
            t1 = int((g[4] or "0:")[:-1]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 1000
            continue
        if not l or l.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or l.isdigit() or t0 is None:
            continue
        l = re.sub(r"<[^>]+>", "", l).strip()
        if l and l != derniere and not (derniere and l in derniere):
            segs.append((t0 - decalage, t1 - decalage, l))
            derniere = l
    return [s for s in segs if s[1] > 0]


def sous_titres(v, dossier, debut):
    d = v["brut"]
    manuels, autos = d.get("subtitles") or {}, d.get("automatic_captions") or {}
    choix = None
    for cle in manuels:
        if cle.split("-")[0] in ("fr", "en") and cle != "live_chat":
            choix = (cle, "--write-subs")
            if cle.startswith("fr"):
                break
    if not choix:
        langue = (d.get("language") or "").split("-")[0]
        orig = sorted([k for k in autos if k.endswith("-orig")],
                      key=lambda k: [f"{langue}-orig", "fr-orig", "en-orig"].index(k)
                      if k in (f"{langue}-orig", "fr-orig", "en-orig") else 9)
        if orig:
            choix = (orig[0], "--write-auto-subs")
        elif langue and langue in autos:
            choix = (langue, "--write-auto-subs")
    if not choix:
        return None
    v["st_auto"] = choix[1] == "--write-auto-subs"   # sous-titres automatiques -> double ecoute avec Whisper (06/11)
    ytdlp(["--skip-download", choix[1], "--sub-format", "vtt", "--sub-langs", choix[0], "--no-playlist",
           "-o", os.path.join(dossier, "st.%(ext)s"), v["url"]], timeout=180)
    vtt = [f for f in os.listdir(dossier) if f.startswith("st.") and f.endswith(".vtt")]
    if not vtt:
        return None
    segs = lire_vtt(os.path.join(dossier, vtt[0]), decalage=debut or 0.0)
    return segs or None


def whisper(video, dossier):
    wav = os.path.join(dossier, "son16k.wav")
    lancer([FFMPEG, "-y", "-i", video, "-vn", "-ar", "16000", "-ac", "1", wav], 600)
    if not os.path.exists(wav) or os.path.getsize(wav) < 10000:
        return None   # pas de piste son
    sortie = os.path.join(dossier, "whisper")
    for exe in (WHISPER, WHISPER_CPU):
        if not os.path.exists(exe):
            continue
        lancer([exe, "-m", WHISPER_MODELE, "-l", "auto", "-f", wav, "-ovtt", "-of", sortie, "-np"], 3600,
               cwd=os.path.dirname(exe))
        if os.path.exists(sortie + ".vtt"):
            segs = lire_vtt(sortie + ".vtt")
            segs = [s for s in segs if not re.fullmatch(r"\W*(\[.*\]|\(.*\)|musique|music)?\W*", s[2], re.I)]
            return segs or None
    return None


# ---------------------------------------------------------------- les images
def changements_de_plan(video, duree):
    r = lancer([FFMPEG, "-hide_banner", "-i", video, "-an", "-vf", "scale=320:-2,select='gt(scene,0.30)',showinfo",
                "-f", "null", "-"], max(300, int(duree * 2)))
    return [float(m) for m in re.findall(r"pts_time:([\d.]+)", r.stderr or "")]


def choisir_moments(duree, plans, segs, images_max):
    """Moments a regarder : (temps, raison). Priorite : moments 'dits' > changements de plan > rythme regulier."""
    pas = max(10.0, duree / max(1, images_max * 0.6))
    ecart = max(3.0, duree / (images_max * 2.5))
    cands = []
    for s in segs or []:
        if MOTS_MONTRES.search(s[2]):
            cands.append((min(duree - 0.5, s[0] + 1.0), 0, "dit"))
    for t in plans:
        cands.append((min(duree - 0.5, t + 0.6), 1, "plan"))
    t = min(2.0, duree / 2)
    while t < duree - 0.5:
        cands.append((t, 2, "rythme"))
        t += pas
    garde = []
    for prio in (0, 2, 1):   # d'abord les moments 'dits', puis la trame reguliere (toute la video), puis les plans
        for c in sorted([c for c in cands if c[1] == prio], key=lambda c: c[0]):
            if all(abs(c[0] - g[0]) >= ecart for g in garde):
                garde.append(c)
    garde.sort(key=lambda c: c[0])
    if len(garde) > images_max:   # trop : on enleve d'abord les plans puis la trame, en gardant l'etalement
        for prio in (1, 2, 0):
            while len(garde) > images_max and any(g[1] == prio for g in garde):
                du_type = [i for i, g in enumerate(garde) if g[1] == prio]
                i = min(du_type, key=lambda i: (garde[i + 1][0] if i + 1 < len(garde) else duree)
                        - (garde[i - 1][0] if i > 0 else 0))
                garde.pop(i)
    return [(round(g[0], 2), g[2]) for g in garde]


def empreinte(chemin):
    im = Image.open(chemin).convert("L").resize((9, 8))
    p = list(im.tobytes())
    return [p[r * 9 + c] > p[r * 9 + c + 1] for r in range(8) for c in range(8)]


def extraire(video, moments, dossier):
    imgs, derniere = [], None
    for t, raison in moments:
        out = os.path.join(dossier, f"img_{int(t * 10):06d}.jpg")
        lancer([FFMPEG, "-y", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", "-vf", "scale='min(896,iw)':-2",
                "-q:v", "3", out], 120)
        if not os.path.exists(out):
            continue
        if Image is not None:
            try:
                e = empreinte(out)
                if derniere is not None and raison != "dit" and sum(a != b for a, b in zip(e, derniere)) <= 4:
                    os.remove(out)   # presque la meme image que la precedente : inutile de la faire decrire
                    continue
                derniere = e
            except Exception:
                pass
        imgs.append({"t": t, "raison": raison, "chemin": out})
    return imgs


def paroles_entre(segs, t0, t1):
    return " ".join(s[2] for s in segs or [] if s[1] > t0 and s[0] < t1).strip()


def appel_lm(corps, timeout, essais=4):
    """LM Studio n'a la place que pour UN gros modele : si Archi (gpt-oss) passe pendant l'analyse, LM Studio
    echange les modeles et coupe la demande en cours (erreur 500). On attend qu'il recharge et on relance."""
    for n in range(essais):
        try:
            return _appel_lm(corps, timeout)
        except Exception as e:
            if n == essais - 1 or "Connection refused" in str(e) or "10061" in str(e):
                raise
            log(f"LM Studio ({corps['model']}) : {str(e)[:80]} -> nouvel essai dans {20 * (n + 1)} s")
            time.sleep(20 * (n + 1))


def _appel_lm(corps, timeout):
    req = urllib.request.Request(LM, data=json.dumps(corps).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        rep = json.loads(r.read().decode("utf-8"))
    m = rep.get("choices", [{}])[0].get("message", {})
    txt = m.get("content") or ""
    return re.sub(r"(?s)<think>.*?</think>", "", txt).strip()


def decrire(img, titre, dit, question):
    with open(img["chemin"], "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    consigne = (f"Image tirée de la vidéo « {titre} », à {hms(img['t'])}. "
                + (f"Ce qui est dit à ce moment : « {dit[:600]} ». " if dit else "On n'entend rien de particulier à ce moment. ")
                + (f"J cherche surtout : « {question[:300]} ». " if question else "")
                + "Décris en français, en 2 à 4 phrases, ce qu'on VOIT : objets, outils, pièces, gestes, réglages, "
                  "texte ou chiffres lisibles à l'écran. N'invente rien, ne devine pas ce qui est hors de l'image. "
                  "Puis une dernière ligne exactement sous la forme « INTERET: n » avec n de 0 (image sans intérêt, "
                  "visage ou écran titre) à 3 (on voit clairement une étape, un réglage ou un résultat).")
    # reasoning_effort none : sinon Gemma 4 "reflechit" et sa reflexion mange tous les mots (reponse vide, 05/11)
    corps = {"model": MODELE_VUE, "temperature": 0.1, "max_tokens": 400, "reasoning_effort": "none", "messages": [{"role": "user", "content": [
        {"type": "text", "text": consigne},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}]}]}
    txt = appel_lm(corps, 300)
    if len(txt.strip()) < 15:
        raise RuntimeError("description vide")
    m = re.search(r"INT[EÉ]R[EÊ]T\W*:\W*([0-3])", txt, re.I)
    note = int(m.group(1)) if m else 1
    txt = re.sub(r"[\s*_#-]*INT[EÉ]R[EÊ]T\W*:.*$", "", txt, flags=re.I | re.S).strip()   # garde la description
    return re.sub(r"\s+", " ", txt), note


# ---------------------------------------------------------------- la synthese
SECTIONS = ("THEME", "RESUME", "MONTRE", "DIT", "ETAPES", "MOMENTS", "A_VERIFIER", "UTILE_POUR_J")


def synthese(v, imgs, segs, question, source_son, segs_st=None):
    lignes = []
    bornes = [i["t"] for i in imgs] + [v["duree"]]
    if segs and imgs and imgs[0]["t"] > 0:
        avant = paroles_entre(segs, -1, imgs[0]["t"])
        if avant:
            lignes.append(f"[{hms(0)}] DIT : {avant}")
        st = paroles_entre(segs_st, -1, imgs[0]["t"])
        if st:
            lignes.append(f"[{hms(0)}] ST : {st}")
    for k, i in enumerate(imgs):
        lignes.append(f"[{hms(i['t'])}] VU : {i['vu']}")
        dit = paroles_entre(segs, i["t"], bornes[k + 1])
        if dit:
            lignes.append(f"[{hms(i['t'])}] DIT : {dit}")
        st = paroles_entre(segs_st, i["t"], bornes[k + 1])
        if st:
            lignes.append(f"[{hms(i['t'])}] ST : {st}")
    if not imgs and segs:
        lignes += [f"[{hms(s[0])}] DIT : {s[2]}" for s in segs]
    trame = "\n".join(lignes)
    if len(trame) > 45000:   # on garde tout le VU, on raccourcit chaque DIT
        trame = "\n".join(l if " VU : " in l else l[:700] for l in lignes)[:45000]
    double = ("Les paroles ont été écoutées DEUX fois : DIT = Whisper (transcription locale), ST = sous-titres "
              "automatiques de YouTube. Compare-les : garde la version la plus cohérente avec les images, et mets dans "
              "A_VERIFIER chaque passage important où elles ne disent pas la même chose. ") if segs_st else ""
    consigne = (
        "Tu fais la fiche d'une vidéo pour J, en français simple, SANS RIEN INVENTER : uniquement ce qui est "
        "dans la trame (VU = décrit par un modèle qui regarde les images, DIT = paroles). Croise les deux par les heures. "
        + double
        + (f"Sa question : « {question} » : réponds-y en priorité. " if question else "")
        + "Réponds avec exactement ces rubriques, chacune sur sa ligne en MAJUSCULES suivie de deux-points :\n"
          "THEME: un thème court (ex. Impression 3D, Montage vidéo, Bricolage)\n"
          "RESUME: 2 à 4 phrases\n"
          "MONTRE: 4 à 8 tirets, ce qu'on voit à l'écran (objets, gestes, réglages), avec [m:ss]\n"
          "DIT: 4 à 8 tirets, les idées et chiffres importants dits, avec [m:ss]\n"
          "ETAPES: si c'est un tuto, étapes numérotées « 1. [m:ss] action — outil/réglage — ce qu'on voit », sinon « Pas un tuto. »\n"
          "MOMENTS: 5 à 8 tirets « [m:ss] — ce qui se passe » (les moments à revoir)\n"
          "A_VERIFIER: tirets, ce qui est douteux ou où image et paroles se contredisent, sinon « Aucune »\n"
          "UTILE_POUR_J: 1 à 2 phrases")
    corps = {"model": MODELE_TEXTE, "temperature": 0.2, "max_tokens": 3500,
             "messages": [{"role": "system", "content": consigne},
                          {"role": "user", "content": f"Titre : {v['titre']} (chaîne {v['chaine']}), durée {duree_txt(v['duree'])}, "
                                                      f"paroles : {source_son}.\n\nTRAME :\n{trame}"}]}
    txt = ""
    for _ in range(3):   # gpt-oss rend parfois une reponse vide : on relance
        txt = appel_lm(corps, 600)
        if len(txt) > 200:
            break
    return decouper(txt)


def decouper(txt):
    d, cle = {}, None
    for l in txt.splitlines():
        m = re.match(r"^\W*(" + "|".join(SECTIONS) + r")\W*\s*:\s*(.*)$", l.strip(), re.I)
        if m:
            cle = m.group(1).upper()
            d[cle] = m.group(2).strip(" *")
        elif cle:
            d[cle] = (d[cle] + "\n" + l.rstrip()).strip()
    return d


def temps_cites(texte):
    out = []
    for m in re.finditer(r"\[(\d+(?::\d{2}){1,2})\]", texte or ""):
        out.append(en_secondes(m.group(1)))
    return [t - DECALAGE for t in out if t is not None]


def choisir_captures(imgs, d):
    """6 captures : les images les plus proches des moments cles cites, puis les plus interessantes, bien etalees."""
    choisies = []
    for t in temps_cites(d.get("MOMENTS", "")) + temps_cites(d.get("ETAPES", "")):
        if not imgs:
            break
        i = min(imgs, key=lambda i: abs(i["t"] - t))
        if abs(i["t"] - t) <= 20 and i not in choisies and i.get("note", 1) >= 1:
            choisies.append(i)
        if len(choisies) >= CAPTURES_GARDEES:
            break
    for i in sorted(imgs, key=lambda i: -i.get("note", 1)):
        if len(choisies) >= CAPTURES_GARDEES:
            break
        if i not in choisies and all(abs(i["t"] - c["t"]) > 15 for c in choisies):
            choisies.append(i)
    return sorted(choisies, key=lambda i: i["t"])


def ecrire_fiche(v, d, captures, source_son, nb_images, debut, fin, question):
    os.makedirs(BIBLIO, exist_ok=True)
    date = v["date"]
    date = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) == 8 else datetime.now().strftime("%Y-%m-%d")
    nom = f"video_{datetime.now():%Y-%m-%d}_{slug(v['titre'])}"
    dossier_cap = os.path.join(BIBLIO, "captures", nom)
    os.makedirs(dossier_cap, exist_ok=True)
    lignes_cap = []
    for c in captures:
        ta = int(c["t"] + DECALAGE)
        f = f"{ta // 60:02d}m{ta % 60:02d}s.jpg"
        shutil.copy2(c["chemin"], os.path.join(dossier_cap, f))
        c["garde"] = os.path.join(dossier_cap, f)
        lignes_cap.append(f"- **[{hms(c['t'])}]** {c['vu'][:220]}\n  ![{hms(c['t'])}](captures/{nom}/{f})")
    passage = ""
    if debut is not None or fin is not None:
        passage = f" — passage {duree_txt(debut or 0)} à {duree_txt(fin) if fin is not None else 'la fin'}"
    lien = v["url"] if est_url(v["url"]) else f"fichier : {v['url']}"
    if est_url(v["url"]) and debut:
        lien += ("&" if "?" in lien else "?") + f"t={int(debut)}"
    def bloc(k, defaut):
        return (d.get(k) or defaut).strip()
    contenu = (
        f"## Analyse vidéo du {datetime.now():%d/%m/%Y} (images + son)\n"
        f"**Titre :** {v['titre']} — {v['chaine']}, {date}{passage}\n"
        f"**Durée analysée :** {duree_txt(v['duree'])} · {nb_images} images regardées · paroles : {source_son}\n"
        + (f"**Question de J :** {question}\n" if question else "")
        + f"**Thème :** {bloc('THEME', 'divers').splitlines()[0]}\n"
        f"**Résumé :** {re.sub(r'\s+', ' ', bloc('RESUME', '(non fourni)'))}\n"
        f"**Ce qui est MONTRÉ :**\n{bloc('MONTRE', '- (rien de notable)')}\n"
        f"**Ce qui est DIT :**\n{bloc('DIT', '- (pas de paroles)')}\n"
        f"**Étapes pas à pas :**\n{bloc('ETAPES', 'Pas un tuto.')}\n"
        f"**Moments clés :**\n{bloc('MOMENTS', '- (aucun)')}\n"
        f"**Captures :**\n" + ("\n".join(lignes_cap) or "- (aucune)") + "\n"
        f"**À vérifier :**\n{bloc('A_VERIFIER', '- Aucune')}\n"
        f"**Utile pour J :** {bloc('UTILE_POUR_J', 'Rien de particulier')}\n"
        f"**Sources :**\n- {lien} (images décrites par le modèle local, paroles : {source_son})\n"
        f"**Liens :**\n- [[videos_analysees]] · [[Bibliothèque]]\n")
    chemin = os.path.join(BIBLIO, nom + ".md")
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(contenu)
    index = os.path.join(BIBLIO, "videos_analysees.md")
    if not os.path.exists(index):
        with open(index, "w", encoding="utf-8") as f:
            f.write("# 🎬 Vidéos analysées (images + son)\n\nPièce : [[Bibliothèque]]. Fiches faites par l'outil "
                    "vision_video : ce qui est montré, ce qui est dit, les étapes et les captures.\n\n")
    if f"[[{nom}]]" in open(index, encoding="utf-8").read():
        return nom, chemin   # meme video refaite le meme jour : la fiche est remplacee, l'index ne bouge pas
    with open(index, "a", encoding="utf-8") as f:
        f.write(f"- {datetime.now():%d/%m/%Y} · [[{nom}]] — {v['titre']} ({bloc('THEME', 'divers').splitlines()[0]})\n")
    return nom, chemin


def afficher(capture, titre):
    if not capture or not os.path.exists(AFFICHER) or os.environ.get("VISION_VIDEO_SANS_PANNEAU"):
        return False
    py = VENV_PY if os.path.exists(VENV_PY) else sys.executable
    r = lancer([py, AFFICHER, "image", capture["garde"], "--titre", titre[:80],
                "--legende", f"[{hms(capture['t'])}] {capture['vu'][:160]}"], 60)
    return r.returncode == 0


# ---------------------------------------------------------------- le travail complet
def travailler(dossier):
    dem = json.load(open(os.path.join(dossier, "demande.json"), encoding="utf-8"))
    source, question = dem["source"], dem.get("question") or ""
    debut, fin, images_max = dem.get("debut"), dem.get("fin"), dem["images_max"]
    v = dem["infos"]
    global DECALAGE
    DECALAGE = float(debut or 0)
    debut_tout = time.time()
    ecrire_etat(en_cours=True, pid=os.getpid(), titre=v["titre"], etape="récupération de la vidéo",
                debut=datetime.now().isoformat(timespec="seconds"), fiche=None, erreur=None, detail=None)
    log(f"DEBUT {v['titre']} ({duree_txt(v['duree'])}) {source}")
    if est_url(source):
        video = telecharger(v, dossier, debut, fin)
    else:
        video = source
        if debut is not None or fin is not None:   # on decoupe le passage du fichier local
            video = os.path.join(dossier, "passage.mp4")
            cmd = [FFMPEG, "-y", "-ss", str(debut or 0), "-i", source]
            if fin is not None:
                cmd += ["-t", str(fin - (debut or 0))]
            lancer(cmd + ["-c", "copy", video], 600)
    duree = float(json.loads(lancer([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "json", video],
                                    60).stdout or "{}").get("format", {}).get("duration") or v["duree"])
    v["duree"] = duree

    ecrire_etat(etape="écoute du son")
    segs, source_son = None, "aucune"
    if est_url(source) and v.get("brut"):
        try:
            segs = sous_titres(v, dossier, debut)
            source_son = "sous-titres YouTube" if segs else source_son
        except Exception as e:
            log(f"sous-titres : {e}")
    segs_st = None   # DOUBLE ECOUTE (06/11) : sous-titres AUTOMATIQUES + Whisper, croises dans la fiche
    if segs and v.get("st_auto"):
        ecrire_etat(etape="double écoute (Whisper en plus des sous-titres)")
        try:
            wh = whisper(video, dossier)
        except Exception as e:
            wh = None
            log(f"whisper (double ecoute) : {e}")
        if wh:
            segs, segs_st = wh, segs
            source_son = "double écoute : Whisper local + sous-titres YouTube automatiques"
    if not segs:
        segs = whisper(video, dossier)
        source_son = "Whisper local" if segs else "aucune parole trouvée"
    log(f"son : {source_son}, {len(segs or [])} morceaux" + (f" + {len(segs_st)} sous-titres" if segs_st else ""))

    ecrire_etat(etape="choix des images")
    plans = changements_de_plan(video, duree)
    moments = choisir_moments(duree, plans, segs, images_max)
    imgs = extraire(video, moments, dossier)
    log(f"images : {len(plans)} changements de plan, {len(moments)} moments, {len(imgs)} images gardees")
    if not imgs:
        raise ErreurSimple("Je n'ai pas réussi à sortir d'images de cette vidéo.")

    bornes = [i["t"] for i in imgs] + [duree]
    try:   # la premiere seule : verifie que Gemma repond (et le charge) avant de lancer les autres
        imgs[0]["vu"], imgs[0]["note"] = decrire(imgs[0], v["titre"], paroles_entre(segs, imgs[0]["t"] - 4,
                                                 min(bornes[1], imgs[0]["t"] + 8)), question)
    except Exception as e:
        raise ErreurSimple("Le modèle qui voit (dans LM Studio) ne répond pas.", str(e)[:300])
    faites = [1]

    def une(k):
        i = imgs[k]
        dit = paroles_entre(segs, i["t"] - 4, min(bornes[k + 1], i["t"] + 8))
        try:
            i["vu"], i["note"] = decrire(i, v["titre"], dit, question)
        except Exception as e:
            i["vu"], i["note"] = "(image non décrite)", 0
            log(f"image {hms(i['t'])} : {e}")
        faites[0] += 1
        ecrire_etat(etape=f"je regarde les images ({faites[0]}/{len(imgs)})")

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=PARALLELE) as pool:
        list(pool.map(une, range(1, len(imgs))))
    ratees = sum(1 for i in imgs if i["vu"] == "(image non décrite)")
    if ratees > len(imgs) / 2:
        raise ErreurSimple(f"Le modèle qui voit a lâché en route ({ratees} images sur {len(imgs)} non décrites). "
                           "LM Studio a peut-être été occupé par autre chose : relance-moi dans un moment.")
    imgs = [i for i in imgs if i["vu"] != "(image non décrite)"]

    ecrire_etat(etape="j'écris la fiche (images et paroles croisées)")
    d = synthese(v, imgs, segs, question, source_son, segs_st)
    if not d.get("RESUME"):
        raise ErreurSimple("Le cerveau d'Archi n'a pas réussi à écrire la fiche.")
    captures = choisir_captures(imgs, d)
    nom, chemin = ecrire_fiche(v, d, captures, source_son, len(imgs), debut, fin, question)
    meilleure = max(captures, key=lambda c: c.get("note", 1)) if captures else None
    montre = afficher(meilleure, v["titre"])
    minutes = round((time.time() - debut_tout) / 60, 1)
    resume = re.sub(r"\s+", " ", d.get("RESUME", "")).strip()
    ecrire_etat(en_cours=False, etape="fini", fiche=chemin, fin=datetime.now().isoformat(timespec="seconds"),
                minutes=minutes, images=len(imgs), son=source_son, resume=resume[:400])
    log(f"FIN {nom} en {minutes} min")
    texte = (f"🎬 VIDÉO ANALYSÉE (images + son) : {v['titre']}\n\n{resume}\n\n"
             f"{len(imgs)} images regardées, paroles : {source_son}, {len(captures)} captures gardées.\n"
             f"Fiche rangée dans la Bibliothèque du château : {nom}")
    prevenir(texte, f"J'ai fini de regarder la vidéo{_qui()}, la fiche est dans ta bibliothèque.")
    return {"ok": True, "fiche": chemin, "nom_fiche": nom, "images": len(imgs), "son": source_son,
            "captures": [c["garde"] for c in captures], "affiche_dans_panneau": montre, "minutes": minutes,
            "resume": resume,
            "phrase_pour_utilisateur": f"C'est fait : j'ai regardé et écouté « {v['titre']} ». {resume} "
                                  f"La fiche est dans ta Bibliothèque ({len(captures)} captures)."}


def travail_en_fond(dossier):
    try:
        res = travailler(dossier)
        json.dump(res, open(os.path.join(dossier, "resultat.json"), "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        phrase = e.phrase if isinstance(e, ErreurSimple) else "L'analyse de la vidéo a planté."
        detail = getattr(e, "detail", "") or str(e)
        log(f"ERREUR {phrase} {detail[:300]}")
        ecrire_etat(en_cours=False, etape="erreur", erreur=phrase, detail=detail[:300])
        prevenir(f"🎬 Analyse vidéo ratée : {phrase}", f"L'analyse de la vidéo a raté{_qui()} : {phrase}")
        return {"ok": False, "phrase_pour_utilisateur": phrase, "detail": detail[:300]}
    finally:
        if not os.environ.get("VISION_VIDEO_GARDER_TEMP"):
            shutil.rmtree(dossier, ignore_errors=True)
    return res


# ---------------------------------------------------------------- la demande d'Archi
def normaliser(p):
    p = {str(k).lower().strip(): v for k, v in (p or {}).items()}
    if isinstance(p.get("parametres"), dict):
        p.update({str(k).lower(): v for k, v in p["parametres"].items()})
    source = ""
    for k in ("source", "lien", "url", "video", "vidéo", "chemin", "fichier_video", "cible"):
        if str(p.get(k) or "").strip():
            source = str(p[k]).strip().strip('"')
            break
    action = unicodedata.normalize("NFD", str(p.get("action") or "").lower().strip())
    action = "".join(c for c in action if unicodedata.category(c) != "Mn")
    if re.search(r"etat|ou en|avance|statut|suivi|fini", action):
        action = "etat"
    if action in ("", "regarder", "analyse", "analyser", "voir", "lancer", "etudier", "étudier"):
        action = "analyser" if source else ("etat" if not action else "analyser")
    if action in ("état", "statut", "ou_en_es_tu", "avancement", "suivi"):
        action = "etat"
    try:
        n = int(float(str(p.get("images_max") or IMAGES_MAX).replace(",", ".")))
    except ValueError:
        n = IMAGES_MAX
    return {"action": action, "source": source, "question": str(p.get("question") or p.get("consigne") or "").strip(),
            "debut": en_secondes(p.get("debut") or p.get("début")), "fin": en_secondes(p.get("fin")),
            "images_max": max(5, min(IMAGES_MAX, n))}


def etat():
    e = lire_etat()
    if not e:
        return {"ok": True, "phrase_pour_utilisateur": "Je n'ai encore analysé aucune vidéo."}
    if e.get("en_cours") and pid_vivant(e.get("pid")):
        return {"ok": True, "en_cours": True, "etape": e.get("etape"),
                "phrase_pour_utilisateur": f"Je suis encore sur « {e.get('titre')} » : {e.get('etape')}."}
    if e.get("etape") == "erreur" or e.get("en_cours"):
        return {"ok": True, "en_cours": False,
                "phrase_pour_utilisateur": f"La dernière analyse (« {e.get('titre')} ») a raté : {e.get('erreur') or 'arrêtée en cours de route'}."}
    return {"ok": True, "en_cours": False, "fiche": e.get("fiche"),
            "phrase_pour_utilisateur": f"La dernière vidéo analysée est « {e.get('titre')} » ({e.get('images')} images, "
                                  f"{e.get('minutes')} min de travail). {e.get('resume', '')} La fiche est dans ta Bibliothèque."}


def analyser(p, sur_place=False):
    source = p["source"]
    if not source:
        return {"ok": False, "phrase_pour_utilisateur": "Donne-moi le lien de la vidéo (YouTube) ou le chemin du fichier."}
    e = lire_etat()
    if e.get("en_cours") and pid_vivant(e.get("pid")):
        return {"ok": False, "phrase_pour_utilisateur": f"Je suis déjà en train de regarder « {e.get('titre')} » "
                                                   f"({e.get('etape')}). Une vidéo à la fois : redemande-moi après."}
    if not est_url(source):
        source = os.path.expandvars(os.path.expanduser(source))
        if not os.path.isfile(source):
            return {"ok": False, "phrase_pour_utilisateur": "Je ne trouve pas ce fichier vidéo sur le PC. Vérifie le chemin."}
    try:
        v = infos_url(source) if est_url(source) else infos_fichier(source)
    except ErreurSimple as err:
        return {"ok": False, "phrase_pour_utilisateur": err.phrase, "detail": err.detail}
    debut, fin = p["debut"], p["fin"]
    if v["duree"] and fin is not None and fin > v["duree"]:
        fin = None
    if debut is not None and v["duree"] and debut >= v["duree"]:
        return {"ok": False, "phrase_pour_utilisateur": f"La vidéo ne dure que {duree_txt(v['duree'])} : le début demandé est après la fin."}
    if fin is not None and debut is not None and fin <= debut:
        return {"ok": False, "phrase_pour_utilisateur": "La fin du passage est avant son début."}
    longueur = (fin if fin is not None else v["duree"]) - (debut or 0)
    if v["duree"] and longueur > DUREE_MAX + 30:
        return {"ok": False, "duree": duree_txt(v["duree"]),
                "phrase_pour_utilisateur": f"« {v['titre']} » dure {duree_txt(v['duree'])} : c'est trop long pour la regarder en "
                                      f"entier (30 min max). Dis-moi quel passage de 30 min regarder, par exemple de "
                                      f"0:00 à 30:00, ou je peux seulement la résumer par ses paroles (outil video)."}
    p = dict(p, debut=debut, fin=fin)
    b = v.get("brut") or {}
    v["brut"] = {k: b.get(k) for k in ("subtitles", "automatic_captions", "language") if b.get(k)}
    v["duree"] = longueur or v["duree"]
    dossier = tempfile.mkdtemp(prefix="vision_video_")
    json.dump(dict(p, source=source, infos=v), open(os.path.join(dossier, "demande.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    nb = min(p["images_max"], max(5, int(longueur / 6)))
    minutes = max(2, round((nb * 3 + 90 + longueur * 0.1) / 60))
    if sur_place:
        return travail_en_fond(dossier)
    ecrire_etat(en_cours=True, pid=None, titre=v["titre"], etape="démarrage", fiche=None, erreur=None)
    py = sys.executable
    pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
    drapeaux = (0x00000008 | 0x00000200 | SANS_FENETRE) if os.name == "nt" else 0   # DETACHED | NEW_GROUP
    proc = subprocess.Popen([pyw if os.path.exists(pyw) else py, os.path.abspath(__file__), "--travail", dossier],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=drapeaux, close_fds=True)
    ecrire_etat(pid=proc.pid)
    return {"ok": True, "en_cours": True, "titre": v["titre"], "duree": duree_txt(longueur),
            "phrase_pour_utilisateur": f"PAS ENCORE FINI : je commence à regarder et écouter « {v['titre']} » "
                                  f"({duree_txt(longueur)}). Ça me prend environ {minutes} minutes ; je te préviens "
                                  f"quand la fiche est rangée dans ta Bibliothèque."}


def main():
    a = sys.argv[1:]
    if "--travail" in a:
        travail_en_fond(a[a.index("--travail") + 1])
        return
    sur_place = "--sur-place" in a
    p = {}
    if "--fichier" in a:
        try:
            with open(a[a.index("--fichier") + 1], encoding="utf-8-sig") as f:
                p = json.load(f)
        except Exception:
            repondre({"ok": False, "phrase_pour_utilisateur": "Je n'ai pas pu lire la demande (fichier JSON illisible)."})
            return
    elif a and not a[0].startswith("--"):
        p = {"action": a[0], "source": a[1] if len(a) > 1 else ""}
    p = normaliser(p)
    if p["action"] == "etat":
        repondre(etat())
    elif p["action"] == "analyser":
        repondre(analyser(p, sur_place))
    else:
        repondre({"ok": False, "phrase_pour_utilisateur": "Je sais seulement : analyser (une vidéo) ou etat (où j'en suis)."})


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        log(f"PLANTAGE {err}")
        repondre({"ok": False, "phrase_pour_utilisateur": "L'outil vision_video a planté.", "detail": str(err)[:300]})
