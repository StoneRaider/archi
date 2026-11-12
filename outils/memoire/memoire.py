# memoire.py - outil maison d'Archi : sa memoire long terme, en fiches Markdown dans le chateau (memoire\<piece>\<sujet>.md).
# Tout reste sur le PC : c'est le modele local (LM Studio) qui repere ce qu'il faut retenir.
#   python memoire.py --fichier demande.json
#   demande.json : {"action": "...", ...}
#     retenir : texte=<le message de l'utilisateur>. Le modele local releve les faits DURABLES que l'utilisateur affirme
#               sur lui, ses proches, ses projets, ses lieux et ses gouts ; l'outil les verifie puis les range.
#               Appele TOUT SEUL par le workflow a chaque message, en arriere-plan (--menage) : l'agent n'a pas a y penser,
#               et la reponse n'attend pas. a_blanc=oui : ne range rien. Les faits retenus sont notes dans memoire\.retenu.jsonl.
#     ecrire  : piece=, sujet=, fait=           un fait dicte tel quel (« retiens que... »)
#     lister  : piece= (facultatif)             les fiches et leur nombre de faits
#     lire    : sujet= (piece= facultatif)      les faits d'une fiche ; sans sujet : tout ce qu'Archi sait
#     oublier : texte=<mots a retrouver>        ESSAI A BLANC : montre les faits concernes ; confirmer=oui : les retire
#     catalogue :                            refait memoire\catalogue.md (une ligne par fiche)
#     lecon   : texte=<la reponse de l'utilisateur>, reponse=<la reponse d'Archi juste avant>
#               Si l'utilisateur CORRIGE Archi (« non, tu ne sais pas faire ca »), le modele local en tire UNE regle courte,
#               rangee dans memoire\lecons\lecons_archi.md et relue par Archi a chaque message (core/contexte.js).
#               Appele tout seul par le workflow avec « retenir » (champ reponse_precedente). Idee reprise de Brahma.
#               Une lecon ne touche jamais aux regles de securite (accord, secrets) : elle est refusee.
# Garde-fous : jamais de mot de passe, de code, de numero de carte, d'IBAN, d'adresse postale ni de numero de telephone ;
# un fait doit reprendre des mots du message (rien d'invente) ; au plus 3 faits par message ; pas de doublon.

import argparse
import datetime
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request

# Le chateau a la meme forme que celui de l'Archi d'origine : des pieces, une fiche par chose, un en-tete (type, piece,
# statut, maj, alias, resume), les rubriques Faits / Hypotheses / Sources / Prochaines etapes / Liens, des liens types
# « relation :: [[fiche]] » (memoire\methodes\ontologie.md), un index par piece et catalogue.md (une ligne par fiche).
# Le greffier ecrit dans 7 pieces ; les autres (lecons, methodes, bibliotheque, enquetes, documents) ne sont pas a lui.
PIECES = ("moi", "personnes", "lieux", "projets", "passions", "travail", "preferences")
# les lecons : une piece a part, jamais remplie par « retenir » (elle n'est pas dans PIECES), mais lue, listee et oubliee
TOUTES = PIECES + ("lecons",)
SORTES = {"moi": "moi", "personnes": "personne", "lieux": "lieu", "projets": "projet", "passions": "passion",
          "travail": "travail", "preferences": "preference", "lecons": "lecon"}
INDEX = {"moi": "Moi", "personnes": "Personnes", "lieux": "Lieux", "projets": "Projets", "passions": "Passions",
         "travail": "Travail", "preferences": "Préférences", "lecons": "Leçons"}
# les liens permis (ontologie) ; un lien qui ne colle a aucune relation devient « voir_aussi »
RELATIONS = ("famille", "ami", "couple", "animal", "membre_de", "habite", "situe_a", "participe", "client",
             "fait_partie_de", "utilise", "voir_aussi")
# ces pieces tiennent en une seule fiche ; le chateau peut en choisir d'autres dans memoire\.greffier.json
# (pas « moi.md » : sous Windows, ce serait le meme fichier que l'index « Moi.md »)
FICHE_UNIQUE_DEFAUT = {"moi": "profil", "preferences": "mes_preferences", "lecons": "lecons_archi"}
DETERMINANTS = re.compile(r"^(mon|ma|mes|le|la|les|l'|notre|nos|un|une)\s*")
MAX_LECONS = 40
MAX_LECON = 200
# la reponse de l'utilisateur ressemble-t-elle a une correction ? (sinon, on ne derange pas le modele)
CORRECTION = re.compile(r"(^|[^a-z])(non|faux|fausse|erreur|tort|inexact|n'importe quoi|"
                        r"tu te (trompes|plantes)|c'est pas (ca|vrai|juste|bon)|ce n'est pas (ca|vrai|juste|bon)|"
                        r"tu (ne )?(sais|peux) pas|tu n'as pas|tu as invente|t'as invente|n'invente|arrete de|"
                        r"je t'ai (deja )?dit|pas comme ca|pas du tout|tu n'es pas capable|tu ne sais rien)([^a-z]|$)")
# une lecon ne change jamais les garde-fous : ce qui en parle est refuse, meme si l'utilisateur le dit
TOUCHE_AUX_REGLES = re.compile(r"accord|confirm|sans (me |lui |te |nous |leur )?(demander|verifier|attendre|poser|prevenir|permission)|"
                               r"ignore|outrepass|contourn|desactiv|directement|tout de suite|feu vert|apercu|permission|"
                               r"consigne|instruction|contenu|supprim|effac|pas besoin|plus besoin|n'attends|"
                               r"ne (montre|demande|verifie|previens|relis) plus|"
                               r"mot de passe|secret|cle api|jeton|token|regle", re.I)
# ... et elle a l'une de ces formes : ce qu'Archi ne sait pas faire, ce qu'il ne doit plus dire, ce qu'il doit relire
FORME_LECON = re.compile(r"^(tu ne (sais|peux) pas|tu n'(as|es) pas|ne (propose|promets|dis|confonds|reponds|presente|annonce) |"
                         r"n'(invente|affirme|annonce|oublie) |relis |verifie )")
MAX_FAITS = 3
MAX_FAIT = 220
VIDES = set(("avec avoir dans pour plus mais tout tous toute toutes cette celle celui ceux sont etre fait faire peux peut veux "
             "vais vous nous elle elles leur leurs quoi quel quelle quels quelles comment quand alors donc aussi tres bien "
             "comme encore parce depuis chez entre sans sous vers votre notre cela ceci moins autre autres meme "
             "utilisateur utilisatrice appelle "
             "est les des une aux par sur que qui son ses mes ton tes pas ont eux lui ils mon ces pour moi toi").split())
# ce qu'on ne retient JAMAIS tout seul
SECRETS = re.compile(r"mot\s+de\s+passe|password|passe\s*:|code\s+(pin|secret|de\s+la\s+carte|d'acces)|\biban\b|\bcvv\b|"
                     r"numero\s+de\s+(carte|compte|securite)|cle\s+(api|secrete|privee)|\btoken\b|\bjeton\b|\b\d{13,19}\b|"
                     r"\b[a-z]{2}\d{2}(\s?\d{4}){3,}", re.I)
TELEPHONE = re.compile(r"(\+\d[\d .-]{7,})|(\b0\d([ .-]?\d\d){4}\b)")
ADRESSE = re.compile(r"\b\d{1,4}(\s?(bis|ter))?,?\s+(rue|avenue|av\.|boulevard|bd|chemin|impasse|allee|place|route|quai|cours)\b", re.I)
PREMIERE_PERSONNE = re.compile(r"(^|[^a-z])(je|j|me|m|moi|mon|ma|mes|nous|notre|nos|on)([^a-z]|$)")

CONSIGNE = """Reasoning: low
Tu es le greffier de la mémoire d'un assistant personnel. On te donne UN message écrit par l'utilisateur{prenom}.
Relève les faits DURABLES que l'utilisateur affirme sur lui-même, ses proches (famille, amis, animaux), ses projets, ses lieux, ses goûts et ses habitudes : ce qui sera encore vrai dans un mois.
Peu importe la forme du message : même une question ou une demande peut contenir au passage une information sur lui (« mon chien, qui s'appelle Rex, … ») ; relève-la. Même une question sur toi ou sur la mémoire (« tu vas t'en souvenir ? », « tu vas créer une fiche ? ») : si elle nomme un proche, un animal, un lieu ou un projet, ce nom est un fait à relever.
Réponds {{"faits":[]}} seulement quand le message n'apprend rien de durable sur lui : un ordre, un rappel à programmer, une humeur ou une activité du moment, la météo.
N'invente rien, ne déduis rien : reprends les mots du message. Jamais de mot de passe, de code, de numéro de carte, d'IBAN, d'adresse postale ni de numéro de téléphone.
Réponds UNIQUEMENT par un objet JSON : {{"faits":[{{"piece":"...","sujet":"...","fait":"...","relation":"...","avec":"..."}}]}}
- piece : personnes (un proche, un groupe ou un animal), lieux, projets, passions (un loisir, un sport, une musique pratiqués), travail (son métier, ses collègues, ses clients), preferences (ce qu'il aime, déteste ou préfère, sa façon de vouloir les réponses), moi (le reste : identité, santé, habitudes).
- sujet : le prénom de la personne ou de l'animal, le nom du projet, du lieu ou de la passion. Un proche désigné seulement par son lien (« mon père », « ma voisine ») dont le message dit quelque chose de durable (un goût, un métier, un âge) : piece personnes, sujet = ce lien, tel quel. Le simple fait de nommer un proche dans une demande (« écris à ma sœur ») n'apprend rien. Si une fiche existe déjà pour cette chose (liste plus bas, avec ses autres noms entre parenthèses), reprends EXACTEMENT le nom de la fiche. Pour moi et preferences : "moi".
- fait : une phrase complète à la troisième personne, qui se comprend seule{appelle}.
- relation et avec : le lien entre ce sujet et une autre chose nommée dans le message (avec = son nom, ou "moi" pour l'utilisateur). relation parmi : famille, ami, couple, animal, membre_de, habite, situe_a, participe, client, voir_aussi. Pas de lien : "" et "".
Exemples :
« Si je te parle de mon chien, qui s'appelle Rex, tu t'en souviendras ? » -> {{"faits":[{{"piece":"personnes","sujet":"Rex","fait":"Rex est le chien de l'utilisateur.","relation":"animal","avec":"moi"}}]}}
« J'adore le jazz mais je déteste le rap. » -> {{"faits":[{{"piece":"preferences","sujet":"moi","fait":"L'utilisateur adore le jazz et déteste le rap.","relation":"","avec":""}}]}}
« Mon grand projet, c'est de restaurer un voilier à La Rochelle. » -> {{"faits":[{{"piece":"projets","sujet":"voilier","fait":"L'utilisateur a pour projet de restaurer un voilier à La Rochelle.","relation":"situe_a","avec":"La Rochelle"}}]}}
« Ma sœur Léa est vétérinaire à Lyon. » -> {{"faits":[{{"piece":"personnes","sujet":"Léa","fait":"Léa est la sœur de l'utilisateur ; elle est vétérinaire à Lyon.","relation":"famille","avec":"moi"}}]}}
« Réponds-moi toujours en deux phrases maximum. » -> {{"faits":[{{"piece":"preferences","sujet":"moi","fait":"L'utilisateur veut des réponses de deux phrases maximum.","relation":"","avec":""}}]}}
« Rappelle-moi d'appeler le dentiste demain. » -> {{"faits":[]}}
« Je suis crevé, quelle journée ! » -> {{"faits":[]}}{connues}"""


SCHEMA = {"type": "json_schema", "json_schema": {"name": "faits_a_retenir", "strict": True, "schema": {
    "type": "object", "required": ["faits"], "additionalProperties": False, "properties": {"faits": {"type": "array", "items": {
        "type": "object", "required": ["piece", "sujet", "fait", "relation", "avec"], "additionalProperties": False, "properties": {
            "piece": {"type": "string", "enum": list(PIECES)}, "sujet": {"type": "string"}, "fait": {"type": "string"},
            "relation": {"type": "string", "enum": [""] + [r for r in RELATIONS if r not in ("fait_partie_de", "utilise")]},
            "avec": {"type": "string"}}}}}}}}


class Erreur(Exception):
    pass


def repondre(ok, phrase, **extra):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(dict(ok=ok, phrase_pour_utilisateur=phrase, **extra), ensure_ascii=False))


def oui(v):
    return str(v or "").strip().lower() in ("oui", "o", "yes", "true", "1", "vrai")


def plat(t):
    """minuscules, sans accents : pour comparer"""
    t = unicodedata.normalize("NFD", str(t or "").lower()).replace("œ", "oe").replace("æ", "ae")
    return "".join(c for c in t if unicodedata.category(c) != "Mn").replace("’", "'")


def mots(t, mini=4):
    return [m for m in re.split(r"[^a-z0-9]+", plat(t)) if len(m) >= mini and m not in VIDES]


def nom_de_fiche(sujet):
    """un nom de fichier sur : lettres, chiffres et tirets bas ; jamais de chemin"""
    t = plat(sujet).strip()
    t = re.sub(r"^(mon|ma|mes|le|la|les|l'|notre|nos|un|une)\s+(?=\S)", "", t) if " " in t or "'" in t else t   # « mon père » -> pere
    s = re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:40].strip("_")
    return s


def base_memoire():
    base = os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files")
    return os.path.join(base, "memoire")


def reglages():
    """memoire\\.greffier.json (facultatif) : {"fiches_uniques": {"moi": "...", "preferences": "..."}, "catalogue": true}"""
    try:
        with open(os.path.join(base_memoire(), ".greffier.json"), encoding="utf-8-sig") as h:
            r = json.load(h)
        return r if isinstance(r, dict) else {}
    except (OSError, ValueError):
        return {}


def fiche_unique(piece):
    propre = nom_de_fiche((reglages().get("fiches_uniques") or {}).get(piece) or "")
    return propre or FICHE_UNIQUE_DEFAUT.get(piece)


def chemin_fiche(piece, sujet):
    if piece not in TOUTES:
        raise Erreur("piece inconnue : " + str(piece)[:30])
    nom = fiche_unique(piece) or nom_de_fiche(sujet)
    if not nom:
        raise Erreur("sujet manquant")
    return os.path.join(base_memoire(), piece, nom + ".md")


# ---------------------------------------------------------------- l'en-tete d'une fiche
def lire_entete(texte):
    """({cle: valeur}, corps) ; sans en-tete : ({}, texte)"""
    t = texte.lstrip("﻿")
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n?", t, re.S)
    if not m:
        return {}, texte
    e = {}
    for l in m.group(1).splitlines():
        if ":" in l:
            k, v = l.split(":", 1)
            e[k.strip()] = v.strip()
    return e, t[m.end():]


def alias_de(entete):
    v = entete.get("alias", "").strip()
    if not v.startswith("["):
        return []
    try:
        a = json.loads(v)
        return [str(x) for x in a] if isinstance(a, list) else []
    except ValueError:
        return [x.strip().strip("\"'") for x in v.strip("[]").split(",") if x.strip()]


def ecrire_entete(entete, corps):
    ordre = ["type", "piece", "statut", "maj", "alias", "resume"]
    lignes = ["---"] + ["%s: %s" % (k, entete[k]) for k in ordre if k in entete]
    lignes += ["%s: %s" % (k, v) for k, v in entete.items() if k not in ordre] + ["---"]
    return "\n".join(lignes) + "\n" + corps.lstrip("\n")


def guillemets(t):
    return '"' + re.sub(r"\s+", " ", str(t)).replace("\\", " ").replace('"', "'").strip()[:160] + '"'


# ---------------------------------------------------------------- une chose = une fiche
def sans_determinant(t):
    return DETERMINANTS.sub("", plat(t).strip()).strip()


def fiches_connues():
    """[(piece, nom, [alias])] des pieces du greffier (les index exceptes)"""
    connues = []
    for p in PIECES:
        d = os.path.join(base_memoire(), p)
        try:
            noms = sorted(f[:-3] for f in os.listdir(d) if f.endswith(".md"))
        except OSError:
            continue
        for n in noms:
            if n == INDEX.get(p) or n[:1].isupper():
                continue
            al = []
            try:
                with open(os.path.join(d, n + ".md"), encoding="utf-8") as h:
                    al = alias_de(lire_entete(h.read(4000))[0])
            except OSError:
                pass
            connues.append((p, n, al))
    return connues


def trouver_fiche(piece, sujet):
    """(piece, nom) de la fiche ou ranger ce sujet : une fiche qui existe deja sous ce nom, un autre nom (alias)
    ou un nom plus long (« laurent » -> laurent_martin), sinon une nouvelle fiche. (None, raison) si c'est ambigu."""
    unique = fiche_unique(piece)
    if unique:
        return piece, unique
    nom = nom_de_fiche(sujet)
    if not nom:
        return None, "sujet manquant"
    connues = fiches_connues()
    exact = [(p, n) for p, n, a in connues if n == nom]
    if exact:
        return sorted(exact, key=lambda x: x[0] != piece)[0]
    voulu = sans_determinant(sujet)
    par_alias = [(p, n) for p, n, a in connues if any(voulu and sans_determinant(x) == voulu for x in a)]
    if len(par_alias) == 1:
        return par_alias[0]
    if len(par_alias) > 1:
        return None, "plusieurs fiches possibles : " + ", ".join(n for p, n in par_alias[:3])
    plus_long = [(p, n) for p, n, a in connues if n.startswith(nom + "_")]
    if len(plus_long) == 1:
        return plus_long[0]
    if len(plus_long) > 1:
        return None, "plusieurs fiches possibles : " + ", ".join(n for p, n in plus_long[:3])
    return piece, nom


# ---------------------------------------------------------------- l'index de la piece et le catalogue
def noter_a_l_index(piece, nom, resume):
    """ajoute « - [[nom]] : resume » a l'index de la piece (le cree s'il manque)"""
    titre = INDEX.get(piece)
    if not titre:
        return
    c = os.path.join(base_memoire(), piece, titre + ".md")
    try:
        with open(c, encoding="utf-8") as h:
            t = h.read()
    except OSError:
        t = ecrire_entete({"type": "index", "piece": piece, "statut": "reference", "maj": datetime.date.today().isoformat(),
                           "alias": "[]", "resume": guillemets("Index de la pièce %s : la liste de ses fiches." % piece)},
                          "# %s\n\nPièce du [[Château]].\n\n## Dans cette pièce\n\n" % titre)
    if nom.lower() == titre.lower() or re.search(r"\[\[%s(\]\]|\|)" % re.escape(nom), t):
        return
    ligne = "- [[%s]] : %s" % (nom, re.sub(r"\s+", " ", resume).strip()[:120])
    m = re.search(r"^## Dans cette pi[eè]ce[^\n]*\n", t, re.M)
    if m:   # en fin de section, avant la section suivante
        suite = re.search(r"^#{1,2} ", t[m.end():], re.M)
        fin = m.end() + suite.start() if suite else len(t)
        t = t[:fin].rstrip("\n") + "\n" + ligne + "\n" + ("\n" + t[fin:] if suite else "")
    else:
        t = t.rstrip("\n") + "\n\n## Dans cette pièce\n\n" + ligne + "\n"
    e, corps = lire_entete(t)
    if e:
        e["maj"] = datetime.date.today().isoformat()
        t = ecrire_entete(e, corps)
    ecrire_fichier(c, t)


def infos_fiche(chemin, nom_affiche):
    try:
        with open(chemin, encoding="utf-8") as h:
            t = h.read()
    except OSError:
        return None
    e, corps = lire_entete(t)
    resume = e.get("resume", "").strip().strip("\"'")
    if not resume:
        titre = re.search(r"\*\*Titre :\*\*\s*(.+)", corps) or re.search(r"^#\s+(.+)", corps, re.M)
        resume = titre.group(1).strip() if titre else ""
    al = alias_de(e)
    return {"nom": nom_affiche, "statut": e.get("statut") or "actif", "maj": e.get("maj") or "?",
            "alias": al, "resume": re.sub(r"\s+", " ", resume)[:160], "type": e.get("type", "")}


def refaire_catalogue():
    """memoire\\catalogue.md : une ligne par fiche (le meme format que l'Archi d'origine). Rend True s'il a change."""
    if reglages().get("catalogue") is False:   # un chateau qui a son propre fabricant de catalogue
        return False
    racine = base_memoire()
    lignes = []
    for p in sorted(d for d in os.listdir(racine) if os.path.isdir(os.path.join(racine, d)) and not d.startswith(".")
                    and d not in ("crypte", "pdfs", "fiches")) if os.path.isdir(racine) else []:
        bloc = []
        for f in sorted(os.listdir(os.path.join(racine, p))):
            if f.endswith(".md"):
                d = infos_fiche(os.path.join(racine, p, f), "%s/%s" % (p, f[:-3]))
                if d:
                    al = (" · alias : " + ", ".join(d["alias"])) if d["alias"] else ""
                    bloc.append("- `%s` · %s · %s%s · %s" % (d["nom"], d["statut"], d["maj"], al, d["resume"]))
        if bloc:
            lignes += ["", "## " + p] + bloc
    entete = ecrire_entete({"type": "index", "piece": '""', "statut": "reference", "maj": datetime.date.today().isoformat(),
                            "alias": "[]", "resume": guillemets("Une ligne par fiche : où chercher sans tout ouvrir.")},
                           "# 📇 Catalogue du château\n\nFabriqué par l'outil memoire (le greffier). NE PAS ÉCRIRE À LA MAIN : on le refait.\n"
                           "Une ligne = une fiche : `pièce/nom` · statut · date · alias · résumé. Voir [[chercher]].\n")
    neuf = entete + "\n".join(lignes) + "\n"
    c = os.path.join(racine, "catalogue.md")
    try:
        with open(c, encoding="utf-8") as h:
            ancien = h.read()
        if [l for l in ancien.splitlines() if not l.startswith("maj: ")] == [l for l in neuf.splitlines() if not l.startswith("maj: ")]:
            return False
    except OSError:
        pass
    ecrire_fichier(c, neuf)
    return True


def ecrire_fichier(c, t):
    os.makedirs(os.path.dirname(c), exist_ok=True)
    tmp = c + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as h:
        h.write(t)
    os.replace(tmp, c)


# ---------------------------------------------------------------- le verrou et le journal
class Verrou:
    """un seul greffier a la fois ecrit dans les fiches (deux messages rapproches lancent deux greffiers)"""

    def __enter__(self):
        os.makedirs(base_memoire(), exist_ok=True)
        self.dossier = os.path.join(base_memoire(), ".verrou_memoire")
        fin = time.time() + 8
        while True:
            try:
                os.mkdir(self.dossier)
                return self
            except OSError:
                try:   # un verrou oublie par un greffier interrompu ne bloque pas les suivants
                    if time.time() - os.path.getmtime(self.dossier) > 60:
                        os.rmdir(self.dossier)
                        continue
                except OSError:
                    pass
                if time.time() > fin:
                    raise Erreur("la memoire est occupee")
                time.sleep(0.1)

    def __exit__(self, *a):
        try:
            os.rmdir(self.dossier)
        except OSError:
            pass


def journal():
    return os.path.join(base_memoire(), ".retenu.jsonl")


def noter_au_journal(retenu):
    """les derniers faits retenus : la page d'accueil les montre au fur et a mesure (50 lignes au plus)"""
    if not retenu:
        return
    f = journal()
    lignes = []
    try:
        with open(f, encoding="utf-8") as h:
            lignes = [l for l in h.read().splitlines() if l.strip()]
    except OSError:
        pass
    maintenant = int(time.time() * 1000)
    for r in retenu:
        lignes.append(json.dumps({"quand": maintenant, "piece": r["piece"], "sujet": r["sujet"], "fait": r["fait"]}, ensure_ascii=False))
    tmp = f + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as h:
        h.write("\n".join(lignes[-50:]) + "\n")
    os.replace(tmp, f)


# ---------------------------------------------------------------- lire et ecrire les fiches
def faits_de(texte):
    """les puces du bloc « **Faits :** » d'une fiche"""
    faits = []
    for bloc in re.split(r"\*\*Faits :\*\*", texte)[1:]:
        for ligne in re.split(r"\n\*\*", bloc)[0].splitlines():
            ligne = ligne.strip()
            if ligne.startswith("- "):
                faits.append(ligne[2:].strip())
    return faits


def sans_date(fait):
    return re.sub(r"^\(\d{2}/\d{2}/\d{4}\)\s*", "", fait)


def fiches(piece=None):
    """[(piece, nom, chemin, [faits])] de toutes les fiches de la memoire vive"""
    sortie = []
    for p in ([piece] if piece else TOUTES):
        d = os.path.join(base_memoire(), p)
        try:
            noms = sorted(f for f in os.listdir(d) if f.endswith(".md"))
        except OSError:
            continue
        for f in noms:
            c = os.path.join(d, f)
            try:
                with open(c, encoding="utf-8") as h:
                    sortie.append((p, f[:-3], c, faits_de(h.read())))
            except OSError:
                continue
    return sortie


def doublon(fait, existants):
    a = set(mots(fait))
    if not a:
        return False
    for e in existants:
        b = set(mots(sans_date(e)))
        if plat(sans_date(e)) == plat(fait) or (b and len(a & b) / float(len(a | b)) >= 0.8):
            return True
    return False


def ajouter_au_bloc(texte, debut, fin, ligne):
    """ajoute « ligne » a la fin du bloc « **Faits :** » qui se trouve entre debut et fin (rend None s'il n'y en a pas)"""
    i = texte.rfind("**Faits :**", debut, fin)
    if i == -1:
        return None
    suite = texte.find("\n**", i + 11)
    titre = re.search(r"\n#{1,2} ", texte[i:])
    bornes = [x for x in (suite, i + titre.start() if titre else -1, fin) if x != -1 and x > i]
    stop = min(bornes) if bornes else len(texte)
    bloc = texte[i:stop].rstrip("\n")
    bloc = re.sub(r"\n- Aucune\s*$", "", bloc)   # « - Aucune » laisse sa place au premier vrai fait
    return texte[:i] + bloc + "\n" + ligne + texte[stop:] if stop < len(texte) else texte[:i] + bloc + "\n" + ligne + "\n"


def nouvelle_fiche(piece, nom, sujet, fait, jour, sources, liens):
    titre = {"moi": "Moi", "preferences": "Goûts et préférences", "lecons": "Leçons apprises"}.get(piece) \
        or (str(sujet).strip()[:60] or nom)
    titre = titre[:1].upper() + titre[1:]
    entete = {"type": SORTES.get(piece, piece), "piece": piece, "statut": "actif", "maj": jour.isoformat(), "alias": "[]",
              "resume": guillemets("%s — %s" % (titre, fait))}
    corps = ("# %s\n\nPièce [[%s]] du [[Château]].\n\n" % (titre, INDEX.get(piece, piece))
             + bloc_ajout(jour, fait, sources, liens, titre="%s — %s" % (titre, fait)))
    return ecrire_entete(entete, corps)


def bloc_ajout(jour, fait, sources, liens, titre=None):
    ligne_fait = "- (%s) %s" % (jour.strftime("%d/%m/%Y"), fait)
    lignes = ["## Ajout du %s (greffier)" % jour.strftime("%d/%m/%Y")]
    if titre:
        lignes.append("**Titre :** " + re.sub(r"\s+", " ", titre)[:160])
    lignes += ["**Faits :**", ligne_fait, "**Hypothèses :**", "- Aucune", "**Sources :**", "- " + sources,
               "**Prochaines étapes :**", "- Aucune", "**Liens :**"] + ["- " + l for l in liens]
    return "\n".join(lignes) + "\n"


def ajouter(piece, sujet, fait, aujourdhui=None, liens=(), sources=None, nom=None):
    """ajoute un fait date a la fiche, au format du chateau ; cree la fiche (et sa ligne d'index) s'il le faut.
    Rend le chemin, ou None si le fait y est deja. nom : la fiche deja choisie par trouver_fiche."""
    jour = aujourdhui or datetime.date.today()
    c = os.path.join(base_memoire(), piece, nom + ".md") if nom else chemin_fiche(piece, sujet)
    nom = os.path.basename(c)[:-3]
    ligne = "- (%s) %s" % (jour.strftime("%d/%m/%Y"), fait)
    sources = sources or "%s, dans un message du %s (retenu par le greffier)" % (
        (os.environ.get("ARCHI_UTILISATEUR") or "l'utilisateur").strip(), jour.strftime("%d/%m/%Y"))
    liens = ["fait_partie_de :: [[%s]]" % INDEX.get(piece, piece)] + [l for l in liens if l]
    if piece == "lecons":   # les lecons : une simple liste relue a chaque message (core/contexte.js)
        if os.path.exists(c):
            with open(c, encoding="utf-8") as h:
                t = h.read()
            if doublon(fait, faits_de(t)):
                return None
            t = ajouter_au_bloc(t, 0, len(t), ligne) or (t.rstrip("\n") + "\n\n**Faits :**\n" + ligne + "\n")
        else:
            t = "# Leçons apprises\n\n**Pièce :** lecons\n**Faits :**\n%s\n" % ligne
        ecrire_fichier(c, t)
        return c
    if os.path.exists(c):
        with open(c, encoding="utf-8") as h:
            t = h.read()
        if doublon(fait, faits_de(t)):
            return None
        entete, corps = lire_entete(t)
        # 1. la Synthese (fiche curee) recoit le fait, pour qu'il soit lu tout de suite
        syn = re.search(r"^##\s*Synth[eè]se[^\n]*\n", corps, re.M)
        if syn:
            fin_syn = re.search(r"^(#\s|---\s*$)", corps[syn.end():], re.M)
            fin = syn.end() + fin_syn.start() if fin_syn else len(corps)
            corps = ajouter_au_bloc(corps, syn.end(), fin, ligne) or corps
        # 2. l'historique : le bloc du jour du greffier s'il existe (dernier bloc), sinon un nouveau bloc a la fin
        dernier = list(re.finditer(r"^## Ajout du %s \(greffier\)[^\n]*\n" % re.escape(jour.strftime("%d/%m/%Y")), corps, re.M))
        suite_bloc = re.search(r"^#{1,2} ", corps[dernier[-1].end():], re.M) if dernier else None
        if dernier and not suite_bloc:
            corps = ajouter_au_bloc(corps, dernier[-1].end(), len(corps), ligne) or corps
            for l in liens[1:]:
                if "- " + l not in corps:
                    corps = corps.rstrip("\n") + "\n- " + l + "\n"
        else:
            corps = corps.rstrip("\n") + "\n\n" + bloc_ajout(jour, fait, sources, liens)
        if not entete:   # une fiche ecrite a la main sans en-tete en recoit un
            titre = (re.search(r"^#\s+(.+)", corps, re.M) or re.search(r"\*\*Titre :\*\*\s*(.+)", corps))
            entete = {"type": SORTES.get(piece, piece), "piece": piece, "statut": "actif", "alias": "[]",
                      "resume": guillemets(titre.group(1) if titre else nom)}
        entete["maj"] = jour.isoformat()
        ecrire_fichier(c, ecrire_entete(entete, corps))
    else:
        ecrire_fichier(c, nouvelle_fiche(piece, nom, sujet, fait, jour, sources, liens))
        if piece != "lecons":
            noter_a_l_index(piece, nom, fait)
    return c


# ---------------------------------------------------------------- les garde-fous d'un fait
def refus(piece, sujet, fait, message):
    """pourquoi ce fait n'est pas retenu (None s'il est bon)"""
    if piece not in PIECES:
        return "piece inconnue"
    fait = str(fait or "").strip()
    if not (8 <= len(fait) <= MAX_FAIT):
        return "fait trop court ou trop long"
    if "\n" in fait or "\r" in fait or fait.startswith(("#", "*", "-")):
        return "forme interdite"
    tout = plat(fait + " " + str(sujet or ""))
    if SECRETS.search(tout) or TELEPHONE.search(fait) or ADRESSE.search(plat(fait)):
        return "donnee sensible"
    if piece not in FICHE_UNIQUE_DEFAUT and not nom_de_fiche(sujet):
        return "sujet manquant"
    if message is not None:
        dits = set(mots(message, 3))
        # rien d'invente : le fait reprend des mots du message (un prenom court compte), et le sujet y figure
        communs = [m for m in mots(fait, 3) if m in dits]
        if len(communs) < 1:
            return "ne vient pas du message"
        if piece not in FICHE_UNIQUE_DEFAUT and not any(m in plat(message) for m in re.split(r"[^a-z0-9]+", plat(sujet)) if len(m) >= 3):
            return "sujet absent du message"
    return None


def parle_de_soi(message):
    """vrai si le message peut contenir un fait sur l'utilisateur : inutile de deranger le modele sinon"""
    m = plat(message)
    return len(m) >= 12 and bool(PREMIERE_PERSONNE.search(re.sub(r"['\-]", " ", m)))


def propre(message):
    """le message de l'utilisateur seulement : pas la description d'une photo ni un contenu venu de l'exterieur"""
    m = str(message or "")
    for marque in ("\n--- contenu de la photo", "\n(Une piece jointe", "<<<", "[CONTENU EXTERIEUR"):
        i = m.find(marque)
        if i != -1:
            m = m[:i]
    return m.strip()[:2000]


# ---------------------------------------------------------------- le modele local
def appeler_modele(consigne, message, schema, appel=None):
    """le texte rendu par le modele local, sa forme imposee par le schema (si le serveur le permet)"""
    corps = {
        "model": os.environ.get("ARCHI_MODELE") or "openai/gpt-oss-20b",
        "temperature": 0,
        "max_tokens": 1600,   # le modele reflechit avant de repondre : 700 ne suffisait pas toujours (relations)
        "reasoning_effort": "low",   # un travail de greffier : pas besoin de longue reflexion (ignore par les modeles qui ne l'ont pas)
        "messages": [{"role": "system", "content": consigne}, {"role": "user", "content": message}],
    }
    if appel is None:
        url = (os.environ.get("ARCHI_LM_URL") or "http://127.0.0.1:1234/v1").rstrip("/") + "/chat/completions"

        def appel(c):
            req = urllib.request.Request(url, data=json.dumps(c).encode("utf-8"), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=75) as r:   # en arriere-plan : la reponse n'attend pas le greffier
                return json.loads(r.read().decode("utf-8"))
    try:
        # la forme de la reponse est imposee : sans cela, le modele ecrit parfois « facts » au lieu de « faits »
        rep = appel(dict(corps, response_format=schema))
    except urllib.error.HTTPError as e:
        if e.code not in (400, 422):
            raise
        rep = appel(corps)   # un serveur qui ne connait pas les schemas : on demande sans, et on lit ce qu'on peut
    return (((rep.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""


def liste_des_fiches(maxi=1500):
    """les fiches deja la, pour que le modele reprenne leur nom au lieu d'en creer une seconde (une chose = une fiche)"""
    par_piece = {}
    for p, n, a in fiches_connues():
        if n == fiche_unique(p):
            continue
        par_piece.setdefault(p, []).append(n + (" (" + ", ".join(a[:3]) + ")" if a else ""))
    if not par_piece:
        return ""
    t = "\nFiches qui existent déjà (nom (autres noms)) : " + " | ".join("%s : %s" % (p, ", ".join(v)) for p, v in par_piece.items())
    return t if len(t) <= maxi else t[:maxi].rsplit(",", 1)[0] + "…"


def proche_nomme(fait, message):
    """(piece, nom) d'une fiche de personne dont le fait parle (son nom complet dans le fait, ou un autre nom comme
    « mon père » dans le message et « père » dans le fait), ou None. Sert quand le modele range dans « moi » un fait
    qui parle d'un proche qui a deja sa fiche."""
    f, m = plat(fait), plat(message)
    trouves = set()
    for p, n, al in fiches_connues():
        if p != "personnes":
            continue
        if len(n) >= 5 and "_" in n and n.replace("_", " ") in f:
            trouves.add((p, n))
            continue
        for a in al:
            pa, noyau = plat(a).strip(), sans_determinant(a)
            if pa != noyau and len(noyau) >= 3 and re.search(r"(^|[^a-z])%s([^a-z]|$)" % re.escape(pa), m) \
                    and re.search(r"(^|[^a-z])%s([^a-z]|$)" % re.escape(noyau), f):
                trouves.add((p, n))
    return trouves.pop() if len(trouves) == 1 else None


def lien_de(f, message):
    """« relation :: [[fiche]] » si le modele a vu un lien, que l'autre chose est nommee dans le message (ou est l'utilisateur)"""
    relation = plat(f.get("relation")).strip().replace(" ", "_")
    avec = str(f.get("avec") or "").strip()
    if not relation or not avec:
        return None
    if relation not in RELATIONS:
        relation = "voir_aussi"
    if sans_determinant(avec) in ("moi", "l'utilisateur", "utilisateur", "je", "lui"):
        cible = fiche_unique("moi")
    else:
        if not any(m in plat(message) for m in re.split(r"[^a-z0-9]+", plat(avec)) if len(m) >= 3):
            return None
        trouve = trouver_fiche("lieux" if relation in ("habite", "situe_a") else "personnes", avec)
        cible = trouve[1] if trouve[0] else None
    return ("%s :: [[%s]]" % (relation, cible)) if cible else None   # (un lien vers la fiche elle-meme est retire plus loin)


def demander_au_modele(message, appel=None):
    """les faits proposes par le modele local : [{piece, sujet, fait}] (liste vide si rien, ou si le modele ne repond pas)"""
    prenom = (os.environ.get("ARCHI_UTILISATEUR") or "").strip()
    consigne = CONSIGNE.format(prenom=(" (prénom : %s)" % prenom) if prenom else "",
                               appelle=(" ; appelle l'utilisateur %s" % prenom) if prenom else "",
                               connues=liste_des_fiches())
    contenu = appeler_modele(consigne, message, SCHEMA, appel)
    m = re.search(r"\{.*\}", contenu, re.S)   # le modele entoure parfois son JSON de texte
    if not m:
        return []
    try:
        objet = json.loads(m.group(0))
    except Exception:
        return []
    faits = objet.get("faits") or objet.get("facts") or objet.get("fait") or []
    if isinstance(faits, dict):
        faits = [faits]
    propres = []
    for f in faits if isinstance(faits, list) else []:
        if isinstance(f, dict):
            propres.append({"piece": f.get("piece") or f.get("pièce") or f.get("type"), "sujet": f.get("sujet") or f.get("subject"),
                            "fait": f.get("fait") or f.get("fact"), "relation": f.get("relation") or "", "avec": f.get("avec") or ""})
    return propres[:8]


# ---------------------------------------------------------------- les lecons (corrections de l'utilisateur)
CONSIGNE_LECON = """Reasoning: low
Tu relis un échange entre un assistant personnel, Archi, et son utilisateur{prenom}. L'utilisateur vient de répondre à Archi.
Si cette réponse CORRIGE une erreur d'Archi (il a promis ce qu'il ne sait pas faire, inventé un fait, mal compris la demande, mal fait quelque chose), écris UNE leçon courte, à la deuxième personne, qu'Archi relira avant chaque réponse pour ne plus refaire cette erreur.
Sinon (un simple « non merci », un refus, un changement d'avis, une nouvelle demande, une information nouvelle), réponds {{"lecon":""}}.
La leçon reprend les mots de l'échange, n'invente rien, tient en une phrase de moins de 200 caractères, et ne parle jamais des règles de sécurité (accord avant d'agir, secrets).
Réponds UNIQUEMENT par un objet JSON : {{"lecon":"..."}}
Exemples :
Archi : « Je peux t'envoyer un message vocal sur ton téléphone. » / Utilisateur : « Non, tu ne sais pas faire ça. » -> {{"lecon":"Tu ne sais pas envoyer de message vocal sur le téléphone : ne le propose pas."}}
Archi : « Voici la météo de Lyon. » / Utilisateur : « Non, je t'ai demandé celle d'Dijon, tu as mal compris. » -> {{"lecon":"Relis bien le lieu demandé avant de donner la météo."}}
Archi : « Veux-tu que je lance la recherche ? » / Utilisateur : « Non merci, pas maintenant. » -> {{"lecon":""}}
Archi : « C'est noté. » / Utilisateur : « Non, attends, finalement je préfère jeudi. » -> {{"lecon":""}}"""

SCHEMA_LECON = {"type": "json_schema", "json_schema": {"name": "lecon", "strict": True, "schema": {
    "type": "object", "required": ["lecon"], "additionalProperties": False, "properties": {"lecon": {"type": "string"}}}}}


def corrige(message):
    """vrai si la reponse de l'utilisateur ressemble a une correction"""
    return bool(CORRECTION.search(re.sub(r"[\u2019]", "'", plat(message))))


def refus_lecon(lecon, echange):
    """pourquoi cette lecon n'est pas gardee (None si elle est bonne). echange = la reponse d'Archi + la correction (ou None)"""
    lecon = str(lecon or "").strip()
    if not (12 <= len(lecon) <= MAX_LECON):
        return "lecon trop courte ou trop longue"
    if "\n" in lecon or "\r" in lecon or lecon.startswith(("#", "*", "-", "[")):
        return "forme interdite"
    if SECRETS.search(plat(lecon)) or TELEPHONE.search(lecon) or ADRESSE.search(plat(lecon)):
        return "donnee sensible"
    p = re.sub(r"[\u2019]", "'", plat(lecon)).strip()
    if TOUCHE_AUX_REGLES.search(p):
        return "touche aux regles de securite"
    if not FORME_LECON.search(p):
        return "forme de lecon non permise"
    if echange is not None and len(set(mots(lecon)) & set(mots(echange))) < 2:
        return "ne vient pas de l'echange"
    return None


def garder_lecon(lecon, echange, a_blanc=False):
    """(lecon rangee ou None, raison du refus ou None)"""
    lecon = re.sub(r"\s+", " ", str(lecon or "")).strip()
    pourquoi = refus_lecon(lecon, echange)
    if pourquoi:
        return None, pourquoi
    if a_blanc:
        return lecon, None
    with Verrou():
        deja = [f for p, n, c, f in fiches("lecons")]
        if sum(len(f) for f in deja) >= MAX_LECONS:
            return None, "deja %d lecons : fais le menage (oublier)" % MAX_LECONS
        if not ajouter("lecons", "lecons", lecon):
            return None, "deja apprise"
        noter_au_journal([{"piece": "lecons", "sujet": "lecons", "fait": lecon}])
    return lecon, None


def tirer_lecon(correction, reponse, appel=None, a_blanc=False):
    """{lecon, pourquoi, appel_modele} : la lecon tiree d'une correction (lecon vide si ce n'en est pas une)"""
    correction, reponse = propre(correction)[:600], propre(reponse)[:900]
    if not reponse or not corrige(correction):
        return {"lecon": "", "pourquoi": "pas une correction", "appel_modele": False}
    prenom = (os.environ.get("ARCHI_UTILISATEUR") or "").strip()
    consigne = CONSIGNE_LECON.format(prenom=(" (prénom : %s)" % prenom) if prenom else "")
    try:
        contenu = appeler_modele(consigne, "Archi : « %s »\nUtilisateur : « %s »" % (reponse, correction), SCHEMA_LECON, appel)
    except Exception as e:
        return {"lecon": "", "pourquoi": "le modele n'a pas repondu", "appel_modele": True, "erreur": str(e)[:150]}
    m = re.search(r"\{.*\}", contenu, re.S)
    try:
        proposee = str((json.loads(m.group(0)) if m else {}).get("lecon") or "").strip()
    except Exception:
        proposee = ""
    if not proposee:
        return {"lecon": "", "pourquoi": "rien a apprendre", "appel_modele": True}
    lecon, pourquoi = garder_lecon(proposee, reponse + " " + correction, a_blanc)
    return {"lecon": lecon or "", "pourquoi": pourquoi, "proposee": proposee[:200], "appel_modele": True}


def act_lecon(d, appel=None):
    r = tirer_lecon(d.get("texte"), d.get("reponse") or d.get("reponse_precedente"), appel, oui(d.get("a_blanc")))
    if r["lecon"]:
        return repondre(True, "Leçon apprise : " + r["lecon"], **r)
    repondre(True, "Pas de leçon (%s)." % (r.get("pourquoi") or "rien"), **r)


def act_retenir(d, appel=None):
    # d'abord la lecon : si l'utilisateur corrige la reponse d'avant (champ reponse_precedente, mis par le workflow)
    lecon = None
    if d.get("reponse_precedente"):
        try:   # une lecon ratee (memoire occupee...) ne fait jamais perdre les faits du message
            lecon = tirer_lecon(d.get("texte"), d.get("reponse_precedente"), appel, oui(d.get("a_blanc")))
        except Exception as e:
            lecon = {"lecon": "", "pourquoi": "lecon non rangee : %s" % str(e)[:120], "appel_modele": True}
    message = propre(d.get("texte"))
    extra = {"lecon": lecon} if lecon is not None else {}
    if not parle_de_soi(message):
        return repondre(True, "Rien à retenir.", retenu=[], appel_modele=False, **extra)
    try:
        proposes = demander_au_modele(message, appel)
    except Exception as e:   # le modele ne repond pas : la conversation continue, sans rien retenir
        return repondre(True, "Rien retenu (le modèle n'a pas répondu).", retenu=[], appel_modele=True, erreur=str(e)[:150], **extra)
    retenu, ecartes = [], []
    for f in proposes:
        piece = plat(f.get("piece")).strip()
        sujet = str(f.get("sujet") or "").strip()
        fait = re.sub(r"\s+", " ", str(f.get("fait") or "")).strip()
        prenom = (os.environ.get("ARCHI_UTILISATEUR") or "").strip()
        if prenom:   # les fiches parlent de la personne par son prenom, pas de « l'utilisateur »
            fait = re.sub(r"\b[Ll]['\u2019]utilisat(eur|rice)\b", lambda m: prenom, fait)
            fait = re.sub(r"\b(de|que) %s\b" % re.escape(prenom), lambda m: m.group(0), fait)
        pourquoi = refus(piece, sujet, fait, message)
        if pourquoi == "sujet absent du message":
            # le fait vient bien du message, mais son sujet est mal nomme : il va dans la fiche de l'utilisateur
            piece, sujet = "moi", "moi"
            pourquoi = refus(piece, sujet, fait, message)
        if pourquoi:
            ecartes.append({"fait": fait[:80], "pourquoi": pourquoi})
            continue
        if len(retenu) >= MAX_FAITS:
            ecartes.append({"fait": fait[:80], "pourquoi": "au plus %d faits par message" % MAX_FAITS})
            continue
        # une chose = une fiche : la fiche qui existe deja (meme nom, autre nom, nom plus long), sinon une nouvelle
        ou, nom = trouver_fiche(piece, sujet)
        if ou in ("moi", "preferences"):   # « mon père s'est mis au golf » rangé chez l'utilisateur : chez le père s'il a sa fiche
            autre = proche_nomme(fait, message)
            if autre:
                ou, nom = autre
        if not ou:
            ecartes.append({"fait": fait[:80], "pourquoi": nom})
            continue
        lien = lien_de(f, message)
        if lien and lien.endswith("[[%s]]" % nom):   # pas de lien d'une fiche vers elle-meme
            lien = None
        if oui(d.get("a_blanc")):
            retenu.append({"piece": ou, "sujet": sujet, "fiche": nom, "fait": fait, "lien": lien or ""})
            continue
        with Verrou():
            chemin = ajouter(ou, sujet, fait, liens=[lien] if lien else [], nom=nom)
            if chemin:
                noter_au_journal([{"piece": ou, "sujet": sujet, "fait": fait}])
        if chemin:
            retenu.append({"piece": ou, "sujet": sujet, "fiche": nom, "fait": fait, "lien": lien or ""})
        else:
            ecartes.append({"fait": fait[:80], "pourquoi": "deja su"})
    if retenu and not oui(d.get("a_blanc")):
        try:
            with Verrou():
                refaire_catalogue()
        except Exception:
            pass   # le catalogue se refera au prochain fait : la memoire, elle, est deja rangee
    phrase = ("Retenu : " + " ; ".join(r["fait"] for r in retenu)) if retenu else "Rien de nouveau à retenir."
    repondre(True, phrase, retenu=retenu, ecartes=ecartes, appel_modele=True, **extra)


def act_ecrire(d):
    piece = plat(d.get("piece") or "moi").strip()
    if piece in ("lecons", "lecon"):
        # les lecons ne viennent QUE des corrections de l'utilisateur (le greffier, action lecon) : jamais de l'agent,
        # qu'une page ou un mail lu pourrait pousser a s'ecrire une « lecon »
        raise Erreur("Je n'écris pas de leçon moi-même : elles viennent toutes seules quand tu me corriges "
                     "(« non, tu ne sais pas faire ça »). Tu peux les lire ou en oublier une.")
    sujet = str(d.get("sujet") or "").strip()
    fait = re.sub(r"\s+", " ", str(d.get("fait") or d.get("contenu") or "")).strip()
    pourquoi = refus(piece, sujet, fait, None)
    if pourquoi:
        raise Erreur("Je ne range pas ce fait (%s). Pièces possibles : %s." % (pourquoi, ", ".join(PIECES)))
    ou, nom = trouver_fiche(piece, sujet)
    if not ou:
        raise Erreur("Je ne sais pas dans quelle fiche le ranger (%s) : donne le nom exact de la fiche." % nom)
    with Verrou():
        if not ajouter(ou, sujet, fait, nom=nom, sources="%s, dicté le %s" % (
                (os.environ.get("ARCHI_UTILISATEUR") or "l'utilisateur").strip(), datetime.date.today().strftime("%d/%m/%Y"))):
            return repondre(True, "Je le savais déjà : " + fait, retenu=[])
        noter_au_journal([{"piece": ou, "sujet": nom, "fait": fait}])
        try:
            refaire_catalogue()
        except Exception:
            pass
    repondre(True, "C'est retenu (%s/%s) : %s" % (ou, nom, fait), retenu=[{"piece": ou, "sujet": nom, "fait": fait}])


def act_lister(d):
    piece = plat(d.get("piece")).strip() or None
    if piece and piece not in TOUTES:
        raise Erreur("Pièce inconnue. Pièces possibles : " + ", ".join(TOUTES) + ".")
    liste = [{"piece": p, "sujet": n, "faits": len(f)} for p, n, _, f in fiches(piece) if f]
    if not liste:
        return repondre(True, "Ma mémoire est encore vide" + (" pour cette pièce." if piece else "."), fiches=[])
    repondre(True, "Ce que j'ai en mémoire : " + " ; ".join("%s/%s (%d)" % (x["piece"], x["sujet"], x["faits"]) for x in liste), fiches=liste)


def act_lire(d):
    sujet, piece = nom_de_fiche(d.get("sujet")), plat(d.get("piece")).strip() or None
    trouvees = [(p, n, f) for p, n, _, f in fiches(piece if piece in TOUTES else None) if f and (not sujet or sujet in n or n in sujet)]
    if not trouvees:
        return repondre(True, "Je n'ai rien en mémoire" + (" sur « %s »." % str(d.get("sujet"))[:40] if sujet else "."), faits=[])
    lignes = ["%s/%s : %s" % (p, n, " | ".join(sans_date(x) for x in f)) for p, n, f in trouvees]
    repondre(True, " || ".join(lignes)[:1800], faits=[{"piece": p, "sujet": n, "faits": f} for p, n, f in trouvees])


def effacer_des_resumes(texte, chemin, retires):
    """un fait oublie disparait aussi du resume de l'en-tete, de la ligne **Titre :** et de l'index de la piece"""
    debuts = [plat(sans_date(f))[:50] for f in retires]
    contient = lambda l: any(x and x in plat(l) for x in debuts)
    e, corps = lire_entete(texte)
    titre = (re.search(r"^#\s+(.+)", corps, re.M) or [None, os.path.basename(chemin)[:-3]])[1].strip()
    if e and contient(e.get("resume", "")):
        e["resume"] = guillemets(titre)
    corps = "\n".join(("**Titre :** " + titre) if l.startswith("**Titre :**") and contient(l) else l for l in corps.split("\n"))
    piece, nom = os.path.basename(os.path.dirname(chemin)), os.path.basename(chemin)[:-3]
    index = os.path.join(base_memoire(), piece, INDEX.get(piece, "") + ".md")
    if INDEX.get(piece) and os.path.exists(index):
        with open(index, encoding="utf-8") as h:
            ix = h.read()
        neuf = "\n".join(("- [[%s]]" % nom) if l.startswith("- [[%s]]" % nom) and contient(l) else l for l in ix.split("\n"))
        if neuf != ix:
            ecrire_fichier(index, neuf)
    return ecrire_entete(e, corps) if e else corps


def act_oublier(d):
    voulus = mots(d.get("texte") or d.get("sujet") or "", 3)   # un prenom court (Rex, Léa) compte aussi
    if not voulus:
        raise Erreur("Dis-moi quoi oublier : texte = quelques mots du fait (un prénom, un sujet).")
    cibles = []
    for p, n, c, f in fiches():
        for fait in f:
            ensemble = set(mots(fait + " " + n, 3))
            if all(v in ensemble for v in voulus):
                cibles.append((p, n, c, fait))
    if not cibles:
        return repondre(True, "Je n'ai aucun fait qui contient ces mots : rien à oublier.", oublie=[])
    apercu = " ; ".join(sans_date(x[3]) for x in cibles)[:900]
    if not oui(d.get("confirmer")):
        return repondre(True, "ESSAI À BLANC, rien n'est effacé. J'oublierais %d fait(s) : %s. Demande à l'utilisateur de confirmer, "
                              "puis rappelle l'outil avec confirmer=oui." % (len(cibles), apercu), a_oublier=[x[3] for x in cibles])
    with Verrou():
        for c in sorted(set(x[2] for x in cibles)):
            a_retirer = set(x[3] for x in cibles if x[2] == c)
            with open(c, encoding="utf-8") as h:
                lignes = h.read().split("\n")
            gardees = [l for l in lignes if not (l.strip().startswith("- ") and l.strip()[2:].strip() in a_retirer)]
            ecrire_fichier(c, effacer_des_resumes("\n".join(gardees), c, a_retirer))
        try:
            refaire_catalogue()
        except Exception:
            pass
        # un fait oublie ne doit pas rester affiche dans « les derniers faits retenus »
        try:
            oublies = set(sans_date(x[3]) for x in cibles)
            with open(journal(), encoding="utf-8") as h:
                gardees = [l for l in h.read().splitlines() if l.strip() and json.loads(l).get("fait") not in oublies]
            with open(journal() + ".tmp", "w", encoding="utf-8", newline="\n") as h:
                h.write("\n".join(gardees) + ("\n" if gardees else ""))
            os.replace(journal() + ".tmp", journal())
        except (OSError, ValueError):
            pass
    repondre(True, "C'est oublié (%d fait(s)) : %s" % (len(cibles), apercu), oublie=[x[3] for x in cibles])


def act_catalogue(d):
    with Verrou():
        change = refaire_catalogue()
    repondre(True, "Catalogue refait." if change else "Catalogue déjà à jour.")


ACTIONS = {"catalogue": act_catalogue, "retenir": act_retenir, "ecrire": act_ecrire, "lister": act_lister, "lire": act_lire, "oublier": act_oublier, "lecon": act_lecon}


def main():
    pa = argparse.ArgumentParser()
    pa.add_argument("--fichier", required=True)
    pa.add_argument("--menage", action="store_true", help="efface le fichier de demande (appel en arriere-plan par le workflow)")
    a = pa.parse_args()
    try:
        with open(a.fichier, encoding="utf-8-sig") as h:
            d = json.load(h)
        if a.menage:
            try:
                os.remove(a.fichier)
            except OSError:
                pass
        if not isinstance(d, dict):
            raise Erreur("demande illisible")
        action = plat(d.get("action") or "lister").strip()
        action = {"lecons": "lecon", "apprendre": "lecon", "retiens": "retenir", "noter": "ecrire", "note": "ecrire", "liste": "lister", "oublie": "oublier",
                  "effacer": "oublier", "supprimer": "oublier", "lis": "lire"}.get(action, action)
        if action not in ACTIONS:
            raise Erreur("Action inconnue. Actions : " + ", ".join(sorted(ACTIONS)) + ".")
        ACTIONS[action](d)
    except Erreur as e:
        repondre(False, str(e))
    except Exception as e:
        repondre(False, "La mémoire a eu un souci : " + str(e)[:150])


if __name__ == "__main__":
    main()
