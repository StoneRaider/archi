# indicateur_polymarket.py - outil maison d'Archi : ce que les marches de prediction Polymarket estiment (05/11/2026).
# Cadrage (05/11/2026) :
#   - un INDICATEUR d'actualite / OSINT : Archi l'appelle quand l'utilisateur parle d'un sujet ;
#   - themes : tout SAUF sport et meteo ; les 10 marches les plus actifs de la semaine + n'importe quel marche sur demande ;
#   - signaux : mouvement brusque de la cote et volume anormal. AUCUNE analyse de comptes ou de parieurs ;
#   - deux passages la nuit (2 h et 6 h, taches Windows) ; une ligne dans le brief de 14 h SEULEMENT s'il y a eu un gros
#     mouvement ; une alerte Telegram (rare, 3 par jour maximum) si >= 20 points en 24 h ET que ca touche les regions suivies
#     (ARCHI_REGIONS_ALERTE, Europe par defaut), un conflit majeur, l'economie ou le pays ou se trouve l'utilisateur ;
#   - "surveille ce marche" : rapport tout de suite, regarde la nuit, point dans le brief du lendemain.
#
#   python indicateur_polymarket.py --fichier demande.json   (appele par outils_maison)
#     action = tendances (defaut sans sujet) | chercher (defaut avec sujet) | surveiller | arreter | suivis
#     sujet  = de quoi parle J (anglais de preference : Polymarket est en anglais) ; quoi = pour arreter ; nombre
#   python indicateur_polymarket.py --passe                 (taches Windows 2 h et 6 h)
#   python indicateur_polymarket.py --brief                 (lignes du brief de 14 h, vide s'il n'y a rien de notable)
#
# GARDE-FOUS DURS (dans le code, pas seulement dans le prompt) :
#   1. LECTURE SEULE : seules des requetes GET vers une liste fermee d'adresses publiques (HOTES_LECTURE). Aucun POST vers
#      Internet ; les seuls POST vont a la machine locale (modele local pour traduire, webhook n8n pour l'alerte Telegram).
#   2. JAMAIS de pari, de compte, de portefeuille, de transaction : aucun code pour ca ; une demande de ce genre est refusee.
#   3. JAMAIS de conseil d'achat, de vente ou de pari : refuse, et tout texte qui en ressemble est retire.
#   4. Les cotes sont dites comme des PROBABILITES ESTIMEES PAR LE MARCHE, jamais comme des certitudes.
#   5. Personne n'est designe : l'outil n'interroge PAS l'API des transactions ni des comptes (data-api exclue de la liste).
import argparse, json, os, re, sys, unicodedata, urllib.error, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

HOME = os.path.expanduser("~")
BASE = os.environ.get("ARCHI_BASE") or os.path.join(HOME, ".n8n-files")
DOS = os.path.join(BASE, "indicateur_polymarket")
SUIVIS = os.path.join(DOS, "suivis.json")
ETAT = os.path.join(DOS, "etat.json")
BRIEF = os.path.join(DOS, "brief.json")
TRAD = os.path.join(DOS, "traductions.json")
JOURNAL = os.path.join(DOS, "journal.txt")
POSITION = os.path.join(BASE, "memoire", "position.json")

GAMMA = "https://gamma-api.polymarket.com"
HOTES_LECTURE = {"gamma-api.polymarket.com", "news.google.com"}     # data-api (comptes, transactions) VOLONTAIREMENT absent
LM = os.environ.get("POLY_LM") or os.environ.get("ARCHI_LM_URL", "http://127.0.0.1:1234/v1").rstrip("/") + "/chat/completions"
LM_MODELE = os.environ.get("ARCHI_MODELE", "qwythos-9b-claude-mythos-5-1m")
# webhook n8n LOCAL qui relaie l'alerte sur Telegram (facultatif : sans lui, l'alerte est seulement notee au journal)
RETOUR = os.environ.get("POLY_RETOUR") or os.environ.get("ARCHI_WEBHOOK_ALERTE", "")
UA = {"User-Agent": "Mozilla/5.0 (Archi, assistant personnel, lecture seule)", "Accept": "application/json, text/xml"}

MOUV_BRIEF = 0.10          # 10 points en 24 h = gros mouvement (ligne dans le brief)
MOUV_ALERTE = 0.20         # 20 points en 24 h + sujet qui touche l'utilisateur = alerte Telegram
VOL_FACTEUR, VOL_MIN = 4.0, 250_000     # volume du jour >= 4 x la moyenne de la semaine, et au moins 250 000 $
LIQ_MIN, VOL24_MIN = 20_000, 20_000     # marches trop petits : cotes qui sautent pour rien
FIN_MIN = timedelta(hours=48)           # marche qui se termine dans moins de 48 h : il bouge forcement, on l'ignore
ALERTES_PAR_JOUR, REPOS_ALERTE = 3, timedelta(hours=48)
MAX_SUIVIS = 15
MAINTENANT = None          # pour les tests

EXCLUS = re.compile(r"^(sports?|esports?|soccer|football|nfl|nba|nhl|mlb|ncaa.*|ufc|mma|boxing|tennis|golf|f1|formula-1|"
                    r"cricket|rugby|baseball|basketball|hockey|ucl|epl|la-liga|serie-a|bundesliga|ligue-1|champions-league|"
                    r"olympics|world-cup|fifa.*|chess|league-of-legends|lol|dota.*|cs2|counter-strike|valorant|games|"
                    r"weather|temperature|daily-temperature|climate-weather|hurricanes?|tweets-markets|mention-markets)$")
SPORT_TITRE = re.compile(r"\b(vs\.?|v\.)\s|\b(nba|nfl|nhl|mlb|ufc|uefa|fifa|premier league|grand prix|super bowl|world series|"
                         r"temperature|highest temp|weather)\b", re.I)

_REGIONS = "|".join(re.escape(x.strip().lower()) for x in os.environ.get("ARCHI_REGIONS_ALERTE", "").split(",") if x.strip())
IMPACT = re.compile(r"\b(" + (_REGIONS + "|" if _REGIONS else "") + r"france|french|macron|le pen|bardella|melenchon|mélenchon|paris|europe|"
                    r"european|eu|ecb|euro|eurozone|nato|russia|russian|ukraine|putin|zelensky|nuclear|war|invade|invasion|"
                    r"military|strike|strikes|attack|missile|ceasefire|iran|china|taiwan|recession|inflation|fed|interest rates?|"
                    r"oil|gas|energy|tariffs?|default|crash|pandemic|martial law|coup)\b", re.I)
IMPACT_TAGS = {"military", "military-strikes", "war", "economy", "fed-rates", "fed", "ecb", "france",
               "french-election", "europe", "eu", "ukraine", "russia", "nuclear", "recession", "inflation", "oil"}
# marches "a paliers" (prix du Bitcoin entre X et Y, hausse ou baisse du jour...) : leurs cotes sautent a chaque
# mouvement du prix, ce n'est pas un signal d'actualite. Visibles a la demande, ignores pour le brief et les alertes.
EXCLUS_SIGNAL = re.compile(r"^(hit-price|crypto-prices|up-or-down|multi-strikes|daily|weekly|pre-market|stocks-prices|"
                           r"price-range|neg-risk-price)$")
PALIERS_TITRE = re.compile(r"(?i)what price will|up or down|price of .+ on |above .+ on |close (above|below)|"
                           r"# ?tweets|how many tweets")
PAYS = {"france": "France", "suisse": "Switzerland", "thailande": "Thailand", "espagne": "Spain", "italie": "Italy",
        "allemagne": "Germany", "belgique": "Belgium", "portugal": "Portugal", "royaume-uni": "United Kingdom",
        "angleterre": "England", "irlande": "Ireland", "pays-bas": "Netherlands", "autriche": "Austria", "grece": "Greece",
        "croatie": "Croatia", "pologne": "Poland", "turquie": "Turkey", "maroc": "Morocco", "tunisie": "Tunisia",
        "algerie": "Algeria", "egypte": "Egypt", "etats-unis": "United States", "usa": "United States", "canada": "Canada",
        "mexique": "Mexico", "bresil": "Brazil", "argentine": "Argentina", "japon": "Japan", "chine": "China",
        "inde": "India", "vietnam": "Vietnam", "viet nam": "Vietnam", "cambodge": "Cambodia", "laos": "Laos",
        "indonesie": "Indonesia", "philippines": "Philippines", "malaisie": "Malaysia", "singapour": "Singapore",
        "coree du sud": "South Korea", "australie": "Australia", "israel": "Israel", "liban": "Lebanon",
        "emirats arabes unis": "UAE", "senegal": "Senegal", "norvege": "Norway", "suede": "Sweden", "danemark": "Denmark",
        "islande": "Iceland", "ukraine": "Ukraine", "russie": "Russia", "nepal": "Nepal", "sri lanka": "Sri Lanka",
        "madagascar": "Madagascar", "cuba": "Cuba", "perou": "Peru", "colombie": "Colombia", "venezuela": "Venezuela"}
FR_EN = {"cessez-le-feu": "ceasefire", "cessez le feu": "ceasefire", "election": "election", "elections": "election",
         "presidentielle": "presidential election", "president": "president", "guerre": "war", "paix": "peace",
         "accord": "deal", "taux": "rates", "bce": "ECB", "inflation": "inflation", "recession": "recession",
         "petrole": "oil", "chine": "China", "russie": "Russia", "etats-unis": "US", "allemagne": "Germany",
         "suisse": "Switzerland", "iran": "Iran", "israel": "Israel", "gaza": "Gaza", "premier ministre": "prime minister",
         "dissolution": "dissolution", "gouvernement": "government", "destitution": "impeachment", "bitcoin": "Bitcoin",
         "ia": "AI", "intelligence artificielle": "AI", "nucleaire": "nuclear", "invasion": "invasion",
         "droits de douane": "tariffs", "chomage": "unemployment", "pape": "pope", "taiwan": "Taiwan", "coree": "Korea"}

REFUS_PARI = re.compile(r"\b(parier|parie|paries|pariez|parions|miser|mise sur|je mise|on mise|misez|"
                        r"place[rz]? (un|des|mon|le) paris?|faire un pari|prendre (un|des) paris?|"
                        r"ach[eè]te[rz]? (des|du|les|mes) (parts|shares|oui|non|yes|no|positions?)|"
                        r"vend(re|s|ez) (mes|des|les) (parts|shares|positions?)|"
                        r"(cr[ée]e|ouvr)[a-z]*(-moi)? (un |mon |le )?compte|portefeuille|wallet|"
                        r"d[ée]pose[rz]? (de l'argent|des fonds|des usdc)|usdc)\b", re.I)
CONSEIL = re.compile(r"\b(dois[- ]je|devrais[- ]je|faut[- ]il (parier|miser|acheter|vendre)|tu me conseilles|tu conseilles|"
                     r"un conseil|bon plan|bon pari|rentable|gagner de l'argent|investir)\b", re.I)
PERSONNES = re.compile(r"\b(qui (a|ont) (pari|mis[eé]?)|quels? comptes?|initi[ée]s?|parieurs?|insider|whales?|baleines?|"
                       r"wallets?|adresses? (du|des) compte)", re.I)
TEXTE_CONSEIL = re.compile(r"\b(achetez|vendez|pariez|misez|investissez|tu devrais (acheter|vendre|parier|miser))\b", re.I)
AVERTISSEMENT = "Ce sont des probabilités estimées par les parieurs du marché, pas des certitudes."


def _qui():
    """« , Camille » : le prenom du profil (ARCHI_UTILISATEUR, regle a l'installation) ; rien s'il manque."""
    p = " ".join((os.environ.get("ARCHI_UTILISATEUR") or "").split())[:30]
    return (", " + p) if p else ""


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


def sans_accent(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "").lower()) if unicodedata.category(c) != "Mn")


def lire(f, defaut):
    try:
        with open(f, encoding="utf-8-sig") as h:
            return json.load(h)
    except Exception:
        return defaut


def ecrire(f, d):
    os.makedirs(os.path.dirname(f), exist_ok=True)
    tmp = f + ".tmp"
    with open(tmp, "w", encoding="utf-8") as h:
        json.dump(d, h, ensure_ascii=False, indent=1)
    os.replace(tmp, f)


def noter(txt):
    try:
        os.makedirs(DOS, exist_ok=True)
        with open(JOURNAL, "a", encoding="utf-8") as h:
            h.write(f"{maintenant():%Y-%m-%d %H:%M} {txt}\n")
    except Exception:
        pass


# ---------- reseau : LECTURE SEULE ----------
def lecture_web(url, timeout=25):
    """GET seulement, et seulement vers HOTES_LECTURE (garde-fou 1 et 5)"""
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" or u.hostname not in HOTES_LECTURE:
        raise Erreur(f"adresse refusée (lecture seule, liste fermée) : {u.hostname}")
    req = urllib.request.Request(url, headers=UA, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def poste_local(url, corps, timeout):
    """POST seulement vers la machine locale (modele local, webhook n8n)"""
    u = urllib.parse.urlparse(url)
    if u.hostname not in {"127.0.0.1", "localhost"}:
        raise Erreur("envoi refusé : seulement vers la machine locale")
    req = urllib.request.Request(url, data=json.dumps(corps).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def gamma(chemin, **params):
    if chemin not in ("/events", "/public-search"):
        raise Erreur("chemin Polymarket non prévu")
    return json.loads(lecture_web(GAMMA + chemin + "?" + urllib.parse.urlencode(params)))


# ---------- lecture des marches ----------
def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _liste(x):
    if isinstance(x, list):
        return x
    try:
        return json.loads(x or "[]")
    except Exception:
        return []


def _date(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except Exception:
        return None


def exclu(ev):
    tags = {str(t.get("slug") or "").lower() for t in ev.get("tags") or [] if isinstance(t, dict)}
    return any(EXCLUS.match(t) for t in tags) or bool(SPORT_TITRE.search(ev.get("title") or ""))


def marches(ev):
    """les marches ouverts d'un evenement, sous une forme simple"""
    out = []
    tags = [str(t.get("slug") or "") for t in ev.get("tags") or [] if isinstance(t, dict)]
    for m in ev.get("markets") or []:
        if m.get("closed") or m.get("active") is False:
            continue
        issues, prix = _liste(m.get("outcomes")), [_f(p) for p in _liste(m.get("outcomePrices"))]
        if not prix:
            continue
        oui = not issues or sans_accent(issues[0]) == "yes"
        option = (m.get("groupItemTitle") or "").strip() if oui else str(issues[0])
        out.append({"id": str(m.get("id")), "evenement": ev.get("title") or "", "slug": ev.get("slug") or "",
                    "question": m.get("question") or ev.get("title") or "", "option": option, "prix": round(prix[0], 4),
                    "d24": round(_f(m.get("oneDayPriceChange")), 4), "d7": round(_f(m.get("oneWeekPriceChange")), 4),
                    "vol24": round(_f(m.get("volume24hr"))), "liquidite": round(_f(m.get("liquidityNum") or m.get("liquidity"))),
                    "fin": m.get("endDate") or ev.get("endDate") or "", "tags": tags,
                    "lien": f"https://polymarket.com/event/{ev.get('slug') or ''}"})
    return out


def principaux(ev, n=3):
    """les options les plus probables d'un evenement (multi-choix) ou la cote du oui (oui/non)"""
    ms = sorted(marches(ev), key=lambda m: -m["prix"])
    return ms[:n]


def evenement(slug):
    d = gamma("/events", slug=slug)
    return d[0] if isinstance(d, list) and d else None


def tendances_semaine(n=10, total=60):
    evs = gamma("/events", active="true", closed="false", archived="false", limit=total, order="volume1wk",
                ascending="false")
    return [e for e in evs if not exclu(e) and marches(e)][:n]


def traduire_requete(sujet):
    s = sans_accent(sujet)
    for fr, en in sorted(FR_EN.items(), key=lambda x: -len(x[0])):
        s = re.sub(r"\b" + re.escape(fr) + r"\b", en, s)
    for fr, en in PAYS.items():
        s = re.sub(r"\b" + re.escape(fr) + r"\b", en, s)
    mots = [w for w in re.split(r"\s+", s) if w and w not in {"le", "la", "les", "de", "du", "des", "en", "et", "a", "au",
                                                              "aux", "sur", "pour", "un", "une", "est", "ce", "que", "qui"}]
    return " ".join(mots)


# mots qui ne suffisent jamais a trouver un marche (05/11 : "situation au Venezuela" ramenait "Situational Awareness")
MOTS_VIDES = set("""le la les l de d du des en et a au aux sur pour un une est ce cet cette ces que qu qui quoi quel quelle
quels quelles ou dans par avec sans son sa ses leur leurs mon ma mes ton ta tes il elle ils elles on y se ne pas plus moins
tres trop va vont sera seront etre avoir fait faire dit dire voir sait savoir parle parler peut veut alors donc mais car
comment pourquoi quand combien situation point etat etats sujet sujets actu actualite actualites info infos nouvelle
nouvelles dernier derniere derniers dernieres derniere tendance tendances question questions chose choses truc trucs
aujourd hui demain hier semaine mois annee jour maintenant ca cela ceci ici chez entre vers depuis apres avant
marche marches cote cotes pronostic pronostics prediction predictions chance chances probabilite probabilites estime
estimation polymarket pari
the of in on at to for and or a an is are be will would what who how why when which this that these those it its
by with from about as into over news update updates latest situation status point odds market markets chance
chances probability prediction predictions""".split())


def _mot(w):
    """forme comparable d'un mot : sans accent, minuscule, sans le s du pluriel"""
    return w[:-1] if len(w) > 3 and w.endswith("s") else w


def mots_importants(texte):
    """les mots qui comptent pour chercher : ni mots vides, ni nombres seuls, ni mots d'une lettre"""
    out = []
    for w in re.findall(r"[a-z0-9]+", sans_accent(texte)):
        if len(w) < 2 or w.isdigit() or w in MOTS_VIDES or _mot(w) in MOTS_VIDES:
            continue
        if _mot(w) not in out:
            out.append(_mot(w))
    return out


def mots_evenement(e):
    """les mots entiers d'un evenement : titre, adresse, questions et options de ses marches.
    Pas les etiquettes : Polymarket range "US strike on Colombia" sous "venezuela"."""
    parts = [e.get("title"), e.get("slug")]
    for m in e.get("markets") or []:
        if isinstance(m, dict):
            parts += [m.get("question"), m.get("groupItemTitle")]
    return {_mot(w) for w in re.findall(r"[a-z0-9]+", sans_accent(" ".join(str(x) for x in parts if x)))}


def chercher_evenements(sujet, n=3):
    essais = [sujet]
    t = traduire_requete(sujet)
    if t and t.lower() != sujet.lower():
        essais.append(t)
    formulations = [set(mots_importants(q)) for q in essais]
    formulations = [f for f in formulations if f]
    if not formulations:
        return []
    # dernier essai : seulement les mots importants (la recherche floue de Polymarket se noie dans "situation", "point"...)
    court = " ".join(mots_importants(essais[-1]))
    if court and court not in [q.lower() for q in essais]:
        essais.append(court)

    def score(e):
        """0 si le marche ne parle pas du sujet ; sinon le nombre de mots importants retrouves en entier.
        Il faut TOUS les mots d'une formulation (un seul manquant tolere a partir de 3 mots) :
        "elections en Thailande" ne doit pas ramener une election a Taiwan."""
        mots, best = mots_evenement(e), 0
        for f in formulations:
            n = len(f & mots)
            if n == len(f) or (len(f) >= 3 and n >= len(f) - 1):
                best = max(best, n)
        return best

    vus, out = set(), []
    for q in essais:
        d = gamma("/public-search", q=q, limit_per_type=10, events_status="active")
        for e in (d.get("events") or []) if isinstance(d, dict) else []:
            if e.get("closed") or e.get("slug") in vus or exclu(e):
                continue
            vus.add(e.get("slug"))
            # un mot important doit se retrouver EN ENTIER dans le marche (pas "situation" dans "Situational")
            s = score(e)
            if s:
                out.append((s, e))
    meilleur = max((s for s, _ in out), default=0)
    out = [e for s, e in out if s == meilleur]
    out.sort(key=lambda e: -_f(e.get("volume") or e.get("volume24hr")))
    complets = []
    for e in out[:n]:
        full = evenement(e["slug"]) or e
        if marches(full) and not exclu(full):
            complets.append(full)
    return complets


# ---------- traduction (modele local, facultatif) et "pourquoi ca bouge" ----------
def traduire(textes, timeout):
    """traduit en francais avec le modele local ; cache ; en cas d'echec, garde l'anglais"""
    cache = lire(TRAD, {})
    manquants = [t for t in dict.fromkeys(textes) if t and t not in cache]
    if manquants and timeout > 0:
        consigne = ("Traduis chaque ligne en français, court et clair, sans rien ajouter ni commenter. "
                    "Réponds UNIQUEMENT en JSON : {\"t\": [\"traduction 1\", ...]} dans le même ordre.\n" +
                    "\n".join(f"{i + 1}. {t}" for i, t in enumerate(manquants[:30])))
        try:
            rep = poste_local(LM, {"model": LM_MODELE, "temperature": 0.1, "max_tokens": 2500,
                                   "messages": [{"role": "user", "content": consigne}]}, timeout)
            txt = json.loads(rep)["choices"][0]["message"].get("content") or ""
            txt = re.sub(r"(?s)<think>.*?</think>", "", txt)
            m = re.search(r"\{.*\}", txt, re.S)
            liste = json.loads(m.group(0)).get("t", []) if m else []
            for en, fr in zip(manquants, liste):
                fr = str(fr).strip()
                if fr and len(fr) < 3 * len(en) + 40 and not TEXTE_CONSEIL.search(fr):
                    cache[en] = fr
            if len(cache) > 3000:
                cache = dict(list(cache.items())[-2000:])
            ecrire(TRAD, cache)
        except Exception as e:
            noter(f"traduction impossible : {str(e)[:120]}")
    return {t: cache.get(t, t) for t in textes}


def mots_cles(m):
    q = re.sub(r"(?i)^will\s+|\?|\bby\b.*$|\bbefore\b.*$|\bin (19|20)\d\d\b|\b(19|20)\d\d\b", " ", m["question"])
    q = re.sub(r"[^\w\s'.-]", " ", q)
    return " ".join(q.split()[:8])


def pourquoi(m, n=2):
    """1 ou 2 titres d'actualite des 2 derniers jours sur le sujet du marche (Google Actualites, lecture seule)"""
    q = mots_cles(m)
    if not q:
        return []
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q + " when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"})
    try:
        racine = ET.fromstring(lecture_web(url, timeout=20))
    except Exception:
        return []
    out = []
    for it in racine.iter("item"):
        titre = (it.findtext("title") or "").strip()
        source = (it.findtext("source") or "").strip()
        if source and titre.endswith(" - " + source):
            titre = titre[: -len(source) - 3]
        if titre:
            out.append({"titre": titre[:160], "source": source[:40]})
        if len(out) >= n:
            break
    return out


# ---------- phrases (garde-fou 4 : estimation du marche) ----------
def pct(p):
    v = round(p * 100)
    return "moins de 1 %" if p < 0.01 and v == 0 else "plus de 99 %" if p > 0.99 and v == 100 else f"{v} %"


def pts(d):
    v = round(d * 100)
    return f"{'+' if v > 0 else ''}{v} point{'s' if abs(v) > 1 else ''}"


def nom(m, tr):
    ev = tr.get(m["evenement"], m["evenement"])
    if m["option"]:
        return f"{ev} — {tr.get(m['option'], m['option'])}"
    return tr.get(m["question"], m["question"])


def phrase_marche(m, tr):
    t = f"{nom(m, tr)} : le marché estime {pct(m['prix'])}"
    if abs(m["d24"]) >= 0.01:
        t += f" ({pts(m['d24'])} en 24 h)"
    return t


def nettoyer(texte):
    """garde-fou 3 : aucune formulation de conseil ne sort de l'outil"""
    return re.sub(r"(?i)\b(tu devrais|je te conseille|il faut) (parier|miser|acheter|vendre)\b[^.]*\.?", "", texte)


# ---------- signaux ----------
def ok_signal(m, now):
    fin = _date(m["fin"])
    return (m["liquidite"] >= LIQ_MIN and m["vol24"] >= VOL24_MIN and (fin is None or fin - now >= FIN_MIN)
            and 0.0 < m["prix"] < 1.0)


def volume_anormal(ev):
    v24, v7 = _f(ev.get("volume24hr")), _f(ev.get("volume1wk"))
    return v24 >= VOL_MIN and v7 > 0 and v24 >= VOL_FACTEUR * (v7 / 7)


def pays_utilisateur():
    p = lire(POSITION, {})
    try:
        if maintenant() - datetime.fromisoformat(p["heure"]) > timedelta(hours=48):
            return None
        pays = sans_accent(str(p.get("lieu") or "").split(",")[-1]).strip()
        return PAYS.get(pays, pays.title() if pays else None)
    except Exception:
        return None


def touche_utilisateur(m, pays):
    texte = " ".join([m["evenement"], m["question"], m["option"]])
    if IMPACT.search(texte) or IMPACT_TAGS & set(m["tags"]):
        return True
    return bool(pays and re.search(r"\b" + re.escape(pays) + r"\b", texte, re.I))


# ---------- actions ----------
def rapport(evs, titre_vide, timeout_trad=20, avec_pourquoi=True):
    if not evs:
        return False, titre_vide, []
    tous = []
    for e in evs:
        tous.extend(principaux(e))
    tr = traduire([m["evenement"] for m in tous] + [m["option"] for m in tous if m["option"]] +
                  [m["question"] for m in tous if not m["option"]], timeout_trad)
    lignes, data = [], []
    for e in evs:
        ms = principaux(e)
        if not ms:
            continue
        ev_fr = tr.get(e.get("title"), e.get("title"))
        if len(ms) == 1 and not ms[0]["option"]:
            l = phrase_marche(ms[0], tr)
        else:
            l = ev_fr + " : " + ", ".join(f"{tr.get(m['option'], m['option']) or 'oui'} {pct(m['prix'])}"
                                          + (f" ({pts(m['d24'])} en 24 h)" if abs(m["d24"]) >= 0.03 else "") for m in ms)
        if volume_anormal(e):
            l += " ; activité inhabituelle aujourd'hui"
        lignes.append(l)
        data.append({"evenement": e.get("title"), "lien": f"https://polymarket.com/event/{e.get('slug')}",
                     "marches": ms})
    plus_gros = max((m for d in data for m in d["marches"]), key=lambda m: abs(m["d24"]), default=None)
    pq = []
    if avec_pourquoi and plus_gros and abs(plus_gros["d24"]) >= 0.05:
        pq = pourquoi(plus_gros)
        if pq:
            trp = traduire([x["titre"] for x in pq], timeout_trad)
            lignes.append("Pourquoi ça bouge (actualité) : " + " ; ".join(
                f"« {trp.get(x['titre'], x['titre'])} » ({x['source']})" for x in pq))
    return True, lignes, data


def act_tendances(p):
    n = max(1, min(10, int(_f(p.get("nombre"), 10) or 10)))
    ok, lignes, data = rapport(tendances_semaine(n), "Je n'ai trouvé aucun marché actif cette semaine.")
    if not ok:
        return False, lignes, {}
    phrase = (f"Sur Polymarket, les {len(data)} marchés les plus suivis "
              "de la semaine (hors sport et météo) :\n" + "\n".join("• " + l for l in lignes) + "\n" + AVERTISSEMENT)
    return True, phrase, {"marches": data}


def act_chercher(p, prefixe=""):
    sujet = str(p.get("sujet") or p.get("quoi") or "").strip()
    if not sujet:
        raise Erreur("Dis-moi sur quel sujet chercher (par exemple : « présidentielle française » ou « Ukraine ceasefire »).")
    evs = chercher_evenements(sujet, max(1, min(5, int(_f(p.get("nombre"), 3) or 3))))
    ok, lignes, data = rapport(evs, f"Polymarket n'a pas de marché ouvert sur « {sujet} » (hors sport et météo). "
                                    "Essaie avec d'autres mots, en anglais si possible.")
    if not ok:
        return True, prefixe + lignes, {"marches": [], "trouve": False}
    phrase = prefixe + f"Sur Polymarket, à propos de « {sujet} » :\n" + "\n".join("• " + l for l in lignes) + "\n" + AVERTISSEMENT
    return True, phrase, {"marches": data, "trouve": True}


def act_surveiller(p):
    sujet = str(p.get("sujet") or p.get("quoi") or "").strip()
    if not sujet:
        raise Erreur("Dis-moi quel sujet ou quel marché surveiller.")
    suivis = lire(SUIVIS, [])
    if len(suivis) >= MAX_SUIVIS:
        raise Erreur(f"J'en surveille déjà {MAX_SUIVIS} : dis-moi d'abord lequel arrêter.")
    evs = chercher_evenements(sujet, 1)
    if not evs:
        return True, (f"Polymarket n'a pas de marché ouvert sur « {sujet} » : je ne peux rien surveiller. "
                      "Essaie avec d'autres mots, en anglais si possible."), {"ajoute": False}
    e = evs[0]
    if any(s["slug"] == e["slug"] for s in suivis):
        ok, phrase, extra = act_chercher({"sujet": sujet, "nombre": 1})
        return True, "Je le surveillais déjà. " + phrase, dict(extra, ajoute=False)
    ms = principaux(e)
    suivis.append({"id": f"s{len(suivis) + 1}{maintenant():%m%d%H%M}", "sujet": sujet, "slug": e["slug"],
                   "evenement": e.get("title"), "depuis": maintenant().isoformat(timespec="minutes"),
                   "dernier": {m["id"]: m["prix"] for m in ms}})
    ecrire(SUIVIS, suivis)
    noter(f"surveiller {e['slug']} ({sujet})")
    ok, lignes, data = rapport([e], "")
    phrase = (f"C'est noté : je surveille « {e.get('title')} ». Je le regarde cette nuit et je te refais le point demain "
              "dans le brief ; dis-moi ensuite si on continue ou si c'est terminé.\nPour l'instant :\n" +
              "\n".join("• " + l for l in lignes) + "\n" + AVERTISSEMENT)
    return True, phrase, {"ajoute": True, "marches": data}


def act_arreter(p):
    quoi = sans_accent(p.get("quoi") or p.get("sujet") or "").strip()
    suivis = lire(SUIVIS, [])
    if not suivis:
        return True, "Je ne surveille aucun marché en ce moment.", {}
    if quoi in {"tout", "tous", "toutes", "all"}:
        garde, retires = [], suivis
    else:
        if not quoi:
            raise Erreur("Dis-moi lequel arrêter : " + " ; ".join(s["sujet"] for s in suivis))
        retires = [s for s in suivis if quoi == sans_accent(s["id"]) or quoi in sans_accent(s["sujet"])
                   or quoi in sans_accent(s["evenement"]) or quoi in sans_accent(s["slug"])]
        garde = [s for s in suivis if s not in retires]
    if not retires:
        return False, "Je ne trouve pas ce suivi. En ce moment je surveille : " + " ; ".join(s["sujet"] for s in suivis), {}
    ecrire(SUIVIS, garde)
    noter("arreter " + ", ".join(s["slug"] for s in retires))
    return True, "C'est fait : je ne surveille plus " + " ; ".join(f"« {s['sujet']} »" for s in retires) + ".", {}


def act_suivis(p):
    suivis = lire(SUIVIS, [])
    if not suivis:
        return True, "Je ne surveille aucun marché en ce moment. Dis « surveille … » pour en ajouter un.", {"suivis": []}
    return True, "Je surveille : " + " ; ".join(f"« {s['sujet']} » (depuis le {s['depuis'][8:10]}/{s['depuis'][5:7]})"
                                                for s in suivis), {"suivis": suivis}


ACTIONS = {"tendances": act_tendances, "chercher": act_chercher, "surveiller": act_surveiller,
           "arreter": act_arreter, "suivis": act_suivis}
ALIAS = {"top": "tendances", "actifs": "tendances", "resume": "tendances", "quoi de neuf": "tendances", "tendance": "tendances",
         "recherche": "chercher", "rechercher": "chercher", "sujet": "chercher", "cote": "chercher", "cotes": "chercher",
         "marche": "chercher", "voir": "chercher", "suivre": "surveiller", "surveille": "surveiller", "ajouter": "surveiller",
         "stop": "arreter", "arrete": "arreter", "retirer": "arreter", "termine": "arreter", "fini": "arreter",
         "ne plus suivre": "arreter", "ne plus surveiller": "arreter", "liste": "suivis", "lister": "suivis",
         "surveilles": "suivis", "suivi": "suivis"}
ACTIONS_INTERDITES = re.compile(r"pari|parier|miser|acheter|vendre|bet|buy|sell|trade|ordre|order|wallet|portefeuille|"
                                r"compte|deposer|retirer_fonds|transaction|connexion|login", re.I)


def traiter(p):
    brut = " ".join(str(p.get(k) or "") for k in ("action", "sujet", "quoi"))
    action = sans_accent(p.get("action") or "").strip().replace("_", " ")
    if ACTIONS_INTERDITES.search(action) or REFUS_PARI.search(brut):
        return False, ("Non : je ne fais que LIRE les cotes publiques de Polymarket. Je ne parie pas, je ne crée pas de compte "
                       "ni de portefeuille, et je ne fais aucune transaction (Polymarket est d'ailleurs interdit en France)."), \
               {"refus": "pari"}
    if PERSONNES.search(brut):
        return False, ("Je ne regarde pas qui parie : je lis seulement les cotes et les volumes publics, sans désigner "
                       "aucun compte ni aucune personne. Je peux te dire ce que le marché estime sur le sujet."), \
               {"refus": "personnes"}
    action = ALIAS.get(action, action)
    if action not in ACTIONS:
        action = "chercher" if (p.get("sujet") or p.get("quoi")) else "tendances"
    prefixe = ""
    if CONSEIL.search(brut):
        prefixe = "Je ne donne aucun conseil de pari ni d'investissement. Voici seulement ce que le marché estime.\n"
    if action == "chercher":
        ok, phrase, extra = act_chercher(p, prefixe)
    else:
        ok, phrase, extra = ACTIONS[action](p)
        phrase = prefixe + phrase if isinstance(phrase, str) else phrase
    return ok, nettoyer(phrase), dict(extra, action=action)


# ---------- passage de nuit ----------
def ligne_signal(s, tr, pq):
    t = phrase_marche(s, tr)
    if pq:
        t += " — actualité : " + " ; ".join(f"« {tr.get(x['titre'], x['titre'])} » ({x['source']})" for x in pq)
    return t


def prevenir(texte, vocal):
    """alerte Telegram par le meme chemin que les autres rapports d'Archi (webhook n8n local)"""
    if os.environ.get("POLY_SANS_TELEGRAM"):
        noter("TELEGRAM (simulé) : " + texte.replace("\n", " | ")[:400])
        return True
    if not RETOUR:
        noter("alerte (pas de webhook ARCHI_WEBHOOK_ALERTE) : " + texte.replace("\n", " | ")[:400])
        return False
    try:
        poste_local(RETOUR, {"type": "REPONSE", "canal": "recolte", "texte": texte, "vocal": vocal}, 60)
        return True
    except Exception as e:
        noter(f"alerte Telegram impossible : {e}")
        return False


def passe():
    now = maintenant()
    jour = now.strftime("%Y-%m-%d")
    evs = {}
    for ordre in ("volume1wk", "volume24hr"):
        for offset in (0, 100):
            try:
                for e in gamma("/events", active="true", closed="false", archived="false", limit=100, offset=offset,
                               order=ordre, ascending="false"):
                    evs.setdefault(e.get("slug"), e)
            except Exception as e:
                noter(f"lecture {ordre}/{offset} impossible : {str(e)[:120]}")
    suivis = lire(SUIVIS, [])
    for s in suivis:
        try:
            e = evenement(s["slug"])
            if e:
                evs[s["slug"]] = e
        except Exception:
            pass
    if not evs:
        noter("passe : Polymarket injoignable")
        return {"ok": False, "raison": "Polymarket injoignable"}
    signaux = []
    for e in evs.values():
        tags = {str(t.get("slug") or "").lower() for t in e.get("tags") or [] if isinstance(t, dict)}
        if exclu(e) or any(EXCLUS_SIGNAL.match(t) for t in tags) or PALIERS_TITRE.search(e.get("title") or ""):
            continue
        vol = volume_anormal(e)
        for m in marches(e):
            if ok_signal(m, now) and (abs(m["d24"]) >= MOUV_BRIEF):
                signaux.append(dict(m, volume_anormal=vol))
    # un seul signal par evenement (le plus gros mouvement)
    par_ev = {}
    for s in sorted(signaux, key=lambda s: -abs(s["d24"])):
        par_ev.setdefault(s["slug"], s)
    signaux = list(par_ev.values())[:6]
    pays = pays_utilisateur()

    # point des suivis
    suivis_l, data_suivis = [], []
    for s in suivis:
        e = evs.get(s["slug"])
        if not e:
            suivis_l.append((s, None))
            continue
        if e.get("closed") or not marches(e):
            suivis_l.append((s, "fini"))
            continue
        suivis_l.append((s, principaux(e)))

    textes = [s["evenement"] for s in signaux] + [s["option"] or s["question"] for s in signaux]
    for _, ms in suivis_l:
        if isinstance(ms, list):
            textes += [m["evenement"] for m in ms] + [m["option"] for m in ms if m["option"]]
    pqs = {s["id"]: pourquoi(s) for s in signaux[:4]}
    textes += [x["titre"] for v in pqs.values() for x in v]
    tr = traduire(textes, 120)

    etat = lire(ETAT, {"alertes": []})
    etat["alertes"] = [a for a in etat.get("alertes", []) if now - datetime.fromisoformat(a["quand"]) < timedelta(days=3)]
    du_jour = [a for a in etat["alertes"] if a["quand"][:10] == jour]
    envoyees = []
    for s in signaux:
        if abs(s["d24"]) < MOUV_ALERTE or not touche_utilisateur(s, pays):
            continue
        if len(du_jour) + len(envoyees) >= ALERTES_PAR_JOUR:
            break
        if any(a["id"] == s["id"] and now - datetime.fromisoformat(a["quand"]) < REPOS_ALERTE for a in etat["alertes"]):
            continue
        texte = ("🔮 Polymarket : mouvement fort cette nuit\n" + ligne_signal(s, tr, pqs.get(s["id"])) +
                 ("\n(activité inhabituelle sur ce marché)" if s.get("volume_anormal") else "") + "\n" + AVERTISSEMENT)
        vocal = f"Mouvement fort sur Polymarket{_qui()} : {nom(s, tr)}, le marché estime maintenant {pct(s['prix'])}."
        if prevenir(nettoyer(texte), vocal):
            envoyees.append({"id": s["id"], "quand": now.isoformat(timespec="seconds")})
            noter(f"alerte {s['slug']} {s['d24']:+.2f}")
    etat["alertes"] += envoyees
    etat["derniere_passe"] = now.isoformat(timespec="seconds")
    ecrire(ETAT, etat)

    # brief de 14 h : une ligne seulement s'il y a un gros mouvement ; le point des suivis
    b = lire(BRIEF, {})
    if b.get("jour") != jour:
        b = {"jour": jour, "mouvements": {}, "suivis": []}
    for s in signaux:
        b["mouvements"][s["id"]] = {"d24": s["d24"], "ligne": nettoyer(ligne_signal(s, tr, (pqs.get(s["id"]) or [])[:1]))}
    b["suivis"] = []
    for s, ms in suivis_l:
        if ms is None:
            b["suivis"].append(f"« {s['sujet']} » : Polymarket injoignable cette nuit.")
        elif ms == "fini":
            b["suivis"].append(f"« {s['sujet']} » : ce marché est terminé (tranché). Dis « arrête de surveiller "
                               f"{s['sujet']} » pour le retirer.")
        else:
            morceaux = []
            for m in ms:
                avant = (s.get("dernier") or {}).get(m["id"])
                evol = f", avant {pct(avant)}" if avant is not None and abs(avant - m["prix"]) >= 0.01 else ""
                morceaux.append(f"{tr.get(m['option'], m['option']) or 'oui'} {pct(m['prix'])}{evol}")
            b["suivis"].append(f"« {s['sujet']} » : le marché estime " + ", ".join(morceaux))
            s["dernier"] = {m["id"]: m["prix"] for m in ms}
            data_suivis.append(s["slug"])
    ecrire(SUIVIS, suivis)
    b["cree"] = now.isoformat(timespec="seconds")
    ecrire(BRIEF, b)
    noter(f"passe : {len(evs)} evenements, {len(signaux)} gros mouvements, {len(envoyees)} alertes, {len(suivis)} suivis")
    return {"ok": True, "evenements": len(evs), "gros_mouvements": len(signaux), "alertes": len(envoyees),
            "suivis": len(suivis)}


def lignes_brief():
    """pour brief.py : rien s'il n'y a pas eu de gros mouvement (decision de J) ; le point des suivis s'il y en a"""
    now = maintenant()
    b = lire(BRIEF, {})
    if not b.get("jour") or (now - datetime.fromisoformat(b.get("cree", "2000-01-01T00:00"))) > timedelta(hours=20):
        return []
    out = []
    mv = sorted(b.get("mouvements", {}).values(), key=lambda x: -abs(x["d24"]))[:3]
    out += ["• " + x["ligne"] for x in mv]
    if b.get("suivis"):
        out += ["👁️ " + x for x in b["suivis"]] + ["(on continue à surveiller ? sinon dis « arrête de surveiller … »)"]
    if mv:
        out.append("(" + AVERTISSEMENT + ")")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fichier")
    ap.add_argument("--passe", action="store_true")
    ap.add_argument("--brief", action="store_true")
    a = ap.parse_args()
    try:
        if a.passe:
            print(json.dumps(passe(), ensure_ascii=False))
            return
        if a.brief:
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass
            print(json.dumps({"lignes": lignes_brief()}, ensure_ascii=False))
            return
        p = {}
        if a.fichier:
            try:
                with open(a.fichier, encoding="utf-8-sig") as h:
                    p = json.load(h)
            except Exception:
                p = {}
        if isinstance(p.get("parametres"), dict):
            p = dict(p, **p["parametres"])
        ok, phrase, extra = traiter(p)
        repondre(ok, phrase, **extra)
    except Erreur as e:
        repondre(False, str(e))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        noter(f"reseau : {e}")
        repondre(False, "Polymarket ne répond pas en ce moment (ou Internet est coupé) : réessaie dans quelques minutes.")
    except Exception as e:
        noter(f"plantage : {type(e).__name__}: {e}")
        repondre(False, f"L'indicateur Polymarket a planté ({type(e).__name__}) : préviens Claude.")


if __name__ == "__main__":
    main()
