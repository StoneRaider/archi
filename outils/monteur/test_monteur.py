"""Tests de monteur.py, hors ligne : un faux depot avec un faux serveur/montage.py, un faux dossier whisper. Aucun vrai
montage, aucun module installe, rien de telecharge."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time

ICI = os.path.dirname(os.path.abspath(__file__))
D = tempfile.mkdtemp(prefix="monteur_")
DEPOT = os.path.join(D, "depot")
WHISPER = os.path.join(D, "whisper")
ETAT = os.path.join(D, "etat.json")
VIDEOS = os.path.join(D, "videos.json")
RECU = os.path.join(D, "recu.json")
COMPORTEMENT = os.path.join(D, "comportement.txt")
os.makedirs(os.path.join(DEPOT, "serveur"))
os.makedirs(WHISPER)
FAUX_MONTAGE = r'''
import json, os, sys, time
D = %r
def lire(f, defaut):
    try:
        return json.load(open(os.path.join(D, f), encoding="utf-8"))
    except Exception:
        return defaut
a = sys.argv[1] if len(sys.argv) > 1 else ""
sys.stdout.reconfigure(encoding="utf-8")
if a == "etat":
    e = lire("etat.json", {})
    print(json.dumps({"ok": True, "etat": e, "phrase_pour_utilisateur": "Je suis en plein montage : " + str(e.get("etape")) if e.get("en_cours") else "Aucun montage en cours."}, ensure_ascii=False))
elif a == "lister":
    print(json.dumps({"ok": True, "videos": lire("videos.json", [])}, ensure_ascii=False))
elif a == "stop":
    e = lire("etat.json", {}); e["stop_demande"] = True
    json.dump(e, open(os.path.join(D, "etat.json"), "w", encoding="utf-8"))
    print(json.dumps({"ok": True, "phrase_pour_utilisateur": "Je demande l'arrêt du montage."}, ensure_ascii=False))
elif a == "--fichier":
    d = json.load(open(sys.argv[2], encoding="utf-8")); os.remove(sys.argv[2])
    json.dump(d, open(os.path.join(D, "recu.json"), "w", encoding="utf-8"), ensure_ascii=False)
    quoi = open(os.path.join(D, "comportement.txt"), encoding="utf-8").read().strip()
    if quoi == "demarre":
        json.dump({"en_cours": True, "etape": "lecture des fichiers"}, open(os.path.join(D, "etat.json"), "w", encoding="utf-8"))
        time.sleep(3)
    elif quoi == "echoue":
        json.dump({"en_cours": False, "etape": "échec", "erreur": "aucune vidéo lisible"}, open(os.path.join(D, "etat.json"), "w", encoding="utf-8"))
    # "muet" : il ne fait rien du tout
''' % D
with open(os.path.join(DEPOT, "serveur", "montage.py"), "w", encoding="utf-8") as h:
    h.write(FAUX_MONTAGE)
os.environ.update(ARCHI_DEPOT=DEPOT, ARCHI_SERVEUR_PY=sys.executable, ARCHI_WHISPER_DIR=WHISPER)
for k in ("ARCHI_WHISPER", "ARCHI_WHISPER_EXE", "ARCHI_WHISPER_MODELE", "ARCHI_FFMPEG"):
    os.environ.pop(k, None)
os.environ["PATH"] = os.path.dirname(sys.executable)      # pas de ffmpeg du PC dans ces tests
sys.path.insert(0, ICI)
import monteur as M  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
ok = ko = 0
M.ATTENTE_DEMARRAGE_S = 4


def verifie(nom, condition, detail=""):
    global ok, ko
    if condition:
        ok += 1
    else:
        ko += 1
        print("ECHEC :", nom, "|", str(detail)[:500])


def ecrire(f, x):
    with open(f, "w", encoding="utf-8") as h:
        if isinstance(x, str):
            h.write(x)
        else:
            json.dump(x, h, ensure_ascii=False)


def lancer(**d):
    f = os.path.join(D, "demande.json")
    ecrire(f, d)
    tampon = io.StringIO()
    ancien = sys.argv
    sys.argv = ["monteur.py", "--fichier", f]
    try:
        with contextlib.redirect_stdout(tampon):
            M.main()
    finally:
        sys.argv = ancien
    return json.loads(tampon.getvalue().strip().splitlines()[-1])


def recu():
    try:
        return json.load(open(RECU, encoding="utf-8"))
    except Exception:
        return None


def menage():
    for f in (ETAT, RECU):
        if os.path.exists(f):
            os.remove(f)


ecrire(VIDEOS, ["2026-11-14 21:03  2.1 Go  À monter\\soiree_1.mp4", "2026-11-14 22:40  1.4 Go  À monter\\soiree_2.mp4", "2026-10-02 10:00  0.8 Go  balade.mp4"])
ecrire(COMPORTEMENT, "demarre")

# ---------------------------------------------------------------- 1. monteur pas installe : il dit ce qui manque, il ne lance rien
for action in ("etat", "lister", "monter", "stop"):
    r = lancer(action=action, confirmer="oui")
    verifie("%s sans ffmpeg ni whisper : dit ce qui manque" % action,
            r["ok"] is False and "n'est pas installé" in r["phrase_pour_utilisateur"] and "ffmpeg.exe" in r["phrase_pour_utilisateur"]
            and "whisper-cli.exe" in r["phrase_pour_utilisateur"] and "ggml-small.bin" in r["phrase_pour_utilisateur"]
            and "rien lancé" in r["phrase_pour_utilisateur"] and recu() is None, r)
open(os.path.join(WHISPER, "ffmpeg.exe"), "w").close()
os.makedirs(os.path.join(WHISPER, "whisper-bin-x64", "Release"))
open(os.path.join(WHISPER, "whisper-bin-x64", "Release", "whisper-cli.exe"), "w").close()
r = lancer(action="monter", confirmer="oui")
verifie("il manque encore le modele de whisper : seul lui est cite", r["ok"] is False and "ggml-small.bin" in r["phrase_pour_utilisateur"]
        and "ffmpeg" not in r["phrase_pour_utilisateur"] and recu() is None, r)
open(os.path.join(WHISPER, "ggml-small.bin"), "w").close()
vrai_python = os.environ["ARCHI_SERVEUR_PY"]
faux_python = os.path.join(D, "python_sans_numpy.cmd")
ecrire(faux_python, "@echo off\r\nexit /b 1\r\n")
if os.name == "nt":
    os.environ["ARCHI_SERVEUR_PY"] = faux_python
    r = lancer(action="monter", confirmer="oui")
    verifie("numpy absent du Python du serveur : dit", r["ok"] is False and "numpy" in r["phrase_pour_utilisateur"] and recu() is None, r)
os.environ["ARCHI_SERVEUR_PY"] = os.path.join(D, "absent.exe")
r = lancer(action="etat")
verifie("Python du serveur absent : dit", r["ok"] is False and "Python du serveur" in r["phrase_pour_utilisateur"], r)
os.environ["ARCHI_SERVEUR_PY"] = vrai_python
try:
    import numpy  # noqa: F401
    NUMPY = True
except ImportError:
    NUMPY = False
if not NUMPY:
    M.pret = lambda: []      # ce PC de test n'a pas numpy : les tests suivants supposent le monteur installe
verifie("tout est la : rien ne manque", M.pret() == [], M.pret())
# une installation faite par installation.bat : ffmpeg dans le PATH d'Archi, whisper.cpp de la voix (ARCHI_WHISPER_EXE, ARCHI_WHISPER_MODELE)
vrai_pret = M.pret
autre = os.path.join(D, "installation")
os.makedirs(os.path.join(autre, "ffmpeg"))
for f in ("ffmpeg/ffmpeg.exe", "whisper-cli.exe", "ggml-small.bin"):
    open(os.path.join(autre, f), "w").close()
os.environ.update(ARCHI_WHISPER_DIR=os.path.join(D, "vide"), ARCHI_FFMPEG=os.path.join(autre, "ffmpeg", "ffmpeg.exe"),
                  ARCHI_WHISPER_EXE=os.path.join(autre, "whisper-cli.exe"), ARCHI_WHISPER_MODELE=os.path.join(autre, "ggml-small.bin"))
l = M.lieux()
verifie("les reglages de la voix servent au monteur", l["ffmpeg"].endswith("ffmpeg.exe") and os.path.exists(l["ffmpeg"]) and l["whisper"] == os.environ["ARCHI_WHISPER_EXE"]
        and l["modele_whisper"] == os.environ["ARCHI_WHISPER_MODELE"], l)
for k in ("ARCHI_FFMPEG", "ARCHI_WHISPER_EXE", "ARCHI_WHISPER_MODELE"):
    os.environ.pop(k)
os.environ["ARCHI_WHISPER_DIR"] = WHISPER

# ---------------------------------------------------------------- 2. etat, lister
menage()
r = lancer()
verifie("etat par defaut", r["ok"] and r["en_cours"] is False and "Aucun montage" in r["phrase_pour_utilisateur"], r)
r = lancer(action="lister")
verifie("lister : seulement le dossier À monter, noms dans « texte »", r["ok"] and r["videos"] == 2 and "soiree_1.mp4" in r["texte"] and "balade" not in r["texte"]
        and "soiree" not in r["phrase_pour_utilisateur"], r)

# ---------------------------------------------------------------- 3. monter : essai a blanc, puis confirmer
r = lancer(action="monter", mode="event", duree_min=8, titre="Soirée  jeux")
verifie("monter sans confirmer : ESSAI A BLANC, rien n'est lance",
        r["ok"] and r["essai"] is True and r["phrase_pour_utilisateur"].startswith("PAS ENCORE FAIT : je monterais les temps forts, 2 vidéo(s) du dossier")
        and recu() is None and r["demande"] == {"mode": "event", "duree_min": 8.0, "titre": "Soirée jeux"}, r)
for faux in ("non", "", None, "plus tard"):
    r = lancer(action="monter", confirmer=faux)
    verifie("confirmer=%r ne lance rien" % (faux,), r.get("essai") is True and recu() is None, r)
r = lancer(action="monter", confirmer="oui", mode="souvenirs", date="2026-10-02")
verifie("monter avec confirmer=oui : le montage a demarre, et l'outil l'a VU tourner",
        r["ok"] and r["lance"] is True and "Le montage est lancé : les souvenirs, 1 vidéo(s) du 2026-10-02" in r["phrase_pour_utilisateur"]
        and recu() == {"mode": "souvenirs", "date": "2026-10-02"}, r)
r = lancer(action="monter", confirmer="oui")
verifie("un montage tourne deja : pas de second", r["ok"] is False and "déjà en cours" in r["phrase_pour_utilisateur"], r)
r = lancer(action="etat")
verifie("etat pendant le montage", r["ok"] and r["en_cours"] is True and "lecture des fichiers" in r["phrase_pour_utilisateur"], r)
r = lancer(action="stop")
verifie("stop pendant le montage", r["ok"] and r["arret_demande"] is True, r)
time.sleep(3.5)
menage()
r = lancer(action="stop")
verifie("stop sans montage : rien a arreter, dit", r["ok"] and r["en_cours"] is False and "rien à arrêter" in r["phrase_pour_utilisateur"], r)

ecrire(COMPORTEMENT, "echoue")
r = lancer(action="monter", confirmer="oui")
verifie("le montage s'arrete tout de suite : dit, jamais « c'est lance »",
        r["ok"] is False and "arrêté tout de suite" in r["phrase_pour_utilisateur"] and "aucune vidéo lisible" in r["phrase_pour_utilisateur"], r)
menage()
ecrire(COMPORTEMENT, "muet")
r = lancer(action="monter", confirmer="oui")
verifie("le montage ne donne aucun signe : l'outil ne dit pas qu'il est parti", r["ok"] is False and r["incertain"] is True
        and "je ne peux pas dire qu'il est parti" in r["phrase_pour_utilisateur"], r)
menage()

r = lancer(action="monter", date="2026-12-25")
verifie("aucune video ce jour-la : rien lance, dit", r["ok"] is False and "aucune vidéo du 2026-12-25" in r["phrase_pour_utilisateur"] and recu() is None, r)
r = lancer(action="monter", date="samedi dernier")
verifie("date mal ecrite : refusee, pas devinee", r["ok"] is False and "AAAA-MM-JJ" in r["phrase_pour_utilisateur"], r)
r = lancer(action="monter", duree_min="longtemps")
verifie("duree illisible : refusee", r["ok"] is False and "nombre de minutes" in r["phrase_pour_utilisateur"], r)
r = lancer(action="effacer")
verifie("action inconnue", r["ok"] is False and "etat, lister, monter, stop" in r["phrase_pour_utilisateur"], r)

# ---------------------------------------------------------------- 4. le code
f = os.path.join(D, "d.json")
with open(f, "w", encoding="utf-8-sig") as h:
    json.dump({"action": "etat"}, h)
env = dict(os.environ, PYTHONIOENCODING="utf-8", ARCHI_WHISPER_DIR=os.path.join(D, "nulle_part"))
pr = subprocess.run([sys.executable, os.path.join(ICI, "monteur.py"), "--fichier", f], capture_output=True, env=env)
r = json.loads(pr.stdout.decode("utf-8").strip().splitlines()[-1])
verifie("ligne de commande, monteur pas installe : une ligne JSON claire", pr.returncode == 0 and r["ok"] is False and "n'est pas installé" in r["phrase_pour_utilisateur"], r)
fiche = json.load(open(os.path.join(ICI, "outil.json"), encoding="utf-8"))
verifie("outil.json", fiche["nom"] == "monteur" and fiche["script"] == "monteur.py" and "ESSAI A BLANC" in fiche["description"] and "confirmer=oui" in fiche["description"])
source = open(os.path.join(ICI, "monteur.py"), encoding="utf-8").read()
verifie("l'outil n'installe rien et n'ouvre aucune adresse", "pip" not in source and "urllib" not in source and "http" not in source)

print(("%d tests OK" % ok) if not ko else ("%d ECHEC(S) sur %d" % (ko, ok + ko)))
sys.exit(1 if ko else 0)
