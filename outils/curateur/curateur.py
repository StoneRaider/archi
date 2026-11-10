# curateur.py - outil maison d'Archi : le CURATEUR relit le chateau (la memoire en fiches Markdown) et propose du
# rangement. Il ne change RIEN tout seul : l'utilisateur choisit les numeros (10/11/2026).
#   python curateur.py --fichier demande.json     (appele par outils_maison)
#     examiner (defaut) : relit toutes les fiches et rend une liste NUMEROTEE de propositions. Rien n'est change.
#                         sans_modele=oui : sans le modele local (il ne cherche alors pas les contradictions)
#     propositions      : relit les propositions en attente (celles de la derniere tournee)
#     appliquer         : numeros = "1 et 3" | "1,3" | "tout". Exige accord=oui (outils_maison) : c'est le oui de l'utilisateur.
#                         Copie de toute la memoire avant (curateur\copies), puis SEULEMENT les numeros choisis.
#     annuler           : remet les fiches comme avant la derniere application, si personne n'y a touche depuis.
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
                    if time.time() - os.path.getmtime(self.dossier) > 60:
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
                                     {"type": "retirer_ligne", "ligne": l}))
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
        for m in LIEN.finditer(f["texte"]):
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
                                     % (f["nom"], court(sans_date(fait), 90), ou), {"type": "retirer_ligne", "ligne": ligne}))
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
                             {"type": "retirer_ligne", "ligne": ancien[0]}))
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
    gardees = gardees[:MAX_PROPOSITIONS]
    for i, p in enumerate(gardees):
        p["n"] = i + 1
    etat = {"cree": maintenant().isoformat(timespec="seconds"), "par": par, "fiches": len(fiches), "modele": modele,
            "propositions": gardees, "appliquees": []}
    ecrire_json(chemin("propositions.json"), etat)
    return etat


def liste_dite(etat, deja=()):
    P = [p for p in etat.get("propositions") or [] if p.get("n") not in set(deja)]
    dites = " ".join("%d) %s" % (p["n"], p["titre"]) for p in P[:MAX_DITES])
    if len(P) > MAX_DITES:
        dites += " Et %d autre(s) sur la page du PC (menu, L'atelier)." % (len(P) - MAX_DITES)
    return P, dites


def phrase_examen(etat):
    P, dites = liste_dite(etat)
    n = etat.get("fiches", 0)
    if not P:
        return "J'ai relu la mémoire (%d fiches) : tout est en ordre, je n'ai rien à proposer." % n
    return ("J'ai relu la mémoire (%d fiches) : %d proposition(s). %s Rien n'est changé : dis « curateur, 1 et 3 » pour en "
            "appliquer, ou « curateur, tout »." % (n, len(P), dites))


def act_examiner(d, appel=None):
    etat = examiner("demande", not oui(d.get("sans_modele")), appel)
    return repondre(True, phrase_examen(etat), propositions=[{"n": p["n"], "titre": p["titre"]} for p in etat["propositions"]])


def act_propositions(_d):
    etat = lire_json(chemin("propositions.json"), {})
    if not etat.get("propositions"):
        return repondre(True, "Je n'ai aucune proposition en attente. Dis « curateur, fais ta tournée » pour que je relise la mémoire.")
    P, dites = liste_dite(etat, etat.get("appliquees") or [])
    quand = datetime.datetime.fromisoformat(etat["cree"]).strftime("%d/%m à %Hh%M")
    if not P:
        return repondre(True, "Tout ce que j'avais proposé le %s est appliqué." % quand)
    return repondre(True, "Mes propositions du %s : %s Dis « curateur, 1 et 3 », ou « curateur, tout »." % (quand, dites),
                    propositions=[{"n": p["n"], "titre": p["titre"]} for p in P])


# ---------------------------------------------------------------- appliquer et annuler
def oui(v):
    return v is True or plat(v).strip() in {"oui", "true", "1", "yes"}


def numeros_de(s, n):
    s = plat(s)
    if re.search(r"\b(tout|toutes|tous)\b", s):
        return list(range(1, n + 1))
    vus = []
    for m in re.finditer(r"\d+|[a-z]+", s):
        x = int(m.group(0)) if m.group(0).isdigit() else NOMBRES.get(m.group(0))
        if x and 1 <= x <= n and x not in vus:
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
    choix = numeros_de(d.get("numeros") or d.get("texte") or "", len(L))
    if not choix:
        raise Erreur("Dis-moi quels numéros appliquer, par exemple « curateur, 1 et 3 », ou « curateur, tout ».")
    deja = set(etat.get("appliquees") or [])
    voulues = [p for p in L if p.get("n") in choix and p.get("n") not in deja]
    if not voulues:
        return repondre(True, "C'est déjà appliqué.")
    faites, sautees, annulation, retires = [], [], [], []
    with Verrou():
        copie = copier_memoire()
        par_fiche = {}
        for p in voulues:
            par_fiche.setdefault(p["fiche"], []).append(p)
        for rel, items in par_fiche.items():
            c = fiche_de(rel)
            try:
                with open(c, encoding="utf-8", newline="") as h:
                    texte = h.read()
            except OSError:
                sautees += [(p["n"], "la fiche n'existe plus") for p in items]
                continue
            if empreinte(texte) != items[0].get("empreinte"):
                sautees += [(p["n"], "la fiche a changé depuis la tournée") for p in items]
                continue
            nouveau, archiver = texte, False
            for p in items:
                a = p.get("action") or {}
                t = a.get("type")
                if t == "remplacer" and a.get("ancien") and a["ancien"] in nouveau:
                    nouveau = nouveau.replace(a["ancien"], str(a.get("nouveau") or ""), 1)
                elif t == "retirer_ligne":
                    lignes = nouveau.split("\n")
                    cible = str(a.get("ligne") or "").rstrip("\r")
                    i = next((k for k, l in enumerate(lignes) if l.rstrip("\r") == cible), None)
                    if i is None:
                        sautees.append((p["n"], "la ligne n'y est plus"))
                        continue
                    retires.append(lignes.pop(i).strip()[2:])
                    nouveau = "\n".join(lignes)
                elif t == "archiver":
                    archiver = True
                elif t != "info":
                    sautees.append((p["n"], "je ne sais pas faire ça"))
                    continue
                faites.append(p["n"])
            if archiver:
                dossier, nom = os.path.split(rel)
                vers = "/".join(x for x in ("_archives", dossier, "%s_%s.md" % (nom[:-3], maintenant().strftime("%Y%m%d_%H%M%S"))) if x)
                cv = fiche_de(vers)
                if nouveau != texte:
                    ecrire_texte(c, nouveau)
                os.makedirs(os.path.dirname(cv), exist_ok=True)
                os.replace(c, cv)
                annulation.append({"type": "archive", "fiche": rel, "vers": vers, "avant": texte})
            elif nouveau != texte:
                ecrire_texte(c, nouveau)
                annulation.append({"type": "modif", "fiche": rel, "avant": texte, "apres": empreinte(nouveau)})
        oublier_du_journal(retires)
        if annulation:
            ecrire_json(chemin("annulation.json"), {"quand": maintenant().isoformat(timespec="seconds"), "copie": copie, "fiches": annulation})
        etat["appliquees"] = sorted(deja | set(faites))
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
    return repondre(bool(faites), phrase, faites=faites, sautees=[n for n, _ in sautees], copie=copie)


def act_annuler(_d):
    a = lire_json(chemin("annulation.json"), {})
    if not a.get("fiches"):
        raise Erreur("Il n'y a rien à annuler.")
    remises, laissees = [], []
    with Verrou():
        for e in a["fiches"]:
            c = fiche_de(e["fiche"])
            if e.get("type") == "archive":
                cv = fiche_de(e["vers"])
                if not os.path.exists(c) and os.path.exists(cv):
                    os.replace(cv, c)
                    ecrire_texte(c, e["avant"])
                    remises.append(e["fiche"])
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
            else:
                laissees.append(e["fiche"])
        ecrire_json(chemin("annulation.json"), {"quand": a.get("quand"), "annulee": maintenant().isoformat(timespec="seconds"), "fiches": []})
        etat = lire_json(chemin("propositions.json"), {})
        if etat.get("propositions"):
            etat["appliquees"] = []
            ecrire_json(chemin("propositions.json"), etat)
    phrase = "C'est annulé : %d fiche(s) remise(s) comme avant." % len(remises)
    if laissees:
        phrase += " Je n'ai pas touché à %s : elle(s) a(ont) changé depuis (la copie %s reste là)." % (", ".join(laissees), a.get("copie", ""))
    return repondre(bool(remises), phrase, remises=remises, laissees=laissees)


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
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
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
    n = len(etat["propositions"])
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
        act = re.sub(r"[^a-z_]", "", plat(d.get("action") or "examiner"))
        act = SYNONYMES.get(act, act)
        if act not in ACTIONS:
            raise Erreur("Action inconnue « %s ». Actions : examiner, propositions, appliquer (numeros), annuler." % act[:30])
        ACTIONS[act](d)
    except Erreur as e:
        repondre(False, str(e))
    except Exception as e:
        repondre(False, "Le curateur a eu un pépin : %s." % type(e).__name__, erreur=str(e)[:200])


if __name__ == "__main__":
    main()
