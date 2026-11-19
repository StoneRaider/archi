# video.py - Archi regarde YouTube pour l'utilisateur : recherche, transcription, resume par le modele local.
#   python video.py chercher "sujet" ["question"]   -> 3 videos pertinentes, resumees
#   python video.py lien "https://youtu.be/..." ["question"]  -> une video precise, resumee
#   python video.py --fichier demande.json                   -> {"action":..., "cible":..., "question":...}
# Sous-titres d'abord (rapide, sans telecharger la video) ; sinon le son + Whisper local (videos <= 15 min).
# Repond une ligne JSON.

import glob
import json
import os
import re
import shutil
import subprocess
SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # pas de fenetre noire devant l utilisateur (13/11)
import sys
import tempfile
import urllib.request

PY = sys.executable
LM = os.environ.get("ARCHI_LM_URL", "http://127.0.0.1:1234/v1").rstrip("/") + "/chat/completions"
MODELE = os.environ.get("ARCHI_MODELE", "qwythos-9b-claude-mythos-5-1m")
FFMPEG_DIR = os.environ.get("ARCHI_WHISPER_DIR") or os.path.join(os.path.expanduser("~"), "whisper")   # dossier de ffmpeg + whisper.cpp (ARCHI_WHISPER_DIR)
WHISPER = os.environ.get("ARCHI_WHISPER") or os.path.join(FFMPEG_DIR, "whisper-bin-x64", "Release", "whisper-cli.exe")
WHISPER_MODELE = os.environ.get("ARCHI_WHISPER_MODELE") or os.path.join(FFMPEG_DIR, "ggml-medium-q5_0.bin")
MAX_TRANSCRIPTION = 14000      # caracteres envoyes au modele par video
DUREE_MAX = 40 * 60            # on ignore les videos de plus de 40 min dans une recherche
DUREE_MAX_WHISPER = 15 * 60    # au-dela, pas de transcription par le son (trop long)


def _qui():
    """« , Camille » : le prenom du profil (ARCHI_UTILISATEUR, regle a l'installation) ; rien s'il manque."""
    p = " ".join((os.environ.get("ARCHI_UTILISATEUR") or "").split())[:30]
    return (", " + p) if p else ""


def ytdlp(args, timeout=120):
    base = [PY, "-m", "yt_dlp", "--no-warnings", "--quiet", "--extractor-args", "youtube:lang=fr"]
    node = shutil.which("node") or ""
    for extra in (["--js-runtimes", "node:" + node], []):
        r = subprocess.run(base + extra + args, capture_output=True, text=True, encoding="utf-8",
                           errors="ignore", timeout=timeout, creationflags=SANS_FENETRE)
        if r.returncode == 0 or "js-runtimes" not in (r.stderr or ""):
            return r
    return r


def infos(url):
    r = ytdlp(["-J", "--skip-download", url], timeout=90)
    if r.returncode != 0:
        raise RuntimeError("vidéo inaccessible : " + (r.stderr or "")[-200:])
    d = json.loads(r.stdout)
    return {"titre": d.get("title", "?"), "chaine": d.get("channel") or d.get("uploader", "?"),
            "url": d.get("webpage_url", url), "duree": int(d.get("duration") or 0), "id": d.get("id")}


def chercher(sujet, n=3):
    r = ytdlp(["-J", "--flat-playlist", f"ytsearch8:{sujet}"], timeout=90)
    if r.returncode != 0:
        raise RuntimeError("recherche YouTube impossible : " + (r.stderr or "")[-200:])
    vids = []
    for e in json.loads(r.stdout).get("entries", []):
        d = int(e.get("duration") or 0)
        if 60 <= d <= DUREE_MAX:
            vids.append({"titre": e.get("title", "?"), "chaine": e.get("channel") or e.get("uploader", "?"),
                         "url": e.get("url") if str(e.get("url", "")).startswith("http")
                         else "https://www.youtube.com/watch?v=" + e["id"], "duree": d, "id": e["id"]})
        if len(vids) == n:
            break
    return vids


def _vtt_en_texte(chemin):
    lignes, derniere = [], ""
    for l in open(chemin, encoding="utf-8", errors="ignore"):
        l = l.strip()
        if not l or "-->" in l or l.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or l.isdigit():
            continue
        l = re.sub(r"<[^>]+>", "", l).strip()
        if l and l != derniere:
            lignes.append(l)
            derniere = l
    texte = " ".join(lignes)
    return re.sub(r"\s+", " ", texte).strip()


def sous_titres(v, dossier):
    """Choisit UNE seule piste (manuelle fr/en, sinon automatique d'origine) : demander les traductions
    automatiques fait bloquer YouTube (erreur 429)."""
    r = ytdlp(["-J", "--skip-download", v["url"]], timeout=90)
    if r.returncode != 0:
        return None, None
    d = json.loads(r.stdout)
    v["duree"] = int(d.get("duration") or v.get("duree") or 0)
    v["upload_date"] = d.get("upload_date") or ""
    manuels = d.get("subtitles") or {}
    autos = d.get("automatic_captions") or {}
    choix = None
    for cle in manuels:
        if cle.split("-")[0] in ("fr", "en") and cle != "live_chat":
            choix = (cle, "--write-subs")
            if cle.startswith("fr"):
                break
    if not choix:
        orig = [k for k in autos if k.endswith("-orig")]
        langue = (d.get("language") or "").split("-")[0]
        prefere = [f"{langue}-orig", "fr-orig", "en-orig"]
        orig.sort(key=lambda k: prefere.index(k) if k in prefere else 9)
        if orig:
            choix = (orig[0], "--write-auto-subs")
        elif langue and langue in autos:
            choix = (langue, "--write-auto-subs")
    if not choix:
        return None, None
    ytdlp(["--skip-download", choix[1], "--sub-format", "vtt", "--sub-langs", choix[0],
           "-o", os.path.join(dossier, "%(id)s.%(ext)s"), v["url"]], timeout=120)
    fichiers = glob.glob(os.path.join(dossier, v["id"] + "*.vtt"))
    if not fichiers:
        return None, None
    return _vtt_en_texte(fichiers[0]), choix[0]


def par_le_son(v, dossier):
    if v["duree"] > DUREE_MAX_WHISPER:
        return None
    ytdlp(["-f", "bestaudio", "-x", "--audio-format", "wav", "--ffmpeg-location", FFMPEG_DIR,
           "-o", os.path.join(dossier, "%(id)s.%(ext)s"), v["url"]], timeout=300)
    brut = os.path.join(dossier, v["id"] + ".wav")
    if not os.path.exists(brut):
        return None
    propre = os.path.join(dossier, v["id"] + "_16k.wav")
    subprocess.run([os.path.join(FFMPEG_DIR, "ffmpeg.exe"), "-y", "-i", brut, "-ar", "16000", "-ac", "1", propre],
                   capture_output=True, timeout=120, creationflags=SANS_FENETRE)
    r = subprocess.run([WHISPER, "-m", WHISPER_MODELE, "-l", "auto", "-f", propre, "-nt"],
                       capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=900, creationflags=SANS_FENETRE)
    return re.sub(r"\s+", " ", r.stdout or "").strip() or None


def resumer(v, texte, question):
    consigne = ("Tu résumes une vidéo YouTube pour " + os.environ.get("ARCHI_UTILISATEUR", "l'utilisateur") + ", en français, sans rien inventer. "
                + (f"Sa question : « {question} ». Concentre-toi sur ce qui y répond. " if question else "")
                + "Donne 5 à 8 points concrets et utiles (conseils, chiffres, étapes), puis une phrase : "
                  "« Verdict : » qui dit si la vidéo vaut le coup. Si la transcription ne parle pas du sujet, dis-le.")
    corps = {"model": MODELE, "temperature": 0.2, "max_tokens": 900,
             "messages": [{"role": "system", "content": consigne},
                          {"role": "user", "content": f"Titre : {v['titre']} (chaîne {v['chaine']})\n\n"
                                                      f"Transcription :\n{texte[:MAX_TRANSCRIPTION]}"}]}
    req = urllib.request.Request(LM, data=json.dumps(corps).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=240) as r:
        rep = json.loads(r.read().decode("utf-8"))
    txt = rep["choices"][0]["message"].get("content") or ""
    return re.sub(r"(?s)<think>.*?</think>", "", txt).strip()


def traiter(v, question, dossier):
    texte, source = sous_titres(v, dossier)
    if not texte:
        texte, source = par_le_son(v, dossier), "son (Whisper)"
    else:
        source = "sous-titres " + source
    duree = f"{v['duree'] // 60} min" if v["duree"] else "?"
    base = {"titre": v["titre"], "chaine": v["chaine"], "url": v["url"], "duree": duree}
    if not texte:
        return dict(base, source="aucune", resume="Pas de transcription possible (ni sous-titres, ni son exploitable).")
    return dict(base, source=source, resume=resumer(v, texte, question))


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--fichier":
        # demande ecrite par n8n dans un fichier : aucun texte libre ne passe par la ligne de commande
        with open(sys.argv[2], encoding="utf-8") as f:
            d = json.load(f)
        action, cible, question = d.get("action", ""), d.get("cible", ""), d.get("question", "")
    else:
        action = sys.argv[1] if len(sys.argv) > 1 else ""
        cible = sys.argv[2] if len(sys.argv) > 2 else ""
        question = sys.argv[3] if len(sys.argv) > 3 else ""
    if not cible:
        raise RuntimeError("rien à chercher")
    dossier = tempfile.mkdtemp(prefix="archi_video_")
    try:
        vids = [infos(cible)] if action == "lien" else chercher(cible)
        if not vids:
            print(json.dumps({"ok": True, "videos": [], "phrase_pour_utilisateur": "Je n'ai trouvé aucune vidéo exploitable sur ce sujet" + _qui() + "."}, ensure_ascii=False))
            return
        res = [traiter(v, question or (cible if action != "lien" else ""), dossier) for v in vids]
        print(json.dumps({"ok": True, "videos": res}, ensure_ascii=False))
    finally:
        shutil.rmtree(dossier, ignore_errors=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print(json.dumps({"ok": False, "erreur": str(err)[:300],
                          "phrase_pour_utilisateur": "Je n'ai pas réussi à lire YouTube" + _qui() + " : " + str(err)[:120]}, ensure_ascii=False))
