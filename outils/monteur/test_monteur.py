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
from datetime import datetime, timedelta

ICI = os.path.dirname(os.path.abspath(__file__))
D = tempfile.mkdtemp(prefix="monteur_")
DEPOT = os.path.join(D, "depot")
WHISPER = os.path.join(D, "whisper")
ETAT = os.path.join(D, "etat.json")
VIDEOS = os.path.join(D, "videos.json")
RECU = os.path.join(D, "recu.jsonl")
COMPORTEMENT = os.path.join(D, "comportement.txt")
os.makedirs(os.path.join(DEPOT, "serveur"))
os.makedirs(WHISPER)
FAUX_MONTAGE = r'''
import json, os, sys, time
from datetime import datetime
D = %r
def lire(f, defaut):
    try:
        return json.load(open(os.path.join(D, f), encoding="utf-8"))
    except Exception:
        return defaut
def etat(**k):
    e = lire("etat.json", {}); e.update(k); e["maj"] = datetime.now().isoformat(timespec="seconds")
    json.dump(e, open(os.path.join(D, "etat.json"), "w", encoding="utf-8"), ensure_ascii=False)
a = sys.argv[1] if len(sys.argv) > 1 else ""
sys.stdout.reconfigure(encoding="utf-8")
if a == "etat":
    e = lire("etat.json", {})
    brut = lire("etat_brut.json", None)
    if brut is not None:
        e = brut
    ph = ("Je suis en plein montage : " + str(e.get("etape"))) if isinstance(e, dict) and e.get("en_cours") else "Aucun montage en cours." + ((" Le dernier a échoué : " + str(e.get("erreur"))) if isinstance(e, dict) and e.get("erreur") else "")
    print(json.dumps({"ok": True, "etat": e, "phrase_pour_utilisateur": ph}, ensure_ascii=False))
elif a == "lister":
    print(json.dumps({"ok": True, "videos": lire("videos.json", [])}, ensure_ascii=False))
elif a == "stop":
    e = lire("etat.json", {}); e["stop_demande"] = True
    json.dump(e, open(os.path.join(D, "etat.json"), "w", encoding="utf-8"))
    print(json.dumps({"ok": True, "phrase_pour_utilisateur": "Je demande l'arrêt du montage."}, ensure_ascii=False))
elif a == "--fichier":
    d = json.load(open(sys.argv[2], encoding="utf-8")); os.remove(sys.argv[2])
    open(os.path.join(D, "recu.jsonl"), "a", encoding="utf-8").write(json.dumps(d, ensure_ascii=False) + "\n")
    quoi = open(os.path.join(D, "comportement.txt"), encoding="utf-8").read().strip()
    if quoi.startswith("demarre"):
        time.sleep(float(quoi.split()[1]) if " " in quoi else 0)
        etat(en_cours=True, etape="lecture des fichiers", erreur=None)
        time.sleep(3)
        etat(en_cours=False, etape="fini")
    elif quoi == "echoue":
        etat(en_cours=False, etape="échec", erreur="aucune vidéo trouvée dans C:\\Users\\Camille\\Videos\\À monter\\anniversaire.mp4")
    # "muet" : il ne fait rien du tout
''' % D
with open(os.path.join(DEPOT, "serveur", "montage.py"), "w", encoding="utf-8") as h:
    h.write(FAUX_MONTAGE)
os.environ.update(ARCHI_DEPOT=DEPOT, ARCHI_SERVEUR_PY=sys.executable, ARCHI_WHISPER_DIR=WHISPER, ARCHI_BASE=os.path.join(D, "chateau"))
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
M.ATTENTE_DEMARRAGE_S = 5


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
        return [json.loads(l) for l in open(RECU, encoding="utf-8").read().splitlines() if l.strip()]
    except Exception:
        return []


def menage():
    for f in (ETAT, RECU, os.path.join(D, "etat_brut.json")):
        if os.path.exists(f):
            os.remove(f)
    M.oublier_essai()


def essai_puis_oui(tache_essai="tst0001", tache_oui="tst0002", **d):
    """l'essai dans un message, le oui dans le suivant (numeros donnes par le lanceur) ; None : pas de numero"""
    M.oublier_essai()
    lancer(**dict(d, action="monter", **({"_tache": tache_essai} if tache_essai else {})))
    return lancer(**dict(d, action="monter", confirmer="oui", **({"_tache": tache_oui} if tache_oui else {})))


ecrire(VIDEOS, ["2026-11-14 21:03  2.1 Go  À monter\\soiree_1.mp4", "2026-11-14 22:40  1.4 Go  À monter\\soiree_2.mp4", "2026-10-02 10:00  0.8 Go  balade.mp4"])
ecrire(COMPORTEMENT, "demarre")

# ---------------------------------------------------------------- 1. monteur pas installe : il dit ce qui manque, il ne lance rien
for action in ("etat", "lister", "monter", "stop"):
    r = lancer(action=action, confirmer="oui")
    verifie("%s sans ffmpeg ni whisper : dit ce qui manque" % action,
            r["ok"] is False and "n'est pas installé" in r["phrase_pour_utilisateur"] and "ffmpeg.exe" in r["phrase_pour_utilisateur"]
            and "whisper-cli.exe" in r["phrase_pour_utilisateur"] and "ggml-small.bin" in r["phrase_pour_utilisateur"]
            and "rien lancé" in r["phrase_pour_utilisateur"] and recu() == [], r)
open(os.path.join(WHISPER, "ffmpeg.exe"), "w").close()
os.makedirs(os.path.join(WHISPER, "whisper-bin-x64", "Release"))
open(os.path.join(WHISPER, "whisper-bin-x64", "Release", "whisper-cli.exe"), "w").close()
r = lancer(action="monter", confirmer="oui")
verifie("il manque encore le modele de whisper : seul lui est cite", r["ok"] is False and "ggml-small.bin" in r["phrase_pour_utilisateur"]
        and "ffmpeg" not in r["phrase_pour_utilisateur"] and recu() == [], r)
open(os.path.join(WHISPER, "ggml-small.bin"), "w").close()
vrai_python = os.environ["ARCHI_SERVEUR_PY"]
if os.name == "nt":
    faux_python = os.path.join(D, "python_sans_numpy.cmd")
    ecrire(faux_python, "@echo off\r\nexit /b 1\r\n")
    os.environ["ARCHI_SERVEUR_PY"] = faux_python
    r = lancer(action="monter", confirmer="oui")
    verifie("numpy absent du Python du serveur : dit", r["ok"] is False and "numpy" in r["phrase_pour_utilisateur"] and recu() == [], r)
os.environ["ARCHI_SERVEUR_PY"] = os.path.join(D, "absent.exe")
r = lancer(action="etat")
verifie("Python du serveur absent : dit", r["ok"] is False and "Python du serveur" in r["phrase_pour_utilisateur"], r)
os.environ["ARCHI_SERVEUR_PY"] = vrai_python
try:
    import numpy  # noqa: F401
    NUMPY = True
except ImportError:
    NUMPY = False
# une installation faite par installation.bat : ffmpeg dans les programmes d'Archi, whisper.cpp de la voix (ARCHI_WHISPER_EXE, ARCHI_WHISPER_MODELE)
autre = os.path.join(D, "installation")
os.makedirs(os.path.join(autre, "ffmpeg"))
for f in ("ffmpeg/ffmpeg.exe", "whisper-cli.exe", "ggml-small.bin"):
    open(os.path.join(autre, f), "w").close()
os.environ.update(ARCHI_WHISPER_DIR=os.path.join(D, "vide"), ARCHI_FFMPEG=os.path.join(autre, "ffmpeg", "ffmpeg.exe"),
                  ARCHI_WHISPER_EXE=os.path.join(autre, "whisper-cli.exe"), ARCHI_WHISPER_MODELE=os.path.join(autre, "ggml-small.bin"))
l = M.lieux()
verifie("les reglages de la voix servent au monteur", os.path.exists(l["ffmpeg"]) and l["whisper"] == os.environ["ARCHI_WHISPER_EXE"]
        and l["modele_whisper"] == os.environ["ARCHI_WHISPER_MODELE"], l)
for k in ("ARCHI_FFMPEG", "ARCHI_WHISPER_EXE", "ARCHI_WHISPER_MODELE"):
    os.environ.pop(k)
os.environ["ARCHI_WHISPER_DIR"] = WHISPER
if not NUMPY:
    M.pret = lambda: []      # ce PC de test n'a pas numpy : les tests suivants supposent le monteur installe
verifie("tout est la : rien ne manque", M.pret() == [], M.pret())

# ---------------------------------------------------------------- 2. etat, lister
menage()
r = lancer()
verifie("etat par defaut", r["ok"] and r["en_cours"] is False and "Aucun montage" in r["phrase_pour_utilisateur"], r)
r = lancer(action="lister")
verifie("lister : seulement le dossier À monter, noms dans « texte »", r["ok"] and r["videos"] == 2 and "soiree_1.mp4" in r["texte"] and "balade" not in r["texte"]
        and "soiree" not in r["phrase_pour_utilisateur"], r)

# ---------------------------------------------------------------- 3. monter : essai a blanc OBLIGATOIRE, puis confirmer
r = lancer(action="monter", mode="event", duree_min=8, titre="Soirée  jeux")
verifie("monter sans confirmer : ESSAI A BLANC, rien n'est lance",
        r["ok"] and r["essai"] is True and r["phrase_pour_utilisateur"].startswith("PAS ENCORE FAIT : je monterais les temps forts, avec le contenu du dossier")
        and recu() == [] and r["demande"] == {"mode": "event", "duree_min": 8.0, "titre": "Soirée jeux"}, r)
for faux in ("non", "", None, "plus tard", ["oui"], {"a": 1}, "oui oui", "ouiii", 1.0):
    r = lancer(action="monter", confirmer=faux)
    verifie("confirmer=%r ne lance rien" % (faux,), r.get("essai") is True and recu() == [], r)
M.oublier_essai()
r = lancer(action="monter", confirmer="oui", mode="souvenirs", date="2026-10-02")
verifie("confirmer=oui du premier coup : essai a blanc, rien n'est lance", r.get("essai") is True and recu() == [], r)
r = lancer(action="monter", confirmer="oui", mode="event", date="2026-10-02")
verifie("confirmer=oui pour un AUTRE montage que celui montre : nouvel essai", r.get("essai") is True and recu() == [], r)
r = essai_puis_oui(None, None, mode="souvenirs")
verifie("essai puis oui SANS numero de message : rien n'est lance (2e relecture)", r.get("essai") is True and "je ne lancerai rien" in r["phrase_pour_utilisateur"] and recu() == [], r)
for bizarre in (5, ["msg0001"], "", "MSG0001", "T-2026-11-21", "ab12c"):
    M.oublier_essai()
    lancer(action="monter", mode="souvenirs", _tache="msg0001")
    r = lancer(action="monter", mode="souvenirs", confirmer="oui", _tache=bizarre)
    verifie("oui avec un numero de message %r : rien n'est lance" % (bizarre,), r.get("essai") is True and recu() == [], r)
r = lancer(action="monter", mode="film")
verifie("mode inconnu : refuse, pas pris pour « event »", r["ok"] is False and "Mode inconnu" in r["phrase_pour_utilisateur"], r)
r = essai_puis_oui("msg0001", "msg0001", mode="souvenirs")
verifie("essai et confirmer=oui dans le MEME message : rien n'est lance", r.get("essai") is True and recu() == [], r)
r = essai_puis_oui("msg0001", "msg0002", mode="souvenirs", date="2026-10-02")
verifie("essai, puis oui au message suivant : le montage a demarre, et l'outil l'a VU tourner",
        r["ok"] and r["lance"] is True and "Le montage est lancé : les souvenirs, avec les vidéos du 2026-10-02" in r["phrase_pour_utilisateur"]
        and recu() == [{"mode": "souvenirs", "date": "2026-10-02"}], r)
r = lancer(action="monter", confirmer="oui", mode="souvenirs", date="2026-10-02")
verifie("un montage tourne deja : pas de second", r["ok"] is False and "déjà en cours" in r["phrase_pour_utilisateur"] and len(recu()) == 1, r)
r = lancer(action="etat")
verifie("etat pendant le montage", r["ok"] and r["en_cours"] is True and "lecture des fichiers" in r["phrase_pour_utilisateur"], r)
r = lancer(action="stop")
verifie("stop pendant le montage", r["ok"] and r["arret_demande"] is True, r)
time.sleep(3.5)
menage()
r = lancer(action="stop")
verifie("stop sans montage : rien a arreter, dit", r["ok"] and r["en_cours"] is False and "rien à arrêter" in r["phrase_pour_utilisateur"], r)

# l'erreur d'un montage PRECEDENT est restee dans l'etat, et le nouveau met 1,5 s a ecrire le sien (relecture du 21/11)
menage()
ecrire(ETAT, {"en_cours": False, "etape": "échec", "erreur": "jeu est ouvert", "maj": (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")})
ecrire(COMPORTEMENT, "demarre 1.5")
r = essai_puis_oui()
verifie("vieille erreur dans l'etat : le nouveau montage n'est pas declare arrete", r["ok"] and r.get("lance") is True, r)
time.sleep(3.5)
menage()
ecrire(COMPORTEMENT, "echoue")
r = essai_puis_oui()
verifie("le montage s'arrete tout de suite : dit, jamais « c'est lance », sans chemin du PC",
        r["ok"] is False and "arrêté tout de suite" in r["phrase_pour_utilisateur"] and "aucune vidéo trouvée" in r["phrase_pour_utilisateur"]
        and "Camille" not in r["phrase_pour_utilisateur"] and "anniversaire.mp4" in r["phrase_pour_utilisateur"], r)
menage()
ecrire(COMPORTEMENT, "muet")
r = essai_puis_oui()
verifie("le montage ne donne aucun signe : l'outil ne dit pas qu'il est parti", r["ok"] is False and r["incertain"] is True
        and "Je ne peux pas dire qu'il est parti" in r["phrase_pour_utilisateur"], r)
menage()
ecrire(ETAT, {"en_cours": False, "erreur": "vieille erreur", "maj": (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")})
r = essai_puis_oui()
verifie("montage muet avec une vieille erreur : « je ne sais pas », pas l'erreur d'hier", r["ok"] is False and r.get("incertain") is True and "vieille" not in r["phrase_pour_utilisateur"], r)

# trois « oui » en meme temps : un seul montage part
menage()
ecrire(COMPORTEMENT, "demarre")
lancer(action="monter", mode="souvenirs", _tache="par0001")
f3 = os.path.join(D, "oui.json")
ecrire(f3, {"action": "monter", "mode": "souvenirs", "confirmer": "oui", "_tache": "par0002"})
procs = [subprocess.Popen([sys.executable, os.path.join(ICI, "monteur.py"), "--fichier", f3], stdout=subprocess.PIPE, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
         for _ in range(3)]
sorties = [json.loads(q.communicate()[0].decode("utf-8").strip().splitlines()[-1]) for q in procs]
verifie("trois oui en meme temps : un seul montage lance", len(recu()) == 1 and sum(1 for x in sorties if x.get("lance")) <= 1, sorties)
time.sleep(3.5)

# un etat « en cours » fige depuis trois jours (montage tue) ne bloque pas le monteur pour toujours
menage()
ecrire(ETAT, {"en_cours": True, "etape": "transcription des voix", "maj": (datetime.now() - timedelta(days=3)).isoformat(timespec="seconds")})
r = lancer(action="etat")
verifie("etat fige depuis 3 jours : dit qu'il a ete interrompu", r["ok"] and r["en_cours"] is False and r["bloque"] is True, r)
ecrire(COMPORTEMENT, "demarre")
r = essai_puis_oui()
verifie("etat fige : un nouveau montage peut partir", r["ok"] and r.get("lance") is True, r)
time.sleep(3.5)
menage()
for brut in ({"en_cours": "false"}, {"en_cours": "true"}, {"en_cours": 1}, "en_cours", [], None):
    ecrire(os.path.join(D, "etat_brut.json"), brut)
    r = lancer(action="etat")
    verifie("etat bizarre %r : pas « en cours », pas de plantage" % (brut,), r["ok"] and r["en_cours"] is False, r)
menage()

r = lancer(action="monter", date="samedi dernier")
verifie("date mal ecrite : refusee, pas devinee", r["ok"] is False and "AAAA-MM-JJ" in r["phrase_pour_utilisateur"], r)
for duree in ("longtemps", "nan"):
    r = lancer(action="monter", duree_min=duree)
    verifie("duree %r : refusee" % duree, r["ok"] is False and "nombre de minutes" in r["phrase_pour_utilisateur"], r)
r = lancer(action="effacer")
verifie("action inconnue", r["ok"] is False and "etat, lister, monter, stop" in r["phrase_pour_utilisateur"], r)
r = lancer(action="monter", forcer=True, fichiers=["C:/secret.mp4"])
verifie("« forcer » et « fichiers » ne passent pas au montage", r["demande"] == {"mode": "event"}, r)

# ---------------------------------------------------------------- 4. le code
f = os.path.join(D, "d.json")
with open(f, "w", encoding="utf-8-sig") as h:
    json.dump({"action": "etat"}, h)
env = dict(os.environ, PYTHONIOENCODING="utf-8", ARCHI_WHISPER_DIR=os.path.join(D, "nulle_part"))
pr = subprocess.run([sys.executable, os.path.join(ICI, "monteur.py"), "--fichier", f], capture_output=True, env=env)
r = json.loads(pr.stdout.decode("utf-8").strip().splitlines()[-1])
verifie("ligne de commande, monteur pas installe : une ligne JSON claire", pr.returncode == 0 and r["ok"] is False and "n'est pas installé" in r["phrase_pour_utilisateur"], r)
fiche = json.load(open(os.path.join(ICI, "outil.json"), encoding="utf-8"))
verifie("outil.json", fiche["nom"] == "monteur" and fiche["script"] == "monteur.py" and "ESSAI A BLANC" in fiche["description"] and "confirmer=oui" in fiche["description"]
        and fiche["recoit_tache"] is True)
source = open(os.path.join(ICI, "monteur.py"), encoding="utf-8").read()
verifie("l'outil n'installe rien et n'ouvre aucune adresse", "pip" not in source and "urllib" not in source and "http" not in source)

print(("%d tests OK" % ok) if not ko else ("%d ECHEC(S) sur %d" % (ko, ok + ko)))
sys.exit(1 if ko else 0)
