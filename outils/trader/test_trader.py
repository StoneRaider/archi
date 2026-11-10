"""Tests de trader.py, hors ligne : faux chateau, faux prix (bougies inventees), faux modele local, fausse horloge.
Aucune demande ne part sur Internet : toute ouverture d'adresse fait echouer le test."""
import contextlib
import io
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta

ICI = os.path.dirname(os.path.abspath(__file__))
D = tempfile.mkdtemp(prefix="trader_")
os.environ["ARCHI_BASE"] = D
os.environ["ARCHI_SANS_ENV"] = "1"
sys.path.insert(0, ICI)
import trader as T  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
ok = ko = 0


def verifie(nom, condition, detail=""):
    global ok, ko
    if condition:
        ok += 1
    else:
        ko += 1
        print("ECHEC :", nom, "|", str(detail)[:400])


# ---------------------------------------------------------------- le faux monde
def reseau_interdit(*a, **k):
    raise AssertionError("un test a voulu ouvrir une adresse : %r" % (a[0].full_url if a and hasattr(a[0], "full_url") else a,))


urllib.request.urlopen = reseau_interdit
T.PAUSE = 0
HORLOGE = [datetime(2026, 11, 10, 10, 0, 0)]   # un mardi
T.maintenant = lambda: HORLOGE[0]
TENDANCE = {}        # paire Kraken -> monte | baisse | plat | panne
ECHELLE = {"XBTUSD": 300.0, "ETHUSD": 20.0, "SOLUSD": 1.0, "XRPUSD": 0.01, "ADAUSD": 0.005, "XDGUSD": 0.001, "LTCUSD": 0.5, "LINKUSD": 0.1}
LECTURES = []


def serie(tendance, echelle, n=720):
    fin = int(time.time()) // 3600 * 3600
    b = []
    for i in range(n):
        x = i / (n - 1)
        p = (100 + 100 * x) if tendance == "monte" else (200 - 100 * x) if tendance == "baisse" else 150.0
        p *= echelle * (1 + 0.004 * math.sin(i * 1.7))
        b.append((fin - (n - 1 - i) * 3600, p * 1.003, p * 0.997, p, 1000.0 + 10 * (i % 7)))
    return b


def fausses_bougies(paire, intervalle=60):
    LECTURES.append(paire)
    t = TENDANCE.get(paire, "monte")
    if t == "panne":
        raise RuntimeError("service indisponible")
    return serie(t, ECHELLE[paire])


T.bougies = fausses_bougies
REPONSE = [{"analyse": "Le marché monte, j'attends.", "decisions": []}]   # ce que le faux modele repondra (objet, texte ou exception)
DEMANDES = []


def faux_modele(corps, timeout=150):
    DEMANDES.append(corps)
    r = REPONSE[0]
    if isinstance(r, Exception):
        raise r
    contenu = r if isinstance(r, str) else "Voici : " + json.dumps(r, ensure_ascii=False)
    return {"choices": [{"message": {"content": contenu}}]}


T.appel_modele = faux_modele


def lancer(**d):
    f = os.path.join(D, "demande.json")
    with open(f, "w", encoding="utf-8") as h:
        json.dump(d, h)
    tampon = io.StringIO()
    ancien = sys.argv
    sys.argv = ["trader.py", "--fichier", f]
    try:
        with contextlib.redirect_stdout(tampon):
            T.main()
    finally:
        sys.argv = ancien
    return json.loads(tampon.getvalue().strip().splitlines()[-1])


def chateau_neuf(**reglages):
    for f in os.listdir(T.DOS) if os.path.isdir(T.DOS) else []:
        os.remove(os.path.join(T.DOS, f))
    if reglages:
        os.makedirs(T.DOS, exist_ok=True)
        with open(T.REGLAGES, "w", encoding="utf-8") as h:
            json.dump(reglages, h)
    HORLOGE[0] = datetime(2026, 11, 10, 10, 0, 0)
    TENDANCE.clear()
    del LECTURES[:], DEMANDES[:]
    REPONSE[0] = {"analyse": "Le marché monte, j'attends.", "decisions": []}


def portefeuille():
    return json.load(open(T.PORTEFEUILLE, encoding="utf-8"))


def journal():
    try:
        return [json.loads(l) for l in open(T.JOURNAL, encoding="utf-8")]
    except OSError:
        return []


def plus_tard(minutes):
    HORLOGE[0] = HORLOGE[0] + timedelta(minutes=minutes)


def decide(*decisions, analyse="Tendance haussière, je prends une petite position."):
    REPONSE[0] = {"analyse": analyse, "decisions": [dict(zip(("action", "actif", "montant_usd", "raison"), x)) for x in decisions]}


# ---------------------------------------------------------------- 1. l'etat d'un portefeuille neuf : aucun reseau
chateau_neuf()
r = lancer(action="etat")
verifie("etat neuf : ok et simulation", r["ok"] is True and r["simulation"] is True, r)
verifie("etat neuf : 1 000 $ fictifs", "1 000,00 $" in r["phrase_pour_utilisateur"] and "fictifs" in r["phrase_pour_utilisateur"], r)
verifie("etat neuf : aucun prix demande", LECTURES == [] and DEMANDES == [], LECTURES)
verifie("etat par defaut (action vide) et synonymes", lancer()["ok"] and lancer(action="Rapport")["ok"] and lancer(action="Où en est")["ok"])

# ---------------------------------------------------------------- 2. les indicateurs
haut, bas = T.indicateurs(serie("monte", 1.0)), T.indicateurs(serie("baisse", 1.0))
verifie("indicateurs : ca monte = au-dessus du nuage", haut["ichimoku"]["position"] == "au-dessus du nuage", haut)
verifie("indicateurs : ca baisse = sous le nuage", bas["ichimoku"]["position"] == "sous le nuage", bas)
verifie("indicateurs : RSI entre 0 et 100", 0 <= haut["rsi14"] <= 100 and 0 <= bas["rsi14"] <= 100, (haut["rsi14"], bas["rsi14"]))
verifie("indicateurs : variation sur 7 jours du bon signe", haut["var_7j_pct"] > 0 > bas["var_7j_pct"], (haut["var_7j_pct"], bas["var_7j_pct"]))
verifie("indicateurs : moyennes calculees", haut["sma20"] and haut["sma50"] and haut["ema200"], haut)

# ---------------------------------------------------------------- 3. un tour : un achat passe, deux decisions refusees
chateau_neuf()
decide(("acheter", "BTC", 150, "tendance de fond"), ("acheter", "ETH", 500, "trop gros"), ("shorter", "DOGE", 50, "pari à la baisse"))
r = lancer(action="tour")
p = portefeuille()
prix_btc = T.indicateurs(serie("monte", ECHELLE["XBTUSD"]))["prix"]
verifie("tour : ok", r["ok"] is True, r)
verifie("tour : un ordre, deux refus", len(r["ordres"]) == 1 and len(r["refus"]) == 2, r)
verifie("tour : l'achat est note", r["ordres"][0]["actif"] == "BTC" and r["ordres"][0]["montant_usd"] == 150 and r["ordres"][0]["frais_usd"] == 0.39, r["ordres"])
verifie("tour : liquidites 850", abs(p["cash"] - 850) < 1e-6, p["cash"])
verifie("tour : quantite = (montant - frais) / prix", abs(p["positions"]["BTC"]["quantite"] - (150 - 150 * 0.0026) / prix_btc) < 1e-9, p["positions"])
verifie("tour : 20 % par actif au plus", "20 %" in r["refus"][0]["refus"], r["refus"])
verifie("tour : ni levier ni vente a decouvert", "ni levier" in r["refus"][1]["refus"], r["refus"])
verifie("tour : la phrase rappelle que c'est un exercice", T.RAPPEL in r["phrase_pour_utilisateur"] and "fictif" in r["phrase_pour_utilisateur"], r)
verifie("tour : la phrase nomme l'actif en clair", "Bitcoin" in r["phrase_pour_utilisateur"] and "tendance de fond" in r["phrase_pour_utilisateur"], r)
verifie("tour : les 8 actifs ont ete lus", len(LECTURES) == 8, LECTURES)
verifie("tour : journal", [l["type"] for l in journal()] == ["tour"] and journal()[0]["ordres"][0]["actif"] == "BTC", journal())
d = DEMANDES[-1]
verifie("tour : forme de reponse imposee au modele", d.get("response_format", {}).get("type") == "json_schema" and d.get("reasoning_effort") == "low", d.keys())
verifie("tour : la consigne dit SIMULATION et jamais de conseil", "SIMULATION" in d["messages"][0]["content"] and "jamais de conseil" in d["messages"][0]["content"])
verifie("tour : le contexte donne le portefeuille et le marche", "PORTEFEUILLE : valeur 1000.00" in d["messages"][1]["content"] and "BTC : {" in d["messages"][1]["content"])
e = lancer(action="etat")
verifie("etat apres un tour : position et dernier tour", "Positions : Bitcoin" in e["phrase_pour_utilisateur"] and "Dernier tour le 10/11 à 10 h 00" in e["phrase_pour_utilisateur"], e)
verifie("etat : ne rafraichit que les actifs detenus", LECTURES[-1] == "XBTUSD" and len(LECTURES) == 9, LECTURES)

# ---------------------------------------------------------------- 4. pas deux tours coup sur coup
n = len(DEMANDES)
plus_tard(3)
r = lancer(action="tour")
verifie("delai : refuse avant 15 minutes", r["ok"] is False and "12 min" in r["phrase_pour_utilisateur"], r)
verifie("delai : le modele n'est pas appele", len(DEMANDES) == n)

# ---------------------------------------------------------------- 5. Bitcoin sous son nuage : aucun achat, la vente reste possible
plus_tard(20)
TENDANCE["XBTUSD"] = "baisse"
decide(("acheter", "SOL", 100, "rebond"), ("vendre", "BTC", 100000, "la raison de l'achat n'existe plus"))
r = lancer(action="tour")
p = portefeuille()
verifie("marche baissier : achat refuse", len(r["refus"]) == 1 and "sous son nuage" in r["refus"][0]["refus"], r["refus"])
verifie("marche baissier : vente passee, bornee a ce qui est detenu", len(r["ordres"]) == 1 and r["ordres"][0]["action"] == "vendre" and r["ordres"][0]["montant_usd"] < 100, r["ordres"])
verifie("marche baissier : la position est fermee", "BTC" not in p["positions"] and "SOL" not in p["positions"], p["positions"])
verifie("marche baissier : perte realisee notee", r["ordres"][0]["resultat_usd"] < 0, r["ordres"])
verifie("marche baissier : le contexte previent le modele", "MARCHÉ BAISSIER" in DEMANDES[-1]["messages"][1]["content"])
verifie("le journal recent est donne au modele", "tendance de fond" in DEMANDES[-1]["messages"][1]["content"])

# ---------------------------------------------------------------- 6. ordres par jour, ordre minimum, actif inconnu, montants bizarres
chateau_neuf(max_ordres_jour=1)
decide(("acheter", "BTC", 50, "a"), ("acheter", "ETH", 50, "b"))
r = lancer(action="tour")
verifie("un ordre par jour : le second est refuse", len(r["ordres"]) == 1 and "limite d'ordres" in r["refus"][0]["refus"], r)
plus_tard(24 * 60)
decide(("acheter", "ETH", 50, "b"))
verifie("le lendemain, le compteur repart", len(lancer(action="tour")["ordres"]) == 1)

chateau_neuf()
decide(("acheter", "PEPE", 50, "x"), ("acheter", "BTC", 3, "trop petit"), ("acheter", "ETH", "beaucoup", "x"))
r = lancer(action="tour")
verifie("actif hors liste, ordre trop petit, montant illisible : tout refuse", r["ordres"] == [] and len(r["refus"]) == 3, r)
verifie("raisons des refus", "autorisés" in r["refus"][0]["refus"] and "trop petit" in r["refus"][1]["refus"] and "illisible" in r["refus"][2]["refus"], r["refus"])
verifie("rien n'a bouge", portefeuille()["cash"] == 1000 and portefeuille()["positions"] == {})
plus_tard(20)
decide(("acheter", "BTC", float("nan"), "x"), ("acheter", "BTC", -50, "x"), ("vendre", "ETH", 50, "rien a vendre"), ("acheter", "SOL", 100, "la quatrieme"))
r = lancer(action="tour")
verifie("NaN, negatif, vente sans position : refuses ; au plus 3 decisions par tour", r["ordres"] == [] and len(r["refus"]) == 3, r)
plus_tard(20)
p = portefeuille()
p["cash"] = 40.0
p["positions"] = {"ETH": {"quantite": 0.1, "prix_moyen": 4000.0}}
p["semaine"] = None   # le portefeuille vient d'etre change a la main : la semaine repart de sa valeur du moment
json.dump(p, open(T.PORTEFEUILLE, "w", encoding="utf-8"))
decide(("acheter", "SOL", 60, "x"))
r = lancer(action="tour")
verifie("pas assez de liquidites", r["ordres"] == [] and "liquidités" in r["refus"][0]["refus"], r)

# ---------------------------------------------------------------- 7. le modele en panne, ou qui repond n'importe quoi : rien ne bouge
chateau_neuf()
REPONSE[0] = ConnectionError("LM Studio arrete")
r = lancer(action="tour")
verifie("modele en panne : pas de tour", r["ok"] is False and "n'a pas bougé" in r["phrase_pour_utilisateur"], r)
verifie("modele en panne : portefeuille intact, erreur au journal", portefeuille()["cash"] == 1000 and portefeuille()["dernier_tour"] is None and journal()[-1]["type"] == "erreur", journal())
REPONSE[0] = "Je pense qu'il faut attendre, sans JSON."
verifie("reponse sans JSON : pas de tour", lancer(action="tour")["ok"] is False)
REPONSE[0] = {"analyse": "ok", "decisions": "acheter tout"}
r = lancer(action="tour")
verifie("decisions illisibles : un tour sans ordre", r["ok"] is True and r["ordres"] == [], r)

# ---------------------------------------------------------------- 8. jamais de conseil
chateau_neuf()
decide(("acheter", "BTC", 100, "Je te conseille d'en acheter aussi"), analyse="Tu devrais acheter du Bitcoin maintenant, c'est le moment.")
r = lancer(action="tour")
verifie("une analyse qui conseille est retiree", "Tu devrais" not in r["phrase_pour_utilisateur"] and "analyse retirée" in r["phrase_pour_utilisateur"], r)
verifie("une raison qui conseille est retiree", "conseille" not in r["phrase_pour_utilisateur"] and r["ordres"][0]["raison"] == "", r)
r = lancer(action="acheter", actif="BTC", montant_usd=500)
verifie("on ne dicte pas d'ordre au trader", r["ok"] is False and "ne lui dicte pas" in r["phrase_pour_utilisateur"], r)
verifie("l'ordre dicte n'a rien change", abs(portefeuille()["cash"] - 900) < 1e-6)
r = lancer(action="marche")
verifie("marche : des chiffres, pas un conseil", r["ok"] and "Bitcoin" in r["phrase_pour_utilisateur"] and "pas un conseil" in r["phrase_pour_utilisateur"], r)

# ---------------------------------------------------------------- 9. stop, reprendre, coupe-circuit de la semaine
chateau_neuf()
verifie("stop", lancer(action="stop")["arrete"] is True and portefeuille()["stop"] == "demande")
n = len(DEMANDES)
r = lancer(action="tour")
verifie("a l'arret : aucun tour, modele pas appele", r["ok"] is False and "à l'arrêt" in r["phrase_pour_utilisateur"] and len(DEMANDES) == n, r)
verifie("etat : dit qu'il est a l'arret", "À L'ARRÊT" in lancer(action="etat")["phrase_pour_utilisateur"])
verifie("reprendre", lancer(action="reprends")["ok"] and portefeuille()["stop"] is False)
decide(("acheter", "BTC", 200, "x"))
verifie("apres la reprise, le tour passe", len(lancer(action="tour")["ordres"]) == 1)

plus_tard(60)
TENDANCE["XBTUSD"] = "baisse"      # la position perd la moitie
p = portefeuille()
p["valeur_debut_semaine"] = 1400.0  # comme si la semaine avait commence bien plus haut
json.dump(p, open(T.PORTEFEUILLE, "w", encoding="utf-8"))
n = len(DEMANDES)
r = lancer(action="tour")
verifie("coupe-circuit : il s'arrete tout seul", r["ok"] and r["arrete"] is True and "coupe-circuit" in r["phrase_pour_utilisateur"], r)
verifie("coupe-circuit : le modele n'est pas appele", len(DEMANDES) == n and portefeuille()["stop"] == "coupe-circuit")
plus_tard(8 * 24 * 60)             # la semaine suivante
decide()
r = lancer(action="tour")
verifie("coupe-circuit : il repart la semaine suivante", r["ok"] and "arrete" not in r and portefeuille()["stop"] is False, r)

# ---------------------------------------------------------------- 10. remise a zero : essai a blanc, puis archive
r = lancer(action="remise_a_zero")
verifie("remise a zero : essai a blanc", r.get("a_blanc") is True and "BTC" in portefeuille()["positions"], r)
r = lancer(action="remise_a_zero", confirmer="oui")
verifie("remise a zero confirmee", r["ok"] and portefeuille()["cash"] == 1000 and portefeuille()["positions"] == {}, r)
verifie("l'ancien portefeuille est archive", r["archive"].startswith("portefeuille_") and os.path.exists(os.path.join(T.DOS, r["archive"])), r)

# ---------------------------------------------------------------- 11. les reglages restent dans leurs bornes
chateau_neuf(max_par_actif_pct=500, capital_depart="beaucoup", frais_pct=True, minutes_entre_tours=0, ordre_min_usd=5, inconnu=1)
c = T.reglages()
verifie("reglages bornes", c["max_par_actif_pct"] == 50 and c["capital_depart"] == 1000.0 and c["frais_pct"] == 0.26
        and c["minutes_entre_tours"] == 5 and c["ordre_min_usd"] == 5 and "inconnu" not in c, c)

# ---------------------------------------------------------------- 12. le service des prix en panne
chateau_neuf()
for paire in ECHELLE:
    TENDANCE[paire] = "panne"
r = lancer(action="tour")
verifie("pas de prix : pas de tour", r["ok"] is False and "Pas de prix" in r["phrase_pour_utilisateur"] and DEMANDES == [], r)
verifie("pas de prix : marche refuse aussi", lancer(action="marche")["ok"] is False)
TENDANCE.clear()
TENDANCE["XBTUSD"] = "panne"
decide(("acheter", "ETH", 100, "x"))
r = lancer(action="tour")
verifie("tendance du Bitcoin inconnue : aucun achat", r["ok"] and r["ordres"] == [] and "inconnue" in r["refus"][0]["refus"], r)
p = portefeuille()
p["positions"] = {"ETH": {"quantite": 0.05, "prix_moyen": 4000.0}}
p["cash"] = 800.0
json.dump(p, open(T.PORTEFEUILLE, "w", encoding="utf-8"))
TENDANCE["ETHUSD"] = "panne"
r = lancer(action="etat")
verifie("etat sans prix : repond quand meme, et le dit", r["ok"] and "Prix non rafraîchis" in r["phrase_pour_utilisateur"] and r["valeur_usd"] == 1000.0, r)

# ---------------------------------------------------------------- 13. un seul tour a la fois
chateau_neuf()
os.makedirs(T.DOS, exist_ok=True)
open(T.VERROU, "w").close()
r = lancer(action="tour")
verifie("verrou : un tour deja en cours", r["ok"] is False and "déjà en train" in r["phrase_pour_utilisateur"], r)
vieux = time.time() - 700
os.utime(T.VERROU, (vieux, vieux))
verifie("verrou : un vieux verrou oublie ne bloque pas", lancer(action="tour")["ok"] is True)
verifie("verrou : rendu apres le tour", not os.path.exists(T.VERROU))

# ---------------------------------------------------------------- 14. lecture seule, liste fermee d'adresses, aucun code de compte
for url in ("https://exemple.invalid/prix", "http://api.kraken.com/0/public/OHLC?pair=XBTUSD", "https://api.kraken.com.exemple.invalid/x", "file:///c:/windows/win.ini"):
    try:
        T.get_json(url)
        verifie("adresse refusee : " + url, False)
    except T.Erreur:
        verifie("adresse refusee : " + url, True)
source = open(os.path.join(ICI, "trader.py"), encoding="utf-8").read()
adresses = set(re.findall(r"https?://[A-Za-z0-9.:-]+", source))
verifie("seules adresses du code : les prix publics et le modele local", adresses == {"https://api.kraken.com", "http://127.0.0.1:1234"}, adresses)
code = "\n".join(l for l in source.splitlines() if not l.lstrip().startswith("#"))
verifie("aucun code de compte ni d'ordre reel", not re.search(r"AddOrder|/private/|API-Key|api_key|apikey|secret|withdraw|password", code, re.I))
verifie("la seule methode vers Internet est GET", "method=" not in code and code.count("data=") == 1)

# ---------------------------------------------------------------- 15. en vrai processus, comme outils_maison le lance
neuf = tempfile.mkdtemp(prefix="trader_cli_")
f = os.path.join(neuf, "d.json")
with open(f, "w", encoding="utf-8-sig") as h:   # PowerShell ecrit parfois un BOM
    json.dump({"action": "etat"}, h)
pr = subprocess.run([sys.executable, os.path.join(ICI, "trader.py"), "--fichier", f], capture_output=True,
                    env=dict(os.environ, ARCHI_BASE=neuf, ARCHI_SANS_ENV="1", PYTHONIOENCODING="utf-8"))
r = json.loads(pr.stdout.decode("utf-8").strip().splitlines()[-1])
verifie("ligne de commande : etat", pr.returncode == 0 and r["ok"] and r["simulation"] and os.path.exists(os.path.join(neuf, "trader", "portefeuille.json")), r)
fiche = json.load(open(os.path.join(ICI, "outil.json"), encoding="utf-8"))
verifie("outil.json : la fiche dit simulation et jamais de conseil", fiche["nom"] == "trader" and fiche["script"] == "trader.py"
        and "SIMULATION" in fiche["description"] and "JAMAIS un conseil" in fiche["description"])

print(("%d tests OK" % ok) if not ko else ("%d ECHEC(S) sur %d" % (ko, ok + ko)))
sys.exit(1 if ko else 0)
