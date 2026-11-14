# mecanicien.py - outil maison d'Archi : le MECANICIEN fabrique de nouveaux outils, dans un atelier a part, et ne les
# installe qu'apres le « valide » de l'utilisateur (10/11/2026).
# Il n'ecrit PAS de programme : il demande au modele local une RECETTE (un site public a interroger, ce qu'il faut en
# garder, un calcul, une phrase), que le moteur fixe recette.py suit. Aucun code invente par le modele n'est execute.
#   python mecanicien.py --fichier demande.json     (appele par outils_maison)
#     etat (defaut) : ce qu'il y a dans l'atelier
#     idee          : texte = ce que l'outil doit faire. Note l'idee, sans rien fabriquer.
#     construire    : numero (une idee notee) ou texte (une nouvelle idee). Exige accord=oui. La fabrication part en
#                     arriere-plan (quelques minutes) ; l'utilisateur est prevenu quand l'outil est teste.
#     voir          : numero. Ce que fait l'outil, ses parametres, les sites qu'il lit, et ses essais.
#     valider       : numero. Exige accord=oui. Installe l'outil teste parmi les outils d'Archi (copie du registre avant).
#     abandonner    : numero.
#     retirer       : nom ou numero. Exige accord=oui. Enleve un outil installe par le mecanicien (rien n'est efface).
#   python mecanicien.py --tournee      (mercredi et dimanche, core/tournees.js) : relit ce qui a rate depuis la derniere
#                                       tournee (atelier\rates.jsonl) et propose 1 a 3 idees d'outils. Il ne fabrique rien.
#   python mecanicien.py --construire N (lance par « construire ») : la fabrication elle-meme.
# Fichiers : <base>\atelier\atelier.json (les idees), <base>\atelier\<n>_<nom>\recette.json (l'outil en cours).
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # pas de fenetre noire devant l utilisateur (13/11)
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
import recette as moteur  # noqa: E402  (le moteur, dans le meme dossier)

ESSAIS_MAX = 3                       # la recette du modele, puis deux corrections au plus
MAX_IDEES = 40
CONSTRUCTION_MAX = datetime.timedelta(minutes=30)
RESERVES = {"outils_maison", "curateur", "mecanicien", "memoire", "planificateur", "wikipedia", "enquete_osint", "lire_page",
            "videos_youtube", "navigateur", "registre", "atelier", "recette"}
ETATS = {"idee": "idée", "construction": "en construction", "teste": "testé, attend ton accord", "rate": "raté",
         "impossible": "pas faisable", "installe": "installé", "abandonne": "abandonné", "retire": "retiré"}
MAINTENANT = None
APPEL = None                         # les tests remplacent le modele
OUVRIR = None                        # les tests remplacent Internet


class Erreur(Exception):
    pass


def repondre(ok, phrase, **extra):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    r = dict(ok=ok, phrase_pour_utilisateur=phrase, **extra)
    print(json.dumps(r, ensure_ascii=False))
    return r


def maintenant():
    return MAINTENANT or datetime.datetime.now().replace(microsecond=0)


def plat(t):
    t = unicodedata.normalize("NFD", str(t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def court(s, n=120):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def prenom():
    p = (os.environ.get("ARCHI_UTILISATEUR") or "").strip()[:30]
    return (p + ", ") if p else ""


# ---------------------------------------------------------------- les dossiers et l'etat de l'atelier
def base():
    return os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files")


def atelier(*x):
    return os.path.join(base(), "atelier", *x)


def lire_json(f, defaut):
    try:
        with open(f, encoding="utf-8-sig") as h:
            return json.load(h)
    except (OSError, ValueError):
        return defaut


def ecrire_json(f, d):
    os.makedirs(os.path.dirname(f), exist_ok=True)
    tmp = f + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8", newline="\n") as h:
        json.dump(d, h, ensure_ascii=False, indent=1)
    os.replace(tmp, f)


class Verrou:
    """un seul a la fois ecrit atelier.json (l'agent, la fabrication en arriere-plan, la tournee)"""

    def __enter__(self):
        os.makedirs(atelier(), exist_ok=True)
        self.d = atelier(".verrou_atelier")
        fin = time.time() + 15
        while True:
            try:
                os.mkdir(self.d)
                return self
            except OSError:
                try:
                    if abs(time.time() - os.path.getmtime(self.d)) > 60:      # abs : horloge revenue en arriere
                        os.rmdir(self.d)
                        continue
                except OSError:
                    pass
                if time.time() > fin:
                    raise Erreur("L'atelier est occupé : réessaie dans une minute.")
                time.sleep(0.1)

    def __exit__(self, *a):
        try:
            os.rmdir(self.d)
        except OSError:
            pass


def lire_etat():
    e = lire_json(atelier("atelier.json"), {})
    if not isinstance(e, dict) or not isinstance(e.get("idees"), list):
        e = {"idees": []}
    return e


def trouver(etat, numero):
    try:
        n = int(re.search(r"\d+", str(numero)).group(0))
    except (AttributeError, ValueError):
        raise Erreur("Dis-moi le numéro de l'idée (par exemple « la 2 »).")
    i = next((x for x in etat["idees"] if x.get("n") == n), None)
    if not i:
        raise Erreur("Je n'ai pas d'idée n°%d dans l'atelier." % n)
    return i


def nouvelle_idee(etat, titre, quoi, source):
    n = max([x.get("n", 0) for x in etat["idees"]] + [0]) + 1
    i = {"n": n, "titre": court(titre, 60), "quoi": court(quoi, 300), "source": source, "etat": "idee",
         "cree": maintenant().isoformat(timespec="seconds"), "maj": maintenant().isoformat(timespec="seconds")}
    etat["idees"].append(i)
    finies = [x for x in etat["idees"] if x.get("etat") in ("abandonne", "rate", "impossible", "retire")]
    while len(etat["idees"]) > MAX_IDEES and finies:      # les plus vieilles idees finies sortent de la liste (pas les outils)
        etat["idees"].remove(finies.pop(0))
    return i


def en_construction(etat):
    for x in etat["idees"]:
        if x.get("etat") == "construction":
            try:
                if maintenant() - datetime.datetime.fromisoformat(x.get("debut", "")) < CONSTRUCTION_MAX:
                    return x
            except ValueError:
                pass
            x["etat"], x["message"] = "rate", "La fabrication a été interrompue (PC éteint ou modèle arrêté)."
    return None


def annoncer(texte):
    """l'annonce part comme un rappel du planificateur : Telegram, l'appli et la page du PC"""
    script = os.path.join(base(), "outils", "planificateur", "planificateur.py")
    if not os.path.exists(script):
        return False
    f = atelier("annonce_%d.json" % int(time.time() * 1000))
    ecrire_json(f, {"texte": texte, "de": "mecanicien"})
    try:
        r = subprocess.run([sys.executable, script, "--annoncer", "--fichier", f], capture_output=True, timeout=40,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"), creationflags=SANS_FENETRE)
        return r.returncode == 0 and '"ok": true' in r.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        try:
            os.remove(f)
        except OSError:
            pass


# ---------------------------------------------------------------- le modele local
def appel_par_defaut(corps):
    url = (os.environ.get("ARCHI_LM_URL") or "http://127.0.0.1:1234/v1").rstrip("/") + "/chat/completions"
    req = urllib.request.Request(url, data=json.dumps(corps).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def demander(messages, schema, max_tokens=3500, effort="medium"):
    corps = {"model": os.environ.get("ARCHI_MODELE") or "openai/gpt-oss-20b", "temperature": 0.2, "max_tokens": max_tokens,
             "reasoning_effort": effort, "messages": messages}
    appel = APPEL or appel_par_defaut
    try:
        rep = appel(dict(corps, response_format=schema))
    except urllib.error.HTTPError as e:
        if e.code not in (400, 422):
            raise
        rep = appel(corps)
    contenu = (((rep.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
    m = re.search(r"\{.*\}", contenu, re.S)
    if not m:
        raise Erreur("le modèle n'a pas rendu de recette")
    try:
        return json.loads(m.group(0)), contenu
    except ValueError:
        raise Erreur("la recette du modèle est illisible")


PAIRE = {"type": "object", "additionalProperties": False, "required": ["nom", "valeur"],
         "properties": {"nom": {"type": "string"}, "valeur": {"type": "string"}}}
SCHEMA_RECETTE = {"type": "json_schema", "json_schema": {"name": "recette", "strict": True, "schema": {
    "type": "object", "additionalProperties": False,
    "required": ["faisable", "pourquoi_pas", "nom", "titre", "quoi", "mode_d_emploi", "parametres", "hotes", "etapes", "phrase", "essais"],
    "properties": {
        "faisable": {"type": "boolean"}, "pourquoi_pas": {"type": "string"},
        "nom": {"type": "string"}, "titre": {"type": "string"}, "quoi": {"type": "string"}, "mode_d_emploi": {"type": "string"},
        "parametres": {"type": "array", "maxItems": 4, "items": {"type": "object", "additionalProperties": False,
                       "required": ["nom", "description", "type", "exemple"],
                       "properties": {"nom": {"type": "string"}, "description": {"type": "string"},
                                      "type": {"type": "string", "enum": ["texte", "nombre"]}, "exemple": {"type": "string"}}}},
        "hotes": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
        "etapes": {"type": "array", "minItems": 1, "maxItems": 4, "items": {"type": "object", "additionalProperties": False,
                   "required": ["type", "url", "garder", "si_vide"],
                   "properties": {"type": {"type": "string", "enum": ["api", "calcul"]}, "url": {"type": "string"},
                                  "garder": {"type": "array", "minItems": 1, "maxItems": 6, "items": PAIRE},
                                  "si_vide": {"type": "string"}}}},
        "phrase": {"type": "string"},
        "essais": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "object", "additionalProperties": False,
                   "required": ["parametres", "doit_contenir"],
                   "properties": {"parametres": {"type": "array", "maxItems": 4, "items": PAIRE}, "doit_contenir": {"type": "string"}}}},
    }}}}

CONSIGNE = """Tu es le mécanicien d'Archi, un assistant sur PC. On te donne une idée d'outil. Tu n'écris PAS de programme : tu écris une RECETTE, qu'un moteur suit pas à pas.
Une recette, c'est :
- des paramètres (au plus 4) : nom en minuscules (ex. ville), type texte ou nombre, et un exemple ;
- des sites (hotes, au plus 3) : des API PUBLIQUES, gratuites, SANS clé ni compte, qui répondent en JSON, en https ;
- des étapes (au plus 4), dans l'ordre :
  * api : url https vers un site déclaré ; {nom} y met un paramètre ou une valeur déjà gardée. garder : des paires nom -> chemin dans la réponse JSON, avec des points (ex. current.temperature_2m, results.0.name). si_vide : la phrase si la réponse ne contient pas ces valeurs (ex. Je ne trouve pas {ville}.).
  * calcul : url vide ; garder : des paires nom -> calcul avec + - * / // % **, des parenthèses, round, abs, min, max, sqrt, floor, ceil, et les noms déjà connus. si_vide vide.
- une phrase en français, en tutoyant, avec des {nom} ; {nom:1} écrit un nombre avec 1 chiffre après la virgule ; chaque nombre est NOMMÉ et a son unité (latitude, longitude, °C, km/h…), pour qu'on ne puisse pas le confondre ;
- 1 à 3 essais : des paramètres, et un bout de texte que la phrase DOIT contenir (vide si la réponse change tout le temps, comme une température).
Si l'idée a besoin d'un compte, d'une clé, de fichiers du PC, d'envoyer quelque chose ou d'agir sur un appareil : faisable=false et pourquoi_pas en une phrase simple.
Exemple de recette (position de la station spatiale) : parametres vide ; hotes ["api.wheretheiss.at"] ; etapes [{type api, url https://api.wheretheiss.at/v1/satellites/25544, garder [{nom lat, valeur latitude}, {nom lon, valeur longitude}, {nom vitesse, valeur velocity}], si_vide "Je n'ai pas la position."}] ; phrase "La station spatiale est au-dessus de la latitude {lat:1}, longitude {lon:1}, à {vitesse:0} km/h." ; essais [{parametres vide, doit_contenir "station spatiale"}].
Le nom de l'outil : minuscules et tirets bas, 3 à 30 caractères (ex. position_iss)."""


def en_recette(m):
    """la reponse du modele (des listes de paires) -> une recette pour le moteur (des dictionnaires)"""
    paires = lambda L: {str(p.get("nom", "")).strip(): str(p.get("valeur", "")).strip() for p in (L or []) if isinstance(p, dict)}
    r = {k: m.get(k) for k in ("nom", "titre", "quoi", "mode_d_emploi", "phrase")}
    r["nom"] = re.sub(r"[^a-z0-9_]", "_", plat(r.get("nom") or "")).strip("_")[:31]
    r["parametres"] = [{"nom": plat(p.get("nom", "")).strip(), "description": str(p.get("description", ""))[:120],
                        "type": p.get("type") if p.get("type") in ("texte", "nombre") else "texte", "exemple": str(p.get("exemple", ""))[:60]}
                       for p in (m.get("parametres") or []) if isinstance(p, dict)]
    r["hotes"] = [re.sub(r"^[a-z]+://", "", plat(h).strip()).split("/")[0] for h in (m.get("hotes") or []) if isinstance(h, str)]
    r["etapes"] = []
    for e in m.get("etapes") or []:
        if not isinstance(e, dict):
            continue
        x = {"type": e.get("type"), "garder": paires(e.get("garder"))}
        if e.get("type") == "api":
            x["url"] = str(e.get("url") or "").strip()
        if str(e.get("si_vide") or "").strip():
            x["si_vide"] = str(e["si_vide"]).strip()
        r["etapes"].append(x)
    r["essais"] = [{"parametres": paires(e.get("parametres")), "doit_contenir": str(e.get("doit_contenir") or "").strip()}
                   for e in (m.get("essais") or []) if isinstance(e, dict)]
    return r


def essayer(r):
    """les essais de la recette, avec le moteur : [(parametres, resultat, reussi, pourquoi)]"""
    sortie = []
    for e in (r.get("essais") or [])[:3]:
        res = moteur.executer(r, e.get("parametres") or {}, OUVRIR)
        attendu = plat(e.get("doit_contenir") or "")
        reussi = bool(res.get("ok")) and (not attendu or attendu in plat(res.get("phrase_pour_utilisateur")))
        pourquoi = "" if reussi else ("l'outil a répondu : %s" % court(res.get("phrase_pour_utilisateur"), 200) if not res.get("ok")
                                      else "la phrase ne contient pas « %s »" % court(e.get("doit_contenir"), 60))
        sortie.append((e.get("parametres") or {}, res, reussi, pourquoi))
    return sortie


def nom_libre(nom, etat):
    reg = lire_json(os.path.join(base(), "outils", "registre.json"), {})
    pris = set(reg) | RESERVES | {x.get("nom") for x in etat["idees"] if x.get("nom") and x.get("etat") in ("teste", "installe", "construction")}
    n, i = nom, 1
    while n in pris or os.path.exists(os.path.join(base(), "outils", n)):
        i += 1
        n = ("%s_%d" % (nom[:27], i))
    return n


def fabriquer(numero):
    """la fabrication, en arriere-plan : recette du modele -> verification -> essais -> au plus deux corrections"""
    with Verrou():
        etat = lire_etat()
        idee = trouver(etat, numero)
        n, titre, quoi = idee["n"], idee["titre"], idee["quoi"]
    messages = [{"role": "system", "content": CONSIGNE}, {"role": "user", "content": "L'idée : %s. %s" % (titre, quoi)}]
    r, problemes, essais = None, ["le modèle n'a pas répondu"], []
    for tentative in range(ESSAIS_MAX):
        try:
            m, brut = demander(messages, SCHEMA_RECETTE)
        except Exception as x:
            problemes = ["le modèle local ne répond pas (%s)" % (x if isinstance(x, Erreur) else type(x).__name__)]
            break
        if m.get("faisable") is False:
            with Verrou():
                etat = lire_etat()
                i = trouver(etat, n)
                i.update(etat="impossible", message=court(m.get("pourquoi_pas") or "Ce n'est pas faisable avec une recette.", 300),
                         maj=maintenant().isoformat(timespec="seconds"))
                ecrire_json(atelier("atelier.json"), etat)
            annoncer("%sle mécanicien ne peut pas fabriquer « %s » : %s" % (prenom(), titre, court(m.get("pourquoi_pas"), 200)))
            return
        r = en_recette(m)
        problemes = moteur.verifier_recette(r)
        if not problemes and not r["essais"]:
            problemes = ["aucun essai"]
        if not problemes:
            essais = essayer(r)
            problemes = ["essai %d : %s" % (k + 1, e[3]) for k, e in enumerate(essais) if not e[2]]
        if not problemes:
            break
        messages += [{"role": "assistant", "content": brut[:6000]},
                     {"role": "user", "content": "Ta recette a ces problèmes : %s. Corrige-la et rends-la ENTIÈRE." % " ; ".join(problemes[:6])}]
    with Verrou():
        etat = lire_etat()
        i = trouver(etat, n)
        if problemes or not r:
            i.update(etat="rate", message=court("Pas réussi : " + " ; ".join(sans_lu(p) for p in problemes[:3]), 300),
                     maj=maintenant().isoformat(timespec="seconds"))
        else:
            r["nom"] = nom_libre(r["nom"], etat)
            dossier = "%d_%s" % (n, r["nom"])
            ecrire_json(atelier(dossier, "recette.json"), r)
            i.update(etat="teste", nom=r["nom"], dossier=dossier, titre=court(r["titre"], 60), quoi=court(r["quoi"], 300),
                     hotes=r["hotes"], parametres=[p["nom"] for p in r["parametres"]],
                     essais=[{"parametres": p, "phrase": court(res.get("phrase_pour_utilisateur"), 300), "reussi": ok}
                             for p, res, ok, _ in essais],
                     message="", maj=maintenant().isoformat(timespec="seconds"))
        ecrire_json(atelier("atelier.json"), etat)
    if problemes or not r:
        annoncer("%sle mécanicien n'a pas réussi l'outil « %s » : %s" % (prenom(), titre, court(sans_lu(problemes[0]), 160)))
    else:
        annoncer("%sl'outil « %s » est prêt et testé (%d essai(s) réussi(s)). Dis « mécanicien, valide la %d » pour que je l'installe, "
                 "ou regarde-le d'abord sur la page du PC (menu, L'atelier)." % (prenom(), court(r["titre"], 60), len(essais), n))


def sans_lu(probleme):
    """un probleme sans ce que l'outil a lu sur un site (le modele le recoit pour corriger, l'utilisateur non)"""
    return re.sub(r"l'outil a répondu : .*", "l'essai n'a pas abouti", str(probleme))


def lancer_fabrication(n):
    """la fabrication prend quelques minutes : elle part en arriere-plan, l'agent n'attend pas"""
    if os.environ.get("ARCHI_MECANICIEN_SUR_PLACE") == "1":      # les tests : sur place
        fabriquer(n)
        return
    drapeaux = 0
    if os.name == "nt":
        drapeaux = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    subprocess.Popen([sys.executable, os.path.join(ICI, "mecanicien.py"), "--construire", str(n)], cwd=ICI,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                     creationflags=drapeaux, start_new_session=(os.name != "nt"))


# ---------------------------------------------------------------- les actions
def act_etat(_d):
    with Verrou():
        etat = lire_etat()
        avant = json.dumps(etat, sort_keys=True)
        en_construction(etat)                  # une fabrication interrompue depuis longtemps passe « ratee »
        if json.dumps(etat, sort_keys=True) != avant:
            ecrire_json(atelier("atelier.json"), etat)
    L = [x for x in etat["idees"] if x.get("etat") not in ("abandonne", "retire")][-8:]
    if not L:
        return repondre(True, "L'atelier est vide. Dis « mécanicien, fabrique-moi un outil qui… » pour me donner une idée.")
    dites = " ; ".join("%d) « %s » : %s" % (x["n"], x["titre"], ETATS.get(x.get("etat"), x.get("etat"))) for x in L)
    return repondre(True, "Dans l'atelier : %s." % dites, idees=[{"n": x["n"], "titre": x["titre"], "etat": x.get("etat")} for x in L])


def act_idee(d):
    texte = court(d.get("texte") or d.get("idee") or "", 300)
    if len(texte) < 8:
        raise Erreur("Dis-moi ce que l'outil doit faire, en une phrase.")
    with Verrou():
        etat = lire_etat()
        i = nouvelle_idee(etat, d.get("titre") or texte, texte, "demande")
        ecrire_json(atelier("atelier.json"), etat)
    return repondre(True, "C'est noté, idée n°%d : « %s ». Dis « mécanicien, construis la %d » pour que je la fabrique." % (i["n"], i["titre"], i["n"]),
                    numero=i["n"])


def act_construire(d):
    with Verrou():
        etat = lire_etat()
        occupe = en_construction(etat)
        if occupe:
            ecrire_json(atelier("atelier.json"), etat)
            raise Erreur("Je suis déjà en train de fabriquer l'idée n°%d (« %s ») : une à la fois." % (occupe["n"], occupe["titre"]))
        if d.get("numero") not in (None, ""):
            i = trouver(etat, d["numero"])
        else:
            texte = court(d.get("texte") or d.get("idee") or "", 300)
            if len(texte) < 8:
                raise Erreur("Dis-moi ce que l'outil doit faire, ou le numéro d'une idée de l'atelier.")
            i = nouvelle_idee(etat, d.get("titre") or texte, texte, "demande")
        if i.get("etat") in ("installe", "teste"):
            raise Erreur("L'idée n°%d est déjà %s." % (i["n"], ETATS[i["etat"]]))
        i.update(etat="construction", debut=maintenant().isoformat(timespec="seconds"), maj=maintenant().isoformat(timespec="seconds"),
                 message="")
        ecrire_json(atelier("atelier.json"), etat)
    lancer_fabrication(i["n"])
    return repondre(True, "Je m'y mets dans l'atelier, idée n°%d : « %s ». Le modèle du PC écrit la recette, puis je l'essaie : "
                          "quelques minutes (je réponds un peu plus lentement pendant ce temps). Je te préviens quand c'est prêt, "
                          "et rien ne s'installe sans ton accord." % (i["n"], i["titre"]), numero=i["n"])


def act_voir(d):
    etat = lire_etat()
    i = trouver(etat, d.get("numero") or d.get("texte"))
    phrase = "Idée n°%d, « %s » (%s) : %s" % (i["n"], i["titre"], ETATS.get(i.get("etat"), ""), i.get("quoi", ""))
    if i.get("etat") in ("teste", "installe"):
        params = ", ".join(i.get("parametres") or []) or "aucun"
        sites = ", ".join(i.get("hotes") or []) or "aucun (un calcul)"
        essais = " ; ".join("%s -> %s" % (", ".join("%s=%s" % kv for kv in e["parametres"].items()) or "sans paramètre", e["phrase"])
                            for e in i.get("essais") or [])
        liste = i.get("essais") or []
        reussis = sum(1 for e in liste if e.get("reussi"))
        # la phrase est dite telle quelle : elle ne contient que nos mots. Ce que l'outil a lu (les essais) est a part,
        # dans « extrait » (balise par le lanceur) et sur la page du PC
        phrase += (" Paramètres : %s. Sites lus : %s. Essais : %d réussi(s) sur %d, leur résultat est sur la page du PC "
                   "(menu, L'atelier)." % (params, sites, reussis, len(liste)))
        extrait = "Essais : %s." % court(essais, 500) if essais else ""
    else:
        extrait = ""
        if i.get("message"):
            phrase += " " + sans_lu(i["message"])
    if extrait:
        return repondre(True, phrase, extrait=extrait)
    return repondre(True, phrase)


def act_valider(d):
    with Verrou():
        etat = lire_etat()
        i = trouver(etat, d.get("numero") or d.get("texte"))
        if i.get("etat") != "teste":
            raise Erreur("L'idée n°%d n'est pas prête à installer (%s)." % (i["n"], ETATS.get(i.get("etat"), i.get("etat"))))
        r = lire_json(atelier(i["dossier"], "recette.json"), None)
        problemes = moteur.verifier_recette(r) if r else ["recette introuvable"]
        if problemes:
            raise Erreur("La recette ne passe plus la vérification (%s) : je ne l'installe pas." % problemes[0])
        reg_f = os.path.join(base(), "outils", "registre.json")
        reg = lire_json(reg_f, None)
        if not isinstance(reg, dict):
            raise Erreur("Le registre des outils est illisible : je n'y touche pas.")
        nom = r["nom"]
        dest = os.path.join(base(), "outils", nom)
        if nom in reg or nom in RESERVES:
            raise Erreur("Un outil s'appelle déjà « %s » : je ne l'écrase pas." % nom)
        # une installation coupee en plein milieu (dossier pose, registre pas encore ecrit) : on la termine
        reprise = (os.path.isdir(dest) and lire_json(os.path.join(dest, "recette.json"), None) == r
                   and os.path.isfile(os.path.join(dest, "outil_recette.py")))
        if os.path.exists(dest) and not reprise:
            raise Erreur("Un outil s'appelle déjà « %s » : je ne l'écrase pas." % nom)
        # prepare a cote, puis un seul renommage : une panne ne laisse jamais un dossier a moitie, ni un nom bloque
        prep = os.path.join(base(), "outils", ".%s_prep" % nom)
        ecrire_json(atelier("registre_avant_%s.json" % maintenant().strftime("%Y%m%d_%H%M%S")), reg)
        reg[nom] = {
            "nom": nom, "titre": r["titre"],
            "description": "MODE D EMPLOI : %s %s Dis à l'utilisateur ce que l'outil a lu, tel quel, sans changer les nombres." % (r["quoi"].rstrip(".") + ".", r["mode_d_emploi"].strip()),
            "script": "outil_recette.py",
            "parametres": [{"nom": p["nom"], "description": p.get("description") or p["nom"]} for p in r["parametres"]],
            "timeout_s": 60,
            "touche": ["fabriqué par le mécanicien"] + (["lit : " + ", ".join(r["hotes"])] if r["hotes"] else []),
            "mecanicien": {"idee": i["n"], "installe_le": maintenant().isoformat(timespec="seconds"), "hotes": r["hotes"]},
        }
        try:
            if not reprise:
                shutil.rmtree(prep, ignore_errors=True)
                os.makedirs(prep)
                # pas de copie du moteur : le lanceur de l'outil utilise celui du mecanicien (une correction vaut pour tous)
                shutil.copy(os.path.join(ICI, "outil_recette.py"), os.path.join(prep, "outil_recette.py"))
                ecrire_json(os.path.join(prep, "recette.json"), r)
                os.rename(prep, dest)
            ecrire_json(reg_f, reg)
        except OSError:
            if not reprise:
                shutil.rmtree(dest if os.path.isdir(dest) else prep, ignore_errors=True)
            shutil.rmtree(prep, ignore_errors=True)
            raise Erreur("Je n'ai pas pu installer l'outil (fichier occupé ?) : rien n'a changé, redis « valide » dans un moment.")
        i.update(etat="installe", installe_le=maintenant().isoformat(timespec="seconds"), maj=maintenant().isoformat(timespec="seconds"))
        ecrire_json(atelier("atelier.json"), etat)
    ex = next((e for e in i.get("essais") or [] if e.get("reussi")), None)
    essai = (" Essaie : « %s »." % ", ".join(str(v) for v in ex["parametres"].values())) if ex and ex["parametres"] else ""
    return repondre(True, "C'est installé : « %s » fait maintenant partie de mes outils (nom : %s).%s Pour l'enlever : « mécanicien, retire %s »."
                    % (r["titre"], nom, essai, nom), nom=nom)


def act_abandonner(d):
    with Verrou():
        etat = lire_etat()
        i = trouver(etat, d.get("numero") or d.get("texte"))
        if i.get("etat") in ("installe", "construction"):
            raise Erreur("L'idée n°%d est %s : je ne peux pas l'abandonner maintenant." % (i["n"], ETATS[i["etat"]]))
        i.update(etat="abandonne", maj=maintenant().isoformat(timespec="seconds"))
        ecrire_json(atelier("atelier.json"), etat)
    return repondre(True, "Idée n°%d abandonnée." % i["n"])


def act_retirer(d):
    with Verrou():
        etat = lire_etat()
        cle = plat(d.get("nom") or "").strip()
        if not cle and d.get("numero") not in (None, ""):
            cle = trouver(etat, d["numero"]).get("nom") or ""
        reg_f = os.path.join(base(), "outils", "registre.json")
        reg = lire_json(reg_f, None)
        if not isinstance(reg, dict) or cle not in reg:
            raise Erreur("Je n'ai pas d'outil « %s »." % cle[:40])
        if not isinstance(reg[cle].get("mecanicien"), dict):
            raise Erreur("« %s » n'a pas été fabriqué par le mécanicien : je n'y touche pas." % cle)
        ecrire_json(atelier("registre_avant_%s.json" % maintenant().strftime("%Y%m%d_%H%M%S")), reg)
        del reg[cle]
        src = os.path.join(base(), "outils", cle)
        vers = atelier("_retires", "%s_%s" % (cle, maintenant().strftime("%Y%m%d_%H%M%S")))
        bouge = False
        try:
            if os.path.isdir(src):             # rien n'est efface : le dossier part dans atelier\_retires
                os.makedirs(atelier("_retires"), exist_ok=True)
                shutil.move(src, vers)
                bouge = True
            ecrire_json(reg_f, reg)
        except OSError:
            if bouge and not os.path.exists(src):
                shutil.move(vers, src)
            raise Erreur("Je n'ai pas pu retirer « %s » (fichier occupé ?) : rien n'a changé." % cle)
        for x in etat["idees"]:
            if x.get("nom") == cle and x.get("etat") == "installe":
                x.update(etat="retire", maj=maintenant().isoformat(timespec="seconds"))
        ecrire_json(atelier("atelier.json"), etat)
    return repondre(True, "C'est retiré : « %s » ne fait plus partie de mes outils (gardé de côté dans l'atelier)." % cle)


# ---------------------------------------------------------------- la tournee : des idees a partir de ce qui a rate
SCHEMA_IDEES = {"type": "json_schema", "json_schema": {"name": "idees", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["idees"],
    "properties": {"idees": {"type": "array", "maxItems": 3, "items": {"type": "object", "additionalProperties": False,
                   "required": ["titre", "quoi"], "properties": {"titre": {"type": "string"}, "quoi": {"type": "string"}}}}}}}}


def rates_depuis(depuis):
    L = []
    try:
        with open(atelier("rates.jsonl"), encoding="utf-8") as h:
            for l in h.read().splitlines()[-500:]:
                try:
                    x = json.loads(l)
                except ValueError:
                    continue
                if isinstance(x, dict) and isinstance(x.get("quand"), (int, float)) and x["quand"] > depuis:
                    L.append(x)
    except OSError:
        pass
    return L


def tournee():
    etat = lire_etat()
    depuis = etat.get("rates_lus") or 0
    L = rates_depuis(depuis)
    fin = max([x["quand"] for x in L] + [depuis])
    if not L:
        with Verrou():
            etat = lire_etat()
            etat["derniere_tournee"] = maintenant().isoformat(timespec="seconds")
            ecrire_json(atelier("atelier.json"), etat)
        return repondre(True, "Rien n'a raté depuis la dernière tournée : pas de nouvelle idée.", idees=[])
    compte = {}
    for x in L:
        k = (str(x.get("type"))[:10], court(x.get("outil"), 40), court(x.get("erreur"), 120))
        compte[k] = compte.get(k, 0) + 1
    lignes = ["- %s %s fois : %s %s" % ("outil inconnu demandé" if t == "inconnu" else "échec de l'outil", n, o, ("(" + e + ")") if e else "")
              for (t, o, e), n in sorted(compte.items(), key=lambda kv: -kv[1])[:15]]
    try:
        m, _ = demander([{"role": "system", "content": "Tu es le mécanicien d'Archi. Voici ce qui a raté cette semaine. Propose 0 à 3 "
                          "idées d'OUTILS NOUVEAUX qui se font avec une API publique gratuite sans clé, ou un simple calcul. Titre court, "
                          "et quoi = ce que l'outil fait, en une phrase. Pas d'idée qui demande un compte, une clé ou un appareil."},
                         {"role": "user", "content": "\n".join(lignes)}], SCHEMA_IDEES, max_tokens=900, effort="low")
        idees = [x for x in (m.get("idees") or []) if isinstance(x, dict) and str(x.get("titre") or "").strip()][:3]
    except Exception:
        return repondre(False, "Le modèle local ne répond pas : la tournée du mécanicien attendra.")
    with Verrou():
        etat = lire_etat()
        nouvelles = [nouvelle_idee(etat, x["titre"], x.get("quoi") or x["titre"], "tournee") for x in idees]
        etat["rates_lus"] = fin
        etat["derniere_tournee"] = maintenant().isoformat(timespec="seconds")
        ecrire_json(atelier("atelier.json"), etat)
    if nouvelles:
        annoncer("%sle mécanicien a %d idée(s) d'outil : %s. Dis « mécanicien, construis la %d » si l'une te plaît."
                 % (prenom(), len(nouvelles), " ; ".join("%d) %s" % (i["n"], i["titre"]) for i in nouvelles), nouvelles[0]["n"]))
    return repondre(True, "%d idée(s) notée(s)." % len(nouvelles), idees=[i["n"] for i in nouvelles])


ACTIONS = {"etat": act_etat, "idee": act_idee, "construire": act_construire, "voir": act_voir, "valider": act_valider,
           "abandonner": act_abandonner, "retirer": act_retirer}
# des synonymes pour LIRE ou NOTER seulement : construire, valider et retirer demandent l'accord, sur leur vrai nom
SYNONYMES = {"liste": "etat", "lister": "etat", "atelier": "etat", "ou_en_es": "etat", "montre": "voir", "detail": "voir",
             "noter": "idee", "note": "idee", "proposer": "idee", "abandonne": "abandonner", "laisse_tomber": "abandonner"}


MODIFIENT = ("construire", "valider", "retirer")     # les memes que sensible_si dans outil.json


def action_de(d, defaut):
    """le nom de l'action, tel quel (accents et majuscules mis a part) : on ne retire AUCUN caractere, sinon « valider. »
    passerait le controle d'accord du lanceur sous un autre nom, puis serait lu « valider » ici"""
    brut = d.get("action")
    if brut is None or (isinstance(brut, str) and not brut.strip()):
        return defaut
    if not isinstance(brut, str):
        raise Erreur("L'action doit être un mot, par exemple « etat ».")
    a = re.sub(r"[\s'-]+", "_", plat(brut).strip())
    if not re.fullmatch(r"[a-z_]{1,30}", a):
        raise Erreur("Action inconnue. Actions : etat, idee, construire, voir, valider, abandonner, retirer.")
    return a


def traiter(d):
    """une demande de l'agent -> la reponse (dict) ; ne leve jamais d'exception"""
    try:
        d = d if isinstance(d, dict) else {}
        act = action_de(d, "etat")
        act = SYNONYMES.get(act, act)
        if act not in ACTIONS:
            raise Erreur("Action inconnue « %s ». Actions : etat, idee, construire, voir, valider, abandonner, retirer." % act[:30])
        if act in MODIFIENT and str(d.get("_accord") or "").strip().lower() != "oui":
            raise Erreur("« %s » change tes outils : il me faut ton accord (outils_maison avec accord=oui)." % act)
        return ACTIONS[act](d)
    except Erreur as e:
        return repondre(False, str(e))
    except Exception as e:
        return repondre(False, "Le mécanicien a eu un pépin : %s." % type(e).__name__, erreur=str(e)[:200])


FABRICATION_MAX = 15 * 60


def abandon_fabrication(numero):
    """le chien de garde : une fabrication trop longue (un site trop lent, un modele bloque) est arretee et marquee ratee"""
    try:
        with Verrou():
            etat = lire_etat()
            for i in etat["idees"]:
                if str(i.get("n")) == str(numero) and i.get("etat") == "construction":
                    i.update(etat="rate", message="Fabrication arrêtée : elle durait plus de %d minutes." % (FABRICATION_MAX // 60))
            ecrire_json(atelier("atelier.json"), etat)
    finally:
        os._exit(3)


def main():
    pa = argparse.ArgumentParser()
    pa.add_argument("--fichier")
    pa.add_argument("--tournee", action="store_true")
    pa.add_argument("--construire")
    a = pa.parse_args()
    try:
        if a.construire:
            chien = threading.Timer(FABRICATION_MAX, abandon_fabrication, args=(a.construire,))
            chien.daemon = True
            chien.start()
            try:
                fabriquer(a.construire)
            except Exception as x:          # en arriere-plan : l'idee passe « ratee », jamais « en construction » pour toujours
                with Verrou():
                    etat = lire_etat()
                    for i in etat["idees"]:
                        if str(i.get("n")) == str(a.construire) and i.get("etat") == "construction":
                            i.update(etat="rate", message="Pépin pendant la fabrication (%s)." % type(x).__name__)
                    ecrire_json(atelier("atelier.json"), etat)
            return
        if a.tournee:
            tournee()
            return
        d = {}
        if a.fichier:
            with open(a.fichier, encoding="utf-8-sig") as h:
                d = json.load(h)
        traiter(d)
    except Erreur as e:
        repondre(False, str(e))
    except Exception as e:
        repondre(False, "Le mécanicien a eu un pépin : %s." % type(e).__name__, erreur=str(e)[:200])


if __name__ == "__main__":
    main()
