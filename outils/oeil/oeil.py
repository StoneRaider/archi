# -*- coding: utf-8 -*-
"""oeil.py - l'oeil d'Archi : ce qui se passe en direct autour d'un LIEU (avions, seismes), avec le globe
gods-eye-view en plus (http://127.0.0.1:4173 sur le PC ; https://oeil.exemple.net depuis le telephone,
par la porte de l'oeil). Donnees publiques, sans cle.

Usage : python oeil.py --fichier demande.json   (ou le JSON en argument)
  {"action": "avions" | "seismes" | "globe" | "tout", "lieu": "Lyon" ou "45.76,4.84", "rayon_km": 50}
  {"action": "montrer", "cible": "avion" | "lieu" | "camera", "lieu": "Lyon" | "ici" | "detroit d'Ormuz"}
     -> ouvre l'OEIL dans l'appli telephone : l'avion le plus proche (suivi en direct), un lieu, ou la camera
        publique la plus proche. "ici" / vide = la position de J (memoire/position.json, envoyee par l'appli).
        Ecrit pc/telephone/oeil/<jeton>.json (ce que l'appli doit afficher) et renvoie oeil_jeton.
Repond UNE ligne JSON {"ok", "phrase_pour_utilisateur", ...}.
Les regles d'usage (vie privee) sont dans le message systeme d'Archi, pas ici.
v2 du 02/11/2026 au soir : action montrer, billets d'entree pour la porte, catalogue des cameras.
"""
import base64
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

UA = {"User-Agent": "Archi-oeil/2.1 (assistant personnel, usage prive)"}
GLOBE = "http://127.0.0.1:4173"
ICI = os.path.dirname(os.path.abspath(__file__))
BASE = os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files")
BOITE = os.environ.get("ARCHI_BOITE_OUTILS") or (os.path.join(os.environ["ARCHI_DEPOT"], "boite_outils")
                                              if os.environ.get("ARCHI_DEPOT") else os.path.join(BASE, "pc", "boite_outils"))
CACHE = os.path.join(ICI, "cache_lieux.json")
CLE_PORTE = os.path.join(ICI, "cle_oeil.txt")                      # partagee avec la porte (Docker)
REGLAGES_PORTE = os.path.join(ICI, "porte.json")                   # {"url_publique": "https://oeil.exemple.net"}
POSITION = os.path.join(BASE, "memoire", "position.json")
CATALOGUE = os.environ.get("ARCHI_CCTV_CATALOGUE") or os.path.join(BOITE, "gods-eye-view", "config", "cctv_sources.json")
SORTIE = os.path.join(BASE, "pc", "telephone", "oeil")
BILLET_S = 30 * 60          # un lien d'entree vaut 30 minutes
PORTE_ABSENTE = []          # rempli si la porte n'est pas configuree (pas d'url publique ou pas de cle)
GARDER_JETONS_S = 2 * 86400


def sortir(d):
    print(json.dumps(d, ensure_ascii=False))
    sys.exit(0)


def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# ---------------------------------------------------------------- lieux
def geocoder(lieu):
    """Ville / site -> (lat, lon, nom). Coordonnees acceptees directement. Cache local."""
    d = geocoder_detail(lieu)
    return d["lat"], d["lon"], d["nom"]


def geocoder_detail(lieu):
    """Comme geocoder, avec le cadre du lieu (bbox [sud, nord, ouest, est]) pour regler l'altitude du globe."""
    m = re.match(r"^\s*(-?\d+(?:[.,]\d+)?)\s*[,; ]\s*(-?\d+(?:[.,]\d+)?)\s*$", lieu)
    if m:
        return {"lat": float(m.group(1).replace(",", ".")), "lon": float(m.group(2).replace(",", ".")), "nom": lieu, "bbox": None}
    cache = {}
    try:
        cache = json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        pass
    k = lieu.strip().lower()
    if k in cache and len(cache[k]) >= 4:
        lat, lon, nom, bbox = cache[k][:4]
        return {"lat": lat, "lon": lon, "nom": nom, "bbox": bbox}
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": lieu, "format": "json", "limit": 1, "accept-language": "fr"})
    r = get(url)
    if not r:
        raise ValueError(f"lieu introuvable : {lieu}")
    lat, lon = float(r[0]["lat"]), float(r[0]["lon"])
    nom = r[0].get("display_name", lieu).split(",")[0]
    bbox = None
    try:
        bbox = [float(x) for x in r[0].get("boundingbox") or []] or None
    except Exception:
        bbox = None
    cache[k] = [lat, lon, nom, bbox]
    try:
        json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass
    time.sleep(1.1)   # politesse Nominatim : 1 demande par seconde
    return {"lat": lat, "lon": lon, "nom": nom, "bbox": bbox}


def position_utilisateur():
    """La derniere position connue de J (envoyee par l'appli a chaque message, ou partagee sur Telegram)."""
    with open(POSITION, encoding="utf-8") as f:
        p = json.load(f)
    age_h = None
    try:
        age_h = (datetime.now() - datetime.fromisoformat(p["heure"])).total_seconds() / 3600
    except Exception:
        pass
    return {"lat": float(p["lat"]), "lon": float(p["lon"]), "nom": p.get("lieu") or "ta position", "bbox": None,
            "age_h": age_h, "position": True}


def est_ici(lieu):
    l = lieu.strip().lower()
    return l in ("", "ici", "moi", "la", "là", "chez moi", "ma position", "autour de moi", "pres de moi", "près de moi",
                 "ou je suis", "où je suis", "de moi", "proche de moi", "position")


def reference(lieu):
    """Le point de depart : la position de J si « ici », sinon le lieu nomme."""
    if est_ici(lieu):
        try:
            return position_utilisateur()
        except Exception:
            raise ValueError("position inconnue")
    d = geocoder_detail(lieu)
    d["position"] = False
    return d


def distance_km(a, b, c, d):
    p = math.pi / 180
    h = 0.5 - math.cos((c - a) * p) / 2 + math.cos(a * p) * math.cos(c * p) * (1 - math.cos((d - b) * p)) / 2
    return 12742 * math.asin(math.sqrt(h))


def cap_vers(lat1, lon1, lat2, lon2):
    """Cap (0-360) de 1 vers 2."""
    p = math.pi / 180
    y = math.sin((lon2 - lon1) * p) * math.cos(lat2 * p)
    x = math.cos(lat1 * p) * math.sin(lat2 * p) - math.sin(lat1 * p) * math.cos(lat2 * p) * math.cos((lon2 - lon1) * p)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def altitude_pour(bbox, defaut=2500):
    """Altitude de camera (m) pour voir tout le cadre d'un lieu : ~1,1 x sa diagonale."""
    if not bbox or len(bbox) < 4:
        return defaut
    s, n, w, e = bbox[:4]
    diag = distance_km(s, w, n, e)
    return int(max(1200, min(3_000_000, diag * 1000 * 1.1)))


# ---------------------------------------------------------------- avions / seismes
def avions(lat, lon, rayon):
    """OpenSky, sans compte (limite ~ 400 requetes/jour, 10 s entre deux)."""
    dlat = rayon / 111.0
    dlon = rayon / (111.0 * max(0.2, math.cos(math.radians(lat))))
    url = ("https://opensky-network.org/api/states/all?" +
           urllib.parse.urlencode({"lamin": lat - dlat, "lamax": lat + dlat, "lomin": lon - dlon, "lomax": lon + dlon}))
    d = get(url, 30)
    out = []
    for s in d.get("states") or []:
        if s[5] is None or s[6] is None:
            continue
        dist = distance_km(lat, lon, s[6], s[5])
        if dist > rayon:
            continue
        out.append({"icao24": str(s[0] or "").lower(), "indicatif": (s[1] or "").strip() or "?", "pays": s[2],
                    "altitude_m": round(s[7] or 0), "vitesse_kmh": round((s[9] or 0) * 3.6), "cap": round(s[10] or 0),
                    "au_sol": bool(s[8]), "distance_km": round(dist, 1), "lat": round(s[6], 4), "lon": round(s[5], 4)})
    out.sort(key=lambda x: x["distance_km"])
    return out


def seismes(lat, lon, rayon, jours=7):
    """EMSC (centre europeen, voit aussi les petits seismes des Alpes) ; USGS en secours (gros seismes du monde)."""
    try:
        return seismes_emsc(lat, lon, rayon, jours)
    except Exception:
        return seismes_usgs(lat, lon, rayon, jours)


def seismes_emsc(lat, lon, rayon, jours=7):
    url = ("https://www.seismicportal.eu/fdsnws/event/1/query?" +
           urllib.parse.urlencode({"format": "json", "lat": lat, "lon": lon, "maxradius": round(rayon / 111.0, 3),
                                   "start": time.strftime("%Y-%m-%d", time.gmtime(time.time() - jours * 86400)),
                                   "orderby": "time", "limit": 20}))
    d = get(url)
    out = []
    for f in d.get("features", []):
        p = f.get("properties", {})
        try:
            quand = datetime.fromisoformat(str(p.get("time", "")).replace("Z", "+00:00")).astimezone().strftime("%d/%m %H:%M")
        except Exception:
            quand = str(p.get("time", ""))[:16]
        out.append({"magnitude": p.get("mag"), "lieu": str(p.get("flynn_region") or "").title(), "quand": quand,
                    "profondeur_km": round(p.get("depth") or 0, 1),
                    "distance_km": round(distance_km(lat, lon, p.get("lat"), p.get("lon")), 1)})
    return out


def seismes_usgs(lat, lon, rayon, jours=7):
    url = ("https://earthquake.usgs.gov/fdsnws/event/1/query?" +
           urllib.parse.urlencode({"format": "geojson", "latitude": lat, "longitude": lon, "maxradiuskm": rayon,
                                   "starttime": time.strftime("%Y-%m-%d", time.gmtime(time.time() - jours * 86400)),
                                   "orderby": "time", "limit": 20}))
    d = get(url)
    out = []
    for f in d.get("features", []):
        p, g = f["properties"], f["geometry"]["coordinates"]
        out.append({"magnitude": p.get("mag"), "lieu": p.get("place"),
                    "quand": time.strftime("%d/%m %H:%M", time.localtime((p.get("time") or 0) / 1000)),
                    "profondeur_km": round(g[2] or 0), "distance_km": round(distance_km(lat, lon, g[1], g[0]), 1)})
    return out


# ---------------------------------------------------------------- cameras publiques
def catalogue_cameras():
    chemin = CATALOGUE
    if not os.path.exists(chemin):
        dossier = os.path.dirname(CATALOGUE)
        autres = sorted(x for x in os.listdir(dossier) if x.startswith("cctv_sources.") and x.endswith(".json")) if os.path.isdir(dossier) else []
        if not autres:
            raise FileNotFoundError("catalogue des cameras introuvable")
        chemin = os.path.join(dossier, autres[0])
    d = json.load(open(chemin, encoding="utf-8"))
    liste = d if isinstance(d, list) else (d.get("cameras") or d.get("sources") or [])
    return [c for c in liste if isinstance(c, dict) and c.get("id") and c.get("lat") is not None and c.get("lon") is not None]


def cameras_proches(lat, lon, n=3):
    out = []
    for c in catalogue_cameras():
        try:
            dist = distance_km(lat, lon, float(c["lat"]), float(c["lon"]))
        except Exception:
            continue
        out.append({"id": c["id"], "nom": c.get("name") or c["id"], "ville": c.get("city") or "", "source": c.get("provider") or "",
                    "type": c.get("feedType") or "image", "lat": float(c["lat"]), "lon": float(c["lon"]),
                    "cap": c.get("headingDeg"), "distance_km": round(dist, 1)})
    out.sort(key=lambda x: x["distance_km"])
    return out[:n]


# ---------------------------------------------------------------- l'oeil (ce que l'appli affiche)
def lire_cle():
    if os.environ.get("ARCHI_CLE_OEIL"):   # le .env d'abord
        return os.environ["ARCHI_CLE_OEIL"].strip()
    try:
        return open(CLE_PORTE, encoding="utf-8-sig").read().strip()   # utf-8-sig : ignore un eventuel BOM Windows
    except Exception:
        return ""


def reglages_porte():
    if os.environ.get("ARCHI_OEIL_URL_PUBLIQUE"):   # le .env d'abord
        return {"url_publique": os.environ["ARCHI_OEIL_URL_PUBLIQUE"].strip()}
    try:
        return json.load(open(REGLAGES_PORTE, encoding="utf-8"))
    except Exception:
        return {}


def billet(cle, jeton):
    """Billet d'entree a duree limitee : jeton.expiration.signature (HMAC de la cle, jamais la cle elle-meme)."""
    exp = int(time.time()) + BILLET_S
    sig = base64.urlsafe_b64encode(hmac.new(cle.encode("utf-8"), f"{jeton}.{exp}".encode("utf-8"), hashlib.sha256).digest()).decode("ascii").rstrip("=")[:32]
    return f"{jeton}.{exp}.{sig}"


def construire_oeil(titre, sous_titre, vue, actions, cible, genre):
    """Ecrit le fichier que le noeud Voix joint a la reponse du telephone ; renvoie l'objet oeil."""
    jeton = secrets.token_hex(6)
    demande = {"id": jeton, "vue": vue, "actions": actions}
    # la demande voyage dans la requete (?archi=...), pas dans le hash : le globe reecrit le hash au demarrage
    archi = "archi=" + urllib.parse.quote(json.dumps(demande, ensure_ascii=False, separators=(",", ":")), safe="")
    url_pc = f"{GLOBE}/?{archi}"
    url = ""
    base = str(reglages_porte().get("url_publique") or "").rstrip("/")
    cle = lire_cle()
    if base and cle:
        url = f"{base}/entree?b={urllib.parse.quote(billet(cle, jeton), safe='')}&vers={urllib.parse.quote('/?embed=1&' + archi, safe='')}"
    else:
        PORTE_ABSENTE.append("ARCHI_OEIL_URL_PUBLIQUE dans le .env" if not base else "ARCHI_CLE_OEIL dans le .env")
    oeil = {"jeton": jeton, "heure": datetime.now().isoformat(timespec="seconds"), "genre": genre, "titre": titre,
            "sous_titre": sous_titre, "url": url, "url_pc": url_pc, "vue": vue, "actions": actions, "cible": cible}
    try:
        os.makedirs(SORTIE, exist_ok=True)
        maintenant = time.time()
        for f in os.listdir(SORTIE):   # on ne garde pas les vieux jetons
            p = os.path.join(SORTIE, f)
            try:
                if f.endswith(".json") and maintenant - os.path.getmtime(p) > GARDER_JETONS_S:
                    os.remove(p)
            except Exception:
                pass
        with open(os.path.join(SORTIE, jeton + ".json"), "w", encoding="utf-8") as f:
            json.dump(oeil, f, ensure_ascii=False)
    except Exception as e:
        oeil["erreur_fichier"] = str(e)[:120]
    return oeil


def finir(res):
    """Derniere retouche avant de repondre : si la porte de l'oeil n'est pas configuree, on le dit au lieu de
    promettre un ecran qui ne viendra pas (l'appli ignore un oeil sans url)."""
    if PORTE_ABSENTE and "phrase_pour_utilisateur" in res:
        res["remarque_oeil"] = "porte de l'oeil non configuree (" + ", ".join(PORTE_ABSENTE) + ") : l'appli n'ouvrira pas l'ecran"
        p = res["phrase_pour_utilisateur"]
        for bout in (" Je te le montre dans l'œil.", " Je te la montre dans l'œil."):
            p = p.replace(bout, "")
        p = p.replace(" ; j'ouvre quand même l'œil sur le ciel.", ".").replace(" dans l'œil.", ".")
        res["phrase_pour_utilisateur"] = p + " L'œil du téléphone n'est pas encore branché : regarde sur le PC."
    sortir(res)


def normaliser_cible(demande):
    c = str(demande.get("cible") or demande.get("quoi") or demande.get("type") or "").strip().lower()
    c = c.replace("é", "e").replace("è", "e").replace("â", "a")
    if re.search(r"avion|vol\b|aerien|aircraft|plane|appareil", c):
        return "avion"
    if re.search(r"cable|internet", c):
        return "cables"
    if re.search(r"bateau|navire|cargo|ferry|vessel|ship|voilier|tanker|petrolier|marin", c):
        return "bateau"
    if re.search(r"feu|incendie|fire|brule|flamme", c):
        return "feux"
    if re.search(r"rue|street|photo de rue|mapillary|trottoir|facade", c):
        return "rue"
    if re.search(r"cam|cctv|webcam|video|surveillance", c):
        return "camera"
    if c in ("", "lieu", "endroit", "zone", "ville", "pays", "carte", "globe", "place"):
        return "lieu"
    return "lieu"


def globe_json(chemin, timeout=40):
    """Les donnees que le globe a deja (bateaux AIS, feux FIRMS) : il tourne sur ce PC."""
    req = urllib.request.Request(GLOBE + chemin, headers={"User-Agent": "Archi-oeil/2.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def bateaux_proches(lat, lon, rayon):
    d = globe_json("/api/vessels/status?maxRows=50000", 30)
    out = []
    for b in d.get("rows") or []:
        try:
            bl, bo = float(b["lat"]), float(b["lon"])
        except Exception:
            continue
        dist = distance_km(lat, lon, bl, bo)
        if dist <= rayon:
            out.append({"mmsi": str(b.get("mmsi") or ""), "nom": (b.get("name") or "").strip() or "sans nom", "lat": round(bl, 4),
                        "lon": round(bo, 4), "vitesse_noeuds": b.get("speed"), "cap": b.get("course"),
                        "destination": (b.get("destination") or "").strip(), "type": b.get("type") or "", "distance_km": round(dist, 1)})
    out.sort(key=lambda x: x["distance_km"])
    return out


def feux_proches(lat, lon, rayon):
    d = globe_json("/api/firms", 90)
    out = []
    for f in d.get("fires") or []:
        try:
            fl, fo = float(f["lat"]), float(f["lon"])
        except Exception:
            continue
        if abs(fl - lat) > rayon / 100 or abs(fo - lon) > rayon / 60:
            continue
        dist = distance_km(lat, lon, fl, fo)
        if dist <= rayon:
            out.append({"lat": fl, "lon": fo, "puissance_mw": f.get("frp"), "date": f.get("acqDate"), "heure_utc": f.get("acqTime"),
                        "distance_km": round(dist, 1)})
    out.sort(key=lambda x: x["distance_km"])
    return out


def montrer(demande):
    cible = normaliser_cible(demande)
    lieu = str(demande.get("lieu") or demande.get("ville") or demande.get("autour") or "").strip()
    try:
        rayon = float(str(demande.get("rayon_km") or 80).replace(",", "."))
    except Exception:
        rayon = 80
    rayon = max(5, min(300, rayon))
    try:
        ref = reference(lieu)
    except Exception as e:
        if "position" in str(e):
            sortir({"ok": False, "phrase_pour_utilisateur": "Je ne connais pas ta position en ce moment BOSS : dis-moi autour de quel lieu regarder, ou renvoie-moi un message depuis l'appli pour qu'elle me donne ta position."})
        sortir({"ok": False, "phrase_pour_utilisateur": f"Je ne trouve pas ce lieu sur la carte : {lieu}.", "erreur": str(e)[:120]})
    lat, lon, nom = ref["lat"], ref["lon"], ref["nom"]
    d_ou = "de toi" if ref.get("position") else f"de {nom}"
    res = {"ok": True, "action": "montrer", "cible": cible, "lieu": nom, "lat": round(lat, 4), "lon": round(lon, 4)}
    if ref.get("position") and ref.get("age_h") is not None and ref["age_h"] > 6:
        res["remarque"] = f"ta position date d'il y a {ref['age_h']:.0f} h"

    if cible == "avion":
        try:
            av = avions(lat, lon, rayon)
        except Exception as e:
            sortir({"ok": False, "phrase_pour_utilisateur": "les avions ne répondent pas pour l'instant (OpenSky limite les demandes, réessaie dans une minute)", "erreur": str(e)[:150]})
        vol = [a for a in av if not a["au_sol"]]
        res["avions"] = av[:15]
        if not vol:
            vue = {"camera": {"lat": lat, "lon": lon, "altitude_m": int(rayon * 2500), "pitch_deg": -70}, "layers": ["flights"],
                   "annotations": [{"type": "pin", "latitude": lat, "longitude": lon, "label": nom, "color": "cyan"}]}
            oeil = construire_oeil(f"Ciel au-dessus {d_ou}", f"Aucun avion en vol à moins de {rayon:.0f} km", vue, [], None, "avion")
            res.update({"oeil_jeton": oeil["jeton"], "lien_telephone": oeil["url"], "lien_pc": oeil["url_pc"],
                        "phrase_pour_utilisateur": f"Aucun avion en vol à moins de {rayon:.0f} km {d_ou} pour l'instant ; j'ouvre quand même l'œil sur le ciel."})
            finir(res)
        a = vol[0]
        titre = f"Avion le plus proche {d_ou}"
        sous = f"{a['indicatif']} · {a['distance_km']} km · {a['altitude_m']} m · {a['vitesse_kmh']} km/h" + (f" · {a['pays']}" if a.get("pays") else "")
        vue = {"camera": {"lat": a["lat"], "lon": a["lon"], "altitude_m": 14000, "pitch_deg": -40,
                          "heading_deg": int(cap_vers(lat, lon, a["lat"], a["lon"]))},
               "layers": ["flights"], "follow": {"kind": "aircraft", "id": a["icao24"]}}
        oeil = construire_oeil(titre, sous, vue, [], a, "avion")
        res.update({"oeil_jeton": oeil["jeton"], "lien_telephone": oeil["url"], "lien_pc": oeil["url_pc"], "avion": a,
                    "phrase_pour_utilisateur": f"L'avion le plus proche {d_ou} : {a['indicatif']}, à {a['distance_km']} km, "
                                          f"{a['altitude_m']} m d'altitude, {a['vitesse_kmh']} km/h"
                                          + (f", immatriculé en {a['pays']}" if a.get("pays") else "") + ". Je te le montre dans l'œil."})
        finir(res)

    if cible == "bateau":
        r_b = max(rayon, 100)
        try:
            bat = bateaux_proches(lat, lon, r_b)
        except Exception as e:
            sortir({"ok": False, "phrase_pour_utilisateur": "Les bateaux ne répondent pas (le globe est-il lancé ?).", "erreur": str(e)[:150]})
        res["bateaux"] = bat[:10]
        if not bat:
            vue = {"camera": {"lat": lat, "lon": lon, "altitude_m": int(r_b * 2000), "pitch_deg": -70}, "layers": ["ais-live-vessels"],
                   "annotations": [{"type": "pin", "latitude": lat, "longitude": lon, "label": nom[:60], "color": "cyan"}]}
            oeil = construire_oeil(f"Bateaux autour {d_ou}", f"Aucun bateau reçu à moins de {r_b:.0f} km", vue, [], None, "bateau")
            res.update({"oeil_jeton": oeil["jeton"], "lien_telephone": oeil["url"], "lien_pc": oeil["url_pc"],
                        "phrase_pour_utilisateur": f"Aucun bateau reçu à moins de {r_b:.0f} km {d_ou} pour l'instant (les bateaux arrivent au fil des minutes) ; j'ouvre quand même l'œil sur la zone."})
            finir(res)
        b = bat[0]
        sous = f"{b['nom']} · {b['distance_km']} km" + (f" · {b['vitesse_noeuds']} nœuds" if b.get("vitesse_noeuds") is not None else "") + (f" · vers {b['destination']}" if b.get("destination") else "")
        vue = {"camera": {"lat": b["lat"], "lon": b["lon"], "altitude_m": 2500, "pitch_deg": -45}, "layers": ["ais-live-vessels"]}
        actions = [{"name": "track_entity", "args": {"query": b["mmsi"] or b["nom"], "layerId": "ais-live-vessels"}, "essais": 20}]
        oeil = construire_oeil(f"Bateau le plus proche {d_ou}", sous, vue, actions, b, "bateau")
        res.update({"oeil_jeton": oeil["jeton"], "lien_telephone": oeil["url"], "lien_pc": oeil["url_pc"], "bateau": b,
                    "phrase_pour_utilisateur": f"Le bateau le plus proche {d_ou} : {b['nom']}, à {b['distance_km']} km"
                                          + (f", en route vers {b['destination']}" if b.get("destination") else "") + f". {len(bat)} bateau{'x' if len(bat) > 1 else ''} dans un rayon de {r_b:.0f} km. Je te le montre dans l'œil."})
        finir(res)

    if cible == "feux":
        r_f = max(rayon, 150)
        bb = ref.get("bbox")
        if bb and len(bb) >= 4:   # un pays ou une region : tout son cadre
            r_f = min(1500, max(r_f, distance_km(bb[0], bb[2], bb[1], bb[3]) / 2))
        try:
            feux = feux_proches(lat, lon, r_f)
        except Exception as e:
            sortir({"ok": False, "phrase_pour_utilisateur": "Les feux ne répondent pas (le globe est-il lancé ?).", "erreur": str(e)[:150]})
        res["feux"] = feux[:10]
        if feux:
            f = feux[0]
            vue = {"camera": {"lat": f["lat"], "lon": f["lon"], "altitude_m": 25000, "pitch_deg": -60}, "layers": ["local-firms"]}
            phrase = (f"{len(feux)} point{'s' if len(feux) > 1 else ''} de feu vu{'s' if len(feux) > 1 else ''} par satellite ces dernières 24 h à moins de {r_f:.0f} km {d_ou} ; "
                      f"le plus proche à {f['distance_km']} km. Je te le montre dans l'œil.")
            sous = f"{len(feux)} détection{'s' if len(feux) > 1 else ''} · la plus proche à {f['distance_km']} km"
        else:
            vue = {"camera": {"lat": lat, "lon": lon, "altitude_m": int(r_f * 2500), "pitch_deg": -75}, "layers": ["local-firms"]}
            phrase = f"Aucun feu vu par satellite ces dernières 24 h à moins de {r_f:.0f} km {d_ou}. J'ouvre l'œil sur la zone."
            sous = f"Aucune détection à moins de {r_f:.0f} km"
        oeil = construire_oeil(f"Feux · {nom}" if not ref.get("position") else "Feux autour de toi", sous, vue, [], feux[0] if feux else None, "feux")
        res.update({"oeil_jeton": oeil["jeton"], "lien_telephone": oeil["url"], "lien_pc": oeil["url_pc"], "phrase_pour_utilisateur": phrase})
        finir(res)

    if cible == "cables":
        alt = max(altitude_pour(ref.get("bbox"), 1_500_000), 800_000)
        vue = {"camera": {"lat": lat, "lon": lon, "altitude_m": alt, "pitch_deg": -80}, "layers": ["telegeography-submarine-cables"]}
        oeil = construire_oeil(f"Câbles sous-marins · {nom if not ref.get('position') else 'autour de toi'}", "Carte TeleGeography", vue, [], None, "cables")
        res.update({"oeil_jeton": oeil["jeton"], "lien_telephone": oeil["url"], "lien_pc": oeil["url_pc"],
                    "phrase_pour_utilisateur": f"Voilà les câbles sous-marins {('autour de ' + nom) if not ref.get('position') else 'autour de toi'} dans l'œil."})
        finir(res)

    if cible == "rue":
        vue = {"camera": {"lat": lat, "lon": lon, "altitude_m": 350, "pitch_deg": -35}, "layers": ["street-level"],
               "annotations": [{"type": "pin", "latitude": lat, "longitude": lon, "label": nom[:60], "color": "cyan"}]}
        oeil = construire_oeil(f"Photos de rue · {nom if not ref.get('position') else 'autour de toi'}", "Mapillary : touche un point vert pour voir la photo", vue, [], None, "rue")
        res.update({"oeil_jeton": oeil["jeton"], "lien_telephone": oeil["url"], "lien_pc": oeil["url_pc"],
                    "phrase_pour_utilisateur": f"J'ouvre les photos de rue {('à ' + nom) if not ref.get('position') else 'autour de toi'} : touche un point vert pour voir la photo."})
        finir(res)

    if cible == "camera":
        try:
            cams = cameras_proches(lat, lon, 3)
        except Exception as e:
            sortir({"ok": False, "phrase_pour_utilisateur": "Je n'ai pas le catalogue des caméras publiques sous la main.", "erreur": str(e)[:150]})
        if not cams:
            sortir({"ok": False, "phrase_pour_utilisateur": "Aucune caméra publique dans mon catalogue."})
        c = cams[0]
        res["cameras"] = cams
        titre = f"Caméra la plus proche {d_ou}"
        sous = f"{c['nom']} · {c['distance_km']} km" + (f" · {c['source']}" if c.get("source") else "")
        vue = {"camera": {"lat": c["lat"], "lon": c["lon"], "altitude_m": 900, "pitch_deg": -45,
                          "heading_deg": int(c["cap"]) if isinstance(c.get("cap"), (int, float)) else 0},
               "layers": ["cctv"]}
        actions = [{"name": "control_cctv", "args": {"action": "select", "cameraQuery": c["id"]}, "essais": 25}]
        oeil = construire_oeil(titre, sous, vue, actions, c, "camera")
        loin = "" if c["distance_km"] < 1 else f" à {c['distance_km']} km"
        res.update({"oeil_jeton": oeil["jeton"], "lien_telephone": oeil["url"], "lien_pc": oeil["url_pc"], "camera": c,
                    "phrase_pour_utilisateur": f"La caméra publique la plus proche {d_ou} : {c['nom']}{loin}"
                                          + (f" ({c['source']})" if c.get("source") else "") + ". Je te la montre dans l'œil."})
        finir(res)

    # un lieu
    alt = altitude_pour(ref.get("bbox"), 2500 if ref.get("position") else 6000)
    pitch = -60 if alt > 100_000 else -45
    vue = {"camera": {"lat": lat, "lon": lon, "altitude_m": alt, "pitch_deg": pitch}, "layers": [],
           "annotations": [{"type": "pin", "latitude": lat, "longitude": lon, "label": nom[:60], "color": "cyan"}]}
    titre = nom if not ref.get("position") else "Autour de toi"
    sous = f"{lat:.4f}, {lon:.4f}" + (f" · vue à {alt / 1000:.0f} km" if alt >= 2000 else "")
    oeil = construire_oeil(titre, sous, vue, [], None, "lieu")
    res.update({"oeil_jeton": oeil["jeton"], "lien_telephone": oeil["url"], "lien_pc": oeil["url_pc"],
                "phrase_pour_utilisateur": f"Voilà {nom} dans l'œil." if not ref.get("position") else "Voilà ce qu'il y a autour de toi dans l'œil."})
    finir(res)


# ---------------------------------------------------------------- programme
def main():
    args = sys.argv[1:]
    demande = {}
    if "--fichier" in args:
        demande = json.load(open(args[args.index("--fichier") + 1], encoding="utf-8"))
    elif args:
        try:
            demande = json.loads(args[0])
        except Exception:
            demande = {"action": "tout", "lieu": " ".join(args)}
    if isinstance(demande.get("parametres"), dict):
        demande = {**demande, **demande["parametres"]}
    action = str(demande.get("action") or "tout").strip().lower()
    if action in ("montrer", "montre", "voir", "afficher", "ouvrir", "oeil", "œil", "show"):
        montrer(demande)
    lieu = str(demande.get("lieu") or demande.get("ville") or "").strip()
    try:
        rayon = float(str(demande.get("rayon_km") or 50).replace(",", "."))
    except Exception:
        rayon = 50
    rayon = max(1, min(300, rayon))
    if not lieu:
        sortir({"ok": False, "phrase_pour_utilisateur": "Dis-moi autour de quel lieu regarder BOSS : une ville, un aéroport, un site."})
    try:
        lat, lon, nom = geocoder(lieu)
    except Exception as e:
        sortir({"ok": False, "phrase_pour_utilisateur": f"Je ne trouve pas ce lieu sur la carte : {lieu}.", "erreur": str(e)[:120]})
    res = {"ok": True, "lieu": nom, "lat": lat, "lon": lon, "rayon_km": rayon, "globe": f"{GLOBE}/#lat={lat}&lon={lon}"}
    phrases = []
    if action in ("avions", "tout"):
        try:
            av = avions(lat, lon, rayon)
            res["avions"] = av[:25]
            vol = [a for a in av if not a["au_sol"]]
            phrases.append(f"{len(vol)} avion{'s' if len(vol) > 1 else ''} en vol dans un rayon de {rayon:.0f} km autour de {nom}"
                           + (f", le plus proche : {vol[0]['indicatif']} à {vol[0]['distance_km']} km, {vol[0]['altitude_m']} m d'altitude" if vol else ""))
        except Exception as e:
            res["avions_erreur"] = str(e)[:150]
            phrases.append("les avions ne répondent pas pour l'instant (OpenSky limite les demandes, réessaie dans une minute)")
    if action in ("seismes", "séismes", "tout"):
        try:
            se = seismes(lat, lon, max(rayon, 100))
            res["seismes"] = se
            phrases.append(f"{len(se)} séisme{'s' if len(se) > 1 else ''} ces 7 derniers jours à moins de {max(rayon, 100):.0f} km"
                           + (f", le dernier : magnitude {se[0]['magnitude']} à {se[0]['distance_km']} km ({se[0]['lieu']}) le {se[0]['quand']}" if se else ""))
        except Exception as e:
            res["seismes_erreur"] = str(e)[:150]
    if action == "globe":
        phrases.append(f"le globe est centré sur {nom}")
    res["phrase_pour_utilisateur"] = (" ; ".join(phrases) or f"Rien de particulier autour de {nom}") + "."
    sortir(res)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        sortir({"ok": False, "phrase_pour_utilisateur": "L'œil a eu un problème, je n'ai pas pu regarder.", "erreur": repr(e)[:200]})
