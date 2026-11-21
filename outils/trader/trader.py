# trader.py - outil maison d'Archi : le TRADER EN SIMULATION (argent fictif, vrais prix publics des cryptos).
#   python trader.py --fichier demande.json      (appele par outils_maison)
#   demande.json : {"action": "..."}
#     etat (defaut)   : ou en est le portefeuille fictif (valeur, positions, dernier tour)
#     tour            : UN tour de decision : il lit les prix, le modele local decide, les garde-fous verifient,
#                       les ordres FICTIFS sont notes dans le portefeuille et le journal
#     marche          : les prix et les indicateurs du moment (lecture seule)
#     stop, reprendre : fige ou relance le trader
#     remise_a_zero   : ESSAI A BLANC, puis confirmer=oui : repart du capital fictif (l'ancien portefeuille est archive)
#
# GARDE-FOUS DURS (dans le code, pas seulement dans la consigne du modele) :
#   1. SIMULATION SEULEMENT : aucun compte, aucune cle, aucun ordre reel. Il n'y a AUCUN code qui parle a un courtier.
#      Internet : seules des requetes GET vers les prix PUBLICS de Kraken (HOTES_LECTURE). Le seul POST va au modele local.
#   2. C'est le trader qui decide seul : on ne lui dicte pas d'ordre (il n'y a pas d'action « acheter » pour l'utilisateur).
#   3. JAMAIS de conseil d'achat ou de vente : chaque phrase rappelle que c'est un exercice, et une analyse qui
#      s'adresse a l'utilisateur comme un conseil est retiree.
#   4. Regles ecrites que le modele ne peut pas depasser : liste fermee d'actifs, ni levier ni vente a decouvert,
#      part maximale par actif, nombre d'ordres par jour, ordre minimum, delai entre deux tours, coupe-circuit de la
#      semaine, et aucun nouvel achat quand le Bitcoin est sous son nuage Ichimoku (marche baissier).
#
# Les donnees (portefeuille fictif, journal, reglages) sont dans <ARCHI_BASE>\trader. Rien d'autre ne sort du PC que
# la demande des prix publics.

import argparse
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

BASE = os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files")
DOS = os.path.join(BASE, "trader")
PORTEFEUILLE = os.path.join(DOS, "portefeuille.json")
JOURNAL = os.path.join(DOS, "journal.jsonl")
REGLAGES = os.path.join(DOS, "reglages.json")
VERROU = os.path.join(DOS, "trader.lock")

KRAKEN = "https://api.kraken.com/0/public/OHLC"
HOTES_LECTURE = {"api.kraken.com"}      # les prix publics, en lecture seule. Aucune adresse de compte ni d'ordre.
UA = {"User-Agent": "Mozilla/5.0 (Archi, assistant personnel, simulation, lecture seule)", "Accept": "application/json"}

# liste FERMEE : le sigle, la paire Kraken, le nom dit a l'utilisateur
ACTIFS = {"BTC": ("XBTUSD", "Bitcoin"), "ETH": ("ETHUSD", "Ether"), "SOL": ("SOLUSD", "Solana"), "XRP": ("XRPUSD", "XRP"),
          "ADA": ("ADAUSD", "Cardano"), "DOGE": ("XDGUSD", "Dogecoin"), "LTC": ("LTCUSD", "Litecoin"), "LINK": ("LINKUSD", "Chainlink")}

DEFAUT = {"capital_depart": 1000.0, "max_par_actif_pct": 20, "perte_max_semaine_pct": 30, "max_ordres_jour": 6,
          "ordre_min_usd": 10, "frais_pct": 0.26, "minutes_entre_tours": 15}
# <ARCHI_BASE>\trader\reglages.json peut changer ces nombres, mais seulement entre ces bornes
BORNES = {"capital_depart": (100, 1000000), "max_par_actif_pct": (5, 50), "perte_max_semaine_pct": (5, 90),
          "max_ordres_jour": (1, 24), "ordre_min_usd": (1, 1000), "frais_pct": (0, 2), "minutes_entre_tours": (5, 1440)}
MAX_DECISIONS = 3
PAUSE = 0.2       # secondes entre deux demandes de prix
RAPPEL = "C'est un exercice : l'argent est fictif, aucun ordre réel n'est passé, et ce n'est pas un conseil."
ALIAS = {"achat": "acheter", "achete": "acheter", "buy": "acheter", "vente": "vendre", "vend": "vendre", "vends": "vendre", "sell": "vendre"}
# une analyse qui parle A l'utilisateur comme un conseil est retiree (le trader raconte ce qu'il fait, il ne recommande rien)
CONSEIL = re.compile(r"\b(tu devrais|vous devriez|je te conseille|je vous conseille|je te recommande|je vous recommande|"
                     r"conseil d'achat|conseil de vente|achetez|vendez|investissez|n'h[eé]site[sz]? pas [aà] (acheter|vendre|investir))\b", re.I)

CONSIGNE = """Reasoning: low
Tu es le TRADER d'Archi. Tu gères SEUL un portefeuille de cryptomonnaies EN SIMULATION : l'argent est fictif (capital de départ {capital:.0f} $), les prix sont réels.
But de l'exercice : faire croître le portefeuille sur des semaines en limitant les pertes. Tu es un investisseur patient : tu suis des tendances de fond, pas des allers-retours de quelques heures.
Règles imposées par le programme (inutile d'essayer de les dépasser, l'ordre serait refusé) :
- actifs autorisés uniquement : {actifs} ;
- achats au comptant, sans levier et sans vente à découvert ; tous les montants sont en dollars ;
- BITCOIN SOUS SON NUAGE ICHIMOKU = MARCHÉ BAISSIER : aucun nouvel achat ne passera. Tu peux garder ou vendre ;
- au plus {max_actif} % du portefeuille sur un même actif ; au plus {max_ordres} ordres par jour ; ordre minimum {ordre_min} $ ;
- frais de {frais} % par ordre : chaque aller-retour coûte, ne bouge pas pour rien ;
- si le portefeuille perd {perte_sem} % sur la semaine, le programme t'arrête.
Méthode : appuie-toi sur les indicateurs fournis (tendance, Ichimoku, RSI, volumes) et sur ton journal récent. « Attendre » est souvent la meilleure décision. Ne te contredis pas d'un tour à l'autre sans raison nouvelle. Ne vends pas à perte par panique.
Tu racontes ce que TU fais dans cet exercice : tu ne donnes jamais de conseil à quelqu'un.
Réponds UNIQUEMENT par un objet JSON, sans texte autour :
{{"analyse": "2 ou 3 phrases simples sur le marché et ta stratégie", "decisions": [{{"action": "acheter" ou "vendre", "actif": "BTC", "montant_usd": 100, "raison": "une phrase"}}]}}
"decisions" peut être vide [] si tu attends. Au plus {max_decisions} décisions par tour."""

SCHEMA = {"type": "json_schema", "json_schema": {"name": "decision_du_trader", "strict": True, "schema": {
    "type": "object", "required": ["analyse", "decisions"], "additionalProperties": False, "properties": {
        "analyse": {"type": "string"},
        "decisions": {"type": "array", "items": {
            "type": "object", "required": ["action", "actif", "montant_usd", "raison"], "additionalProperties": False, "properties": {
                "action": {"type": "string", "enum": ["acheter", "vendre"]}, "actif": {"type": "string", "enum": list(ACTIFS)},
                "montant_usd": {"type": "number"}, "raison": {"type": "string"}}}}}}}}


class Erreur(Exception):
    pass


def repondre(ok, phrase, **extra):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(dict(ok=ok, phrase_pour_utilisateur=phrase, simulation=True, **extra), ensure_ascii=False))


def maintenant():
    return datetime.now()


# ---------------------------------------------------------------- petits outils
def plat(s):
    s = unicodedata.normalize("NFD", str(s or "").strip().lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub("[^a-z0-9]+", "_", s).strip("_")


def _dollars(x):
    """1012.4 -> « 1 012,40 $ »"""
    t = "{:,.2f}".format(abs(x)).replace(",", " ").replace(".", ",")
    return ("−" if x < 0 else "") + t + " $"


def pct(x, signe=True):
    t = ("%+.2f" if signe else "%.2f") % x
    return t.replace(".", ",").replace("-", "−") + " %"


def prix_dit(x):
    """un prix lisible : 68 120 $ ; 0,1832 $"""
    if x >= 100:
        return "{:,.0f}".format(x).replace(",", " ") + " $"
    if x >= 1:
        return ("%.2f" % x).replace(".", ",") + " $"
    return ("%.4f" % x).replace(".", ",") + " $"


def lire(chemin, defaut):
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defaut


def ecrire(chemin, d):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, chemin)


def journal(d):
    os.makedirs(DOS, exist_ok=True)
    d = dict(d, date=maintenant().isoformat(timespec="seconds"))
    with open(JOURNAL, "a", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")


def lignes_journal(n=400):
    try:
        with open(JOURNAL, encoding="utf-8") as f:
            brut = f.readlines()[-n:]
    except OSError:
        return []
    L = []
    for l in brut:
        try:
            x = json.loads(l)
            if isinstance(x, dict):
                L.append(x)
        except Exception:
            pass   # une ligne abimee ne cache pas les autres
    return L


class Verrou:
    """un seul tour a la fois (deux demandes en meme temps n'ecrivent pas le meme portefeuille)"""

    def __enter__(self):
        os.makedirs(DOS, exist_ok=True)
        for _ in range(2):
            try:
                self.fd = os.open(VERROU, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(VERROU) > 600:   # un tour plante il y a longtemps
                        os.remove(VERROU)
                        continue
                except OSError:
                    pass
                break
        raise Erreur("Le trader est déjà en train de travailler. Réessaie dans une minute.")

    def __exit__(self, *a):
        try:
            os.close(self.fd)
        finally:
            try:
                os.remove(VERROU)
            except OSError:
                pass


def reglages():
    c = dict(DEFAUT)
    perso = lire(REGLAGES, None)
    if isinstance(perso, dict):
        for k, (bas, haut) in BORNES.items():
            v = perso.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                c[k] = min(haut, max(bas, v))
    return c


def neuf(c):
    return {"cash": float(c["capital_depart"]), "capital_depart": float(c["capital_depart"]), "positions": {},
            "cree": maintenant().isoformat(timespec="seconds"), "stop": False, "semaine": None,
            "valeur_debut_semaine": float(c["capital_depart"]), "jour": None, "ordres_jour": 0, "dernier_tour": None, "historique": []}


def portefeuille(c):
    p = lire(PORTEFEUILLE, None)
    if not isinstance(p, dict) or not isinstance(p.get("positions"), dict) or not isinstance(p.get("cash"), (int, float)):
        p = neuf(c)
        ecrire(PORTEFEUILLE, p)
    for k, v in neuf(c).items():
        p.setdefault(k, v)
    return p


# ---------------------------------------------------------------- le marche (prix publics Kraken, sans cle)
def get_json(url, timeout=15):
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or u.hostname not in HOTES_LECTURE:
        raise Erreur("adresse refusée : le trader ne lit que les prix publics")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.loads(r.read(4000000).decode("utf-8"))


def bougies(paire, intervalle=60):
    """bougies d'une heure : [(heure, haut, bas, cloture, volume)]"""
    d = get_json(KRAKEN + "?pair=" + urllib.parse.quote(paire) + "&interval=%d" % intervalle)
    if d.get("error"):
        raise RuntimeError(", ".join(str(e) for e in d["error"])[:120])
    cle = [k for k in d["result"] if k != "last"][0]
    # [time, open, high, low, close, vwap, volume, count]
    b = [(int(x[0]), float(x[2]), float(x[3]), float(x[4]), float(x[6])) for x in d["result"][cle]]
    if len(b) < 60 or not all(math.isfinite(v) and v > 0 for x in b[-60:] for v in x[1:4]):
        raise RuntimeError("bougies illisibles")
    return b


def sma(v, n):
    return sum(v[-n:]) / n if len(v) >= n else None


def ema(v, n):
    if len(v) < n:
        return None
    k, e = 2 / (n + 1), sum(v[:n]) / n
    for x in v[n:]:
        e = x * k + e * (1 - k)
    return e


def rsi(v, n=14):
    if len(v) <= n:
        return None
    gains = pertes = 0.0
    for a, b in zip(v[-n - 1:-1], v[-n:]):
        d = b - a
        gains += max(d, 0)
        pertes += max(-d, 0)
    if pertes == 0:
        return 100.0
    return 100 - 100 / (1 + gains / pertes)


def milieu(hauts, bas, n, fin=None):
    h, b = (hauts[:fin], bas[:fin]) if fin else (hauts, bas)
    return (max(h[-n:]) + min(b[-n:])) / 2 if len(h) >= n else None


def indicateurs(b):
    clo, hau, bas_, vol = [x[3] for x in b], [x[1] for x in b], [x[2] for x in b], [x[4] for x in b]
    prix = clo[-1]
    tenkan, kijun = milieu(hau, bas_, 9), milieu(hau, bas_, 26)
    # le nuage d'aujourd'hui se calcule avec les valeurs d'il y a 26 bougies
    tk26, kj26 = milieu(hau, bas_, 9, -26), milieu(hau, bas_, 26, -26)
    ssa = (tk26 + kj26) / 2 if tk26 and kj26 else None
    ssb = milieu(hau, bas_, 52, -26)
    if ssa and ssb:
        haut_n, bas_n = max(ssa, ssb), min(ssa, ssb)
        nuage = "au-dessus du nuage" if prix > haut_n else "sous le nuage" if prix < bas_n else "dans le nuage"
        couleur = "vert" if ssa > ssb else "rouge"
    else:
        nuage, couleur = "?", "?"

    def il_y_a(secondes):
        cible = b[-1][0] - secondes
        avant = [x[3] for x in b if x[0] <= cible]
        return avant[-1] if avant and b[0][0] <= cible else None
    c24, c7j = il_y_a(24 * 3600), il_y_a(7 * 24 * 3600)
    v24 = (prix / c24 - 1) * 100 if c24 else None
    v7j = (prix / c7j - 1) * 100 if c7j else None
    volr = (sum(vol[-24:]) / sum(vol[-48:-24]) - 1) * 100 if len(vol) >= 48 and sum(vol[-48:-24]) > 0 else None

    def f(x, d=2):
        return None if x is None else round(x, d)
    return {"prix": prix, "var_24h_pct": f(v24), "var_7j_pct": f(v7j), "rsi14": f(rsi(clo)),
            "sma20": f(sma(clo, 20), 6), "sma50": f(sma(clo, 50), 6), "ema200": f(ema(clo, 200), 6),
            "ichimoku": {"tenkan_sur_kijun": bool(tenkan and kijun and tenkan > kijun), "position": nuage, "nuage": couleur},
            "volume_24h_vs_veille_pct": f(volr, 1)}


def lire_marche(actifs=None):
    """prix et indicateurs des actifs demandes (tous par defaut) : (prix, marche, erreurs)"""
    prix, marche, erreurs = {}, {}, []
    for i, a in enumerate(actifs or list(ACTIFS)):
        if a not in ACTIFS:
            continue
        if i:
            time.sleep(PAUSE)   # on ne martele pas le service public
        try:
            ind = indicateurs(bougies(ACTIFS[a][0]))
            prix[a], marche[a] = ind["prix"], ind
        except Erreur:
            raise
        except Exception as e:
            erreurs.append("%s : %s" % (a, str(e)[:80]))
    return prix, marche, erreurs


# ---------------------------------------------------------------- le portefeuille fictif et ses regles
def valeur(p, prix):
    return p["cash"] + sum(q["quantite"] * prix.get(a, q["prix_moyen"]) for a, q in p["positions"].items())


def remettre_compteurs(p, v, t):
    sem, jour = t.strftime("%G-%V"), t.strftime("%Y-%m-%d")
    if p.get("semaine") != sem:
        p["semaine"], p["valeur_debut_semaine"] = sem, v
        if p.get("stop") == "coupe-circuit":
            p["stop"] = False   # nouvelle semaine : il repart
    if p.get("jour") != jour:
        p["jour"], p["ordres_jour"] = jour, 0


def verifier(c, p, prix, v, d, regime):
    """(ok, raison) : les regles ecrites. Le modele ne peut pas les changer."""
    if not isinstance(d, dict):
        return False, "décision illisible"
    a = str(d.get("actif", "")).upper().strip()
    action = plat(d.get("action"))
    action = ALIAS.get(action, action)
    d["actif"], d["action"] = a, action
    if a not in ACTIFS:
        return False, "%s n'est pas dans la liste des actifs autorisés" % (a[:12] or "?")
    if a not in prix:
        return False, "pas de prix pour %s" % a
    if action not in ("acheter", "vendre"):
        return False, "action inconnue (acheter ou vendre seulement : ni levier, ni vente à découvert)"
    if p["ordres_jour"] >= c["max_ordres_jour"]:
        return False, "limite d'ordres du jour atteinte"
    try:
        montant = float(d.get("montant_usd", 0))
    except Exception:
        return False, "montant illisible"
    if not math.isfinite(montant) or montant <= 0:
        return False, "montant illisible"
    if action == "vendre":
        detenu = p["positions"].get(a, {}).get("quantite", 0) * prix[a]
        if detenu <= 0:
            return False, "aucune position sur %s" % a
        d["montant_usd"] = min(montant, detenu)
        return True, ""
    if montant < c["ordre_min_usd"]:
        return False, "ordre trop petit (%s)" % _dollars(montant)
    if regime == "sous le nuage":
        return False, "le Bitcoin est sous son nuage Ichimoku (marché baissier) : aucun nouvel achat"
    if regime not in ("au-dessus du nuage", "dans le nuage"):
        return False, "tendance du Bitcoin inconnue : aucun nouvel achat ce tour-ci"
    if montant > p["cash"] + 0.005:
        return False, "pas assez de liquidités (%s)" % _dollars(p["cash"])
    deja = p["positions"].get(a, {}).get("quantite", 0) * prix[a]
    if deja + montant > v * c["max_par_actif_pct"] / 100 + 0.01:
        return False, "dépasserait %g %% du portefeuille sur %s" % (c["max_par_actif_pct"], a)
    d["montant_usd"] = montant
    return True, ""


def executer(c, p, prix, d):
    """passe l'ordre FICTIF dans le portefeuille (verifier a deja dit oui)"""
    a, action, montant = d["actif"], d["action"], float(d["montant_usd"])
    px, fp = prix[a], float(c["frais_pct"])
    p["ordres_jour"] += 1
    if action == "acheter":
        montant = min(montant, p["cash"])
        frais = montant * fp / 100
        q = (montant - frais) / px
        pos = p["positions"].setdefault(a, {"quantite": 0.0, "prix_moyen": px})
        pos["prix_moyen"] = (pos["quantite"] * pos["prix_moyen"] + q * px) / (pos["quantite"] + q)
        pos["quantite"] += q
        p["cash"] -= montant
        return {"actif": a, "action": "acheter", "montant_usd": round(montant, 2), "prix": px, "frais_usd": round(frais, 2)}
    pos = p["positions"][a]
    montant = min(montant, pos["quantite"] * px)
    q = montant / px
    frais = montant * fp / 100
    realise = q * (px - pos["prix_moyen"]) - frais
    pos["quantite"] -= q
    p["cash"] += montant - frais
    if pos["quantite"] * px < 1:   # une poussiere : la position est fermee
        p["cash"] += pos["quantite"] * px
        p["positions"].pop(a, None)
    return {"actif": a, "action": "vendre", "montant_usd": round(montant, 2), "prix": px, "frais_usd": round(frais, 2),
            "resultat_usd": round(realise, 2)}


# ---------------------------------------------------------------- le cerveau : le modele local
def appel_modele(corps, timeout=150):
    url = (os.environ.get("ARCHI_LM_URL") or "http://127.0.0.1:1234/v1").rstrip("/") + "/chat/completions"
    req = urllib.request.Request(url, data=json.dumps(corps).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def demander(c, contexte):
    """{"analyse": str, "decisions": [..]} propose par le modele local"""
    consigne = CONSIGNE.format(capital=c["capital_depart"], actifs=", ".join("%s (%s)" % (a, n) for a, (_, n) in ACTIFS.items()),
                               max_actif="%g" % c["max_par_actif_pct"], max_ordres="%g" % c["max_ordres_jour"],
                               ordre_min="%g" % c["ordre_min_usd"], frais="%g" % c["frais_pct"],
                               perte_sem="%g" % c["perte_max_semaine_pct"], max_decisions=MAX_DECISIONS)
    corps = {"model": os.environ.get("ARCHI_MODELE") or "qwythos-9b-claude-mythos-5-1m", "temperature": 0.3, "max_tokens": 1500,
             "reasoning_effort": "low",
             "messages": [{"role": "system", "content": consigne}, {"role": "user", "content": contexte}]}
    try:
        # la forme de la reponse est imposee : sans cela, le modele se trompe parfois dans le nom des champs
        rep = appel_modele(dict(corps, response_format=SCHEMA))
    except urllib.error.HTTPError as e:
        if e.code not in (400, 422):
            raise
        rep = appel_modele(corps)   # un serveur qui ne connait pas les schemas : on demande sans
    txt = (((rep.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
    txt = re.sub(r"(?s)<think>.*?</think>", "", txt)
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise RuntimeError("réponse du modèle sans JSON")
    d = json.loads(m.group(0))
    if not isinstance(d, dict):
        raise RuntimeError("réponse du modèle illisible")
    decisions = d.get("decisions", d.get("décisions", []))
    analyse = re.sub(r"\s+", " ", str(d.get("analyse") or d.get("analysis") or "")).strip()[:400]
    if CONSEIL.search(analyse):
        analyse = "(analyse retirée : elle ressemblait à un conseil)"
    return {"analyse": analyse, "decisions": decisions if isinstance(decisions, list) else []}


def raison_propre(d):
    r = re.sub(r"\s+", " ", str(d.get("raison") or "")).strip()[:160]
    return "" if CONSEIL.search(r) else r


# ---------------------------------------------------------------- ce qu'on dit a l'utilisateur
def nom(a):
    return ACTIFS[a][1] if a in ACTIFS else a


def phrase_ordre(o):
    return "%s %s de %s%s" % ("achat de" if o["action"] == "acheter" else "vente de", _dollars(o["montant_usd"]), nom(o["actif"]),
                              (" (" + o["raison"] + ")") if o.get("raison") else "")


def quand_dit(iso):
    try:
        t = datetime.fromisoformat(iso)
        return "le %s à %d h %02d" % (t.strftime("%d/%m"), t.hour, t.minute)
    except Exception:
        return "récemment"


def bilan(c, p, prix, frais_prix=True):
    v = valeur(p, prix)
    depart = float(p.get("capital_depart") or c["capital_depart"])
    t = "Le portefeuille fictif vaut %s, soit %s depuis le départ à %s. Liquidités : %s." % (
        _dollars(v), pct((v / depart - 1) * 100), _dollars(depart), _dollars(p["cash"]))
    if p["positions"]:
        t += " Positions : " + ", ".join(
            "%s %s (%s)" % (nom(a), _dollars(q["quantite"] * prix.get(a, q["prix_moyen"])),
                            pct((prix.get(a, q["prix_moyen"]) / q["prix_moyen"] - 1) * 100))
            for a, q in p["positions"].items()) + "."
        if not frais_prix:
            t += " (Prix non rafraîchis : le service des prix ne répond pas.)"
    else:
        t += " Aucune position."
    return t, v


def positions_detail(p, prix):
    return {a: {"quantite": round(q["quantite"], 8), "prix_moyen": q["prix_moyen"], "valeur_usd": round(q["quantite"] * prix.get(a, q["prix_moyen"]), 2),
                "plus_value_pct": round((prix.get(a, q["prix_moyen"]) / q["prix_moyen"] - 1) * 100, 2)} for a, q in p["positions"].items()}


# ---------------------------------------------------------------- les actions
def a_etat(d):
    c = reglages()
    p = portefeuille(c)
    prix, frais = {}, True
    if p["positions"]:
        try:
            prix, _, erreurs = lire_marche(list(p["positions"]))
            frais = not erreurs
        except Exception:
            prix, frais = {}, False
    t, v = bilan(c, p, prix, frais)
    tours = [l for l in lignes_journal() if l.get("type") == "tour"]
    if not tours:
        t = ("Le trader n'a encore rien fait : %s fictifs l'attendent. Dis « fais un tour de trader » pour qu'il regarde le marché et décide."
             % _dollars(p["cash"])) if not p["positions"] else t
    else:
        dernier = tours[-1]
        ordres = dernier.get("ordres") or []
        t += " Dernier tour %s : %s." % (quand_dit(dernier.get("date", "")),
                                         " ; ".join(phrase_ordre(o) for o in ordres) if ordres else "il a attendu")
    if p.get("stop"):
        t += " Il est À L'ARRÊT (%s)." % ("coupe-circuit de la semaine" if p["stop"] == "coupe-circuit" else "à ta demande")
    repondre(True, "Trader en simulation. " + t + " " + RAPPEL, valeur_usd=round(v, 2), liquidites_usd=round(p["cash"], 2),
             positions=positions_detail(p, prix), tours=len(tours), arrete=bool(p.get("stop")))


def a_marche(d):
    prix, marche, erreurs = lire_marche()
    if not prix:
        raise Erreur("Pas de prix : le service public des prix ne répond pas. Vérifie Internet et réessaie.")
    morceaux = []
    for a, m in marche.items():
        bouts = []
        if m.get("var_24h_pct") is not None:
            bouts.append(pct(m["var_24h_pct"]) + " sur 24 h")
        if m.get("rsi14") is not None:
            bouts.append("RSI %d" % round(m["rsi14"]))
        if m["ichimoku"]["position"] != "?":
            bouts.append(m["ichimoku"]["position"])
        morceaux.append("%s %s (%s)" % (nom(a), prix_dit(m["prix"]), ", ".join(bouts)))
    repondre(True, "Les prix du moment (publics, bougies d'une heure) : " + " ; ".join(morceaux) + ". Ce sont des chiffres, pas un conseil.",
             marche=marche, erreurs=erreurs[:5])


def a_tour(d):
    c = reglages()
    with Verrou():
        p = portefeuille(c)
        t0 = maintenant()
        if p.get("stop") == "demande":
            raise Erreur("Le trader est à l'arrêt, à ta demande. Dis « trader, reprends » pour le relancer.")
        if p.get("dernier_tour"):
            try:
                ecoule = (t0 - datetime.fromisoformat(p["dernier_tour"])).total_seconds() / 60
            except Exception:
                ecoule = 1e9
            if 0 <= ecoule < c["minutes_entre_tours"]:
                reste = max(1, int(math.ceil(c["minutes_entre_tours"] - ecoule)))
                raise Erreur("Le dernier tour date de %d min : le trader ne se contredit pas d'une minute à l'autre. "
                             "Prochain tour possible dans %d min. Demande-moi où il en est en attendant." % (int(ecoule), reste))
        prix, marche, erreurs = lire_marche()
        if not prix:
            raise Erreur("Pas de prix : le service public des prix ne répond pas. Vérifie Internet et réessaie. Le portefeuille n'a pas bougé.")
        regime = (marche.get("BTC") or {}).get("ichimoku", {}).get("position")
        v = valeur(p, prix)
        remettre_compteurs(p, v, t0)

        # coupe-circuit de la semaine (ecrit dans le programme)
        perte_sem = (v / p["valeur_debut_semaine"] - 1) * 100 if p["valeur_debut_semaine"] else 0.0
        if not p.get("stop") and perte_sem <= -c["perte_max_semaine_pct"]:
            p["stop"] = "coupe-circuit"
        if p.get("stop"):
            ecrire(PORTEFEUILLE, p)
            journal({"type": "pause", "valeur": round(v, 2), "raison": p["stop"]})
            t, _ = bilan(c, p, prix)
            repondre(True, "Le trader s'est arrêté tout seul : le portefeuille fictif a perdu %s cette semaine (coupe-circuit). "
                     "Il repartira la semaine prochaine, ou avant si tu dis « trader, reprends ». %s %s" % (pct(abs(perte_sem), False), t, RAPPEL),
                     valeur_usd=round(v, 2), arrete=True)
            return

        derniers = ["%s : %s | ordres : %s | refusés : %s" % (l.get("date", "")[:16], str(l.get("analyse", ""))[:200],
                                                               json.dumps(l.get("ordres", []), ensure_ascii=False),
                                                               json.dumps([r.get("refus") for r in l.get("refus", [])], ensure_ascii=False))
                    for l in lignes_journal(40) if l.get("type") == "tour"][-5:]
        depart = float(p.get("capital_depart") or c["capital_depart"])
        contexte = ("Date : %s\n" % t0.strftime("%Y-%m-%d %H:%M") +
                    "TENDANCE DU MARCHÉ : Bitcoin %s%s\n" % (regime or "?", " → MARCHÉ BAISSIER : aucun nouvel achat possible" if regime == "sous le nuage" else "") +
                    "PORTEFEUILLE : valeur %.2f $ | liquidités %.2f $ | depuis le début %+.2f %% | cette semaine %+.2f %% | ordres aujourd'hui %d/%g\n"
                    % (v, p["cash"], (v / depart - 1) * 100, perte_sem, p["ordres_jour"], c["max_ordres_jour"]) +
                    "POSITIONS : %s\n\n" % json.dumps(positions_detail(p, prix), ensure_ascii=False) +
                    "MARCHÉ (bougies d'une heure, prix en $) :\n" +
                    "\n".join("%s : %s" % (a, json.dumps({k: x for k, x in m.items() if x is not None}, ensure_ascii=False, separators=(",", ":")))
                              for a, m in marche.items()) +
                    "\n\nTON JOURNAL RÉCENT :\n" + ("\n".join(derniers) or "(premier tour)"))
        try:
            rep = demander(c, contexte)
        except Exception as e:
            ecrire(PORTEFEUILLE, p)
            journal({"type": "erreur", "erreur": str(e)[:200], "valeur": round(v, 2)})
            raise Erreur("Le modèle local n'a pas rendu de décision lisible : pas de tour cette fois, le portefeuille n'a pas bougé. Réessaie dans un instant.")
        p["dernier_tour"] = t0.isoformat(timespec="seconds")
        ordres, refus = [], []
        for dec in rep["decisions"][:MAX_DECISIONS]:
            ok, raison = verifier(c, p, prix, valeur(p, prix), dec, regime)
            if ok:
                o = executer(c, p, prix, dec)
                o["raison"] = raison_propre(dec)
                ordres.append(o)
            else:
                refus.append({"decision": {k: str(x)[:60] for k, x in dec.items()} if isinstance(dec, dict) else str(dec)[:60], "refus": raison})
        v2 = valeur(p, prix)
        p["historique"] = (p.get("historique", []) + [{"date": t0.isoformat(timespec="minutes"), "valeur": round(v2, 2)}])[-500:]
        ecrire(PORTEFEUILLE, p)
        entree = {"type": "tour", "valeur": round(v2, 2), "analyse": rep["analyse"], "ordres": ordres, "refus": refus,
                  "actifs_lus": len(prix), "tendance_btc": regime, "ordres_jour": p["ordres_jour"]}
        if erreurs:
            entree["erreurs_marche"] = erreurs[:5]
        journal(entree)

    t = "Le trader a fait son tour."
    if rep["analyse"]:
        t += " Son analyse : « %s »" % rep["analyse"].rstrip(".") + "."
    t += " Ordres fictifs : " + (" ; ".join(phrase_ordre(o) for o in ordres) if ordres else "aucun, il attend") + "."
    if refus:
        t += " Refusé par les garde-fous : " + " ; ".join(r["refus"] for r in refus) + "."
    b, _ = bilan(c, p, prix)
    repondre(True, t + " " + b + " " + RAPPEL, valeur_usd=round(v2, 2), ordres=ordres, refus=refus, tendance_btc=regime,
             positions=positions_detail(p, prix))


def a_stop(d):
    c = reglages()
    with Verrou():
        p = portefeuille(c)
        p["stop"] = "demande"
        ecrire(PORTEFEUILLE, p)
        journal({"type": "stop"})
    repondre(True, "C'est arrêté : le trader ne passe plus aucun ordre fictif. Dis « trader, reprends » pour le relancer.", arrete=True)


def a_reprendre(d):
    c = reglages()
    with Verrou():
        p = portefeuille(c)
        etait = p.get("stop")
        p["stop"] = False
        if etait == "coupe-circuit":
            p["valeur_debut_semaine"] = None   # le prochain tour repart de la valeur du moment
            p["semaine"] = None
        ecrire(PORTEFEUILLE, p)
        journal({"type": "reprise"})
    repondre(True, "C'est reparti : le trader décidera au prochain tour." if etait else "Le trader n'était pas arrêté.", arrete=False)


def a_remise(d):
    c = reglages()
    oui = plat(d.get("confirmer")) in ("oui", "true", "1", "vrai")
    with Verrou():
        p = portefeuille(c)
        tours = len([l for l in lignes_journal() if l.get("type") == "tour"])
        if not oui:
            repondre(True, "ESSAI À BLANC, rien n'est changé : je remettrais le portefeuille fictif à %s (liquidités %s aujourd'hui, %d position(s), %d tour(s) au journal). "
                     "L'ancien serait archivé. Dis oui pour confirmer." % (_dollars(c["capital_depart"]), _dollars(p["cash"]), len(p["positions"]), tours),
                     a_blanc=True)
            return
        archive = ""
        if os.path.exists(PORTEFEUILLE):
            archive = "portefeuille_%s.json" % maintenant().strftime("%Y%m%d_%H%M%S")
            os.replace(PORTEFEUILLE, os.path.join(DOS, archive))
        ecrire(PORTEFEUILLE, neuf(c))
        journal({"type": "remise_a_zero", "archive": archive})
    repondre(True, "C'est fait : le portefeuille fictif repart de %s. L'ancien est archivé dans le dossier trader." % _dollars(c["capital_depart"]),
             archive=archive)


ACTIONS = {"etat": a_etat, "tour": a_tour, "marche": a_marche, "stop": a_stop, "reprendre": a_reprendre, "remise_a_zero": a_remise}
SYNONYMES = {"": "etat", "rapport": "etat", "bilan": "etat", "resume": "etat", "ou_en_est": "etat", "portefeuille": "etat",
             "cycle": "tour", "decider": "tour", "decide": "tour", "faire_un_tour": "tour", "prix": "marche", "marches": "marche", "cours": "marche",
             "arreter": "stop", "arrete": "stop", "pause": "stop", "reprends": "reprendre", "relancer": "reprendre",
             "remise": "remise_a_zero", "reset": "remise_a_zero", "recommencer": "remise_a_zero", "repartir_de_zero": "remise_a_zero"}


# ---------------------------------------------------------------- le tour du jour (lance par core/tournees.js)
def annoncer(texte):
    """l'annonce part comme un rappel du planificateur : Telegram, l'appli et la page du PC"""
    import subprocess
    script = os.path.join(BASE, "outils", "planificateur", "planificateur.py")
    if not os.path.exists(script):
        return False
    f = os.path.join(DOS, "annonce_%d.json" % int(time.time() * 1000))
    try:
        os.makedirs(DOS, exist_ok=True)
        with open(f, "w", encoding="utf-8") as h:
            json.dump({"texte": texte, "de": "trader"}, h, ensure_ascii=False)
        r = subprocess.run([sys.executable, script, "--annoncer", "--fichier", f], capture_output=True, timeout=40,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0 and '"ok": true' in r.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        try:
            os.remove(f)
        except OSError:
            pass


def tournee(annonce=None):
    """UN tour, comme « action=tour », puis une annonce courte. Trader a l'arret, tour trop rapproche, prix ou modele
    absents : aucun tour, AUCUNE annonce (on n'annonce que ce qui a ete fait). Les garde-fous sont ceux de a_tour."""
    import contextlib
    import io
    tampon = io.StringIO()
    try:
        with contextlib.redirect_stdout(tampon):
            a_tour({})
        r = json.loads(tampon.getvalue().strip().splitlines()[-1])
    except Erreur as e:
        return repondre(False, str(e), tournee=True, annonce=False)
    except Exception as e:
        return repondre(False, "Le trader a eu un souci : " + str(e)[:150], tournee=True, annonce=False)
    if not (isinstance(r, dict) and r.get("ok") is True):
        return repondre(False, str((r or {}).get("phrase_pour_utilisateur") or "Pas de tour."), tournee=True, annonce=False)
    prenom = (os.environ.get("ARCHI_UTILISATEUR") or "").strip()[:30]
    n = len(r.get("ordres") or [])
    texte = "%sle trader a fait son tour du jour, en simulation : %s, portefeuille fictif à %s. Dis « trader, où en es-tu » pour le détail. %s" % (
        (prenom + ", ") if prenom else "", ("%d ordre(s) fictif(s)" % n) if n else "aucun ordre", _dollars(float(r.get("valeur_usd") or 0)), RAPPEL)
    fait = (annonce or annoncer)(texte)
    extra = {k: v for k, v in r.items() if k not in ("ok", "phrase_pour_utilisateur", "simulation")}
    return repondre(True, r["phrase_pour_utilisateur"], tournee=True, annonce=bool(fait), **extra)


def main():
    pa = argparse.ArgumentParser()
    pa.add_argument("--fichier")
    pa.add_argument("--tournee", action="store_true")
    a = pa.parse_args()
    if a.tournee:
        return tournee()
    if not a.fichier:
        return repondre(False, "Il manque --fichier.")
    try:
        with open(a.fichier, encoding="utf-8-sig") as h:
            d = json.load(h)
        if not isinstance(d, dict):
            raise Erreur("demande illisible")
        action = plat(d.get("action"))
        action = SYNONYMES.get(action, action)
        if action not in ACTIONS:
            raise Erreur("Action inconnue. Le trader décide seul, en simulation : on ne lui dicte pas d'ordre. "
                         "Actions : etat, tour, marche, stop, reprendre, remise_a_zero.")
        ACTIONS[action](d)
    except Erreur as e:
        repondre(False, str(e))
    except Exception as e:
        repondre(False, "Le trader a eu un souci : " + str(e)[:150])


if __name__ == "__main__":
    main()
