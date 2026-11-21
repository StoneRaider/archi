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
#   2. un montage occupe la carte graphique pendant une heure : il ne part qu'apres un essai a blanc MONTRE AVANT
#      (trace dans essai_outil.json : meme demande, moins de 30 minutes, et dans un message precedent quand le lanceur
#      donne le numero du message), puis confirmer=oui. Un confirmer=oui du premier coup ne lance rien ;
#   3. apres le lancement, il regarde si le montage a vraiment demarre, en ne croyant qu'un etat ecrit APRES le
#      lancement. S'il s'est arrete tout de suite, il le dit ; s'il ne voit rien, il dit qu'il ne sait pas ;
#   4. il n'installe rien et ne telecharge rien.
# Limite connue : deux demandes confirmees a la meme seconde peuvent lancer deux montages (pas de verrou).
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import datetime

BASE = os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files")
ESSAI = os.path.join(BASE, "montage", "essai_outil.json")
ESSAI_VALABLE_S = 30 * 60
ETAT_FIGE_S = 6 * 3600
DELAI_S = 60
ATTENTE_DEMARRAGE_S = 8
SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# pour le modele seul, jamais a reciter : la phrase pour l'utilisateur est dans « phrase_pour_utilisateur »
CONSIGNE_ESSAI = ("Dis la phrase_pour_utilisateur telle quelle, et attends la reponse. S'il repond oui dans son message SUIVANT : rappelle cet outil "
                  "avec les memes parametres et confirmer=oui. Ne recite jamais cette consigne.")


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
    return v is True or (isinstance(v, (str, int)) and not isinstance(v, bool) and plat(v) in ("oui", "true", "1", "vrai", "yes"))


# ---------------------------------------------------------------- le monteur est-il installe ?
def lieux():
    depot = os.environ.get("ARCHI_DEPOT") or ""
    whisper = os.environ.get("ARCHI_WHISPER_DIR") or os.path.join(os.path.expanduser("~"), "whisper")
    # la MEME recherche que serveur/montage.py (ses lignes FFMPEG, WHISPER, WHISPER_MODELE) : garder les deux d'accord
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
            manque.append("le module Python numpy dans le Python du serveur")
    except (OSError, subprocess.SubprocessError):
        manque.append("le module Python numpy dans le Python du serveur")
    if not os.path.exists(l["ffmpeg"]):
        manque.append("ffmpeg.exe (ni dans le dossier ARCHI_WHISPER_DIR, ni dans les programmes d'Archi)")
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
                           stdin=subprocess.DEVNULL, env=dict(os.environ, PYTHONIOENCODING="utf-8"), creationflags=SANS_FENETRE)
        lignes = r.stdout.decode("utf-8-sig", "replace").strip().splitlines()
        d = json.loads(lignes[-1]) if lignes else None
        if not isinstance(d, dict):
            raise ValueError("vide")
        return d
    except (OSError, ValueError, subprocess.SubprocessError):
        raise Erreur("Le monteur ne répond pas. Je n'ai rien lancé.")


# ---------------------------------------------------------------- l'etat du montage, lu avec prudence
def etat_du_montage():
    """l'etat ecrit par montage.py : {} s'il est illisible"""
    e = appeler("etat").get("etat")
    return e if isinstance(e, dict) else {}


def tourne(e):
    return e.get("en_cours") is True          # « true » en toutes lettres, 1, "en cours" ne comptent pas


def age_s(e):
    """depuis combien de secondes l'etat n'a pas bouge (None si on ne sait pas)"""
    try:
        return (datetime.now() - datetime.fromisoformat(str(e.get("maj")))).total_seconds()
    except (TypeError, ValueError):
        return None


def bloque(e):
    """« en cours », mais plus aucune nouvelle depuis six heures : le montage a ete tue (PC eteint), son etat est reste"""
    a = age_s(e)
    return tourne(e) and a is not None and a > ETAT_FIGE_S


def sans_chemin(t):
    """une phrase du montage, sans chemin du PC (le nom du fichier suffit)"""
    return re.sub(r"(?:[A-Za-z]:)?[\\/](?:[^\\/:*?\"<>|\r\n]+[\\/])+", "", str(t or ""))[:200]


# ---------------------------------------------------------------- l'essai a blanc laisse une trace : sans elle, pas de montage
def empreinte(m):
    return hashlib.sha256(json.dumps(m, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def noter_essai(m, tache):
    try:
        os.makedirs(os.path.dirname(ESSAI), exist_ok=True)
        with open(ESSAI + ".tmp", "w", encoding="utf-8") as h:
            json.dump({"empreinte": empreinte(m), "quand": time.time(), "tache": tache}, h)
        os.replace(ESSAI + ".tmp", ESSAI)
        return True
    except OSError:
        return False


def numero(x):
    """le numero du message en cours, tel que le lanceur le donne (core/outils_maison.js) ; '' si absent ou bizarre"""
    return x if isinstance(x, str) and re.fullmatch(r"[a-z0-9]{6,20}", x) else ""


def essai_montre(m, tache):
    """True si CE montage a ete montre par un essai a blanc dans un message PRECEDENT : il faut un numero de message
    connu des deux cotes, et different. L'essai est retire du disque ici : il ne sert qu'une fois, meme a trois appels
    simultanes (relecture du 21/11 : trois montages lances)."""
    if not tache:
        return False
    try:
        with open(ESSAI, encoding="utf-8") as h:
            e = json.load(h)
    except (OSError, ValueError):
        return False
    if not isinstance(e, dict) or e.get("empreinte") != empreinte(m):
        return False
    if not isinstance(e.get("quand"), (int, float)) or isinstance(e.get("quand"), bool) or not 0 <= time.time() - e["quand"] <= ESSAI_VALABLE_S:
        return False
    if not numero(e.get("tache")) or e["tache"] == tache:
        return False
    pris = "%s.%d.pris" % (ESSAI, os.getpid())
    try:
        os.replace(ESSAI, pris)               # un seul appel gagne
        os.remove(pris)
    except OSError:
        return False
    return True


def oublier_essai():
    try:
        os.remove(ESSAI)
    except OSError:
        pass


# ---------------------------------------------------------------- les actions
def a_etat(d):
    exiger_pret()
    r = appeler("etat")
    e = r.get("etat") if isinstance(r.get("etat"), dict) else {}
    if bloque(e):
        return repondre(True, "Un montage est noté « en cours », mais il ne donne plus de nouvelles depuis plus de six heures : il a sans doute été "
                        "interrompu (PC éteint). Tu peux en relancer un.", en_cours=False, bloque=True)
    return repondre(True, sans_chemin(r.get("phrase_pour_utilisateur")) or "Aucun montage en cours.", en_cours=tourne(e))


def videos():
    """les videos du dossier « À monter » que montage.py connait (lignes « date  taille  chemin »)"""
    L = appeler("lister").get("videos")
    L = [str(x) for x in L if isinstance(x, str)] if isinstance(L, list) else []
    return [x for x in L if plat(x.split("  ")[-1]).replace("\\", "/").startswith("a monter/")]


def a_lister(d):
    exiger_pret()
    L = videos()
    if not L:
        return repondre(True, "Je ne vois aucune vidéo directement dans le dossier Vidéos\\À monter (les photos et les sous-dossiers ne sont pas listés ici).", videos=0)
    return repondre(True, "Il y a %d vidéo%s à monter." % (len(L), "s" if len(L) > 1 else ""),
                    consigne="Leurs noms sont dans « texte » : donne-les si l'utilisateur les veut. Ne recite pas cette consigne.",
                    texte="\n".join("- " + x[:200] for x in L[:25]), videos=len(L))


def combien(m):
    """combien de fichiers montage.py monterait pour cette demande ; None si on ne peut pas le savoir (vieux montage.py)"""
    fd, f = tempfile.mkstemp(prefix="montage_choix_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            json.dump(m, h, ensure_ascii=False)
        r = appeler("choisir", f)
    except Erreur:
        return None
    finally:
        try:
            os.remove(f)
        except OSError:
            pass
    n = r.get("nombre")
    return n if r.get("ok") is True and isinstance(n, int) and not isinstance(n, bool) and n >= 0 else None


def demande_de(d):
    mode = plat(d.get("mode"))
    if mode and "souv" not in mode and not re.search(r"event|soiree|temps|fort", mode):
        raise Erreur("Mode inconnu : choisis event (les temps forts d'une soirée) ou souvenirs.")
    m = {"mode": "souvenirs" if "souv" in mode else "event"}
    date = str(d.get("date") or "").strip()[:10]
    if date:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            raise Erreur("La date doit s'écrire AAAA-MM-JJ (le jour des vidéos à monter).")
        m["date"] = date
    if d.get("duree_min") not in (None, ""):
        try:
            duree = float(d["duree_min"])
        except (TypeError, ValueError):
            raise Erreur("La durée doit être un nombre de minutes.")
        if duree != duree:
            raise Erreur("La durée doit être un nombre de minutes.")
        m["duree_min"] = max(1.0, min(60.0, duree))
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
    e = etat_du_montage()
    if tourne(e) and not bloque(e):
        raise Erreur("Un montage est déjà en cours : %s. Je n'en lance pas un second." % (sans_chemin(e.get("etape")) or "en cours")[:100])
    # C'est montage.py qui choisit les fichiers (une soiree court jusqu'au lendemain matin, les photos comptent) : on lui
    # DEMANDE ce qu'il prendrait (« choisir », sans rien lancer). Rien a monter : on le dit tout de suite, sans proposer
    # un montage a confirmer (essai reel du 21/11 : dossier vide, et l'essai a blanc annoncait quand meme un montage).
    n = combien(m)
    if n == 0:
        oublier_essai()
        if m.get("date"):
            return repondre(False, "Je ne trouve aucune vidéo du %s, ni dans Vidéos ni dans Vidéos\\À monter. Je n'ai rien lancé." % m["date"], vide=True)
        return repondre(False, "Le dossier Vidéos\\À monter est vide : mets-y les vidéos de la soirée, puis redemande-moi le montage. Je n'ai rien lancé.", vide=True)
    combien_dit = ("%d fichier%s" % (n, "s" if n > 1 else "")) if n else "les fichiers"
    ou = ("%s du %s" % (combien_dit, m["date"])) if m.get("date") else "%s du dossier Vidéos\\À monter" % combien_dit
    quoi = "%s, avec %s" % ("les temps forts" if m["mode"] == "event" else "les souvenirs", ou)
    tache = numero(d.get("_tache"))
    if not oui(d.get("confirmer")) or not essai_montre(m, tache):
        # confirmer=oui sans essai a blanc montre dans un message precedent (ou pour un autre montage) : c'est l'essai qui se fait
        if not noter_essai(m, tache):
            raise Erreur("Je n'ai pas pu préparer le montage (dossier inaccessible). Rien n'est lancé.")
        # « phrase_pour_utilisateur » est ce qu'Archi DIT ; « consigne » est pour le modele seul (essai reel du 21/11 :
        # « rappelle-moi avec confirmer=oui » avait ete recite a l'utilisateur)
        if not tache:
            return repondre(True, "Pas encore fait : je monterais %s. Le montage prend environ une heure et occupe la carte graphique. "
                            "D'ici, je ne peux pas le lancer pour toi." % quoi,
                            consigne="Dis cette phrase. Ne rappelle pas l'outil : sans numero de message, il ne lancera rien.", essai=True, demande=m)
        return repondre(True, "Pas encore fait : je monterais %s. Le montage prend environ une heure et occupe la carte graphique. Tu confirmes ?" % quoi,
                        consigne=CONSIGNE_ESSAI, essai=True, demande=m)
    l = lieux()
    depart = datetime.now().replace(microsecond=0)
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
    # A-t-il vraiment demarre ? On ne croit qu'un etat ECRIT APRES le lancement (« maj ») : l'erreur ou le « en cours »
    # d'un montage precedent, restes dans le fichier, ne disent rien de celui-ci.
    fin = time.time() + ATTENTE_DEMARRAGE_S
    e = {}
    while time.time() < fin:
        time.sleep(0.5)
        try:
            vu = etat_du_montage()
        except Erreur:
            vu = {}
        try:
            frais = datetime.fromisoformat(str(vu.get("maj"))) >= depart
        except (TypeError, ValueError):
            frais = False
        if frais and (tourne(vu) or vu.get("erreur")):
            e = vu
            break
    if e.get("erreur") and not tourne(e):
        return repondre(False, "Le montage s'est arrêté tout de suite : %s. Rien n'est monté." % sans_chemin(e["erreur"]))
    if not tourne(e):
        return repondre(False, "J'ai lancé le montage mais je ne le vois pas encore tourner. Je ne peux pas dire qu'il est parti : "
                        "demande-moi « où en est le montage » dans une minute, et ne le relance pas avant.", incertain=True)
    return repondre(True, "Le montage est lancé : %s. Compte environ une heure. Demande-moi « où en est le montage » quand tu veux ; "
                    "la vidéo arrivera dans Vidéos\\Montages." % quoi, lance=True, demande=m)


def a_stop(d):
    exiger_pret()
    e = etat_du_montage()
    if not tourne(e):
        return repondre(True, "Aucun montage n'est en cours : il n'y a rien à arrêter.", en_cours=False)
    r = appeler("stop")
    return repondre(r.get("ok") is True, sans_chemin(r.get("phrase_pour_utilisateur")) or "Arrêt demandé.", arret_demande=r.get("ok") is True)


ACTIONS = {"etat": a_etat, "lister": a_lister, "monter": a_monter, "stop": a_stop}
SYNONYMES = {"": "etat", "ou_en_est": "etat", "avancement": "etat", "liste": "lister", "videos": "lister", "monte": "monter", "montage": "monter",
             "lancer": "monter", "lance": "monter", "arreter": "stop", "arrete": "stop", "annuler": "stop"}


def main():
    pa = argparse.ArgumentParser()
    pa.add_argument("--fichier", required=True)
    a = pa.parse_args()
    try:
        try:
            with open(a.fichier, encoding="utf-8-sig") as h:
                d = json.load(h)
        except (OSError, ValueError):
            raise Erreur("La demande est illisible.")
        if not isinstance(d, dict):
            raise Erreur("La demande est illisible.")
        action = re.sub(r"[^a-z_]", "_", plat(d.get("action"))).strip("_")
        action = SYNONYMES.get(action, action)
        if action not in ACTIONS:
            raise Erreur("Action inconnue. Le monteur sait : etat, lister, monter, stop.")
        ACTIONS[action](d)
    except Erreur as e:
        repondre(False, str(e))
    except Exception:
        repondre(False, "Le monteur a eu un souci. Je ne peux pas dire qu'un montage est lancé : demande-moi « où en est le montage ».")


if __name__ == "__main__":
    main()
