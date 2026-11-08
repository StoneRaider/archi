# test_indicateur_polymarket.py - tests hors ligne (faux HOME, Polymarket et actualites simules).
#   python test_indicateur_polymarket.py
import json, os, sys, tempfile, unittest
from datetime import datetime, timedelta

FAUX = tempfile.mkdtemp(prefix="poly_test_")
os.environ["USERPROFILE"] = FAUX
os.environ["HOME"] = FAUX
os.environ["ARCHI_BASE"] = os.path.join(FAUX, ".n8n-files")   # jamais le vrai chateau
os.environ["POLY_SANS_TELEGRAM"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import indicateur_polymarket as P  # noqa: E402

assert P.BASE.startswith(FAUX), "le faux HOME n'est pas pris"
NOW = datetime(2026, 11, 6, 2, 0)
P.MAINTENANT = NOW
FIN = "2027-06-30T12:00:00Z"


def marche(id_, q, prix, d24, option="", vol24=100_000, liq=100_000, fin=FIN, issues='["Yes", "No"]'):
    return {"id": id_, "question": q, "groupItemTitle": option, "outcomes": issues,
            "outcomePrices": json.dumps([str(prix), str(round(1 - prix, 4))]), "oneDayPriceChange": d24,
            "oneWeekPriceChange": d24, "volume24hr": vol24, "liquidityNum": liq, "endDate": fin, "active": True,
            "closed": False}


def ev(slug, titre, ms, tags=("politics",), v24=100_000, v7=700_000):
    return {"slug": slug, "title": titre, "tags": [{"slug": t} for t in tags], "markets": ms, "volume24hr": v24,
            "volume1wk": v7, "volume": v7 * 10, "endDate": FIN}


EVS = [
    ev("thai", "Will Thailand hold a snap election before 2027?", [marche("m1", "Will Thailand hold a snap election before 2027?", 0.70, 0.25)]),
    ev("senate", "Ohio Senate race winner", [marche("m2", "Will the Democrat win Ohio?", 0.60, 0.22, option="Democrat")]),
    ev("france", "French government falls by...?", [marche("m3", "Will the French government fall by December 31?", 0.55, 0.30, option="December 31")]),
    ev("petit", "Will Macron resign?", [marche("m4", "Will Macron resign?", 0.05, 0.03)]),
    ev("bientot", "Will Russia strike Kyiv on November 7?", [marche("m5", "Will Russia strike Kyiv on November 7?", 0.8, 0.40, fin="2026-11-07T12:00:00Z")]),
    ev("minuscule", "Will Ukraine sign a deal?", [marche("m6", "Will Ukraine sign a deal?", 0.5, 0.35, vol24=500, liq=900)]),
    ev("foot", "Real Madrid vs Barcelona", [marche("m7", "Real Madrid vs Barcelona", 0.5, 0.40)], tags=("sports", "soccer")),
    ev("btc", "What price will Bitcoin hit in November?", [marche("m8", "Will Bitcoin reach 100k?", 0.2, -0.45, option="100k")], tags=("crypto", "hit-price")),
    ev("ecb", "ECB rate decision in December?", [marche("m9", "Will the ECB cut rates?", 0.4, -0.21, option="Cut")], tags=("economy",)),
    ev("nato", "NATO invokes Article 5 by...?", [marche("m10", "Will NATO invoke Article 5?", 0.3, 0.26, option="March 31")], tags=("world",)),
    ev("chaud", "Will the Fed cut rates in December?", [marche("m11", "Will the Fed cut rates in December?", 0.5, 0.02)], v24=3_000_000, v7=1_400_000),
]


class Faux:
    def __init__(self):
        self.appels, self.posts = [], []

    def gamma(self, chemin, **params):
        self.appels.append((chemin, params))
        if chemin == "/events" and "slug" in params:
            return [e for e in EVS if e["slug"] == params["slug"]]
        if chemin == "/events":
            if params.get("offset", 0):
                return []
            return list(EVS)
        if chemin == "/public-search":
            q = params["q"].lower()
            return {"events": [dict(e, markets=[]) for e in EVS if any(w in e["title"].lower() for w in q.split())]}
        raise AssertionError(chemin)


class Base(unittest.TestCase):
    def setUp(self):
        self.f = Faux()
        P.gamma = self.f.gamma
        P.pourquoi = lambda m, n=2: [{"titre": "Headline about " + m["evenement"][:20], "source": "Reuters"}]
        P.traduire = lambda textes, timeout: {t: t for t in textes}
        self.envoyes = []
        P.prevenir = lambda texte, vocal: self.envoyes.append(texte) or True
        for f in (P.SUIVIS, P.ETAT, P.BRIEF):
            if os.path.exists(f):
                os.remove(f)
        P.ecrire(P.POSITION, {"lat": 13.7, "lon": 100.5, "lieu": "Bangkok, Thaïlande", "heure": (NOW - timedelta(hours=3)).isoformat()})


class Refus(Base):
    def test_paris_refuses(self):
        for d in ({"sujet": "parie 100 euros sur Le Pen"}, {"action": "acheter", "sujet": "Le Pen"},
                  {"sujet": "crée-moi un compte Polymarket"}, {"action": "bet"}, {"sujet": "mon portefeuille"},
                  {"sujet": "achète des parts oui sur la Fed"}, {"action": "trade"}):
            ok, phrase, extra = P.traiter(d)
            self.assertFalse(ok, d)
            self.assertEqual(extra.get("refus"), "pari", d)
            self.assertIn("LIRE", phrase)
        self.assertEqual(self.f.appels, [], "aucun appel réseau sur un refus")

    def test_personnes_refusees(self):
        for s in ("qui sont les initiés sur Maduro", "quels comptes ont parié", "les parieurs qui gagnent", "whales Iran"):
            ok, phrase, extra = P.traiter({"sujet": s})
            self.assertFalse(ok, s)
            self.assertEqual(extra.get("refus"), "personnes")

    def test_sujets_legitimes_pas_refuses(self):
        for s in ("trade war China", "Strategy va vendre ses bitcoins", "Conseil constitutionnel", "motion de censure",
                  "Will Strategy sell Bitcoin", "mise en examen", "vendredi Macron"):
            ok, phrase, extra = P.traiter({"sujet": s})
            self.assertNotIn("refus", extra, s)

    def test_conseil(self):
        ok, phrase, _ = P.traiter({"sujet": "Macron, dois-je parier dessus ?"})
        self.assertFalse(ok)  # "parier" -> refus net
        ok, phrase, _ = P.traiter({"sujet": "Macron resign, tu me conseilles quoi ?"})
        self.assertTrue(phrase.startswith("Je ne donne aucun conseil"))


class Reseau(unittest.TestCase):
    def test_hotes(self):
        import importlib
        Q = importlib.reload(P)
        for u in ("https://data-api.polymarket.com/v2/trades", "https://clob.polymarket.com/order",
                  "http://gamma-api.polymarket.com/events", "https://evil.example/"):
            with self.assertRaises(Q.Erreur):
                Q.lecture_web(u)
        with self.assertRaises(Q.Erreur):
            Q.poste_local("https://api.telegram.org/bot/x", {}, 1)
        with self.assertRaises(Q.Erreur):
            Q.gamma("/orders")
        self.assertNotIn("data-api.polymarket.com", Q.HOTES_LECTURE)
        Q.MAINTENANT = NOW

    def test_pas_de_code_de_pari(self):
        import re
        with open(P.__file__, encoding="utf-8") as h:
            src = h.read().lower()
        for mot in ("private_key", "privatekey", "signer", "post_order", "clob_client", "web3", "eth_account", "api_key"):
            self.assertIsNone(re.search(r"" + mot + r"", src), mot)


class Lecture(Base):
    def test_tendances_sans_sport(self):
        ok, phrase, extra = P.traiter({})
        self.assertTrue(ok)
        self.assertEqual(extra["action"], "tendances")
        self.assertNotIn("Real Madrid", phrase)
        self.assertIn("le marché estime", phrase)
        self.assertIn(P.AVERTISSEMENT, phrase)

    def test_chercher(self):
        ok, phrase, extra = P.traiter({"sujet": "Thailand election"})
        self.assertTrue(ok)
        self.assertIn("70 %", phrase)
        self.assertIn("+25 points en 24 h", phrase)
        self.assertIn("Pourquoi ça bouge", phrase)

    def test_chercher_francais(self):
        self.assertIn("Thailand", P.traduire_requete("élections en Thaïlande"))
        ok, phrase, extra = P.traiter({"sujet": "élections en Thaïlande"})
        self.assertTrue(extra["trouve"], phrase)

    def test_rien_trouve(self):
        ok, phrase, extra = P.traiter({"sujet": "zzzz"})
        self.assertTrue(ok)
        self.assertFalse(extra["trouve"])

    def test_mots_vides_et_mots_entiers(self):
        # 05/11 : "situation au Venezuela" ramenait "Situational Awareness" (la recherche Polymarket est floue)
        bruit = ev("sa", "Situational Awareness AI fund raises $1B?", [marche("sa1", "Will Situational Awareness raise $1B?", 0.3, 0.01)])
        vz = ev("vz", "Will Maduro leave Venezuela in 2026?", [marche("vz1", "Will Maduro leave Venezuela in 2026?", 0.2, 0.01)])
        EVS.append(bruit)
        try:
            ok, phrase, extra = P.traiter({"action": "chercher", "sujet": "situation au Venezuela"})
            self.assertTrue(ok)
            self.assertFalse(extra["trouve"], phrase)          # pas de marche Venezuela : "aucun marché"
            self.assertNotIn("Situational", phrase)
            EVS.append(vz)
            ok, phrase, extra = P.traiter({"action": "chercher", "sujet": "situation au Venezuela"})
            self.assertTrue(extra["trouve"], phrase)
            self.assertIn("Venezuela", phrase)
            self.assertNotIn("Situational", phrase)
            self.assertTrue(all("Venezuela" in m["evenement"] for m in extra["marches"]))
            ok, phrase, extra = P.traiter({"sujet": "le point sur la situation"})  # que des mots vides
            self.assertFalse(extra["trouve"])
            ok, phrase, extra = P.traiter({"sujet": "élections au Venezuela"})  # "election" seul ne suffit pas
            self.assertNotIn("Thailand", phrase)
        finally:
            for e in (bruit, vz):
                if e in EVS:
                    EVS.remove(e)

    def test_volume_anormal(self):
        ok, phrase, _ = P.traiter({"sujet": "Fed cut"})
        self.assertIn("activité inhabituelle", phrase)

    def test_pourcentages(self):
        self.assertEqual(P.pct(0.004), "moins de 1 %")
        self.assertEqual(P.pct(0.996), "plus de 99 %")
        self.assertEqual(P.pts(-0.12), "-12 points")


class Suivis(Base):
    def test_cycle(self):
        ok, phrase, extra = P.traiter({"action": "surveiller", "sujet": "Thailand"})
        self.assertTrue(extra["ajoute"])
        self.assertIn("C'est noté", phrase)
        ok, phrase, extra = P.traiter({"action": "surveille", "sujet": "Thailand"})
        self.assertIn("déjà", phrase)
        ok, phrase, _ = P.traiter({"action": "liste"})
        self.assertIn("Thailand", phrase)
        P.passe()
        lignes = P.lignes_brief()
        self.assertTrue(any(l.startswith("👁️") and "Thailand" in l for l in lignes))
        ok, phrase, _ = P.traiter({"action": "arrete", "quoi": "thailand"})
        self.assertTrue(ok)
        self.assertEqual(P.lire(P.SUIVIS, None), [])

    def test_maximum(self):
        P.ecrire(P.SUIVIS, [{"id": f"s{i}", "sujet": f"x{i}", "slug": f"x{i}", "evenement": "x", "depuis": "2026-11-05T10:00"}
                            for i in range(P.MAX_SUIVIS)])
        with self.assertRaises(P.Erreur):
            P.traiter({"action": "surveiller", "sujet": "Thailand"})


class Nuit(Base):
    def test_passe(self):
        r = P.passe()
        self.assertTrue(r["ok"])
        b = P.lire(P.BRIEF, {})
        ids = set(b["mouvements"])
        self.assertIn("m1", ids)       # Thailande +25
        self.assertIn("m2", ids)       # Senat +22 : ligne du brief mais pas d'alerte
        self.assertNotIn("m4", ids)    # +3 : rien
        self.assertNotIn("m5", ids)    # se termine dans moins de 48 h
        self.assertNotIn("m6", ids)    # marche minuscule
        self.assertNotIn("m7", ids)    # sport
        self.assertNotIn("m8", ids)    # paliers de prix du Bitcoin
        # alertes : 3 maximum, seulement ce qui touche J (France, pays ou il est, BCE, OTAN), jamais le Senat de l'Ohio
        self.assertEqual(len(self.envoyes), 3)
        self.assertFalse(any("Ohio" in t for t in self.envoyes))
        self.assertTrue(any("French government" in t for t in self.envoyes))
        self.assertTrue(all(P.AVERTISSEMENT in t and "le marché estime" in t for t in self.envoyes))
        # deuxieme passage (6 h) : pas de doublon d'alerte
        P.MAINTENANT = NOW + timedelta(hours=4)
        P.passe()
        self.assertEqual(len(self.envoyes), 3)
        P.MAINTENANT = NOW

    def test_pays_de_l_utilisateur(self):
        r = P.passe()
        self.assertTrue(any("Thailand" in t for t in self.envoyes), "la Thaïlande doit alerter quand J y est")

    def test_pas_en_thailande(self):
        P.ecrire(P.POSITION, {"lieu": "Villeneuve-Exemple, France", "heure": NOW.isoformat()})
        P.passe()
        self.assertFalse(any("Thailand" in t for t in self.envoyes))

    def test_brief(self):
        P.passe()
        P.MAINTENANT = NOW + timedelta(hours=12)
        lignes = P.lignes_brief()
        P.MAINTENANT = NOW
        mv = [l for l in lignes if l.startswith("• ")]
        self.assertEqual(len(mv), 3)
        self.assertIn("French government", mv[0])   # +30, le plus gros

    def test_brief_vide_si_rien(self):
        global EVS
        garde = list(EVS)
        EVS[:] = [ev("calme", "Will Macron resign?", [marche("c1", "Will Macron resign?", 0.05, 0.01)])]
        try:
            P.passe()
            self.assertEqual(P.lignes_brief(), [])
            self.assertEqual(self.envoyes, [])
        finally:
            EVS[:] = garde

    def test_brief_perime(self):
        P.passe()
        P.MAINTENANT = NOW + timedelta(days=1, hours=1)
        self.assertEqual(P.lignes_brief(), [])
        P.MAINTENANT = NOW

    def test_injoignable(self):
        def panne(*a, **k):
            raise OSError("coupé")
        P.gamma = panne
        r = P.passe()
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
