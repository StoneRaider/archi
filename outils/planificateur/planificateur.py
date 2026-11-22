# planificateur.py - outil maison d'Archi : faire quelque chose PLUS TARD, EN BOUCLE ou A L'ARRIVEE SUR UN LIEU (03/11/2026).
#   python planificateur.py --fichier demande.json     (appele par outils_maison)
#     ajouter  : texte (le rappel), et UN declencheur :
#                  a = "11h" | "11:30" | "demain 9h" | "jeudi 18h" | "dans 20 min" | "2026-11-04 11:00"
#                  tous_les = "jour" | "lundi" | "lundi,jeudi" | "semaine" | "mois" (le 1er)  + heure = "9h"
#                  lieu = "chalet" | "jardin" | ... (fiche lieu avec GPS)  + chaque_fois = oui (sinon une seule fois)
#                optionnel : outil + outil_parametres (JSON) = une ACTION a faire a ce moment (seulement les outils
#                  de la liste ACTIONS_PERMISES ; essai a blanc sauf confirmer=oui : l'accord de J vaut pour plus tard)
#     lister   : les taches en attente
#     annuler  : quoi = numero (ex. "t3") ou un bout du texte ; confirmer=oui si plusieurs
#     retenir_lieu : nom, et ou = "ici" (derniere position du telephone) | "48.85, 2.35" | une adresse ; rayon (m)
#     lieux    : les lieux connus avec GPS
#   python planificateur.py --tick                     (le reveil n8n, chaque minute) -> {"telegram": [textes]}
#   python planificateur.py --boite --fichier pos.json (l'appli : lat, lon, precision_m, age_s, recus=[ids deja lus])
#        -> {"annonces": [{id, texte, audio_ogg_base64}], "suivre_position": vrai s'il existe un rappel lie a un lieu}
# Fichiers : .n8n-files\planificateur\taches.json, annonces.json, journal.txt ; .n8n-files\memoire\lieux\lieux_gps.json
# Regles dures (dans le code) : pas plus de 50 taches en attente ; action differee seulement pour ACTIONS_PERMISES ;
# une tache a heure fixe ratee de plus d'1 h (PC eteint) n'est PAS executee : J est prevenu.
import argparse, json, math, os, re, subprocess, sys, unicodedata, urllib.parse, urllib.request
SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # pas de fenetre noire devant l utilisateur (13/11)
from datetime import datetime, timedelta

HOME = os.path.expanduser("~")
BASE = os.environ.get("ARCHI_BASE") or os.path.join(HOME, ".n8n-files")
DOS = os.path.join(BASE, "planificateur")
TACHES = os.path.join(DOS, "taches.json")
ANNONCES = os.path.join(DOS, "annonces.json")
JOURNAL = os.path.join(DOS, "journal.txt")
LIEUX = os.path.join(BASE, "memoire", "lieux", "lieux_gps.json")
FICHES = os.path.join(BASE, "memoire", "lieux")
POSITION = os.path.join(BASE, "memoire", "position.json")
OUTILS = os.path.join(BASE, "outils")
PY = os.environ.get("ARCHI_PY", "")
VOIX = os.path.join(BASE, "pc", "telephone", "telephone.py")
ACTIONS_PERMISES = {"prises_shelly"}       # outils qu'Archi peut lancer tout seul plus tard (avec l'accord donne a la creation)
RETARD_MAX = timedelta(hours=1)
POSITION_FRAICHE = timedelta(minutes=10)
MAX_TACHES = 50
RAYON_DEFAUT = 150
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MAINTENANT = None  # pour les tests : figer l'heure


class Erreur(Exception):
    pass


def maintenant():
    return MAINTENANT or datetime.now().replace(microsecond=0)


def repondre(ok, phrase, **extra):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(dict(ok=ok, phrase_pour_utilisateur=phrase, **extra), ensure_ascii=False))


def prenom():
    """Le prenom du profil (ARCHI_UTILISATEUR, regle a l'installation). Vide : les phrases s'en passent."""
    return re.sub(r"\s+", " ", os.environ.get("ARCHI_UTILISATEUR") or "").strip()[:30]


def interpeller(phrase):
    """« Camille, rappel : ... » ; sans prenom connu : « Rappel : ... »."""
    p = prenom()
    return f"{p}, {phrase}" if p else phrase[:1].upper() + phrase[1:]


def virgule_prenom():
    """« C'est noté, Camille : ... » ; sans prenom connu : « C'est noté : ... »."""
    p = prenom()
    return f", {p}" if p else ""


def sans_accent(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "").lower()) if unicodedata.category(c) != "Mn")


def oui(v):
    return v is True or sans_accent(v).strip() in {"true", "oui", "1", "yes", "vas-y", "ok"}


def lire(f, defaut, strict=False):
    """strict=True (taches.json) : un fichier present mais illisible n'est JAMAIS remplace par une liste vide"""
    if not os.path.exists(f):
        return defaut
    try:
        with open(f, encoding="utf-8-sig") as h:
            return json.load(h)
    except Exception:
        if strict:
            try:
                import glob, shutil
                if not glob.glob(f + ".illisible_*"):      # une seule copie, pas une par minute
                    shutil.copy(f, f + f".illisible_{datetime.now():%Y%m%d%H%M%S}")
            except Exception:
                pass
            raise Erreur("Le fichier des tâches est abîmé (copie gardée à côté) : je ne touche à rien. Préviens l'administrateur d'Archi.")
        return defaut


def ecrire(f, d):
    os.makedirs(os.path.dirname(f), exist_ok=True)
    tmp = f + ".tmp"
    with open(tmp, "w", encoding="utf-8") as h:
        json.dump(d, h, ensure_ascii=False, indent=1)
    os.replace(tmp, f)


def noter(t):
    try:
        os.makedirs(DOS, exist_ok=True)
        with open(JOURNAL, "a", encoding="utf-8") as h:
            h.write(f"{maintenant():%Y-%m-%d %H:%M} {t}\n")
    except Exception:
        pass


# ---------------------------------------------------------------- l'heure, en francais
def heure_de(s):
    """'11h', '11 h 30', '11:30', '9h05', 'midi', 'minuit' -> (h, m) ou None"""
    s = sans_accent(s)
    if re.search(r"\bmidi\b", s):
        return 12, 0
    if re.search(r"\bminuit\b", s):
        return 0, 0
    m = re.search(r"\b(\d{1,2})\s*(?:h|:|heures?)\s*(\d{2})?\b", s)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if h > 23 or mi > 59:
        raise Erreur(f"Heure impossible : « {s} ».")
    if re.search(r"\b(du soir|de l.apres-midi|pm)\b", s) and h < 12:
        h += 12
    return h, mi


def quand_de(s):
    """une date-heure a partir de '11h', 'demain 9h', 'jeudi 18h', 'dans 20 min', '2026-11-04 11:00', '4/11 11h'"""
    t = sans_accent(s).strip()
    if not t:
        raise Erreur("Dis-moi quand (ex. « 11h », « demain 9h », « dans 20 minutes »).")
    now = maintenant()
    m = re.search(r"dans\s+(\d+)\s*h\s*(\d{1,2})\b", t)
    if m:
        return now + timedelta(hours=int(m.group(1)), minutes=int(m.group(2)))
    m = re.search(r"dans\s+(?:une?\s+)?(quart d.heure|demi.heure|\d+|une?|deux|trois)\s*(min|minutes?|h|heures?|jours?|j)?", t)
    if m:
        mots = {"un": 1, "une": 1, "deux": 2, "trois": 3}
        q = m.group(1)
        if q.startswith("quart"):
            return now + timedelta(minutes=15)
        if q.startswith("demi"):
            return now + timedelta(minutes=30)
        n = int(q) if q.isdigit() else mots[q]
        u = (m.group(2) or "min")
        if u.startswith("h"):
            return now + timedelta(hours=n)
        if u.startswith("j"):
            return now + timedelta(days=n)
        return now + timedelta(minutes=n)
    # une duree en minutes, seule, sans « dans » (un petit modele ecrit a="2 min" : essai reel du 22/11). Seulement les
    # minutes : « 2 h » seul reste une heure (2 h du matin).
    m = re.fullmatch(r"(\d{1,4})\s*(?:min|mins|minutes?|mn)\.?", t)
    if m:
        return now + timedelta(minutes=int(m.group(1)))
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})[ t](\d{1,2}):(\d{2})", t)
    if m:
        return datetime(*map(int, m.groups()))
    jour, jour_semaine = None, False
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
    if m:
        an = int(m.group(3) or now.year)
        an = an + 2000 if an < 100 else an
        jour = datetime(an, int(m.group(2)), int(m.group(1))).date()
    elif "apres-demain" in t or "apres demain" in t:
        jour = (now + timedelta(days=2)).date()
    elif "demain" in t:
        jour = (now + timedelta(days=1)).date()
    elif "aujourd" in t or "ce soir" in t or "cet apres" in t or "ce matin" in t:
        jour = now.date()
    else:
        for i, j in enumerate(JOURS):
            if re.search(r"\b" + j + r"\b", t):
                d = (i - now.weekday()) % 7
                jour = (now + timedelta(days=d or 7)).date() if d or "prochain" in t else now.date()
                jour_semaine = True
                break
    hm = heure_de(t)
    if not hm:
        if "ce soir" in t:
            hm = (20, 0)
        elif "ce matin" in t:
            hm = (9, 0)
        else:
            raise Erreur(f"Je n'ai pas compris l'heure dans « {s} ». Donne une heure (ex. « 11h », « demain 9h »).")
    if jour is None:
        q = now.replace(hour=hm[0], minute=hm[1], second=0)
        return q if q > now else q + timedelta(days=1)
    d = datetime(jour.year, jour.month, jour.day, hm[0], hm[1])
    if jour_semaine and d <= now:      # « jeudi 18h » dit le jeudi a 20h = jeudi prochain
        d += timedelta(days=7)
    return d


def prochaine_boucle(tache, apres):
    """prochaine date d'une tache en boucle strictement apres 'apres'"""
    h, mi = tache["heure"]
    jours = tache.get("jours")          # liste 0-6, ou None = tous les jours
    if tache.get("mois"):
        d = apres.replace(day=1, hour=h, minute=mi, second=0)
        while d <= apres:
            d = (d.replace(day=28) + timedelta(days=4)).replace(day=1, hour=h, minute=mi)
        return d
    d = apres.replace(hour=h, minute=mi, second=0)
    for _ in range(8):
        if d > apres and (not jours or d.weekday() in jours):
            return d
        d += timedelta(days=1)
    return d


def jours_de(s):
    t = sans_accent(s)
    if re.search(r"\b(jour|jours|matin|soir)\b", t) and not any(j in t for j in JOURS):
        return None, False
    if "mois" in t:
        return None, True
    if "semaine de travail" in t or "jours ouvr" in t or "en semaine" in t:
        return [0, 1, 2, 3, 4], False
    if "week-end" in t or "weekend" in t:
        return [5, 6], False
    if "semaine" in t and not any(j in t for j in JOURS):
        return [maintenant().weekday()], False
    js = [i for i, j in enumerate(JOURS) if re.search(r"\b" + j + r"s?\b", t)]
    if not js:
        raise Erreur(f"Je n'ai pas compris « tous les {s} ». Exemples : jour, lundi, lundi et jeudi, mois.")
    return js, False


# ---------------------------------------------------------------- les lieux
def distance_m(a, b, c, d):
    r = 6371000
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def cle_lieu(s):
    return re.sub(r"[^a-z0-9]+", "_", sans_accent(s)).strip("_")


def trouver_lieu(nom, exact=False):
    lieux = lire(LIEUX, {})
    n = cle_lieu(nom)
    if not n:
        return None, None
    for k, l in lieux.items():
        noms = [k] + [cle_lieu(a) for a in l.get("alias", [])] + [cle_lieu(l.get("nom", ""))]
        if n in noms:
            return k, l
    if exact:
        return None, None
    for k, l in lieux.items():   # un bout du nom ("chalet" pour "maison_exemple")
        noms = [k] + [cle_lieu(a) for a in l.get("alias", [])]
        if any(n in x or (len(x) > 3 and x in n) for x in noms):
            return k, l
    return None, None


def position_recente():
    p = lire(POSITION, {})
    try:
        quand = datetime.fromisoformat(str(p.get("heure")))
    except Exception:
        return None
    if maintenant() - quand > POSITION_FRAICHE * 3:
        return None
    return float(p["lat"]), float(p["lon"]), quand


def geocoder(adresse):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": adresse, "format": "jsonv2", "limit": 1, "countrycodes": os.environ.get("ARCHI_PAYS", "fr")})
    req = urllib.request.Request(url, headers={"User-Agent": "Archi-assistant-personnel/1.0 (usage prive)"})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read().decode("utf-8"))
    if not d:
        raise Erreur(f"Je ne trouve pas « {adresse} » sur la carte. Dis « retiens cet endroit » quand tu y es.")
    return float(d[0]["lat"]), float(d[0]["lon"]), d[0].get("display_name", "")[:120]


def retenir_lieu(p):
    nom = str(p.get("nom") or p.get("lieu") or "").strip()
    if not nom:
        raise Erreur("Quel nom pour cet endroit ? (ex. « club », « chez Marco »)")
    ou = str(p.get("ou") or p.get("adresse") or "ici").strip()
    rayon = int(float(str(p.get("rayon") or RAYON_DEFAUT).replace(",", ".")))
    rayon = max(50, min(rayon, 2000))
    m = re.match(r"^\s*(-?\d+[.,]\d+)\s*[,; ]\s*(-?\d+[.,]\d+)\s*$", ou)
    if m:
        lat, lon, src = float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", ".")), "coordonnees donnees"
    elif sans_accent(ou) in {"ici", "la", "ma position", "position", "la ou je suis"}:
        pos = position_recente()
        if not pos:
            raise Erreur("Je n'ai pas ta position récente : ouvre l'appli Archi (ou partage ta position sur Telegram), puis redis-le.")
        lat, lon, src = pos[0], pos[1], f"ta position de {pos[2]:%H:%M}"
    else:
        lat, lon, src = geocoder(ou)
    lieux = lire(LIEUX, {})
    k, ancien = trouver_lieu(nom, exact=True)   # jamais ecraser un autre lieu au nom proche
    k = k or cle_lieu(nom)
    alias = sorted(set((ancien or {}).get("alias", []) + [a.strip() for a in str(p.get("alias") or "").split(",") if a.strip()] + [nom]))
    lieux[k] = {"nom": (ancien or {}).get("nom") or nom, "alias": alias, "lat": round(lat, 6), "lon": round(lon, 6),
                "rayon": rayon, "source": src, "mis_a_jour": maintenant().isoformat(timespec="minutes")}
    ecrire(LIEUX, lieux)
    noter(f"lieu {k} : {lat:.5f}, {lon:.5f} r={rayon} ({src})")
    return {"lieu": k, "lat": lieux[k]["lat"], "lon": lieux[k]["lon"], "rayon": rayon,
            "phrase": f"C'est noté{virgule_prenom()} : « {lieux[k]['nom']} » est retenu ({src}), avec un rayon de {rayon} mètres."}


# ---------------------------------------------------------------- les taches
def nouvel_id(taches):
    n = 1 + max([int(t["id"][1:]) for t in taches if re.match(r"^t\d+$", t.get("id", ""))] or [0])
    return f"t{n}"


def decrire(t):
    q = t["quand"]
    if q["type"] == "heure":
        d = datetime.fromisoformat(q["a"])
        quand = f"le {JOURS[d.weekday()]} {d.day}/{d.month} à {d.hour} h" + (f" {d.minute:02d}" if d.minute else "")
    elif q["type"] == "boucle":
        h = f"{q['heure'][0]} h" + (f" {q['heure'][1]:02d}" if q["heure"][1] else "")
        quand = ("le 1er de chaque mois" if q.get("mois") else "tous les jours" if not q.get("jours")
                 else "tous les " + " et ".join(JOURS[j] for j in q["jours"])) + f" à {h}"
    else:
        quand = ("à chaque arrivée" if q.get("chaque_fois") else "à ton arrivée") + f" : {q.get('lieu_nom', q['lieu'])}"
    act = f" + {t['action']['outil']} {json.dumps(t['action']['parametres'], ensure_ascii=False)}" if t.get("action") else ""
    return f"{t['id']} · {quand} · {t['texte']}{act}"


def action_permise(outil, op):
    """LISTE BLANCHE stricte des actions differees, verifiee a la creation ET juste avant l'execution.
    Seulement la prise du radiateur : allumer / eteindre (+ duree_min). Rien d'autre, jamais la prise du PC."""
    if outil != "prises_shelly" or not isinstance(op, dict):
        raise Erreur("Seul le radiateur peut être piloté plus tard.")
    if cle_lieu(op.get("prise", "")) != "radiateur":
        raise Erreur("Seule la prise du radiateur peut être pilotée plus tard (jamais celle du PC).")
    a = cle_lieu(op.get("action", ""))
    if a not in {"eteindre", "allumer"}:
        raise Erreur("Action différée possible : allumer ou eteindre le radiateur.")
    propre = {"action": a, "prise": "radiateur"}
    if a == "allumer":
        try:
            propre["duree_min"] = max(1, min(int(float(str(op.get("duree_min") or 180).replace(",", "."))), 720))
        except ValueError:
            propre["duree_min"] = 180
    return propre


def ajouter(p):
    texte = str(p.get("texte") or p.get("rappel") or p.get("quoi") or "").strip()
    action = None
    if p.get("outil"):
        outil = cle_lieu(p["outil"])
        if outil not in ACTIONS_PERMISES:
            raise Erreur(f"Je ne peux pas lancer « {outil} » tout seul plus tard (règle de sécurité). "
                         f"Je peux te faire un RAPPEL à la place, et tu le lanceras toi-même.")
        op = p.get("outil_parametres") or {}
        if isinstance(op, str):
            try:
                op = json.loads(op)
            except Exception:
                raise Erreur("outil_parametres doit être du JSON, ex. {\"action\":\"eteindre\",\"prise\":\"radiateur\"}.")
        op = action_permise(outil, op)
        if p.get("lieu"):
            raise Erreur("Une action (radiateur) ne se programme qu'à une HEURE, pas à l'arrivée sur un lieu (sécurité). "
                         "Je peux te faire un rappel au lieu à la place.")
        action = {"outil": outil, "parametres": op}
        if not texte:
            texte = f"{outil} : " + ", ".join(f"{k}={v}" for k, v in op.items())
    if not texte:
        raise Erreur("Qu'est-ce que je dois te rappeler (ou faire) ?")
    if p.get("lieu"):
        k, l = trouver_lieu(p["lieu"])
        if not l:
            connus = ", ".join(v.get("nom", k) for k, v in lire(LIEUX, {}).items()) or "aucun"
            raise Erreur(f"Je ne connais pas encore l'endroit « {p['lieu']} » (lieux connus : {connus}). "
                         f"Dis « retiens cet endroit : {p['lieu']} » quand tu y es, ou donne-moi son adresse.")
        quand = {"type": "lieu", "lieu": k, "lieu_nom": l.get("nom", k), "chaque_fois": oui(p.get("chaque_fois"))}
        pos = position_recente()       # deja sur place : on attend la prochaine VRAIE arrivee
        if pos and maintenant() - pos[2] <= POSITION_FRAICHE and distance_m(pos[0], pos[1], l["lat"], l["lon"]) <= l.get("rayon", RAYON_DEFAUT):
            quand["dedans"] = True
            quand["vu"] = maintenant().isoformat(timespec="minutes")
    elif p.get("tous_les"):
        hm = heure_de(str(p.get("heure") or p.get("a") or p.get("tous_les")))
        if not hm:
            raise Erreur("À quelle heure ? (ex. tous_les=lundi, heure=9h)")
        jours, mois = jours_de(str(p["tous_les"]))
        quand = {"type": "boucle", "heure": list(hm), "jours": jours, "mois": mois}
    elif p.get("a") or p.get("quand") or p.get("heure"):
        d = quand_de(str(p.get("a") or p.get("quand") or p.get("heure")))
        if d <= maintenant():
            raise Erreur(f"Cette heure est déjà passée ({d:%d/%m %H:%M}).")
        if d > maintenant() + timedelta(days=400):
            raise Erreur("C'est dans plus d'un an : trop loin pour moi.")
        quand = {"type": "heure", "a": d.isoformat(timespec="minutes")}
    else:
        raise Erreur("Il me faut un moment (a=\"11h\", \"dans 20 min\"…), une boucle (tous_les + heure) ou un lieu.")
    taches = lire(TACHES, [], True)
    if sum(t["statut"] == "attente" for t in taches) >= MAX_TACHES:
        raise Erreur(f"Il y a déjà {MAX_TACHES} tâches en attente : annules-en d'abord.")
    t = {"id": nouvel_id(taches), "cree": maintenant().isoformat(timespec="minutes"), "texte": texte, "quand": quand,
         "action": action, "statut": "attente"}
    if quand["type"] == "boucle":
        quand["prochaine"] = prochaine_boucle(quand, maintenant()).isoformat(timespec="minutes")
    if action and not oui(p.get("confirmer")):
        return False, "PAS ENCORE FAIT (essai à blanc) : je programmerais " + decrire(t) + \
            ". Si J dit oui, rappelle avec confirmer=oui : son accord vaudra pour l'exécution.", {"essai": True}
    taches.append(t)
    ecrire(TACHES, taches)
    noter("ajout " + decrire(t))
    return True, "C'est programmé" + virgule_prenom() + " : " + decrire(t) + ".", {"tache": t["id"]}


def lister(_p=None):
    ts = [t for t in lire(TACHES, [], True) if t["statut"] == "attente"]
    if not ts:
        return True, "Aucune tâche programmée" + virgule_prenom() + ".", {"taches": []}
    return True, f"{len(ts)} tâche(s) programmée(s) : " + " ; ".join(decrire(t) for t in ts), {"taches": [decrire(t) for t in ts]}


def annuler(p):
    q = sans_accent(p.get("quoi") or p.get("id") or p.get("texte") or "").strip()
    if not q:
        raise Erreur("Laquelle ? Donne son numéro (ex. t3) ou un bout de son texte.")
    taches = lire(TACHES, [], True)
    att = [t for t in taches if t["statut"] == "attente"]
    vis = [t for t in att if t["id"] == q] or [t for t in att if q in sans_accent(t["texte"]) or q in sans_accent(decrire(t))]
    if not vis:
        raise Erreur(f"Aucune tâche en attente ne correspond à « {q} ».")
    if len(vis) > 1 and not oui(p.get("confirmer")):
        return False, f"PAS ENCORE FAIT : {len(vis)} tâches correspondent ({' ; '.join(decrire(t) for t in vis)}). " \
                      "Donne le numéro, ou confirmer=oui pour toutes les annuler.", {}
    for t in vis:
        t["statut"] = "annule"
        t["fin"] = maintenant().isoformat(timespec="minutes")
    ecrire(TACHES, taches)
    noter("annule " + ", ".join(t["id"] for t in vis))
    return True, "C'est annulé : " + " ; ".join(decrire(t) for t in vis) + ".", {}


# ---------------------------------------------------------------- le declenchement
def lancer_action(a):
    """lance l'outil maison comme outils_maison, avec confirmer=oui (accord donne a la creation de la tache).
    La liste blanche est reverifiee ici : une tache modifiee a la main ne peut pas piloter autre chose."""
    try:
        op = action_permise(a.get("outil"), a.get("parametres"))
    except Erreur as e:
        return False, f"refusé par sécurité ({e})"
    reg = lire(os.path.join(OUTILS, "registre.json"), {})
    o = reg.get(a["outil"])
    if not o:
        return False, f"l'outil {a['outil']} n'est pas disponible"
    dos = os.path.join(OUTILS, a["outil"])
    f = os.path.join(dos, f"demande_planif_{datetime.now():%H%M%S%f}.json")
    with open(f, "w", encoding="utf-8") as h:
        json.dump(dict(op, confirmer="oui"), h, ensure_ascii=False)
    try:
        py = PY if os.path.isfile(PY) else sys.executable
        r = subprocess.run([py, os.path.join(dos, o["script"]), "--fichier", f], cwd=dos, capture_output=True,
                           timeout=min(int(o.get("timeout_s", 30)), 45), env=dict(os.environ, PYTHONIOENCODING="utf-8"), creationflags=SANS_FENETRE)
        d = json.loads(r.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
        return bool(d.get("ok")), str(d.get("phrase_pour_utilisateur", ""))[:300]
    except Exception as e:
        return False, f"l'outil a planté ({str(e)[:120]})"
    finally:
        try:
            os.remove(f)
        except Exception:
            pass


def faire_voix(texte):
    """fichier .ogg de la voix d'Archi (comme les reponses de l'appli) ; vide si la voix ne marche pas"""
    if os.environ.get("PLANIF_SANS_VOIX") == "1" or not os.path.isfile(VOIX):
        return ""
    try:
        py = PY if os.path.isfile(PY) else sys.executable
        r = subprocess.run([py, VOIX, "voix"], input=texte.encode("utf-8"), capture_output=True, timeout=30, creationflags=SANS_FENETRE)
        f = r.stdout.decode("utf-8", "replace").strip().splitlines()[-1]
        if os.path.isfile(f):
            dest = os.path.join(DOS, "voix", f"annonce_{datetime.now():%Y%m%d_%H%M%S_%f}.ogg")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(f, "rb") as a, open(dest, "wb") as b:
                b.write(a.read())
            return dest
    except Exception:
        pass
    return ""


def nouvelle_annonce(t, texte, annonces):
    a = {"id": f"a{datetime.now():%Y%m%d%H%M%S%f}", "tache": t["id"], "texte": texte,
         "cree": maintenant().isoformat(timespec="seconds"), "audio": "", "voix_faite": False, "telegram": False, "appli": False}
    annonces.append(a)
    noter(f"declenche {t['id']} : {texte}")
    return a


class Verrou:
    """une seule passe a la fois (le reveil n8n, l'appli et Archi peuvent arriver en meme temps).
    Une passe sous verrou dure quelques secondes (la voix est fabriquee APRES) ; verrou perime apres 5 min."""
    def __init__(self, attendre_s=0):
        self.f, self.attendre_s, self.pris = os.path.join(DOS, "verrou"), attendre_s, False

    def __enter__(self):
        import time
        os.makedirs(DOS, exist_ok=True)
        fin = time.time() + self.attendre_s
        while True:
            try:
                os.close(os.open(self.f, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                self.pris = True
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.f) > 300:
                        os.remove(self.f)
                        continue
                except OSError:
                    continue
                if time.time() >= fin:
                    return self
                time.sleep(0.5)

    def __exit__(self, *a):
        if self.pris:
            try:
                os.remove(self.f)
            except OSError:
                pass


def a_l_heure(t, taches, annonces, now):
    """tache a heure fixe ou en boucle arrivee : statut ECRIT avant de lancer l'action (jamais deux fois)"""
    q = t["quand"]
    d = datetime.fromisoformat(q["a"] if q["type"] == "heure" else q["prochaine"])
    if d > now:
        return
    retard = now - d
    if q["type"] == "heure":
        t["statut"] = "rate" if retard > RETARD_MAX else ("en_cours" if t.get("action") else "fait")
        t["fin"] = now.isoformat(timespec="minutes")
    else:
        q["prochaine"] = prochaine_boucle(q, now).isoformat(timespec="minutes")
    ecrire(TACHES, taches)                      # d'abord noter, ensuite agir
    if retard > RETARD_MAX:
        texte = interpeller(f"je n'ai pas pu le faire à l'heure (le PC était éteint, {int(retard.total_seconds() // 60)} min de retard) : {t['texte']}.")
        if t.get("action"):
            texte += " Je ne lance pas l'action en retard : dis-moi si tu veux toujours."
    elif t.get("action"):
        ok, phrase = lancer_action(t["action"])
        texte = interpeller(f"comme prévu : {phrase}" if ok else f"la tâche « {t['texte']} » a raté : {phrase}")
        t["resultat"] = phrase
        if q["type"] == "heure":
            t["statut"] = "fait" if ok else "rate"
        ecrire(TACHES, taches)
    else:
        texte = interpeller(f"rappel : {t['texte']}")
    nouvelle_annonce(t, texte, annonces)


def au_lieu(t, lieux, position, annonces, now):
    """tache liee a un lieu : se declenche a l'ENTREE dans le rayon (il faut ressortir franchement pour recommencer)"""
    q = t["quand"]
    l = lieux.get(q["lieu"])
    if not l or "lat" not in l or "lon" not in l:
        return False
    rayon = float(l.get("rayon", RAYON_DEFAUT))
    lat, lon, precision = position
    if precision and precision > rayon:          # position trop floue pour ce lieu : on ne decide rien
        return False
    dist = distance_m(lat, lon, float(l["lat"]), float(l["lon"]))
    dedans = dist <= rayon
    change = False
    if dedans and not q.get("dedans"):
        if not q.get("chaque_fois"):
            t["statut"] = "fait"
            t["fin"] = now.isoformat(timespec="minutes")
        nouvelle_annonce(t, interpeller(f"rappel ({q.get('lieu_nom', q['lieu'])}) : {t['texte']}"), annonces)
        change = True
    if dedans != bool(q.get("dedans")) and (dedans or dist > rayon * 1.5):
        q["dedans"] = dedans
        change = True
    try:
        ancien_vu = datetime.fromisoformat(q["vu"]) if q.get("vu") else None
    except ValueError:
        ancien_vu = None
    q["vu"] = now.isoformat(timespec="minutes")
    if ancien_vu is None or now - ancien_vu > timedelta(minutes=10):
        change = True                             # « vu » doit etre sur le disque, sinon faux « reparti » apres 1 h
    return change


def tick(position=None, envoyer_telegram=True):
    """une passe (SOUS VERROU, quelques secondes) : declenche ce qui est du. position = (lat, lon, precision_m) fraiche,
    sinon position.json si fraiche. envoyer_telegram=False (passage de l'appli) : le Telegram part au prochain reveil."""
    now = maintenant()
    taches = lire(TACHES, [], True)
    annonces = lire(ANNONCES, [])
    if position is None:
        p = position_recente()
        if p and now - p[2] <= POSITION_FRAICHE:
            position = (p[0], p[1], float(lire(POSITION, {}).get("precision_m") or 0))
    lieux = lire(LIEUX, {})
    change = False
    for t in taches:
        if t.get("statut") == "en_cours":         # coupure pendant une action : on ne sait pas si elle a eu lieu
            try:
                if now - datetime.fromisoformat(t.get("fin", "")) > timedelta(minutes=10):
                    t["statut"] = "incertain"
                    change = True
                    nouvelle_annonce(t, interpeller(f"je ne sais pas si « {t['texte']} » a été fait (coupure pendant l'action) : vérifie le radiateur."), annonces)
            except ValueError:
                pass
            continue
        if t.get("statut") != "attente":
            continue
        try:
            q = t["quand"]
            if q["type"] in ("heure", "boucle"):
                a_l_heure(t, taches, annonces, now)
            elif q["type"] == "lieu":
                if position:
                    change = au_lieu(t, lieux, position, annonces, now) or change
                elif q.get("dedans") and q.get("vu") and now - datetime.fromisoformat(q["vu"]) > timedelta(hours=1):
                    q["dedans"] = False          # plus de nouvelles depuis 1 h : la prochaine arrivee comptera
                    change = True
        except Exception as e:                    # une tache abimee ne bloque pas les autres
            noter(f"tache {t.get('id')} en erreur : {type(e).__name__} {str(e)[:100]}")
    if change:
        ecrire(TACHES, taches)
    a_envoyer = [a for a in annonces if not a["telegram"]] if envoyer_telegram else []
    for a in a_envoyer:
        a["telegram"] = True
    gardees = [a for a in annonces if now - datetime.fromisoformat(a["cree"]) < timedelta(days=3)]
    for a in annonces:                            # menage : la voix des vieilles annonces
        if a not in gardees and a.get("audio"):
            try:
                os.remove(a["audio"])
            except OSError:
                pass
    ecrire(ANNONCES, gardees)
    return [a["texte"] for a in a_envoyer]


def preparer_voix(max_n=3):
    """HORS verrou : fabrique la voix des annonces qui n'en ont pas encore (quelques secondes chacune)"""
    a_faire = [a for a in lire(ANNONCES, []) if not a.get("voix_faite")][:max_n]
    faites = {a["id"]: faire_voix(a["texte"]) for a in a_faire}
    if not faites:
        return
    with Verrou(20) as v:
        if not v.pris:
            return
        annonces = lire(ANNONCES, [])
        for a in annonces:
            if a["id"] in faites:
                a["audio"], a["voix_faite"] = faites[a["id"]], True
        ecrire(ANNONCES, annonces)


def position_de_l_appli(p, source="appli"):
    """(lat, lon, precision) si la position envoyee par l'appli est valable et recente, sinon None"""
    try:
        lat, lon = float(p["lat"]), float(p["lon"])
    except Exception:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    try:
        age = max(0.0, float(p.get("age_s") or 0))
    except ValueError:
        age = 0.0
    if age > POSITION_FRAICHE.total_seconds():
        return None
    try:
        precision = max(0.0, float(p.get("precision_m") or 0))
    except ValueError:
        precision = 0.0
    quand = maintenant() - timedelta(seconds=age)
    ancienne = lire(POSITION, {})
    try:
        proche = distance_m(lat, lon, float(ancienne.get("lat", 0)), float(ancienne.get("lon", 0))) < 2000
    except Exception:
        proche = False
    ecrire(POSITION, {"lat": lat, "lon": lon, "lieu": ancienne.get("lieu", "") if proche else "",
                      "heure": quand.isoformat(timespec="seconds"), "precision_m": round(precision), "source": source})
    return lat, lon, precision


def boite_passe(p):
    """SOUS VERROU : position, declenchement, accuses de reception de l'appli"""
    position = position_de_l_appli(p)
    tick(position, envoyer_telegram=False)       # le Telegram de ces annonces part au prochain reveil n8n (1 min)
    recus = {str(x) for x in (p.get("recus") or []) if isinstance(x, (str, int))}
    if recus:
        annonces = lire(ANNONCES, [])
        for a in annonces:
            if a["id"] in recus:
                a["appli"] = True
        ecrire(ANNONCES, annonces)


def boite_reponse():
    """les annonces que l'appli n'a pas encore confirmees (moins de 2 h), voix comprise ; et faut-il suivre la position"""
    import base64
    pour_appli = []
    for a in lire(ANNONCES, []):
        age = maintenant() - datetime.fromisoformat(a["cree"])
        if a["appli"] or age > timedelta(hours=2):
            continue
        if not a.get("voix_faite") and age < timedelta(minutes=3):
            continue                              # la voix arrive au prochain passage (sinon : un bip et la voix perdue)
        audio = ""
        try:
            if a.get("audio") and os.path.isfile(a["audio"]):
                with open(a["audio"], "rb") as h:
                    audio = base64.b64encode(h.read()).decode()
        except Exception:
            audio = ""
        pour_appli.append({"id": a["id"], "texte": a["texte"], "audio_ogg_base64": audio})
    suivre = any(t.get("statut") == "attente" and t["quand"]["type"] == "lieu" for t in lire(TACHES, [], True))
    return pour_appli, suivre


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fichier")
    ap.add_argument("--tick", action="store_true")
    ap.add_argument("--boite", action="store_true")
    ap.add_argument("--position", action="store_true")   # position partagee ailleurs (Telegram) : --fichier {lat, lon}
    ap.add_argument("--annoncer", action="store_true")   # une annonce d'un autre outil (le curateur, le mecanicien) : --fichier {texte, de}
    a = ap.parse_args()
    p = {}
    if a.fichier:
        try:
            with open(a.fichier, encoding="utf-8-sig") as h:
                p = json.load(h)
        except Exception:
            p = {}
    try:
        if a.tick:                                # rapide : pas de voix ici (elle se fait au passage de l'appli)
            alerte = os.path.join(DOS, "alerte_taches_abimees")
            try:
                with Verrou(0) as v:
                    textes = tick() if v.pris else []
                if os.path.exists(alerte):
                    os.remove(alerte)
            except Erreur as e:
                textes = []
                if not os.path.exists(alerte):    # une seule alerte, pas une par minute
                    open(alerte, "w").close()
                    textes = [interpeller(str(e))]
            print(json.dumps({"ok": True, "telegram": textes}, ensure_ascii=False))
            return
        if a.position:                            # position partagee sur Telegram (trombone > Position)
            with Verrou(15) as v:
                pos = position_de_l_appli(p, source=str(p.get("source") or "telegram")[:20]) if v.pris else None
                if pos:
                    tick(pos, envoyer_telegram=False)   # une arrivee sur un lieu part au prochain reveil (1 min)
            if not pos:
                repondre(False, "Je n'ai pas pu noter cette position (illisible ou trop ancienne).")
                return
            ls = lire(LIEUX, {})
            ici = [v_.get("nom", k) for k, v_ in ls.items()
                   if distance_m(pos[0], pos[1], float(v_.get("lat", 0)), float(v_.get("lon", 0))) <= float(v_.get("rayon") or 150)]
            repondre(True, "Position notée" + (f" : tu es à « {ici[0]} »." if ici else ".")
                     + " Tu peux dire « retiens cet endroit : ici » pour en faire un lieu.", lieu=ici[0] if ici else "")
            return
        if a.annoncer:                            # elle part comme un rappel : Telegram, appli, page du PC
            texte = re.sub(r"\s+", " ", str(p.get("texte") or "")).strip()[:600]
            de = re.sub(r"[^a-z_]", "", sans_accent(p.get("de") or "outil"))[:20] or "outil"
            if not texte:
                raise Erreur("Annonce vide.")
            with Verrou(20) as v:
                if not v.pris:
                    raise Erreur("Le planificateur est occupé : annonce pas posée.")
                annonces = lire(ANNONCES, [])
                nouvelle_annonce({"id": "tournee_" + de}, texte, annonces)
                ecrire(ANNONCES, annonces)
            repondre(True, "Annonce posée.")
            return
        if a.boite:
            with Verrou(15) as v:
                if v.pris:
                    boite_passe(p)
            preparer_voix(max_n=1)                # 30 s au plus : l'appli attend la reponse
            annonces, suivre = boite_reponse()
            print(json.dumps({"ok": True, "annonces": annonces, "suivre_position": suivre}, ensure_ascii=False))
            return
        act = sans_accent(p.get("action") or "")
        if not act:
            act = "ajouter" if (p.get("texte") or p.get("outil")) else "lister"
        with Verrou(20) as v:   # pas en meme temps qu'une passe du reveil (evite d'ecraser taches.json)
            if not v.pris:
                raise Erreur("Le planificateur est occupé une seconde : réessaie.")
            if act in {"ajouter", "programmer", "planifier", "rappel", "rappeler", "creer"}:
                ok, phrase, extra = ajouter(p)
            elif act in {"lister", "liste", "voir", "taches"}:
                ok, phrase, extra = lister(p)
            elif act in {"annuler", "supprimer", "effacer", "retirer"}:
                ok, phrase, extra = annuler(p)
            elif act in {"retenir_lieu", "retenir", "lieu", "nouveau_lieu", "memoriser_lieu"}:
                r = retenir_lieu(p)
                ok, phrase, extra = True, r.pop("phrase"), r
            elif act in {"lieux", "liste_lieux"}:
                ls = lire(LIEUX, {})
                ok, phrase, extra = True, ("Lieux connus : " + ", ".join(f"{v.get('nom', k)} ({v.get('rayon')} m)" for k, v in ls.items())
                                           if ls else "Aucun lieu avec GPS pour l'instant."), {}
            else:
                raise Erreur(f"Action inconnue « {act} ». Actions : ajouter, lister, annuler, retenir_lieu, lieux.")
        repondre(ok, phrase, **extra)
    except Erreur as e:
        repondre(False, str(e))
    except Exception as e:
        repondre(False, f"Le planificateur a eu un souci : {type(e).__name__} {str(e)[:150]}")


if __name__ == "__main__":
    main()
