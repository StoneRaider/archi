# curateur.py - outil maison d'Archi : le CURATEUR relit le chateau (la memoire en fiches Markdown) et propose du
# rangement. Il ne change RIEN tout seul : l'utilisateur choisit les numeros (10/11/2026).
#   python curateur.py --fichier demande.json     (appele par outils_maison)
#     examiner (defaut) : relit toutes les fiches et rend une liste NUMEROTEE de propositions. Rien n'est change.
#                         sans_modele=oui : sans le modele local (il ne cherche alors pas les contradictions)
#     propositions      : relit les propositions en attente (celles de la derniere tournee)
#     appliquer         : numeros = "1 et 3" | "1,3" | "tout". Exige accord=oui (outils_maison) : c'est le oui de l'utilisateur.
#                         Copie de toute la memoire avant (curateur\copies), puis SEULEMENT les numeros choisis.
#     annuler           : remet les fiches comme avant les applications (toutes, depuis la tournee), si personne n'y a
#                         touche depuis.
# Les numeros ne changent pas de sens tant que la liste est en cours : une nouvelle tournee garde les numeros deja
# annonces et donne les suivants aux nouvelles propositions (« curateur, 1 » vise toujours ce qu'on a entendu).
#   python curateur.py --tournee    (le passage du dimanche, lance par core/tournees.js) : examine, puis previent
#                                   l'utilisateur par une annonce du planificateur (Telegram, appli, page du PC).
# Ce qu'il cherche, dans le code : un lien [[...]] qui ne mene a aucune fiche, un fait en double, une ligne qui ressemble
# a un secret (mot de passe, IBAN, numero de telephone), une fiche vide, un projet « en cours » sans nouvelle depuis
# 90 jours, une fiche geante. Le modele local cherche en plus deux faits qui se contredisent.
# Garde-fous : il ne supprime jamais de fiche (une fiche vide part dans memoire\_archives) ; une proposition dont la
# fiche a change depuis la tournee n'est pas appliquee ; un secret n'est jamais recopie dans sa reponse.
import argparse
import datetime
import difflib
import hashlib
import json
import os
import re
import subprocess
SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # pas de fenetre noire devant l utilisateur (13/11)
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile

PIECES = ("moi", "personnes", "projets", "lieux", "preferences")
CONNUES = PIECES + ("bibliotheque", "methodes")
PERSO = ("moi", "personnes", "projets", "lieux", "preferences")   # la ou un secret n'a rien a faire
MAX_PROPOSITIONS = 12
MAX_DITES = 5                       # au-dela, la phrase renvoie a la page du PC (la voix ne lit pas 12 propositions)
VALIDITE = datetime.timedelta(days=8)
DUREE_LISTE = datetime.timedelta(days=28)   # au-dela, une nouvelle liste (numeros depuis 1, annulations oubliees)
ENDORMI = datetime.timedelta(days=90)
GEANTE = 15000
COPIES_GARDEES = 10
MAX_FAITS_MODELE = 80
MAINTENANT = None                   # pour les tests : figer l'heure

VIDES = set(("avec avoir dans pour plus mais tout tous toute toutes cette celle celui ceux sont etre fait faire peux peut veux "
             "vais vous nous elle elles leur leurs quoi quel quelle quels quelles comment quand alors donc aussi tres bien "
             "comme encore parce depuis chez entre sans sous vers votre notre cela ceci moins autre autres meme "
             "utilisateur utilisatrice appelle").split())
# les memes motifs que l'outil memoire (il refuse de les retenir) : ici, on les repere dans les fiches ecrites a la main
SECRETS = re.compile(r"mot\s+de\s+passe|password|passe\s*:|code\s+(pin|secret|de\s+la\s+carte|d'acces)|\biban\b|\bcvv\b|"
                     r"numero\s+de\s+(carte|compte|securite)|cle\s+(api|secrete|privee)|\btoken\b|\bjeton\b|\b\d{13,19}\b|"
                     r"\b[a-z]{2}\d{2}(\s?\d{4}){3,}", re.I)
TELEPHONE = re.compile(r"(\+\d[\d .-]{7,})|(\b0\d([ .-]?\d\d){4}\b)")
LIEN = re.compile(r"\[\[([^\[\]|#\n]{1,80})(?:[|#][^\[\]\n]{0,80})?\]\]")
DATE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
STATUT = re.compile(r"^\s*\*\*Statut\s*:\*\*\s*en\s+cours\b", re.I)
REMPLISSAGE = set("curateur applique appliquer appliques appliquez la le les l et n numero numeros no proposition propositions "
                  "oui juste seulement stp svp ok d de des du vas y va s il te plait".split())
# les seuls mots permis autour des numeros : tout autre mot (« laisse la 2 », « garde la 2 », « de 1 a 4 »,
# « les 2 premieres ») fait redemander, plutot qu'appliquer ce qui n'etait pas voulu
PERMIS = REMPLISSAGE | set("je j veux voudrais bien accord daccord merci seule seul uniquement aussi puis ces celle celles "
                           "ci fais faire go c est ca bon parfait alors donc maintenant moi archi pour er re ere "
                           "egalement choisis choisi prends prend accepte valide valider and".split())
NEGATIONS = re.compile(r"\b(sauf|pas|mais|sans|excepte|exceptee|exceptees|hormis|moins|non|ni)\b")
CHIFFRE_EN_LETTRES = r"(?:deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze)"
NOMBRES = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9,
           "dix": 10, "onze": 11, "douze": 12, "premiere": 1, "premier": 1}


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
    t = unicodedata.normalize("NFD", str(t or "").lower()).replace("œ", "oe").replace("æ", "ae")
    return "".join(c for c in t if unicodedata.category(c) != "Mn").replace("’", "'")


def mots(t, mini=4):
    return [m for m in re.split(r"[^a-z0-9]+", plat(t)) if len(m) >= mini and m not in VIDES]


def cle(s):
    return re.sub(r"[^a-z0-9]+", "_", plat(s)).strip("_")


def sans_date(fait):
    return re.sub(r"^\(\d{2}/\d{2}/\d{4}\)\s*", "", fait)


def court(s, n=110):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def empreinte(texte):
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()[:20]


def secret(ligne):
    return bool(SECRETS.search(plat(ligne)) or TELEPHONE.search(ligne))


# ---------------------------------------------------------------- les dossiers
def base():
    return os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files")


def dos_memoire():
    return os.path.join(base(), "memoire")


def chemin(nom):
    return os.path.join(base(), "curateur", nom)


def fiche_de(rel):
    """le chemin d'une fiche, jamais en dehors de la memoire (rel vient d'un fichier qu'on a ecrit nous-memes, mais quand meme)"""
    racine = os.path.realpath(dos_memoire())
    c = os.path.realpath(os.path.join(racine, *str(rel).split("/")))
    if not c.startswith(racine + os.sep):
        raise Erreur("chemin de fiche refusé")
    return c


def lire_json(f, defaut):
    try:
        with open(f, encoding="utf-8-sig") as h:
            return json.load(h)
    except (OSError, ValueError):
        return defaut


def ecrire_json(f, d):
    os.makedirs(os.path.dirname(f), exist_ok=True)
    tmp = f + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as h:
        json.dump(d, h, ensure_ascii=False, indent=1)
    os.replace(tmp, f)


def ecrire_texte(c, t):
    os.makedirs(os.path.dirname(c), exist_ok=True)
    tmp = c + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as h:   # newline="" : on garde les fins de ligne de la fiche
        h.write(t)
    os.replace(tmp, c)


class Verrou:
    """le meme verrou que l'outil memoire : le greffier ne range pas un fait pendant que le curateur change une fiche"""

    def __enter__(self):
        os.makedirs(dos_memoire(), exist_ok=True)
        self.dossier = os.path.join(dos_memoire(), ".verrou_memoire")
        fin = time.time() + 15
        while True:
            try:
                os.mkdir(self.dossier)
                return self
            except OSError:
                try:
                    if abs(time.time() - os.path.getmtime(self.dossier)) > 60:      # abs : horloge revenue en arriere
                        os.rmdir(self.dossier)
                        continue
                except OSError:
                    pass
                if time.time() > fin:
                    raise Erreur("La mémoire est occupée : réessaie dans une minute.")
                time.sleep(0.1)

    def __exit__(self, *a):
        try:
            os.rmdir(self.dossier)
        except OSError:
            pass


# ---------------------------------------------------------------- lire le chateau
def lire_fiches():
    """[{rel, chemin, texte, piece, nom}] de toutes les fiches .md (sans les archives ni les dossiers caches)"""
    racine = dos_memoire()
    L = []
    for dos, sous, fichiers in os.walk(racine):
        sous[:] = sorted(s for s in sous if not s.startswith((".", "_")))
        for f in sorted(fichiers):
            if not f.lower().endswith(".md"):
                continue
            c = os.path.join(dos, f)
            rel = os.path.relpath(c, racine).replace("\\", "/")
            try:
                with open(c, encoding="utf-8", newline="") as h:
                    t = h.read(2000000)
            except (OSError, UnicodeDecodeError):
                continue
            L.append({"rel": rel, "chemin": c, "texte": t, "piece": rel.split("/")[0] if "/" in rel else "", "nom": f[:-3]})
            if len(L) >= 3000:
                return L
    return L


def lignes_de_faits(texte):
    """[(ligne_exacte, fait)] des puces des blocs « **Faits :** »"""
    out, dedans = [], False
    for l in texte.split("\n"):
        s = l.strip()
        if s.startswith("**Faits :**"):
            dedans = True
            continue
        if s.startswith("**") or s.startswith("#"):
            dedans = False
            continue
        if dedans and s.startswith("- "):
            out.append((l, s[2:].strip()))
    return out


def date_du_fait(fait):
    m = re.match(r"^\((\d{2})/(\d{2})/(\d{4})\)", fait)
    if not m:
        return None
    try:
        return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def proposition(type_, f, titre, action):
    return {"type": type_, "fiche": f["rel"], "titre": titre, "action": action, "empreinte": empreinte(f["texte"])}


def retirer(ligne):
    """une ligne a retirer est gardee par son EMPREINTE : un secret ne reste pas en clair dans propositions.json"""
    return {"type": "retirer_ligne", "empreinte_ligne": empreinte(ligne.rstrip("\r"))}


def trouver_ligne(lignes, a):
    if a.get("empreinte_ligne"):
        return next((k for k, l in enumerate(lignes) if empreinte(l.rstrip("\r")) == a["empreinte_ligne"]), None)
    cible = str(a.get("ligne") or "").rstrip("\r")      # l'ancien format
    return next((k for k, l in enumerate(lignes) if cible and l.rstrip("\r") == cible), None)


def s_applique(p, texte):
    """la proposition vise-t-elle encore quelque chose dans ce texte ?"""
    a = p.get("action") or {}
    if a.get("type") == "remplacer":
        return bool(a.get("ancien")) and a["ancien"] in texte
    if a.get("type") == "retirer_ligne":
        return trouver_ligne(texte.split("\n"), a) is not None
    return True


# ---------------------------------------------------------------- ce qu'il cherche
def chercher_secrets(fiches):
    P = []
    for f in fiches:
        if f["piece"] not in PERSO:
            continue
        for i, l in enumerate(f["texte"].split("\n")):
            if l.strip() and secret(l):
                P.append(proposition("secret", f, "Dans « %s », la ligne %d ressemble à un mot de passe, un code ou un numéro de "
                                     "téléphone : je propose de la retirer de la mémoire (je ne la recopie pas ici)." % (f["nom"], i + 1),
                                     retirer(l)))
    return P


def chercher_liens(fiches):
    vrais = {}
    for f in fiches:
        vrais.setdefault(cle(f["nom"]), f["nom"])
    connus = set(vrais) | set(CONNUES)
    for f in fiches:
        connus.update(cle(x) for x in f["rel"].split("/")[:-1])
    P = []
    for f in fiches:
        vus = set()
        for m in (m for l in f["texte"].split("\n") if not secret(l) for m in LIEN.finditer(l)):
            brut, cible = m.group(0), m.group(1).strip()
            k = cle(cible)
            if not k or k in connus or brut in vus:
                continue
            vus.add(brut)
            proche = difflib.get_close_matches(k, sorted(vrais), n=1, cutoff=0.75)
            if proche:
                nouveau = "[[%s]]" % vrais[proche[0]]
                titre = "Lien cassé dans « %s » : %s ne mène à aucune fiche. Je propose %s." % (f["nom"], court(brut, 60), nouveau)
            else:
                nouveau = cible
                titre = ("Lien cassé dans « %s » : %s ne mène à aucune fiche. Je propose de le laisser en simple texte."
                         % (f["nom"], court(brut, 60)))
            P.append(proposition("lien_casse", f, titre, {"type": "remplacer", "ancien": brut, "nouveau": nouveau}))
    return P


def pareil(a, b):
    a, b = sans_date(a), sans_date(b)
    if plat(a).strip(" .") == plat(b).strip(" ."):
        return True
    x, y = set(mots(a)), set(mots(b))
    return len(x) >= 3 and len(y) >= 3 and len(x & y) / float(len(x | y)) >= 0.8


def chercher_doublons(fiches):
    """un fait ecrit deux fois dans la meme fiche, ou dans deux fiches de « moi » ou de « preferences » (lues ensemble)"""
    P = []
    deja = {"moi": [], "preferences": []}
    for f in fiches:
        vus = list(deja.get(f["piece"], []))
        for ligne, fait in lignes_de_faits(f["texte"]):
            if secret(ligne):
                continue
            avant = next((v for v in vus if pareil(fait, v[0])), None)
            if avant:
                ou = "plus haut" if avant[1] == f["nom"] else "dans « %s »" % avant[1]
                P.append(proposition("fait_double", f, "Fait en double dans « %s » : « %s » est déjà écrit %s. Je propose de retirer la copie."
                                     % (f["nom"], court(sans_date(fait), 90), ou), retirer(ligne)))
            else:
                vus.append((fait, f["nom"]))
        if f["piece"] in deja:
            deja[f["piece"]] = vus
    return P


def chercher_vides(fiches):
    P = []
    for f in fiches:
        if not f["piece"]:
            continue
        reste = [l for l in f["texte"].split("\n")
                 if l.strip() and not l.strip().startswith("#") and not re.match(r"^\s*\*\*[^*]{1,30}:\*\*\s*\S{0,30}\s*$", l)]
        if len("".join(reste).strip()) < 15:
            P.append(proposition("fiche_vide", f, "La fiche « %s » (%s) est vide : je propose de la ranger aux archives." % (f["nom"], f["piece"]),
                                 {"type": "archiver"}))
    return P


def derniere_date(f):
    dates = []
    for j, m, a in DATE.findall(f["texte"]):
        try:
            dates.append(datetime.date(int(a), int(m), int(j)))
        except ValueError:
            pass
    dates = [d for d in dates if d <= maintenant().date()]
    if dates:
        return max(dates)
    try:
        return datetime.date.fromtimestamp(os.path.getmtime(f["chemin"]))
    except OSError:
        return None


def chercher_endormis(fiches):
    P = []
    for f in fiches:
        if f["piece"] != "projets":
            continue
        ligne = next((l for l in f["texte"].split("\n") if STATUT.match(l)), None)
        d = derniere_date(f)
        if not ligne or not d or maintenant().date() - d <= ENDORMI:
            continue
        fin = "\r" if ligne.endswith("\r") else ""
        nouveau = "**Statut :** en pause (rangé par le curateur le %s : rien de neuf depuis le %s)." % (
            maintenant().strftime("%d/%m/%Y"), d.strftime("%d/%m/%Y"))
        P.append(proposition("projet_endormi", f, "Le projet « %s » est « en cours », mais rien de neuf depuis le %s : je propose de le "
                             "passer « en pause »." % (f["nom"], d.strftime("%d/%m/%Y")),
                             {"type": "remplacer", "ancien": ligne, "nouveau": nouveau + fin}))
    return P


def chercher_geantes(fiches):
    return [proposition("fiche_geante", f, "La fiche « %s » est très longue (%d caractères) : on pourra la découper ensemble. "
                        "Rien à appliquer, c'est pour info." % (f["nom"], len(f["texte"])), {"type": "info"})
            for f in fiches if len(f["texte"]) > GEANTE]


# ---------------------------------------------------------------- le modele local : deux faits qui se contredisent
CONSIGNE = ("Tu es le curateur d'une mémoire personnelle. Voici des faits numérotés, rangés par fiche. Trouve UNIQUEMENT les paires "
            "de faits de la MÊME fiche qui se contredisent vraiment : ils parlent de la même chose et ne peuvent pas être vrais en "
            "même temps (exemple : « habite à Lyon » et « habite à Nantes »). Deux faits différents mais compatibles ne se "
            "contredisent pas. Au plus 3 paires. S'il n'y en a aucune, rends une liste vide.")
SCHEMA = {"type": "json_schema", "json_schema": {"name": "contradictions", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["paires"],
    "properties": {"paires": {"type": "array", "maxItems": 3, "items": {
        "type": "object", "additionalProperties": False, "required": ["a", "b", "pourquoi"],
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}, "pourquoi": {"type": "string"}}}}}}}}


def appel_par_defaut(corps):
    url = (os.environ.get("ARCHI_LM_URL") or "http://127.0.0.1:1234/v1").rstrip("/") + "/chat/completions"
    req = urllib.request.Request(url, data=json.dumps(corps).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def chercher_contradictions(fiches, appel=None):
    numerotes = []          # (fiche, ligne, fait)
    lignes = []
    for f in fiches:
        if f["piece"] not in ("moi", "preferences", "personnes"):
            continue
        faits = [(l, x) for l, x in lignes_de_faits(f["texte"]) if not secret(l)]
        if len(faits) < 2:
            continue
        lignes.append("Fiche « %s » :" % f["nom"])
        for l, x in faits:
            if len(numerotes) >= MAX_FAITS_MODELE:
                break
            numerotes.append((f, l, x))
            lignes.append("%d. %s" % (len(numerotes), court(sans_date(x), 200)))
    if len(numerotes) < 2:
        return []
    corps = {"model": os.environ.get("ARCHI_MODELE") or "openai/gpt-oss-20b", "temperature": 0, "max_tokens": 900,
             "reasoning_effort": "low",
             "messages": [{"role": "system", "content": CONSIGNE}, {"role": "user", "content": "\n".join(lignes)}]}
    appel = appel or appel_par_defaut
    try:
        rep = appel(dict(corps, response_format=SCHEMA))
    except urllib.error.HTTPError as e:
        if e.code not in (400, 422):
            raise
        rep = appel(corps)
    contenu = (((rep.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
    m = re.search(r"\{.*\}", contenu, re.S)
    try:
        paires = json.loads(m.group(0)).get("paires") if m else []
    except ValueError:
        paires = []
    P, prises = [], set()
    for p in paires if isinstance(paires, list) else []:
        try:
            a, b = int(p.get("a")), int(p.get("b"))
        except (TypeError, ValueError, AttributeError):
            continue
        if a == b or not (1 <= a <= len(numerotes) and 1 <= b <= len(numerotes)) or a in prises or b in prises:
            continue
        fa, la, xa = numerotes[a - 1]
        fb, lb, xb = numerotes[b - 1]
        # le modele invente parfois : meme fiche, et au moins un mot commun qui n'est ni le prenom ni le nom de la fiche
        hors = set(mots(os.environ.get("ARCHI_UTILISATEUR") or "", 3)) | set(mots(fa["nom"].replace("_", " "), 3))
        if fa is not fb or not ((set(mots(sans_date(xa), 3)) & set(mots(sans_date(xb), 3))) - hors):
            continue
        if pareil(xa, xb):
            continue        # deux fois le meme fait : c'est un doublon (il a sa proposition), pas une contradiction
        da, db = date_du_fait(xa), date_du_fait(xb)
        a_plus_vieux = (da < db) if (da and db and da != db) else (a < b)   # sans date : la ligne du dessous est la plus recente
        ancien, recent = ((la, xa), (lb, xb)) if a_plus_vieux else ((lb, xb), (la, xa))
        prises.update((a, b))
        P.append(proposition("contradiction", fa, "Deux faits se contredisent dans « %s » : « %s » et « %s ». Je propose de garder le plus "
                             "récent, « %s », et de retirer l'autre." % (fa["nom"], court(sans_date(ancien[1]), 80),
                                                                         court(sans_date(recent[1]), 80), court(sans_date(recent[1]), 80)),
                             retirer(ancien[0])))
    return P


# ---------------------------------------------------------------- examiner
def examiner(par="demande", avec_modele=True, appel=None):
    fiches = lire_fiches()
    P = chercher_secrets(fiches)
    modele = False
    if avec_modele:
        try:
            P += chercher_contradictions(fiches, appel)
            modele = True
        except Exception:
            pass            # le modele n'est pas la (LM Studio eteint) : la tournee se fait sans lui
    for chercher in (chercher_liens, chercher_doublons, chercher_vides, chercher_endormis, chercher_geantes):
        P += chercher(fiches)
    vues, gardees = set(), []
    for p in P:             # une meme ligne n'a qu'une proposition (un secret en double : une seule fois)
        k = (p["fiche"], json.dumps(p["action"], sort_keys=True))
        if k not in vues:
            vues.add(k)
            gardees.append(p)
    ancien = lire_json(chemin("propositions.json"), {})
    if en_cours(ancien):
        liste, appliquees = fusionner(ancien, gardees)
        debut = ancien.get("debut") or ancien.get("cree")
    else:
        liste, appliquees = gardees[:MAX_PROPOSITIONS], []
        for i, p in enumerate(liste):
            p["n"] = i + 1
        debut = maintenant().isoformat(timespec="seconds")
        # une nouvelle liste : les annulations de l'ancienne sont oubliees (leurs numeros ne veulent plus rien dire,
        # et une ligne secrete retiree ne doit jamais revenir des semaines plus tard)
        if os.path.exists(chemin("annulation.json")):
            ecrire_json(chemin("annulation.json"), {"etapes": [], "oubliee": debut})
    etat = {"cree": maintenant().isoformat(timespec="seconds"), "debut": debut, "par": par, "fiches": len(fiches), "modele": modele,
            "propositions": liste, "appliquees": appliquees}
    ecrire_json(chemin("propositions.json"), etat)
    return etat


def en_attente(etat):
    deja = set(etat.get("appliquees") or [])
    return [p for p in etat.get("propositions") or [] if isinstance(p, dict) and p.get("n") not in deja and not p.get("obsolete")]


def en_cours(etat):
    """une liste encore en cours : recente, avec des propositions annoncees et pas encore appliquees"""
    try:
        cree = datetime.datetime.fromisoformat(etat.get("cree"))
        debut = datetime.datetime.fromisoformat(etat.get("debut") or etat.get("cree"))
    except (TypeError, ValueError):
        return False
    return (maintenant() - cree <= VALIDITE and maintenant() - debut <= DUREE_LISTE
            and any(p.get("type") != "info" for p in en_attente(etat)))


def cle_prop(p):
    """ce que vise une proposition (fiche, sorte, ligne visee, ce qui est propose). Seul le texte propose pour un projet
    endormi est laisse de cote : il porte la date du jour. La cible proposee d'un lien casse, elle, fait partie du sens :
    si elle change, c'est une autre proposition (le numero entendu n'applique jamais une autre cible)."""
    a = p.get("action")
    if isinstance(a, dict) and p.get("type") == "projet_endormi":
        a = {k: v for k, v in a.items() if k != "nouveau"}
    return (p.get("fiche"), p.get("type"), json.dumps(a, sort_keys=True))


def fusionner(ancien, trouvees):
    """les numeros deja annonces gardent leur sens : une proposition retrouvee garde son numero, une disparue devient
    « plus d'actualite » (son numero n'est jamais redonne), une nouvelle prend le numero suivant"""
    deja = set(ancien.get("appliquees") or [])
    par_cle = {cle_prop(p): p for p in trouvees}
    liste, vues = [], set()
    for p in ancien.get("propositions") or []:
        if not isinstance(p, dict) or not isinstance(p.get("n"), int):
            continue
        k = cle_prop(p)
        if p["n"] in deja:          # deja appliquee : si le meme souci revient, c'est un nouveau souci (nouveau numero)
            liste.append(p)
            continue
        vues.add(k)
        if k in par_cle:          # retrouvee (meme une « plus d'actualite » qui revient) : meme numero, meme sens
            q = dict(par_cle[k], n=p["n"])
            q.pop("obsolete", None)
            liste.append(q)
        else:
            liste.append(dict(p, obsolete=True))
    suivant = max([p["n"] for p in liste] + [0]) + 1
    attente = len(en_attente({"propositions": liste, "appliquees": list(deja)}))
    for p in trouvees:
        if cle_prop(p) in vues or attente >= MAX_PROPOSITIONS:
            continue
        liste.append(dict(p, n=suivant))
        suivant += 1
        attente += 1
    return liste, sorted(deja)


def rafraichir(etat, rel, texte):
    """apres NOTRE ecriture d'une fiche, ses autres propositions en attente restent applicables si elles visent encore
    quelque chose (sinon « la fiche a change » les bloquerait a tort)"""
    for p in en_attente(etat):
        if p.get("fiche") == rel and s_applique(p, texte):
            p["empreinte"] = empreinte(texte)


def exemple(P):
    ns = [p["n"] for p in P if p.get("type") != "info"][:2]
    return "« curateur, %s »" % " et ".join(str(n) for n in ns) if ns else "« curateur, tout »"


def liste_dite(etat):
    P = en_attente(etat)
    dites = " ".join("%d) %s" % (p["n"], p["titre"]) for p in P[:MAX_DITES])
    if len(P) > MAX_DITES:
        dites += " Et %d autre(s) sur la page du PC (menu, L'atelier)." % (len(P) - MAX_DITES)
    return P, dites


def phrase_examen(etat):
    P, dites = liste_dite(etat)
    n = etat.get("fiches", 0)
    if not P:
        return "J'ai relu la mémoire (%d fiches) : tout est en ordre, je n'ai rien à proposer." % n
    return ("J'ai relu la mémoire (%d fiches) : %d proposition(s). %s Rien n'est changé : dis %s pour en "
            "appliquer, ou « curateur, tout »." % (n, len(P), dites, exemple(P)))


def act_examiner(d, appel=None):
    etat = examiner("demande", not oui(d.get("sans_modele")), appel)
    return repondre(True, phrase_examen(etat), propositions=[{"n": p["n"], "titre": p["titre"]} for p in en_attente(etat)])


def act_propositions(_d):
    etat = lire_json(chemin("propositions.json"), {})
    if not etat.get("propositions"):
        return repondre(True, "Je n'ai aucune proposition en attente. Dis « curateur, fais ta tournée » pour que je relise la mémoire.")
    P, dites = liste_dite(etat)
    quand = datetime.datetime.fromisoformat(etat["cree"]).strftime("%d/%m à %Hh%M")
    if not P:
        return repondre(True, "Tout ce que j'avais proposé le %s est appliqué." % quand)
    return repondre(True, "Mes propositions du %s : %s Dis %s, ou « curateur, tout »." % (quand, dites, exemple(P)),
                    propositions=[{"n": p["n"], "titre": p["titre"]} for p in P])


# ---------------------------------------------------------------- appliquer et annuler
def oui(v):
    return v is True or plat(v).strip() in {"oui", "true", "1", "yes"}


def numeros_de(s, attente):
    """les numeros choisis. « tout » seulement s'il est dit seul (= toutes les propositions en attente). Une phrase avec
    une exception (« tout sauf la 3 », « pas la 2 ») est refusee : mieux vaut redemander qu'appliquer ce qui n'etait pas
    voulu. Des chiffres : seuls les chiffres comptent (« une seule : la 4 » -> 4)."""
    s = plat(s)
    if NEGATIONS.search(s):
        raise Erreur("Dis-moi seulement les numéros à appliquer, sans exception : par exemple « curateur, 1 et 3 ».")
    # entre deux chiffres, seuls des mots (verifies plus bas) et ces signes : « 1-3 », « 1−3 », « 1~3 », « 1..3 »,
    # « 1_3 » (de 1 a 3, ou 1 et 3 ?) font redemander
    for entre in re.findall(r"(?<=\d)\D+(?=\d)", s):
        if not re.fullmatch(r"[\s,;/&+#°']*", re.sub(r"[a-z]+", " ", entre)):
            raise Erreur("Je n'ai pas compris : dis chaque numéro, par exemple « curateur, 1, 2 et 3 ».")
    jetons = re.findall(r"\d+|[a-z]+", s)
    mots = [m for m in jetons if not m.isdigit()]
    if any(m not in PERMIS and m not in NOMBRES and m not in ("tout", "toutes", "tous") for m in mots):
        raise Erreur("Je n'ai pas compris : dis seulement les numéros à appliquer (par exemple « curateur, 1 et 3 »), "
                     "ou « curateur, tout ».")
    reste = [m for m in mots if m not in PERMIS]
    tout = [m for m in reste if m in ("tout", "toutes", "tous")]
    chiffres_dits = any(m.isdigit() for m in jetons)
    if tout and (chiffres_dits or len(tout) != len(reste)):
        raise Erreur("Je n'ai pas compris : dis « curateur, tout », ou seulement des numéros, par exemple « curateur, 1 et 3 ».")
    if tout:
        return sorted(attente)
    # « les deux », « ces deux-là » = les deux propositions, ou la n°2 ? « les 2 » dicte pareil : sur les mots (pas les
    # signes entre eux), un nombre en lettres apres « les »/« ces », ou un seul numero dit, fait redemander
    combien = len([m for m in jetons if m.isdigit() or m in NOMBRES])
    for i, m in enumerate(jetons):
        if m not in ("les", "ces"):
            continue
        j = i + 1
        while j < len(jetons) and jetons[j] in ("numero", "numeros", "n", "no", "proposition", "propositions"):
            j += 1
        suivant = jetons[j] if j < len(jetons) else ""
        if (suivant in NOMBRES and suivant not in ("un", "une")) or (suivant.isdigit() and combien == 1):
            raise Erreur("Je n'ai pas compris : dis chaque numéro à appliquer, par exemple « curateur, 1 et 3 », "
                         "ou « curateur, tout ».")
    # dans l'ordre dit ; « un », « une » sont des articles quand un chiffre est dit (« une seule : la 4 » -> 4)
    chiffres = [int(m) if m.isdigit() else NOMBRES[m] for m in jetons
                if m.isdigit() or (m in NOMBRES and not (chiffres_dits and m in ("un", "une")))]
    vus = []
    for x in chiffres:
        if x not in vus:
            vus.append(x)
    return vus


def copier_memoire():
    """une copie zip de toute la memoire avant de toucher a quoi que ce soit (les 10 dernieres sont gardees)"""
    dos = chemin("copies")
    os.makedirs(dos, exist_ok=True)
    nom = "memoire_%s.zip" % maintenant().strftime("%Y%m%d_%H%M%S")
    cible = os.path.join(dos, nom)
    i = 1
    while os.path.exists(cible):
        i += 1
        cible = os.path.join(dos, nom.replace(".zip", "_%d.zip" % i))
    racine = dos_memoire()
    with zipfile.ZipFile(cible + ".tmp", "w", zipfile.ZIP_DEFLATED) as z:
        for dos_, sous, fichiers in os.walk(racine):
            sous[:] = [s for s in sous if s != ".verrou_memoire"]
            for f in fichiers:
                c = os.path.join(dos_, f)
                z.write(c, os.path.relpath(c, racine))
    os.replace(cible + ".tmp", cible)
    vieilles = sorted(f for f in os.listdir(dos) if f.startswith("memoire_") and f.endswith(".zip"))
    for f in vieilles[:-COPIES_GARDEES]:      # nos propres copies, jamais une fiche
        try:
            os.remove(os.path.join(dos, f))
        except OSError:
            pass
    return os.path.basename(cible)


def oublier_du_journal(faits):
    """un fait retire ne doit plus s'afficher dans « les derniers faits retenus » de la page"""
    f = os.path.join(dos_memoire(), ".retenu.jsonl")
    if not faits or not os.path.exists(f):
        return
    try:
        retires = set(plat(sans_date(x)).strip() for x in faits)
        gardees = []
        with open(f, encoding="utf-8") as h:
            for l in h.read().splitlines():
                try:
                    if l.strip() and plat(json.loads(l).get("fait")).strip() not in retires:
                        gardees.append(l)
                except ValueError:
                    gardees.append(l)
        with open(f + ".tmp", "w", encoding="utf-8", newline="\n") as h:
            h.write("\n".join(gardees) + ("\n" if gardees else ""))
        os.replace(f + ".tmp", f)
    except OSError:
        pass


def act_appliquer(d):
    etat = lire_json(chemin("propositions.json"), {})
    L = etat.get("propositions") or []
    if not L:
        raise Erreur("Je n'ai aucune proposition en attente : dis « curateur, fais ta tournée » d'abord.")
    try:
        cree = datetime.datetime.fromisoformat(etat["cree"])
    except (KeyError, TypeError, ValueError):
        cree = datetime.datetime(2000, 1, 1)
    if maintenant() - cree > VALIDITE:
        raise Erreur("Mes propositions ont plus d'une semaine : je refais une tournée d'abord (« curateur, fais ta tournée »).")
    attente = [p["n"] for p in en_attente(etat)]
    choix = numeros_de(d.get("numeros") or d.get("texte") or "", attente)
    if not choix:
        raise Erreur("Dis-moi quels numéros appliquer, par exemple « curateur, 1 et 3 », ou « curateur, tout ».")
    deja = set(etat.get("appliquees") or [])
    par_n = {p.get("n"): p for p in L if isinstance(p, dict)}
    voulues = [par_n[n] for n in choix if n in attente]
    sautees = [(n, "déjà appliquée" if n in deja else "plus d'actualité" if par_n.get(n, {}).get("obsolete")
                else "pas dans la liste") for n in choix if n not in attente]
    if not voulues:
        if all(n in deja for n in choix):
            return repondre(True, "C'est déjà appliqué.")
        raise Erreur("Rien à appliquer : " + " ; ".join("%d (%s)" % s for s in sautees) + ". Dis « curateur, tes propositions » pour la liste.")
    faites, plan, secrets = [], [], False
    with Verrou():
        copie = copier_memoire()
        par_fiche = {}
        for p in voulues:
            par_fiche.setdefault(p["fiche"], []).append(p)
        # 1. tout preparer, sans rien ecrire
        for rel, items in par_fiche.items():
            c = fiche_de(rel)
            try:
                with open(c, encoding="utf-8", newline="") as h:
                    texte = h.read()
            except OSError:
                sautees += [(p["n"], "la fiche n'existe plus") for p in items]
                continue
            nouveau, archiver, nums, retires = texte, False, [], []
            for p in items:
                if empreinte(texte) != p.get("empreinte"):
                    sautees.append((p["n"], "la fiche a changé depuis la tournée"))
                    continue
                a = p.get("action") or {}
                t = a.get("type")
                if t == "remplacer" and a.get("ancien") and a["ancien"] in nouveau:
                    nouveau = nouveau.replace(a["ancien"], str(a.get("nouveau") or ""), 1)
                elif t == "retirer_ligne":
                    lignes = nouveau.split("\n")
                    i = trouver_ligne(lignes, a)
                    if i is None:
                        sautees.append((p["n"], "la ligne n'y est plus"))
                        continue
                    retires.append(lignes.pop(i).strip()[2:])
                    nouveau = "\n".join(lignes)
                    secrets = secrets or p.get("type") == "secret"
                elif t == "archiver":
                    archiver = True
                elif t != "info":
                    sautees.append((p["n"], "je ne sais pas faire ça"))
                    continue
                nums.append(p["n"])
            if not nums:
                continue
            if archiver:
                dossier, nom = os.path.split(rel)
                vers = "/".join(x for x in ("_archives", dossier, "%s_%s.md" % (nom[:-3], maintenant().strftime("%Y%m%d_%H%M%S"))) if x)
                plan.append({"type": "archive", "fiche": rel, "vers": vers, "avant": texte, "apres": empreinte(nouveau), "numeros": nums,
                             "_nouveau": nouveau, "_retires": retires})
            elif nouveau != texte:
                plan.append({"type": "modif", "fiche": rel, "avant": texte, "apres": empreinte(nouveau), "numeros": nums,
                             "_nouveau": nouveau, "_retires": retires})
            else:
                faites += nums          # rien a ecrire (une info) : c'est vu
        # 2. l'annulation est ecrite AVANT la premiere fiche : une panne au milieu reste annulable
        if plan:
            pile = lire_annulation()
            pile["etapes"].append({"quand": maintenant().isoformat(timespec="seconds"), "copie": copie,
                                   "fiches": [{k: v for k, v in e.items() if not k.startswith("_")} for e in plan]})
            ecrire_json(chemin("annulation.json"), pile)
        # 3. les fiches ; quoi qu'il arrive, l'etat dit ce qui a vraiment ete ecrit
        try:
            for e in plan:
                c = fiche_de(e["fiche"])
                if e["type"] == "archive":
                    cv = fiche_de(e["vers"])
                    if e["_nouveau"] != e["avant"]:
                        ecrire_texte(c, e["_nouveau"])
                    os.makedirs(os.path.dirname(cv), exist_ok=True)
                    os.replace(c, cv)
                else:
                    ecrire_texte(c, e["_nouveau"])
                    rafraichir(etat, e["fiche"], e["_nouveau"])
                faites += e["numeros"]
                oublier_du_journal(e["_retires"])
        finally:
            etat["appliquees"] = sorted(deja | set(faites))
            for e in plan:              # les autres propositions de ces fiches suivent le nouveau texte
                if e["type"] == "modif" and set(e["numeros"]) <= set(faites):
                    rafraichir(etat, e["fiche"], e["_nouveau"])
            ecrire_json(chemin("propositions.json"), etat)
    try:
        with open(chemin("journal.jsonl"), "a", encoding="utf-8") as h:
            h.write(json.dumps({"quand": maintenant().isoformat(timespec="seconds"), "faites": faites,
                                "sautees": [n for n, _ in sautees], "copie": copie}, ensure_ascii=False) + "\n")
    except OSError:
        pass
    phrase = ("C'est fait : %s appliqué(e)s. J'ai gardé une copie de la mémoire d'avant (%s). Pour revenir en arrière : « curateur, annule »."
              % (" et ".join(str(n) for n in faites), copie) if faites else "Je n'ai rien appliqué.")
    if sautees:
        phrase += " Pas fait : " + " ; ".join("%d (%s)" % s for s in sautees) + "."
    if secrets and faites:
        phrase += (" La ligne retirée reste dans les copies de sécurité du curateur (dossier curateur : copies, et annulation.json "
                   "jusqu'à la prochaine liste) : efface les copies si tu veux qu'elle disparaisse tout à fait.")
    return repondre(bool(faites), phrase, faites=faites, sautees=[n for n, _ in sautees], copie=copie)


def lire_annulation():
    """la pile des applications depuis la tournee : « annuler » les defait toutes, de la plus recente a la plus ancienne"""
    a = lire_json(chemin("annulation.json"), {})
    etapes = a.get("etapes") if isinstance(a, dict) else None
    if not isinstance(etapes, list):            # l'ancien format : une seule application
        etapes = [{"quand": a.get("quand"), "copie": a.get("copie"), "fiches": a["fiches"]}] if isinstance(a, dict) and a.get("fiches") else []
    return {"etapes": [e for e in etapes if isinstance(e, dict) and e.get("fiches")]}


def act_annuler(_d):
    pile = lire_annulation()
    if not pile["etapes"]:
        raise Erreur("Il n'y a rien à annuler.")
    remises, laissees, rendus, textes = [], [], set(), {}
    with Verrou():
        for etape in reversed(pile["etapes"]):
            for e in reversed(etape["fiches"]):
                c = fiche_de(e["fiche"])
                nums = set(x for x in e.get("numeros") or [] if isinstance(x, int))
                if e.get("type") == "archive":
                    cv = fiche_de(e["vers"])
                    if not os.path.exists(c) and os.path.exists(cv):
                        os.replace(cv, c)
                        ecrire_texte(c, e["avant"])
                        remises.append(e["fiche"])
                        rendus |= nums
                        textes[e["fiche"]] = e["avant"]
                    elif os.path.exists(c) and not os.path.exists(cv):
                        # jamais archivee (panne au milieu) : la fiche a peut-etre deja ete reecrite (ligne retiree)
                        try:
                            with open(c, encoding="utf-8", newline="") as h:
                                actuel = h.read()
                        except OSError:
                            actuel = None
                        if actuel == e["avant"]:
                            rendus |= nums
                        elif actuel is not None and e.get("apres") and empreinte(actuel) == e["apres"]:
                            ecrire_texte(c, e["avant"])
                            remises.append(e["fiche"])
                            rendus |= nums
                            textes[e["fiche"]] = e["avant"]
                        else:
                            laissees.append(e["fiche"])
                    else:
                        laissees.append(e["fiche"])
                    continue
                try:
                    with open(c, encoding="utf-8", newline="") as h:
                        actuel = h.read()
                except OSError:
                    actuel = None
                if actuel is not None and empreinte(actuel) == e.get("apres"):
                    ecrire_texte(c, e["avant"])
                    remises.append(e["fiche"])
                    rendus |= nums
                    textes[e["fiche"]] = e["avant"]
                elif actuel is not None and actuel == e.get("avant"):
                    rendus |= nums          # jamais ecrite (panne au milieu) : deja comme avant
                else:
                    laissees.append(e["fiche"])
        ecrire_json(chemin("annulation.json"), {"etapes": [], "annulee": maintenant().isoformat(timespec="seconds")})
        etat = lire_json(chemin("propositions.json"), {})
        if etat.get("propositions"):
            etat["appliquees"] = sorted(set(etat.get("appliquees") or []) - rendus)   # seulement ce qui a vraiment ete remis
            for rel, texte in textes.items():
                rafraichir(etat, rel, texte)
            ecrire_json(chemin("propositions.json"), etat)
    remises = list(dict.fromkeys(remises))
    phrase = "C'est annulé : %d fiche(s) remise(s) comme avant." % len(remises)
    if laissees:
        phrase += (" Je n'ai pas touché à %s : elle(s) a(ont) changé depuis (la copie %s reste là)."
                   % (", ".join(dict.fromkeys(laissees)), pile["etapes"][-1].get("copie") or ""))
    return repondre(bool(remises or rendus), phrase, remises=remises, laissees=laissees)


# ---------------------------------------------------------------- la tournee du dimanche
def annoncer(texte):
    """l'annonce part comme un rappel du planificateur : Telegram, l'appli et la page du PC"""
    script = os.path.join(base(), "outils", "planificateur", "planificateur.py")
    if not os.path.exists(script):
        return False
    f = chemin("annonce_%d.json" % int(time.time() * 1000))
    ecrire_json(f, {"texte": texte, "de": "curateur"})
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


def tournee(appel=None):
    etat = examiner("tournee", True, appel)
    n = len(en_attente(etat))
    annonce = False
    if n:
        prenom = (os.environ.get("ARCHI_UTILISATEUR") or "").strip()[:30]
        annonce = annoncer("%sle curateur a relu la mémoire : %d proposition(s) pour la ranger. Dis « curateur, tes propositions » "
                           "pour les entendre. Rien ne change sans ton accord." % ((prenom + ", ") if prenom else "", n))
    return repondre(True, phrase_examen(etat), tournee=True, annonce=annonce, nombre=n)


ACTIONS = {"examiner": act_examiner, "propositions": act_propositions, "appliquer": act_appliquer, "annuler": act_annuler}
# des mots pour LIRE seulement : rien qui change la memoire ne passe par un synonyme (l'accord est verifie sur « appliquer » et « annuler »)
SYNONYMES = {"tournee": "examiner", "relire": "examiner", "relis": "examiner", "ranger": "examiner", "range": "examiner",
             "verifier": "examiner", "examine": "examiner", "menage": "examiner", "etat": "propositions", "liste": "propositions",
             "lister": "propositions", "voir": "propositions"}


MODIFIENT = ("appliquer", "annuler")      # les memes que sensible_si dans outil.json


def action_de(d, defaut):
    """le nom de l'action, tel quel (accents et majuscules mis a part) : on ne retire AUCUN caractere, sinon « appliquer. »
    passerait le controle d'accord du lanceur sous un autre nom, puis serait lu « appliquer » ici"""
    brut = d.get("action")
    if brut is None or (isinstance(brut, str) and not brut.strip()):
        return defaut
    if not isinstance(brut, str):
        raise Erreur("L'action doit être un mot, par exemple « examiner ».")
    a = re.sub(r"[\s'-]+", "_", plat(brut).strip())
    if not re.fullmatch(r"[a-z_]{1,30}", a):
        raise Erreur("Action inconnue. Actions : examiner, propositions, appliquer (numeros), annuler.")
    return a


def main():
    pa = argparse.ArgumentParser()
    pa.add_argument("--fichier")
    pa.add_argument("--tournee", action="store_true")
    a = pa.parse_args()
    try:
        if a.tournee:
            tournee()
            return
        d = {}
        if a.fichier:
            with open(a.fichier, encoding="utf-8-sig") as h:
                d = json.load(h)
        if not isinstance(d, dict):
            d = {}
        act = action_de(d, "examiner")
        act = SYNONYMES.get(act, act)
        if act not in ACTIONS:
            raise Erreur("Action inconnue « %s ». Actions : examiner, propositions, appliquer (numeros), annuler." % act[:30])
        if act in MODIFIENT and str(d.get("_accord") or "").strip().lower() != "oui":
            raise Erreur("« %s » change la mémoire : il me faut ton accord (outils_maison avec accord=oui)." % act)
        ACTIONS[act](d)
    except Erreur as e:
        repondre(False, str(e))
    except Exception as e:
        repondre(False, "Le curateur a eu un pépin : %s." % type(e).__name__, erreur=str(e)[:200])


if __name__ == "__main__":
    main()
