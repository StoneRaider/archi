# monteur.py - outil maison d'Archi : le monteur video (temps forts d'une soiree, souvenirs d'une sortie).
#
#   python monteur.py --fichier demande.json          (appele par outils_maison)
#   demande.json : {"action": "...", ...}
#     etat (defaut)  ou en est le montage en cours, ou comment s'est fini le dernier
#     lister         les videos a monter (dossier Videos\À monter)
#     monter         mode = event (temps forts) ou souvenirs ; date = AAAA-MM-JJ (sinon le dossier « À monter ») ;
#                    duree_min ; titre ; ambiance ; participants ; confirmer. SANS confirmer=oui : ESSAI A BLANC, rien
#                    n'est lance. AVEC confirmer=oui : le montage part en arriere-plan (environ une heure).
#     stop           arrete le montage en cours a la fin de l'etape
#
# Repond UNE ligne JSON : {"ok", "phrase_pour_utilisateur", ...}.
#
# Cet outil ne monte rien lui-meme : il lance serveur/montage.py avec le Python du serveur d'Archi. Regles tenues ici :
#   1. AVANT tout, il verifie que le monteur est installe (voir pret()). S'il manque quelque chose, il dit QUOI et ne
#      lance rien : jamais de « c'est parti » pour un montage qui ne peut pas tourner ;
#   2. un montage occupe la carte graphique pendant une heure : il ne part qu'apres un essai a blanc et confirmer=oui ;
#   3. apres le lancement, il regarde si le montage a vraiment demarre. S'il s'est arrete tout de suite, il le dit ;
#   4. il n'installe rien et ne telecharge rien.
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata

DELAI_S = 60
ATTENTE_DEMARRAGE_S = 6
SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Erreur(Exception):
    pass


def repondre(ok, phrase, **extra):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(dict(ok=ok, phrase_pour_utilisateur=phrase, **extra), ensure_ascii=False))


def plat(t):
    t = unicodedata.normalize("NFD", str(t or ""))
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower().strip()


def oui(v):
    return v is True or plat(v) in ("oui", "true", "1", "vrai", "yes")


# ---------------------------------------------------------------- le monteur est-il installe ?
def lieux():
    depot = os.environ.get("ARCHI_DEPOT") or ""
    whisper = os.environ.get("ARCHI_WHISPER_DIR") or os.path.join(os.path.expanduser("~"), "whisper")
    # la MEME recherche que serveur/montage.py (ses lignes FFMPEG, WHISPER, WHISPER_MODELE) : garder les deux d'accord
    import shutil
    ffmpeg = os.path.join(whisper, "ffmpeg.exe")
    if not os.path.exists(ffmpeg):
        ffmpeg = os.environ.get("ARCHI_FFMPEG") or shutil.which("ffmpeg") or ffmpeg
    exe = os.environ.get("ARCHI_WHISPER") or os.path.join(whisper, "whisper-bin-x64", "Release", "whisper-cli.exe")
    if not os.path.exists(exe):
        exe = os.environ.get("ARCHI_WHISPER_EXE") or exe
    modele = os.path.join(whisper, "ggml-small.bin")
    if not os.path.exists(modele):
        modele = os.environ.get("ARCHI_WHISPER_MODELE") or modele
    return {
        "script": os.path.join(depot, "serveur", "montage.py") if depot else "",
        "python": os.environ.get("ARCHI_SERVEUR_PY") or (os.path.join(depot, "serveur", "venv", "Scripts", "python.exe") if depot else ""),
        "ffmpeg": ffmpeg,
        "whisper": exe,
        "modele_whisper": modele,
    }


def pret():
    """la liste de ce qui manque pour monter (vide = tout est la). Aucune installation, aucun telechargement."""
    l = lieux()
    manque = []
    if not l["script"] or not os.path.exists(l["script"]):
        return ["le serveur d'Archi (serveur/montage.py, réglage ARCHI_DEPOT)"]
    if not l["python"] or not os.path.exists(l["python"]):
        return ["le Python du serveur d'Archi (serveur\\venv)"]
    try:
        r = subprocess.run([l["python"], "-c", "import numpy"], capture_output=True, timeout=30, creationflags=SANS_FENETRE)
        if r.returncode != 0:
            manque.append("le module Python numpy dans serveur\\venv")
    except (OSError, subprocess.SubprocessError):
        manque.append("le module Python numpy dans serveur\\venv")
    if not os.path.exists(l["ffmpeg"]):
        manque.append("ffmpeg.exe (dans le dossier ARCHI_WHISPER_DIR)")
    if not os.path.exists(l["whisper"]):
        manque.append("whisper-cli.exe (whisper.cpp, pour les sous-titres)")
    if not os.path.exists(l["modele_whisper"]):
        manque.append("le modèle de whisper (ggml-small.bin)")
    return manque


def exiger_pret():
    manque = pret()
    if manque:
        raise Erreur("Le monteur vidéo n'est pas installé sur ce PC. Il manque : %s. Je n'ai rien lancé." % " ; ".join(manque))


def appeler(*args):
    """une commande courte de montage.py (etat, stop, lister) : sa derniere ligne JSON"""
    l = lieux()
    try:
        r = subprocess.run([l["python"], l["script"]] + list(args), capture_output=True, timeout=DELAI_S, cwd=os.path.dirname(l["script"]),
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"), creationflags=SANS_FENETRE)
        lignes = r.stdout.decode("utf-8", "replace").strip().splitlines()
        d = json.loads(lignes[-1]) if lignes else None
        if not isinstance(d, dict):
            raise ValueError("vide")
        return d
    except (OSError, ValueError, subprocess.SubprocessError):
        raise Erreur("Le monteur ne répond pas. Je n'ai rien lancé.")


# ---------------------------------------------------------------- les actions
def a_etat(d):
    exiger_pret()
    r = appeler("etat")
    e = r.get("etat") if isinstance(r.get("etat"), dict) else {}
    return repondre(True, str(r.get("phrase_pour_utilisateur") or "Aucun montage en cours.")[:500], en_cours=bool(e.get("en_cours")))


def videos(date=""):
    """les lignes « date  taille  chemin » que montage.py connait ; avec une date : celles de ce jour ; sinon le dossier « À monter »"""
    L = [str(x) for x in (appeler("lister").get("videos") or []) if isinstance(x, str)]
    if date:
        return [x for x in L if x.startswith(date)]
    return [x for x in L if plat(x.split("  ")[-1]).replace("\\", "/").startswith("a monter/")]


def a_lister(d):
    exiger_pret()
    L = videos()
    if not L:
        return repondre(True, "Aucune vidéo à monter : dépose tes vidéos dans le dossier Vidéos\\À monter.", videos=0)
    return repondre(True, "%d vidéo(s) à monter. Leurs noms sont dans « texte »." % len(L), texte="\n".join("- " + x[:200] for x in L[:25]), videos=len(L))


def demande_de(d):
    m = {"mode": "souvenirs" if "souv" in plat(d.get("mode")) else "event"}
    date = str(d.get("date") or "").strip()[:10]
    if date:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            raise Erreur("La date doit s'écrire AAAA-MM-JJ (le jour des vidéos à monter).")
        m["date"] = date
    if d.get("duree_min") not in (None, ""):
        try:
            m["duree_min"] = max(1.0, min(60.0, float(d["duree_min"])))
        except (TypeError, ValueError):
            raise Erreur("La durée doit être un nombre de minutes.")
    if d.get("titre"):
        m["titre"] = " ".join(str(d["titre"]).split())[:40]
    if d.get("ambiance"):
        a = plat(d["ambiance"])
        if a in ("epique", "calme", "energique"):
            m["ambiance"] = a
    if d.get("participants"):
        m["participants"] = [x.strip()[:40] for x in re.split(r"[,;\n]+", str(d["participants"])) if x.strip()][:12]
    for k in ("garder", "enlever"):
        if d.get(k):
            m[k] = str(d[k])[:300]
    return m


def a_monter(d):
    exiger_pret()
    m = demande_de(d)
    e = appeler("etat").get("etat")
    if isinstance(e, dict) and e.get("en_cours"):
        raise Erreur("Un montage est déjà en cours : %s. Je n'en lance pas un second." % str(e.get("etape") or "en cours")[:100])
    L = videos(m.get("date", ""))
    ou = ("du %s" % m["date"]) if m.get("date") else "du dossier Vidéos\\À monter"
    if not L:
        raise Erreur("Je ne trouve aucune vidéo %s : je n'ai rien lancé." % ou)
    quoi = "%s, %d vidéo(s) %s" % ("les temps forts" if m["mode"] == "event" else "les souvenirs", len(L), ou)
    if not oui(d.get("confirmer")):
        return repondre(True, "PAS ENCORE FAIT : je monterais %s. Le montage prend environ une heure et occupe la carte graphique. "
                        "Demande à l'utilisateur s'il confirme ; s'il dit oui, rappelle-moi avec les mêmes paramètres et confirmer=oui." % quoi,
                        essai=True, videos=len(L), demande=m)
    l = lieux()
    fd, f = tempfile.mkstemp(prefix="montage_", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as h:
        json.dump(m, h, ensure_ascii=False)
    try:
        subprocess.Popen([l["python"], l["script"], "--fichier", f], cwd=os.path.dirname(l["script"]),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                         env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                         creationflags=SANS_FENETRE | getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    except OSError:
        raise Erreur("Le montage n'a pas pu démarrer. Rien n'est lancé.")
    # a-t-il vraiment demarre ? montage.py ecrit son etat des les premieres secondes
    fin = time.time() + ATTENTE_DEMARRAGE_S
    e = {}
    while time.time() < fin:
        time.sleep(0.5)
        try:
            e = appeler("etat").get("etat") or {}
        except Erreur:
            e = {}
        if e.get("en_cours") or e.get("erreur"):
            break
    if e.get("erreur") and not e.get("en_cours"):
        return repondre(False, "Le montage s'est arrêté tout de suite : %s. Rien n'est monté." % str(e["erreur"])[:200])
    if not e.get("en_cours"):
        return repondre(False, "J'ai lancé le montage mais je ne le vois pas tourner. Demande-moi « où en est le montage » dans une minute ; "
                        "pour l'instant je ne peux pas dire qu'il est parti.", incertain=True)
    return repondre(True, "Le montage est lancé : %s. Compte environ une heure. Demande-moi « où en est le montage » quand tu veux ; "
                    "la vidéo arrivera dans Vidéos\\Montages." % quoi, lance=True, videos=len(L), demande=m)


def a_stop(d):
    exiger_pret()
    e = appeler("etat").get("etat")
    if not (isinstance(e, dict) and e.get("en_cours")):
        return repondre(True, "Aucun montage n'est en cours : il n'y a rien à arrêter.", en_cours=False)
    r = appeler("stop")
    return repondre(r.get("ok") is True, str(r.get("phrase_pour_utilisateur") or "Arrêt demandé.")[:300], arret_demande=r.get("ok") is True)


ACTIONS = {"etat": a_etat, "lister": a_lister, "monter": a_monter, "stop": a_stop}
SYNONYMES = {"": "etat", "ou_en_est": "etat", "avancement": "etat", "liste": "lister", "videos": "lister", "monte": "monter", "montage": "monter",
             "lancer": "monter", "lance": "monter", "arreter": "stop", "arrete": "stop", "annuler": "stop"}


def main():
    pa = argparse.ArgumentParser()
    pa.add_argument("--fichier", required=True)
    a = pa.parse_args()
    try:
        with open(a.fichier, encoding="utf-8-sig") as h:
            d = json.load(h)
        if not isinstance(d, dict):
            raise Erreur("La demande est illisible.")
        action = re.sub(r"[^a-z_]", "_", plat(d.get("action"))).strip("_")
        action = SYNONYMES.get(action, action)
        if action not in ACTIONS:
            raise Erreur("Action inconnue. Le monteur sait : etat, lister, monter, stop.")
        ACTIONS[action](d)
    except Erreur as e:
        repondre(False, str(e))
    except Exception as e:
        repondre(False, "Le monteur a eu un souci : " + str(e)[:150])


if __name__ == "__main__":
    main()
