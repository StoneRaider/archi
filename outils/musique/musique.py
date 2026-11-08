# -*- coding: utf-8 -*-
"""musique.py - Archi propose de la musique selon les GOUTS de l'utilisateur, a partir de SA bibliotheque musicale.
Index : memoire\\passions\\musique_index.tsv (fabrique par indexer.py, lecture seule du dossier Music).
Fiche de gouts : memoire\\passions\\musique_gouts.md.
Usage : python musique.py --fichier demande.json   (outil maison d'Archi)

Actions :
  proposer  ambiance=calme|pechu|fete|route (facultatif), genre=reggae|dub|rap|rock|electro|... (facultatif),
            artiste=... (facultatif), nombre=3 (defaut)  -> des morceaux tires de sa bibliotheque + la recherche YouTube a lancer
  chercher  q=nom d'artiste ou de titre  -> ce qu'il a de cet artiste / ce titre
  gouts     -> le resume de ses gouts (genres et artistes qui dominent)
Repond UNE ligne JSON {"ok", "phrase_pour_utilisateur", ...}. Ne lance rien : pour ecouter, Archi appelle ensuite l'outil telephone
(action youtube, recherche = "artiste titre").
"""
import csv
import json
import os
import random
import re
import sys
import unicodedata
from collections import Counter, defaultdict

BASE = os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files")
INDEX = os.path.join(BASE, "memoire", "passions", "musique_index.tsv")
try:  # la table perso de l'utilisateur complete la table generique
    _PERSO = json.load(open(os.path.join(BASE, "memoire", "passions", "musique_artistes.json"), encoding="utf-8"))
except Exception:
    _PERSO = {}

# genre (etiquette du fichier) -> famille
FAMILLES = [
    ("dub", r"\bdub\b|dubstep|steppa"),
    ("reggae", r"reggae|roots|rocksteady|lovers|ska\b|ragga|dancehall|jamai"),
    ("rap", r"hip ?-?hop|\brap\b|rnb|r&b|gangsta|trip ?-?hop"),
    ("electro", r"electro|electronic|techno|house|trance|drum|jungle|breakbeat|big beat|idm|ambient|downtempo|chill|lounge|abstract|electronica|dance"),
    ("rock", r"rock|metal|punk|grunge|hardcore|indie|alternative|alternatif|psyche|ska punk|fusion"),
    ("monde", r"latin|world|monde|balkan|klezmer|gypsy|tzigane|cumbia|salsa|afro|tropical|flamenco|reggaeton|mestizo"),
    ("blues", r"blues|soul|jazz|funk|gospel"),
    ("chanson", r"chanson|variet|french pop|pop fr"),
]
# artistes connus de sa bibliotheque sans etiquette fiable -> famille
# artistes sans etiquette fiable -> famille. Petite table generique ; chacun complete la sienne dans
# memoire/passions/musique_artistes.json ({"artiste": "famille"}), lue en plus (elle reste dans le chateau).
ARTISTES = {
    "bob marley": "reggae", "peter tosh": "reggae", "lee scratch perry": "dub", "king tubby": "dub",
    "wu tang clan": "rap", "iam": "rap", "the doors": "rock", "nirvana": "rock", "daft punk": "electro",
    "massive attack": "electro", "manu chao": "monde", "nina simone": "blues", "miles davis": "blues",
}
# ambiance -> familles (de la plus a la moins indiquee)
AMBIANCES = {
    "calme": ["reggae", "dub", "electro", "blues"],
    "route": ["reggae", "dub", "electro", "rap", "monde"],
    "pechu": ["rap", "rock", "dub", "monde", "electro"],
    "fete": ["monde", "rap", "dub", "electro", "reggae", "rock"],
}
# mots qui, dans un genre « electro », veulent dire calme
CALME_ELECTRO = r"trip|downtempo|chill|ambient|lounge|abstract"
PECHU_ELECTRO = r"drum|jungle|techno|big beat|breakbeat|dance|house"


def sans(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def sortir(d):
    print(json.dumps(d, ensure_ascii=False))
    sys.exit(0)


def charger():
    if not os.path.exists(INDEX):
        sortir({"ok": False, "phrase_pour_utilisateur": "L'index de ta musique n'est pas encore fabriqué sur le PC."})
    L = []
    with open(INDEX, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r.get("artiste") and r.get("titre"):
                L.append(r)
    return L


def famille_genre(g):
    g = sans(g)
    if not g or g in ("other", "autre", "unknown", "inconnu", "misc", "general", "blank"):
        return ""
    for nom, motif in FAMILLES:
        if re.search(motif, g):
            return nom
    return ""


ARTISTES.update({str(k).lower(): str(v).lower() for k, v in (_PERSO or {}).items()})


def classer(L):
    """famille de chaque morceau : son etiquette, sinon la famille dominante de l'artiste, sinon la table ARTISTES."""
    par_artiste = defaultdict(Counter)
    for r in L:
        r["_a"] = sans(r["artiste"]).replace("the ", "the ", 1)
        fg = famille_genre(r.get("genre", ""))
        r["_f"] = fg
        if fg:
            par_artiste[r["_a"]][fg] += 1
    for r in L:
        if not r["_f"]:
            c = par_artiste.get(r["_a"])
            if c:
                r["_f"] = c.most_common(1)[0][0]
            else:
                a = r["_a"]
                for nom, fam in ARTISTES.items():
                    if a == nom or a.startswith(nom + " ") or a.startswith("the " + nom):
                        r["_f"] = fam
                        break
    return L


def ok_ambiance(r, amb):
    f, g = r["_f"], sans(r.get("genre", ""))
    if amb == "calme" and f == "electro" and re.search(PECHU_ELECTRO, g):
        return False
    if amb == "pechu" and f == "electro" and re.search(CALME_ELECTRO, g):
        return False
    return True


def poids_artiste(L):
    return Counter(r["_a"] for r in L)


def normaliser_ambiance(a):
    a = sans(a)
    if re.search(r"calm|tranquil|pose|zen|doux|cool|chill|relax|detente|soir", a): return "calme"
    if re.search(r"route|voiture|conduite|rouler|trajet", a): return "route"
    if re.search(r"pechu|energi|patate|nerv|dynami|motiv|sport|bouge|fort|rythm", a): return "pechu"
    if re.search(r"fete|soiree|danse|apero|ambiance", a): return "fete"
    return ""


def proposer(L, d):
    amb = normaliser_ambiance(d.get("ambiance", "")) or ("" if d.get("genre") or d.get("artiste") else "route")
    genre = sans(d.get("genre", ""))
    art = sans(d.get("artiste", ""))
    n = max(1, min(8, int(float(d.get("nombre") or 3))))
    deja = set(sans(x) for x in (d.get("eviter") or []) if x) if isinstance(d.get("eviter"), list) else set()
    pool = [r for r in L if r["_f"] and r["_f"] != "chanson"]
    if art:
        pool = [r for r in L if art in r["_a"]]
    elif genre:
        fam = famille_genre(genre) or genre
        pool = [r for r in pool if r["_f"] == fam or genre in sans(r.get("genre", ""))]
    elif amb:
        fams = AMBIANCES[amb]
        pool = [r for r in pool if r["_f"] in fams and ok_ambiance(r, amb)]
    pool = [r for r in pool if r["_a"] not in deja and not re.search(r"various|divers|compil|inconnu|unknown|^va$", r["_a"])
            and len(r["titre"]) > 1 and not re.match(r"^(piste|track)\s*\d+$", sans(r["titre"]))]
    if not pool:
        sortir({"ok": False, "phrase_pour_utilisateur": "Je ne trouve rien qui colle dans ta bibliothèque pour cette demande."})
    # tirage : un morceau par artiste, les artistes tres presents (ses preferes) ont plus de chances
    pa = poids_artiste(pool)
    choix, vus = [], set()
    rnd = random.Random()
    essais = 0
    # chaque morceau pese 1/racine(nb de morceaux de son artiste) : les artistes tres presents ressortent plus, sans tout ecraser
    poids = [1.0 / (pa[x["_a"]] ** 0.5) for x in pool]
    while len(choix) < n and essais < 2000:
        essais += 1
        r = rnd.choices(pool, weights=poids, k=1)[0]
        if r["_a"] in vus and not art:
            continue
        vus.add(r["_a"])
        choix.append(r)
        if art and len(choix) >= min(n, len(pool)):
            break
    out = [{"artiste": r["artiste"], "titre": r["titre"], "album": r.get("album", ""), "famille": r["_f"],
            "recherche_youtube": f'{r["artiste"]} {r["titre"]}'} for r in choix]
    lst = " ; ".join(f'« {x["titre"]} » de {x["artiste"]}' for x in out)
    quoi = {"calme": "pour rouler tranquille", "route": "pour la route", "pechu": "un peu plus pêchu", "fete": "pour la fête"}.get(amb, "")
    phrase = f"Dans ta bibliothèque, {quoi + ' ' if quoi else ''}je te propose : {lst}. Je lance lequel ?"
    return {"ok": True, "ambiance": amb, "propositions": out, "phrase_pour_utilisateur": phrase,
            "pour_lancer": "outils_maison action=utiliser, outil=telephone, parametres={\"action\":\"youtube\",\"recherche\":\"<recherche_youtube>\"}"}


def chercher(L, d):
    q = sans(d.get("q") or d.get("recherche") or d.get("artiste") or d.get("titre") or "")
    if not q:
        sortir({"ok": False, "phrase_pour_utilisateur": "Quel artiste ou quel titre je cherche dans ta musique ?"})
    a = [r for r in L if q in r["_a"]]
    t = [r for r in L if q in sans(r["titre"])] if not a else []
    res = a or t
    if not res:
        return {"ok": True, "trouve": 0, "phrase_pour_utilisateur": f"Tu n'as rien de « {q} » dans ta bibliothèque."}
    ex = random.sample(res, min(5, len(res)))
    lst = " ; ".join(f'« {r["titre"]} » de {r["artiste"]}' for r in ex)
    return {"ok": True, "trouve": len(res), "exemples": [{"artiste": r["artiste"], "titre": r["titre"], "album": r.get("album", "")} for r in ex],
            "phrase_pour_utilisateur": f"Tu as {len(res)} morceau{'x' if len(res) > 1 else ''} qui correspond{'ent' if len(res) > 1 else ''} à « {q} », par exemple : {lst}."}


def gouts(L):
    fam = Counter(r["_f"] for r in L if r["_f"])
    art = Counter(r["artiste"] for r in L if not re.search(r"various|divers|compil|inconnu|unknown", sans(r["artiste"])))
    noms = {"reggae": "reggae", "dub": "dub", "rap": "rap et hip-hop", "electro": "électro et trip-hop", "rock": "rock, métal et punk",
            "monde": "latino et musiques du monde", "blues": "blues, soul et jazz", "chanson": "chanson"}
    f = ", ".join(f"{noms.get(k, k)} ({v})" for k, v in fam.most_common(6))
    a = ", ".join(k for k, _ in art.most_common(12))
    return {"ok": True, "morceaux": len(L), "familles": dict(fam.most_common()), "artistes": [k for k, _ in art.most_common(30)],
            "phrase_pour_utilisateur": f"Ta bibliothèque compte {len(L)} morceaux. Ce qui domine : {f}. Tes artistes les plus présents : {a}."}


def main():
    args = sys.argv[1:]
    d = {}
    if "--fichier" in args:
        d = json.load(open(args[args.index("--fichier") + 1], encoding="utf-8"))
    elif args:
        try:
            d = json.loads(args[0])
        except Exception:
            d = {"action": "chercher", "q": " ".join(args)}
    if isinstance(d.get("parametres"), dict):
        d = {**d, **d["parametres"]}
    a = sans(d.get("action") or "proposer")
    L = classer(charger())
    if a in ("proposer", "propose", "suggerer", "choisir", "trouver"):
        sortir(proposer(L, d))
    if a in ("chercher", "cherche", "recherche", "artiste"):
        sortir(chercher(L, d))
    if a in ("gouts", "gout", "profil", "resume"):
        sortir(gouts(L))
    sortir({"ok": False, "phrase_pour_utilisateur": "Pour la musique je sais : proposer (selon l'ambiance), chercher un artiste, ou résumer tes goûts."})


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        sortir({"ok": False, "phrase_pour_utilisateur": "Je n'ai pas réussi à fouiller ta musique.", "erreur": repr(e)[:200]})
