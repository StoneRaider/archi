# test_planificateur.py - tests du planificateur dans un faux HOME (rien ne touche le vrai PC). python test_planificateur.py
import importlib, json, os, sys, tempfile
from datetime import datetime, timedelta

ICI = os.path.dirname(os.path.abspath(__file__))
OK = KO = 0


def verif(nom, cond, detail=""):
    global OK, KO
    if cond:
        OK += 1
    else:
        KO += 1
        print("ECHEC", nom, detail)


def nouveau_home():
    h = tempfile.mkdtemp(prefix="planif_")
    os.environ["HOME"] = os.environ["USERPROFILE"] = h
    os.environ["ARCHI_BASE"] = os.path.join(h, ".n8n-files")   # jamais le vrai chateau
    os.environ["ARCHI_PY"] = sys.executable
    os.environ["PLANIF_SANS_VOIX"] = "1"
    # fausse prise Shelly : un outil qui note ce qu'on lui demande
    d = os.path.join(h, ".n8n-files", "outils", "prises_shelly")
    os.makedirs(d)
    open(os.path.join(d, "prises_shelly.py"), "w").write(
        "import json,sys,os\nd=json.load(open(sys.argv[2]))\nopen(os.path.join(os.path.dirname(__file__),'appels.txt'),'a').write(json.dumps(d)+'\\n')\n"
        "print(json.dumps({'ok':True,'phrase_pour_utilisateur':'C est fait : radiateur eteint.'}))\n")
    json.dump({"prises_shelly": {"nom": "prises_shelly", "script": "prises_shelly.py", "timeout_s": 20}},
              open(os.path.join(h, ".n8n-files", "outils", "registre.json"), "w"))
    os.makedirs(os.path.join(h, ".n8n-files", "memoire", "lieux"))
    import planificateur as P
    P = importlib.reload(P)
    P.PY = sys.executable
    return h, P


def appel(P, **p):
    import io, contextlib
    f = os.path.join(P.DOS, "..", "demande_test.json")
    os.makedirs(P.DOS, exist_ok=True)
    json.dump(p, open(f, "w"))
    sys.argv = ["planificateur.py", "--fichier", f]
    b = io.StringIO()
    with contextlib.redirect_stdout(b):
        P.main()
    return json.loads(b.getvalue())


def boite(P, p):
    """comme l'appli : un passage, puis l'accuse de reception des annonces recues"""
    with P.Verrou(5):
        P.boite_passe(p)
    P.preparer_voix(max_n=5)
    ann, _ = P.boite_reponse()
    with P.Verrou(5):
        P.boite_passe({"recus": [a["id"] for a in ann]})
    return ann


sys.path.insert(0, ICI)
h, P = nouveau_home()
L = datetime(2026, 11, 4, 9, 0)   # mercredi 4 novembre, 9 h
P.MAINTENANT = L

# --- comprendre l'heure
q = P.quand_de
verif("11h", q("11h") == datetime(2026, 11, 4, 11, 0))
verif("8h -> demain", q("8h") == datetime(2026, 11, 5, 8, 0))
verif("11 h 30", q("à 11 h 30") == datetime(2026, 11, 4, 11, 30))
verif("demain 9h", q("demain 9h") == datetime(2026, 11, 5, 9, 0))
verif("apres-demain", q("après-demain à 7h15") == datetime(2026, 11, 6, 7, 15))
verif("jeudi 18h", q("jeudi 18h") == datetime(2026, 11, 5, 18, 0))
verif("mercredi 8h (deja passe) -> semaine pro", q("mercredi 8h") == datetime(2026, 11, 11, 8, 0))
verif("dans 20 min", q("dans 20 minutes") == L + timedelta(minutes=20))
verif("2 min seul = dans 2 min", q("2 min") == L + timedelta(minutes=2) and q("15 minutes") == L + timedelta(minutes=15))
verif("2 h seul reste une heure", q("2 h") != L + timedelta(hours=2) or L.hour == 0)
verif("dans 2 h", q("dans 2 heures") == L + timedelta(hours=2))
verif("dans une heure", q("dans une heure") == L + timedelta(hours=1))
verif("dans un quart d'heure", q("dans un quart d'heure") == L + timedelta(minutes=15))
verif("ISO", q("2026-12-24 18:30") == datetime(2026, 12, 24, 18, 30))
verif("date FR", q("24/12 18h") == datetime(2026, 12, 24, 18, 0))
verif("midi", q("midi") == datetime(2026, 11, 4, 12, 0))
verif("8h du soir", q("8h du soir") == datetime(2026, 11, 4, 20, 0))
try:
    q("bientôt"); verif("heure absente refusee", False)
except P.Erreur:
    verif("heure absente refusee", True)

# --- ajouter un rappel a heure fixe, lister, declencher
r = appel(P, action="ajouter", texte="appeler le notaire", a="11h")
verif("ajout rappel", r["ok"] and r["tache"] == "t1", r)
r = appel(P, action="lister")
verif("lister", r["ok"] and "notaire" in r["phrase_pour_utilisateur"], r)
P.MAINTENANT = datetime(2026, 11, 4, 10, 59)
verif("pas encore l'heure", P.tick() == [])
P.MAINTENANT = datetime(2026, 11, 4, 11, 0)
t = P.tick()
verif("rappel a l'heure", len(t) == 1 and "notaire" in t[0], t)
verif("une seule fois", P.tick() == [])
P.MAINTENANT = L

# --- action differee : essai a blanc puis confirmer, puis execution avec confirmer=oui
r = appel(P, action="ajouter", outil="prises_shelly", outil_parametres='{"action":"eteindre","prise":"radiateur"}', a="11h")
verif("action = essai a blanc", not r["ok"] and r["phrase_pour_utilisateur"].startswith("PAS ENCORE FAIT"), r)
verif("essai a blanc n'ecrit rien", not any(t.get("action") for t in P.lire(P.TACHES, [])))
r = appel(P, action="ajouter", outil="prises_shelly", outil_parametres={"action": "eteindre", "prise": "radiateur"}, a="11h", confirmer="oui")
verif("action programmee", r["ok"], r)
P.MAINTENANT = datetime(2026, 11, 4, 11, 1)
t = P.tick()
appels = open(os.path.join(h, ".n8n-files", "outils", "prises_shelly", "appels.txt")).read()
verif("action lancee avec confirmer=oui", '"confirmer": "oui"' in appels and "radiateur" in appels, appels)
verif("annonce de l'action", len(t) == 1 and "radiateur eteint" in t[0], t)
P.MAINTENANT = L

# --- refus de securite
r = appel(P, action="ajouter", outil="ranger_mails", outil_parametres="{}", a="11h", confirmer="oui")
verif("outil non permis refuse", not r["ok"] and "RAPPEL" in r["phrase_pour_utilisateur"], r)
r = appel(P, action="ajouter", outil="prises_shelly", outil_parametres='{"action":"eteindre","prise":"pc"}', a="11h", confirmer="oui")
verif("prise du PC refusee", not r["ok"] and "PC" in r["phrase_pour_utilisateur"], r)
r = appel(P, action="ajouter", texte="x", a="2026-01-01 08:00")
verif("heure passee refusee", not r["ok"], r)
r = appel(P, action="ajouter", texte="x")
verif("sans declencheur refuse", not r["ok"], r)

# --- PC eteint : retard de plus d'1 h -> pas d'action, J prevenu
appel(P, action="ajouter", outil="prises_shelly", outil_parametres={"action": "eteindre", "prise": "radiateur"}, a="10h", confirmer="oui")
n_avant = open(os.path.join(h, ".n8n-files", "outils", "prises_shelly", "appels.txt")).read().count("\n")
P.MAINTENANT = datetime(2026, 11, 4, 12, 30)
t = P.tick()
n_apres = open(os.path.join(h, ".n8n-files", "outils", "prises_shelly", "appels.txt")).read().count("\n")
verif("retard > 1h : pas d'action", n_apres == n_avant, (n_avant, n_apres))
verif("retard > 1h : prevenu", len(t) == 1 and "PC était éteint" in t[0], t)
P.MAINTENANT = L

# --- boucle
r = appel(P, action="ajouter", texte="sortir les poubelles", tous_les="lundi", heure="19h")
verif("boucle lundi", r["ok"] and "tous les lundi" in r["phrase_pour_utilisateur"], r)
tache = [x for x in P.lire(P.TACHES, []) if x["texte"] == "sortir les poubelles"][0]
verif("prochaine = lundi 9/11 19h", tache["quand"]["prochaine"] == "2026-11-09T19:00", tache)
P.MAINTENANT = datetime(2026, 11, 9, 19, 0)
t = P.tick()
verif("boucle declenchee", any("poubelles" in x for x in t), t)
tache = [x for x in P.lire(P.TACHES, []) if x["texte"] == "sortir les poubelles"][0]
verif("boucle reprogrammee 16/11", tache["quand"]["prochaine"] == "2026-11-16T19:00" and tache["statut"] == "attente", tache)
P.MAINTENANT = L
r = appel(P, action="ajouter", texte="brief", tous_les="jour", heure="7h")
verif("tous les jours", r["ok"] and "tous les jours" in r["phrase_pour_utilisateur"], r)
r = appel(P, action="ajouter", texte="loyer", tous_les="mois", heure="10h")
t2 = [x for x in P.lire(P.TACHES, []) if x["texte"] == "loyer"][0]
verif("tous les mois = 1er decembre", t2["quand"]["prochaine"] == "2026-12-01T10:00", t2)
verif("en semaine", P.jours_de("en semaine")[0] == [0, 1, 2, 3, 4])

# --- lieux
r = appel(P, action="ajouter", texte="lait", lieu="chalet")
verif("lieu inconnu -> explique", not r["ok"] and "retiens cet endroit" in r["phrase_pour_utilisateur"], r)
P.ecrire(P.POSITION, {"lat": 48.856600, "lon": 2.352200, "heure": L.isoformat()})
r = appel(P, action="retenir_lieu", nom="chalet", ou="ici", alias="maison")
verif("retenir ici", r["ok"] and r["rayon"] == 150, r)
r = appel(P, action="retenir_lieu", nom="jardin partage", ou="48.8584, 2.2945", rayon=300, alias="potager,jardinet")
verif("retenir coordonnees", r["ok"] and r["rayon"] == 300, r)
verif("alias", P.trouver_lieu("potager")[0] == "jardin_partage" and P.trouver_lieu("jardinet")[0] == "jardin_partage")
r = appel(P, action="ajouter", texte="aller voir la voisin pour le colis", lieu="au chalet")
verif("rappel au chalet", r["ok"], r)
r = appel(P, action="ajouter", texte="cueillir les tomates", lieu="jardin", chaque_fois="oui")
verif("rappel jardin chaque fois", r["ok"] and "chaque arrivée" in r["phrase_pour_utilisateur"], r)
r = appel(P, action="ajouter", outil="prises_shelly", outil_parametres={"action": "allumer", "prise": "radiateur"}, lieu="chalet", confirmer="oui")
verif("action sur un lieu refusee", not r["ok"] and "HEURE" in r["phrase_pour_utilisateur"], r)
P.ecrire(P.ANNONCES, [])
# J est loin du jardin
a = boite(P, {"lat": 48.910523, "lon": 2.297719})
verif("loin : rien", a == [], a)
# J arrive au jardin (a 200 m du centre, rayon 300)
a = boite(P, {"lat": 48.860223, "lon": 2.294519})
verif("arrivee jardin", len(a) == 1 and "tomates" in a[0]["texte"], a)
a = boite(P, {"lat": 48.860223, "lon": 2.294519})
verif("reste sur place : pas de doublon", a == [], a)
a = boite(P, {"lat": 48.861423, "lon": 2.294519})   # ~330 m : sorti du rayon mais pas franchement (< 450 m)
a2 = boite(P, {"lat": 48.858923, "lon": 2.294519})
verif("bord du rayon : pas de re-declenchement", a == [] and a2 == [], (a, a2))
boite(P, {"lat": 48.706123, "lon": 2.254519})               # repart loin
a = boite(P, {"lat": 48.858523, "lon": 2.294619})
verif("revient : chaque_fois re-declenche", len(a) == 1, a)
# telegram : le reveil n8n envoie les annonces nees d'un passage de l'appli
t = P.tick()
verif("telegram apres passage appli", any("tomates" in x for x in t), t)
# arrivee au chalet : une seule fois
a = boite(P, {"lat": 48.856923, "lon": 2.352419})
verif("arrivee chalet", len(a) == 1 and "voisin" in a[0]["texte"], a)
boite(P, {"lat": 49.006123, "lon": 2.454519}); a = boite(P, {"lat": 48.856923, "lon": 2.352419})
verif("chalet : une seule fois", a == [], a)
verif("position mise a jour par l'appli", P.lire(P.POSITION, {}).get("source") == "appli")
a = boite(P, {"lat": "n'importe quoi"})
verif("position illisible : pas de plantage", a == [], a)

# --- position floue ou vieille : ignoree ; annonce non confirmee : renvoyee
appel(P, action="ajouter", texte="fermer le portail", lieu="jardin")
P.boite_passe({"lat": 48.706123, "lon": 2.254519})            # loin
with P.Verrou(5):
    P.boite_passe({"lat": 48.858523, "lon": 2.294619, "precision_m": 2500})
verif("position trop floue : rien", not any("portail" in a["texte"] for a in P.boite_reponse()[0]))
with P.Verrou(5):
    P.boite_passe({"lat": 48.858523, "lon": 2.294619, "age_s": 3600})
verif("position vieille : rien", not any("portail" in a["texte"] for a in P.boite_reponse()[0]))
with P.Verrou(5):
    P.boite_passe({"lat": 48.858523, "lon": 2.294619, "precision_m": 20, "age_s": 30})
P.preparer_voix(max_n=5)
a1 = [a for a in P.boite_reponse()[0] if "portail" in a["texte"]]
a2 = [a for a in P.boite_reponse()[0] if "portail" in a["texte"]]
verif("annonce re-proposee tant que non confirmee", len(a1) == 1 and len(a2) == 1, (a1, a2))
with P.Verrou(5):
    P.boite_passe({"recus": [a1[0]["id"]]})
verif("annonce confirmee : plus renvoyee", not any("portail" in a["texte"] for a in P.boite_reponse()[0]))
verif("suivre_position si rappel de lieu", P.boite_reponse()[1] is True)

# --- deja sur place a la creation : pas de declenchement immediat
P.ecrire(P.POSITION, {"lat": 48.856600, "lon": 2.352200, "heure": P.maintenant().isoformat()})
r = appel(P, action="ajouter", texte="arroser", lieu="chalet")
t1 = P.tick(); verif("deja sur place : attend la prochaine arrivee", not any("arroser" in x for x in t1), t1)
# pas de nouvelles depuis plus d'1 h : la prochaine arrivee compte
P.ecrire(P.POSITION, {"lat": 48.856600, "lon": 2.352200, "heure": "2026-11-01T00:00:00"})
P.MAINTENANT = L + timedelta(hours=2); P.tick()
a = boite(P, {"lat": 48.856923, "lon": 2.352419})
verif("retour apres 1 h sans nouvelles : rappel", any("arroser" in x["texte"] for x in a), a)
P.MAINTENANT = L

# --- securite de l'action
for op in ({"action": "eteindre", "prise": "pc_bureau"}, {"action": "eteindre", "prise": "ordinateur"}, {"action": "eteindre"},
           {"action": "reboot", "prise": "radiateur"}):
    r = appel(P, action="ajouter", outil="prises_shelly", outil_parametres=op, a="11h", confirmer="oui")
    verif(f"liste blanche {op}", not r["ok"], r)
taches = P.lire(P.TACHES, [], True)
taches.append({"id": "t99", "texte": "pirate", "statut": "attente", "quand": {"type": "heure", "a": "2026-11-04T08:59"},
               "action": {"outil": "prises_shelly", "parametres": {"action": "eteindre", "prise": "pc"}}})
taches.append({"id": "t98", "texte": "lieu abime", "statut": "attente", "quand": {"type": "lieu", "lieu": "nulle_part"}})
P.ecrire(P.TACHES, taches)
n0 = open(os.path.join(h, ".n8n-files", "outils", "prises_shelly", "appels.txt")).read().count("pc")
t1 = P.tick()
verif("tache modifiee a la main : refusee a l'execution", any("sécurité" in x for x in t1) and
      open(os.path.join(h, ".n8n-files", "outils", "prises_shelly", "appels.txt")).read().count("pc") == n0, t1)
verif("dans 1h30", P.quand_de("dans 1h30") == L + timedelta(hours=1, minutes=30))
r = appel(P, action="retenir_lieu", nom="chal", ou="47.7, 2.1")
verif("retenir un nom proche n'ecrase pas", P.lire(P.LIEUX, {})["chalet"]["lat"] == 48.8566, P.lire(P.LIEUX, {}).get("chalet"))

# --- action coupee en plein milieu : prevenu apres 10 min
taches = P.lire(P.TACHES, [], True)
taches.append({"id": "t77", "texte": "eteindre le radiateur", "statut": "en_cours", "fin": (L - timedelta(minutes=20)).isoformat(timespec="minutes"),
               "quand": {"type": "heure", "a": "2026-11-04T08:40"}})
P.ecrire(P.TACHES, taches)
t1 = P.tick()
verif("action coupee : incertain + prevenu", any("je ne sais pas" in x.lower() for x in t1) and
      [x for x in P.lire(P.TACHES, [], True) if x["id"] == "t77"][0]["statut"] == "incertain", t1)
# annonce sans voix : pas donnee a l'appli pendant 3 min
P.ecrire(P.ANNONCES, [{"id": "a1", "tache": "t1", "texte": "x", "cree": L.isoformat(), "audio": "", "voix_faite": False, "telegram": True, "appli": False}])
verif("annonce sans voix retenue 3 min", P.boite_reponse()[0] == [])
P.MAINTENANT = L + timedelta(minutes=4)
verif("puis donnee sans voix", len(P.boite_reponse()[0]) == 1)
P.MAINTENANT = L

# --- annuler
r = appel(P, action="annuler", quoi="poubelles")
verif("annuler par texte", r["ok"], r)
r = appel(P, action="annuler", quoi="zzz")
verif("annuler inconnu", not r["ok"], r)
appel(P, action="ajouter", texte="rdv A", a="15h"); appel(P, action="ajouter", texte="rdv B", a="16h")
r = appel(P, action="annuler", quoi="rdv")
verif("annuler plusieurs : demande", not r["ok"] and "PAS ENCORE FAIT" in r["phrase_pour_utilisateur"], r)
r = appel(P, action="annuler", quoi="rdv", confirmer="oui")
verif("annuler plusieurs confirme", r["ok"], r)
r = appel(P, action="lieux")
verif("lieux", "jardin" in r["phrase_pour_utilisateur"] and "chalet" in r["phrase_pour_utilisateur"], r)
r = appel(P)
verif("sans action = lister", r["ok"], r)
r = appel(P, action="danser")
verif("action inconnue", not r["ok"], r)

# --- verrou : une passe deja en cours -> le tick ne fait rien ; verrou perime -> repris
import io, contextlib
with P.Verrou(0) as v1:
    with P.Verrou(0) as v2:
        verif("verrou exclusif", v1.pris and not v2.pris)
open(os.path.join(P.DOS, "verrou"), "w").close()
os.utime(os.path.join(P.DOS, "verrou"), (0, 0))
with P.Verrou(0) as v3:
    verif("verrou perime repris", v3.pris)
sys.argv = ["planificateur.py", "--tick"]
b = io.StringIO()
with contextlib.redirect_stdout(b):
    P.main()
verif("--tick en ligne de commande", json.loads(b.getvalue())["ok"], b.getvalue())

open(P.TACHES, "w").write("{abime")
r = appel(P, action="ajouter", texte="x", a="11h")
verif("taches.json abime : on ne touche a rien", not r["ok"] and open(P.TACHES).read() == "{abime", r)
def tick_cli():
    sys.argv = ["planificateur.py", "--tick"]
    b = io.StringIO()
    with contextlib.redirect_stdout(b):
        P.main()
    return json.loads(b.getvalue())["telegram"]
t1, t2 = tick_cli(), tick_cli()
import glob
verif("abime : une seule alerte Telegram", len(t1) == 1 and "abîmé" in t1[0] and t2 == [], (t1, t2))
verif("abime : une seule copie", len(glob.glob(P.TACHES + ".illisible_*")) == 1)

# --- position partagee sur Telegram (--position) : notee, lieu reconnu, rappel de lieu declenche
h, P = nouveau_home()
import io, contextlib


def cli(args, entree):
    f = os.path.join(h, "pos.json")
    json.dump(entree, open(f, "w"))
    sys.argv = ["planificateur.py"] + args + ["--fichier", f]
    b = io.StringIO()
    with contextlib.redirect_stdout(b):
        P.main()
    return json.loads(b.getvalue().strip().splitlines()[-1])


P.ecrire(P.LIEUX, {"jardin_partage": {"nom": "jardin partage", "lat": 48.8584, "lon": 2.2945, "rayon": 300}})
appel(P, action="ajouter", texte="cueillir les tomates", lieu="jardin")
r = cli(["--position"], {"lat": 48.8590, "lon": 2.2950, "source": "telegram"})
verif("position telegram notee + lieu reconnu", r["ok"] and r["lieu"] == "jardin partage", r)
verif("position telegram enregistree", P.lire(P.POSITION, {}).get("source") == "telegram")
t = P.tick()
verif("rappel de lieu declenche par la position telegram", any("tomates" in x for x in t), t)
r = cli(["--position"], {"lat": "n'importe quoi"})
verif("position illisible refusee", not r["ok"], r)

# --- le prenom du profil a la place de « BOSS » (19/11) : ARCHI_UTILISATEUR, sinon la phrase s'en passe
os.environ["ARCHI_UTILISATEUR"] = "Camille"
verif("interpeller avec prenom", P.interpeller("rappel : pain") == "Camille, rappel : pain")
r = appel(P, action="ajouter", texte="acheter du pain", a="demain 9h")
verif("ajout : prenom du profil", r["ok"] and r["phrase_pour_utilisateur"].startswith("C'est programmé, Camille : "), r)
os.environ["ARCHI_UTILISATEUR"] = "  "
verif("interpeller sans prenom", P.interpeller("rappel : pain") == "Rappel : pain")
r = appel(P, action="ajouter", texte="acheter du lait", a="demain 10h")
verif("ajout : sans prenom", r["ok"] and r["phrase_pour_utilisateur"].startswith("C'est programmé : "), r)
verif("plus de BOSS dans le planificateur", "BOSS" not in open(os.path.join(ICI, "planificateur.py"), encoding="utf-8").read())
os.environ.pop("ARCHI_UTILISATEUR", None)

print(f"{OK} OK, {KO} ECHEC")
sys.exit(1 if KO else 0)
