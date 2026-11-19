# tester_vision_video.py - tests SANS Internet ni vrai LM Studio : fausse video (ffmpeg), faux LM Studio,
# fausse Bibliotheque et faux etat dans un dossier temporaire. Ecrit tests.json si tout passe.
#   python tester_vision_video.py
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

ICI = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(os.path.expanduser("~"), ".n8n", "assistant", "assistant-main", "venv", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = sys.executable
FFMPEG = shutil.which("ffmpeg") or os.path.join(os.environ.get("ARCHI_WHISPER_DIR") or os.path.join(os.path.expanduser("~"), "whisper"), "ffmpeg.exe")
APPELS = {"vue": 0, "texte": 0}


class FauxLM(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        # une demande « vue » porte une image ; le nom du modele ne dit plus rien (un seul modele voit et ecrit, 19/11)
        vue = any(isinstance(m.get("content"), list) for m in corps.get("messages") or [])
        if vue and corps.get("reasoning_effort") != "none":
            APPELS["vue"] += 1
            rep = ""   # comme un modele qui reflechit sans budget : reponse vide
        elif vue:
            APPELS["vue"] += 1
            rep = "On voit une mire de couleurs et un compteur. **INTERET: 2**"   # tout sur une ligne
        else:
            APPELS["texte"] += 1
            rep = ("THEME: Essai\nRESUME: Une mire de test sans paroles.\nMONTRE:\n- [0:05] une mire\n"
                   "DIT:\n- (rien)\nETAPES: Pas un tuto.\nMOMENTS:\n- [0:05] — la mire\n- [0:40] — la fin\n"
                   "A_VERIFIER: Aucune\nUTILE_POUR_J: Rien.")
        out = json.dumps({"choices": [{"message": {"content": rep}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def main():
    tmp = tempfile.mkdtemp(prefix="test_vv_")
    srv = HTTPServer(("127.0.0.1", 0), FauxLM)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = dict(os.environ, VISION_VIDEO_SANS_TELEGRAM="1", VISION_VIDEO_SANS_PANNEAU="1",
               VISION_VIDEO_BIBLIO=os.path.join(tmp, "biblio"), VISION_VIDEO_ETAT=os.path.join(tmp, "etat.json"),
               VISION_VIDEO_JOURNAL=os.path.join(tmp, "journal.txt"),
               VISION_VIDEO_LM=f"http://127.0.0.1:{srv.server_port}/v1/chat/completions")
    courte = os.path.join(tmp, "essai.mp4")
    longue = os.path.join(tmp, "longue.mp4")
    subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10", "-t", "45", courte],
                   capture_output=True)
    subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i", "color=c=blue:size=64x48:rate=1", "-t", "1900", longue],
                   capture_output=True)
    pas_video = os.path.join(tmp, "note.txt")
    open(pas_video, "w").write("bonjour")

    def outil(demande, *extra, env2=None):
        f = os.path.join(tmp, "demande.json")
        json.dump(demande, open(f, "w", encoding="utf-8"))
        r = subprocess.run([PY, os.path.join(ICI, "vision_video.py"), *extra, "--fichier", f], capture_output=True,
                           text=True, encoding="utf-8", env=env2 or env, timeout=900)
        try:
            return json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            return {"ok": None, "brut": (r.stdout + r.stderr)[-400:]}

    cas = []

    def verif(nom, cond, rep):
        cas.append((nom, bool(cond)))
        print(("OK   " if cond else "RATE ") + nom + ("" if cond else f"  -> {rep}"))

    r = outil({"action": "analyser"})
    verif("sans source : demande le lien", r["ok"] is False and "lien" in r["phrase_pour_utilisateur"], r)
    r = outil({"source": os.path.join(tmp, "absent.mp4")})
    verif("fichier absent : refus clair", r["ok"] is False and "trouve pas" in r["phrase_pour_utilisateur"], r)
    r = outil({"source": pas_video})
    verif("fichier qui n'est pas une video", r["ok"] is False and "vidéo" in r["phrase_pour_utilisateur"], r)
    r = outil({"source": longue})
    verif("video de 31 min : refus + propose un passage", r["ok"] is False and "30 min" in r["phrase_pour_utilisateur"], r)
    r = outil({"source": courte, "debut": "1:00"})
    verif("debut apres la fin : refus", r["ok"] is False and "après la fin" in r["phrase_pour_utilisateur"], r)
    r = outil({"source": courte, "debut": "0:30", "fin": "0:10"})
    verif("fin avant debut : refus", r["ok"] is False and "avant" in r["phrase_pour_utilisateur"], r)
    r = outil({"action": "danser", "source": courte})
    verif("action inconnue : explique", r["ok"] is False and "analyser" in r["phrase_pour_utilisateur"], r)
    r = outil({"action": "etat"})
    verif("etat sans historique", r["ok"] and "aucune" in r["phrase_pour_utilisateur"], r)

    # une analyse est deja en cours (pid vivant = ce test)
    json.dump({"en_cours": True, "pid": os.getpid(), "titre": "autre", "etape": "images"},
              open(env["VISION_VIDEO_ETAT"], "w", encoding="utf-8"))
    r = outil({"source": courte})
    verif("une video a la fois", r["ok"] is False and "déjà" in r["phrase_pour_utilisateur"], r)
    os.remove(env["VISION_VIDEO_ETAT"])

    # LM Studio injoignable
    env_mort = dict(env, VISION_VIDEO_LM="http://127.0.0.1:9/v1/chat/completions")
    r = outil({"source": courte}, "--sur-place", env2=env_mort)
    verif("LM Studio eteint : erreur expliquee", r["ok"] is False and "LM Studio" in r["phrase_pour_utilisateur"], r)

    # analyse complete (passage 0:05 -> 0:45 d'un fichier local, sans paroles)
    r = outil({"parametres": {"lien": courte, "question": "que montre la mire ?", "debut": "0:05", "images_max": "12"}},
              "--sur-place")
    fiche = r.get("fiche") or ""
    contenu = open(fiche, encoding="utf-8").read() if os.path.exists(fiche) else ""
    verif("analyse complete : fiche ecrite", r["ok"] and contenu.count("**Ce qui est MONTRÉ :**") == 1, r)
    verif("images plafonnees (<= 12) et decrites", 0 < r.get("images", 99) <= 12 and APPELS["vue"] == r["images"], r)
    verif("6 captures max gardees a cote de la fiche",
          0 < len(r.get("captures", [])) <= 6 and all(os.path.exists(c) for c in r["captures"]), r)
    verif("heures de la vraie video (passage decale de 5 s)", "[0:05]" in contenu and "passage 0:05" in contenu, contenu[:300])
    verif("index videos_analysees mis a jour",
          os.path.exists(os.path.join(env["VISION_VIDEO_BIBLIO"], "videos_analysees.md")), r)
    verif("description des captures gardee (bug du 05/11)", "** On voit une mire" in contenu, contenu[-900:])
    verif("son absent : dit honnetement", "aucune parole" in contenu, contenu[:300])
    r = outil({"action": "où en es-tu"})
    verif("etat apres l'analyse", r["ok"] and "mire" in r["phrase_pour_utilisateur"].lower(), r)

    # lancement en arriere-plan : rend la main tout de suite
    r = outil({"source": courte, "images_max": 5})
    verif("arriere-plan : PAS ENCORE FINI + duree annoncee",
          r["ok"] and r["phrase_pour_utilisateur"].startswith("PAS ENCORE FINI") and "minutes" in r["phrase_pour_utilisateur"], r)
    import time
    for _ in range(120):
        e = json.load(open(env["VISION_VIDEO_ETAT"], encoding="utf-8"))
        if not e.get("en_cours"):
            break
        time.sleep(1)
    verif("arriere-plan : finit tout seul", e.get("etape") == "fini" and os.path.exists(e.get("fiche") or ""), e)

    srv.shutdown()
    ok = sum(c[1] for c in cas)
    print(f"\n{ok}/{len(cas)} reussis")
    shutil.rmtree(tmp, ignore_errors=True)
    return ok, len(cas)


if __name__ == "__main__":
    ok, n = main()
    sys.exit(0 if ok == n else 1)
