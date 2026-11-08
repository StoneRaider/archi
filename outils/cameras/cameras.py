# cameras.py - outil maison d'Archi : les cameras de l'utilisateur, en LOCAL (RTSP sur le reseau de la maison),
# sans le cloud du fabricant. Essayee sur une vraie camera en octobre 2026.
#
#   python cameras.py --fichier demande.json
#   demande.json : {"action": "liste" | "chercher" | "ajouter" | "verifier" | "photo" | "video",
#                   "camera": "entree" (nom ; la premiere par defaut), "duree_s": 10,
#                   pour ajouter : "nom", "ip", "marque" (imou, dahua, hikvision, reolink, tapo, axis, foscam, generique),
#                                  "port", "chemin" (flux RTSP si generique)}
# Repond UNE ligne JSON : {"ok": true/false, "phrase_pour_utilisateur": "...", ...}
#
# Fichiers (jamais publies, voir .gitignore) :
#   cameras.json : {"entree": {"ip": "192.168.1.20", "marque": "imou"}, ...}   (cree par « chercher » ou « ajouter »)
#   secret.json  : {"entree": {"utilisateur": "admin", "code": "..."}}         (cree par l'utilisateur lui-meme)
#   ou variables d'environnement ARCHI_CAMERA_<NOM>_CODE / ARCHI_CAMERA_<NOM>_UTILISATEUR.
# Le code n'est JAMAIS affiche : il est masque dans tous les messages.
#
# GARDE-FOUS DANS LE CODE :
#   - seulement des adresses du reseau LOCAL (privees) : jamais une camera sur Internet, jamais celle d'un tiers ;
#   - LECTURE SEULE : l'outil lit l'image, il ne change aucun reglage de la camera ;
#   - video limitee a 120 s ; fichiers ranges dans .n8n-files/camera.

import argparse
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote

DOSSIER = os.path.dirname(os.path.abspath(__file__))
SECRET = os.environ.get("ARCHI_CAMERAS_SECRET") or os.path.join(DOSSIER, "secret.json")
CAMERAS = os.environ.get("ARCHI_CAMERAS") or os.path.join(DOSSIER, "cameras.json")
BASE = os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files")
SORTIES = os.path.join(BASE, "camera")
DUREE_DEFAUT, DUREE_MAX = 10, 120

# chemins RTSP habituels par marque (flux principal) ; port 554 sauf mention
MARQUES = {
    "imou": (554, "/cam/realmonitor?channel=1&subtype=0"),
    "dahua": (554, "/cam/realmonitor?channel=1&subtype=0"),
    "amcrest": (554, "/cam/realmonitor?channel=1&subtype=0"),
    "hikvision": (554, "/Streaming/Channels/101"),
    "ezviz": (554, "/Streaming/Channels/101"),
    "annke": (554, "/Streaming/Channels/101"),
    "reolink": (554, "/h264Preview_01_main"),
    "tapo": (554, "/stream1"),
    "axis": (554, "/axis-media/media.amp"),
    "uniview": (554, "/media/video1"),
    "foscam": (88, "/videoMain"),
    "generique": (554, "/"),
}
INDICES = {"imou": "imou", "dahua": "dahua", "hikvision": "hikvision", "hik": "hikvision", "ezviz": "ezviz",
           "reolink": "reolink", "tp-link": "tapo", "tapo": "tapo", "axis": "axis", "foscam": "foscam", "uniview": "uniview"}


class Erreur(Exception):
    """Probleme a expliquer simplement a l'utilisateur."""


def repondre(ok, phrase, **extra):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(dict(ok=ok, phrase_pour_utilisateur=phrase, **extra), ensure_ascii=False))


def lire_json(chemin, defaut=None):
    try:
        with open(chemin, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return defaut


def ecrire_json(chemin, data):
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, chemin)


def nom_propre(n):
    n = re.sub(r"[^a-z0-9_]+", "_", str(n or "").strip().lower()).strip("_")
    return n[:30]


def trouver_programme(nom):
    """ffmpeg / ffprobe : dans le PATH, sinon dans le dossier WinGet."""
    chemin = shutil.which(nom)
    if chemin:
        return chemin
    racine = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages")
    if os.path.isdir(racine):
        for base, _, fichiers in os.walk(racine):
            if nom + ".exe" in fichiers:
                return os.path.join(base, nom + ".exe")
    raise Erreur(f"Je ne trouve pas le logiciel {nom} sur le PC (installe ffmpeg).")


def ip_locale_valide(ip):
    """seulement le reseau local : une adresse publique est refusee"""
    try:
        a = ipaddress.ip_address(str(ip).strip())
    except ValueError:
        raise Erreur(f"L'adresse « {str(ip)[:40]} » n'est pas une adresse de reseau valable.")
    if not a.is_private or a.is_loopback or a.is_link_local or a.is_multicast:
        raise Erreur("Je ne regarde que les cameras de ton reseau local (adresse privee, ex. 192.168.x.y), "
                     "jamais une camera sur Internet.")
    return str(a)


def mon_ip():
    """Adresse du PC sur le reseau de la maison (aucun paquet n'est envoye)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        raise Erreur("Le PC ne semble connecte a aucun reseau.")
    finally:
        s.close()


def port_ouvert(ip, port=554, delai=0.6):
    try:
        with socket.create_connection((ip, port), timeout=delai):
            return True
    except OSError:
        return False


def serveur_rtsp(ip, port=554):
    """Demande polie (OPTIONS, sans code) pour savoir quel logiciel video repond."""
    try:
        with socket.create_connection((ip, port), timeout=2) as s:
            s.sendall(f"OPTIONS rtsp://{ip}:{port}/ RTSP/1.0\r\nCSeq: 1\r\n\r\n".encode())
            texte = s.recv(2048).decode("latin-1", "replace")
        m = re.search(r"^Server:\s*(.+)$", texte, re.M | re.I)
        return m.group(1).strip() if m else ("RTSP" if texte.startswith("RTSP") else "")
    except OSError:
        return ""


def sonde_onvif(ip_locale, attente=3.0):
    """Appel standard ONVIF (WS-Discovery) : les cameras du reseau se presentent."""
    message = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
        'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" '
        'xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
        f'<e:Header><w:MessageID>uuid:{uuid.uuid4()}</w:MessageID>'
        '<w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>'
        '<w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>'
        '</e:Header><e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body></e:Envelope>'
    ).encode()
    trouves = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s.bind((ip_locale, 0))
        s.settimeout(attente)
        s.sendto(message, ("239.255.255.250", 3702))
        while True:
            try:
                donnees, (ip, _) = s.recvfrom(65535)
            except socket.timeout:
                break
            texte = donnees.decode("utf-8", "replace")
            marques = re.findall(r"onvif://www\.onvif\.org/(?:name|hardware)/([^\s<]+)", texte)
            trouves[ip] = " ".join(dict.fromkeys(marques))
    except OSError:
        pass
    finally:
        s.close()
    return trouves


def deviner_marque(texte):
    t = (texte or "").lower()
    for indice, marque in INDICES.items():
        if indice in t:
            return marque
    return "generique"


# ---------- actions ----------

def act_liste(_d):
    cams = lire_json(CAMERAS, {}) or {}
    if not cams:
        return "Aucune camera enregistree : dis « cherche les cameras » ou ajoute-en une (nom, ip, marque).", {"cameras": {}}
    return (f"{len(cams)} camera(s) : " + ", ".join(f"{n} ({c.get('marque', 'generique')})" for n, c in cams.items()) + ".",
            {"cameras": {n: {"ip": c.get("ip"), "marque": c.get("marque")} for n, c in cams.items()}})


def act_chercher(_d):
    ip_pc = mon_ip()
    reseau = ipaddress.ip_network(ip_pc + "/24", strict=False)
    onvif = {ip: nom for ip, nom in sonde_onvif(ip_pc).items() if ipaddress.ip_address(ip) in reseau}
    adresses = [str(h) for h in reseau.hosts() if str(h) != ip_pc]
    with ThreadPoolExecutor(max_workers=64) as pool:
        ouverts = [ip for ip, ok in zip(adresses, pool.map(port_ouvert, adresses)) if ok]
    trouvees = []
    for ip in sorted(set(ouverts) | set(onvif), key=ipaddress.ip_address):
        serveur = serveur_rtsp(ip) if ip in ouverts else ""
        trouvees.append({"ip": ip, "onvif": onvif.get(ip, ""), "serveur": serveur,
                         "marque": deviner_marque(onvif.get(ip, "") + " " + serveur)})
    if not trouvees:
        raise Erreur("Je n'ai trouve aucune camera sur ton WiFi. Verifie qu'elle est allumee et sur la meme box que le PC.")
    cams = lire_json(CAMERAS, {}) or {}
    connues = {c.get("ip") for c in cams.values()}
    nouvelles = 0
    for t in trouvees:
        if t["ip"] in connues:
            continue
        i = 1
        while f"camera{i}" in cams:
            i += 1
        cams[f"camera{i}"] = {"ip": t["ip"], "marque": t["marque"], "trouvee_le": datetime.now().isoformat(timespec="minutes")}
        nouvelles += 1
    ecrire_json(CAMERAS, cams)
    phrase = (f"J'ai trouve {len(trouvees)} appareil(s) video sur ton WiFi ({nouvelles} nouveau(x)). "
              "Renomme-les si tu veux (ajouter avec nom et ip), puis range le code de chacune dans secret.json.")
    return phrase, {"trouvees": trouvees}


def act_ajouter(d):
    nom = nom_propre(d.get("nom") or d.get("camera"))
    if not nom:
        raise Erreur("Donne un nom a la camera (ex. entree, jardin).")
    ip = ip_locale_valide(d.get("ip"))
    marque = str(d.get("marque") or "generique").strip().lower()
    if marque not in MARQUES:
        raise Erreur("Marque inconnue. Choix : " + ", ".join(sorted(MARQUES)) + " (generique = donne le chemin RTSP).")
    cam = {"ip": ip, "marque": marque}
    if d.get("port"):
        try:
            cam["port"] = int(d["port"])
        except (TypeError, ValueError):
            raise Erreur("Le port doit etre un nombre.")
    if d.get("chemin"):
        ch = str(d["chemin"]).strip()
        if not ch.startswith("/") or any(c in ch for c in " @\r\n"):
            raise Erreur("Le chemin RTSP doit commencer par / (sans identifiant ni espace).")
        cam["chemin"] = ch[:200]
    cams = lire_json(CAMERAS, {}) or {}
    cams[nom] = cam
    ecrire_json(CAMERAS, cams)
    return f"Camera « {nom} » enregistree ({marque}, {ip}). Range son code dans secret.json sous le nom « {nom} ».", {"camera": nom}


def choisir(d):
    cams = lire_json(CAMERAS, {}) or {}
    if not cams:
        raise Erreur("Je ne connais encore aucune camera : dis « cherche les cameras » ou ajoute-en une.")
    nom = nom_propre(d.get("camera") or d.get("nom") or "") or next(iter(cams))
    if nom not in cams:
        proches = [n for n in cams if nom in n]
        if len(proches) != 1:
            raise Erreur(f"Je ne connais pas la camera « {nom} ». Cameras : {', '.join(cams)}.")
        nom = proches[0]
    c = cams[nom]
    ip = ip_locale_valide(c.get("ip"))
    port_def, chemin_def = MARQUES.get(c.get("marque") or "generique", MARQUES["generique"])
    port = int(c.get("port") or port_def)
    if not port_ouvert(ip, port, delai=2):
        raise Erreur(f"La camera « {nom} » ne repond pas ({ip}). Elle est peut-etre eteinte ou a change d'adresse : "
                     "relance « chercher ».")
    return nom, ip, port, c.get("chemin") or chemin_def


def flux(nom, ip, port, chemin):
    """Adresse RTSP complete + ce qu'il faut masquer dans les messages."""
    secret = (lire_json(SECRET, {}) or {}).get(nom) or {}
    cle_env = "ARCHI_CAMERA_" + nom.upper()
    code = str(os.environ.get(cle_env + "_CODE") or secret.get("code") or "").strip()
    util = str(os.environ.get(cle_env + "_UTILISATEUR") or secret.get("utilisateur") or "admin").strip()
    if not code:
        raise Erreur(f"Il manque le code de la camera « {nom} » : range-le dans secret.json, "
                     f"sous la forme {{\"{nom}\": {{\"utilisateur\": \"admin\", \"code\": \"...\"}}}}.")
    url = f"rtsp://{quote(util, safe='')}:{quote(code, safe='')}@{ip}:{port}{chemin}"
    return url, [code, quote(code, safe="")]


def lancer(commande, a_masquer, delai):
    """Lance ffmpeg/ffprobe ; traduit les erreurs courantes ; ne laisse jamais filer le code."""
    try:
        r = subprocess.run(commande, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=delai)
    except subprocess.TimeoutExpired:
        raise Erreur("La camera a mis trop de temps a envoyer l'image.")
    if r.returncode != 0:
        erreur = r.stderr or ""
        for m in a_masquer:
            erreur = erreur.replace(m, "****")
        if re.search(r"401|Unauthorized", erreur, re.I):
            raise Erreur("La camera refuse le code : verifie celui de secret.json (etiquette sous la camera ou mot de passe).")
        if re.search(r"404|Not Found", erreur, re.I):
            raise Erreur("La camera ne propose pas de flux a ce chemin : change la marque ou donne le chemin RTSP.")
        if re.search(r"refused|timed out|Connection", erreur, re.I):
            raise Erreur("La camera refuse la video locale : il faut peut-etre activer RTSP dans son appli.")
        lignes = [l for l in erreur.strip().splitlines() if l.strip()]
        raise Erreur("La lecture video a echoue : " + (lignes[-1][:200] if lignes else "raison inconnue") + ".")
    return r.stdout


def act_verifier(d):
    nom, ip, port, chemin = choisir(d)
    url, masque = flux(nom, ip, port, chemin)
    sortie = lancer([trouver_programme("ffprobe"), "-v", "error", "-rtsp_transport", "tcp",
                     "-show_entries", "stream=codec_type,codec_name,width,height,avg_frame_rate", "-of", "json", url], masque, 30)
    infos = json.loads(sortie or "{}").get("streams") or []
    video = next((s for s in infos if s.get("codec_type") == "video"), None)
    if not video:
        raise Erreur("La camera repond, mais je ne recois pas d'image.")
    try:
        n, q = (video.get("avg_frame_rate") or "0/1").split("/")
        ips = round(int(n) / int(q)) if int(q) else 0
    except ValueError:
        ips = 0
    son = any(s.get("codec_type") == "audio" for s in infos)
    phrase = (f"L'image de « {nom} » arrive bien : {video.get('width')} par {video.get('height')} pixels, "
              f"{str(video.get('codec_name', '')).upper()}" + (f", {ips} images par seconde" if ips else "")
              + (", avec le son." if son else ", sans le son."))
    return phrase, {"camera": nom, "video": video, "son": son}


def nom_fichier(sous_dossier, nom, extension):
    dossier = os.path.join(SORTIES, sous_dossier)
    os.makedirs(dossier, exist_ok=True)
    return os.path.join(dossier, nom + "_" + datetime.now().strftime("%Y-%m-%d_%H%M%S") + extension)


def act_photo(d):
    nom, ip, port, chemin = choisir(d)
    url, masque = flux(nom, ip, port, chemin)
    fichier = nom_fichier("photos", nom, ".jpg")
    lancer([trouver_programme("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
            "-rtsp_transport", "tcp", "-i", url, "-frames:v", "1", "-q:v", "2", fichier], masque, 40)
    if not os.path.isfile(fichier) or os.path.getsize(fichier) == 0:
        raise Erreur("La photo n'a pas pu etre enregistree.")
    return f"Voici la photo de « {nom} ».", {"camera": nom, "fichier": fichier}


def lire_duree(d):
    brut = d.get("duree_s", DUREE_DEFAUT)
    try:
        duree = int(float(brut if brut not in (None, "") else DUREE_DEFAUT))
    except (TypeError, ValueError):
        raise Erreur(f"La duree « {brut} » n'est pas un nombre de secondes.")
    if not 1 <= duree <= DUREE_MAX:
        raise Erreur(f"La duree doit etre entre 1 et {DUREE_MAX} secondes (demande : {duree}).")
    return duree


def act_video(d):
    duree = lire_duree(d)  # verifiee AVANT de contacter la camera
    nom, ip, port, chemin = choisir(d)
    url, masque = flux(nom, ip, port, chemin)
    fichier = nom_fichier("videos", nom, ".mp4")
    lancer([trouver_programme("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
            "-rtsp_transport", "tcp", "-i", url, "-t", str(duree),
            "-map", "0:v:0", "-map", "0:a?", "-c:v", "copy", "-c:a", "aac", "-movflags", "+faststart", fichier],
           masque, duree + 60)
    if not os.path.isfile(fichier) or os.path.getsize(fichier) == 0:
        raise Erreur("La video n'a pas pu etre enregistree.")
    return f"J'ai enregistre {duree} secondes de « {nom} ».", {"camera": nom, "fichier": fichier, "duree_s": duree}


ACTIONS = {"liste": act_liste, "chercher": act_chercher, "ajouter": act_ajouter,
           "verifier": act_verifier, "photo": act_photo, "video": act_video}
ALIAS = {"lister": "liste", "cameras": "liste", "trouver": "chercher", "scanner": "chercher", "enregistrer": "ajouter",
         "image": "photo", "montrer": "photo", "voir": "photo", "filmer": "video", "test": "verifier"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fichier", required=True)
    args = p.parse_args()
    d = lire_json(args.fichier)
    if not isinstance(d, dict):
        return repondre(False, "La demande est illisible.")
    if isinstance(d.get("parametres"), dict):
        d = {**d, **d["parametres"]}
    action = str(d.get("action") or "liste").strip().lower()
    action = ALIAS.get(action, action)
    if action not in ACTIONS:
        return repondre(False, "Commande inconnue. Choix : " + ", ".join(ACTIONS) + ".")
    try:
        phrase, extra = ACTIONS[action](d)
        repondre(True, phrase, action=action, **extra)
    except Erreur as e:
        repondre(False, str(e), action=action)
    except Exception as e:  # imprevu : message court, sans detail technique sensible
        repondre(False, f"Probleme imprevu avec la camera ({type(e).__name__}).", action=action)


if __name__ == "__main__":
    main()
