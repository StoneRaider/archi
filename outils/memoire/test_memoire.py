"""Tests de memoire.py sur un faux chateau, avec un faux modele local (un petit serveur qui repond ce qu'on lui dicte)."""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading

ICI = os.path.dirname(os.path.abspath(__file__))
D = tempfile.mkdtemp(prefix="memoire_")
MEM = os.path.join(D, "memoire")
os.makedirs(os.path.join(MEM, "preferences"))
with open(os.path.join(MEM, "preferences", "archi_et_moi.md"), "w", encoding="utf-8") as h:
    h.write("## Archi et moi\n**Faits :**\n- Camille préfère des réponses courtes.\n**Hypothèses :**\n- Camille aime le matin.\n")
ok = ko = 0
REPONSE = {"faits": []}   # ce que le faux modele repondra
DEMANDES = []


class FauxModele(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8"))
        DEMANDES.append(corps)
        contenu = REPONSE if isinstance(REPONSE, str) else "Voici : " + json.dumps(REPONSE, ensure_ascii=False)
        rep = json.dumps({"choices": [{"message": {"content": contenu}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(rep)))
        self.end_headers()
        self.wfile.write(rep)

    def log_message(self, *a):
        pass


serveur = http.server.HTTPServer(("127.0.0.1", 0), FauxModele)
threading.Thread(target=serveur.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:%d/v1" % serveur.server_address[1]


def appel(lm=URL, **d):
    f = os.path.join(D, "d.json")
    with open(f, "w", encoding="utf-8") as h:
        json.dump(d, h)
    r = subprocess.run([sys.executable, os.path.join(ICI, "memoire.py"), "--fichier", f], capture_output=True,
                       env=dict(os.environ, ARCHI_BASE=D, ARCHI_LM_URL=lm, ARCHI_MODELE="faux", ARCHI_UTILISATEUR="Camille",
                                ARCHI_SANS_ENV="1", PYTHONIOENCODING="utf-8"))
    return json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])


def verif(nom, cond, detail=""):
    global ok, ko
    ok, ko = (ok + 1, ko) if cond else (ok, ko + 1)
    if not cond:
        print("ECHEC", nom, str(detail)[:400])


def lire(piece, nom):
    with open(os.path.join(MEM, piece, nom + ".md"), encoding="utf-8") as h:
        return h.read()


# --- retenir : le modele propose, l'outil verifie et range
REPONSE = {"faits": [{"piece": "personnes", "sujet": "Médor", "fait": "Médor est le chien de Camille."}]}
r = appel(action="retenir", texte="Si je te parle de mon chien, qui s'appelle Médor, tu vas le retenir ?")
verif("fait retenu", r["ok"] and len(r["retenu"]) == 1 and r["retenu"][0]["sujet"] == "Médor", r)
verif("fiche creee dans personnes", os.path.exists(os.path.join(MEM, "personnes", "medor.md")), os.listdir(MEM))
t = lire("personnes", "medor")
verif("fiche lisible : titre, piece, fait date", t.startswith("# Médor\n") and "**Pièce :** personnes" in t and "**Faits :**\n- (" in t
      and t.rstrip().endswith("Médor est le chien de Camille."), t)
verif("le modele recoit le message et le prenom", DEMANDES[-1]["messages"][1]["content"].startswith("Si je te parle")
      and "Camille" in DEMANDES[-1]["messages"][0]["content"] and DEMANDES[-1]["temperature"] == 0, DEMANDES[-1])
# le meme fait une seconde fois : pas de doublon
r = appel(action="retenir", texte="Mon chien s'appelle Médor, je te l'ai déjà dit.")
verif("pas de doublon", r["ok"] and r["retenu"] == [] and r["ecartes"][0]["pourquoi"] == "deja su", r)
verif("une seule ligne dans la fiche", lire("personnes", "medor").count("\n- ") == 1)
# un second fait sur le meme sujet : meme fiche
REPONSE = {"faits": [{"piece": "personnes", "sujet": "Médor", "fait": "Médor a huit ans et adore la neige."}]}
r = appel(action="retenir", texte="Tu sais, mon Médor a huit ans et adore la neige.")
verif("second fait, meme fiche", len(r["retenu"]) == 1 and lire("personnes", "medor").count("\n- ") == 2, r)

# --- pas de premiere personne : le modele n'est meme pas derange
n = len(DEMANDES)
r = appel(action="retenir", texte="Quels outils as-tu ?")
verif("question sans « je » : aucun appel au modele", r["ok"] and r["retenu"] == [] and r["appel_modele"] is False and len(DEMANDES) == n, r)
r = appel(action="retenir", texte="Bonjour")
verif("message trop court : aucun appel", r["appel_modele"] is False and len(DEMANDES) == n, r)

# --- les garde-fous
REPONSE = {"faits": [
    {"piece": "moi", "sujet": "moi", "fait": "Le mot de passe de Camille est tulipe42."},
    {"piece": "personnes", "sujet": "Léa", "fait": "Léa, la sœur de Camille, répond au 06 12 34 56 78."},
    {"piece": "personnes", "sujet": "Léa", "fait": "Léa, la sœur de Camille, habite 12 rue des Lilas à Lyon."},
    {"piece": "personnes", "sujet": "Gaston", "fait": "Gaston est le voisin de Camille."},
    {"piece": "cave", "sujet": "vin", "fait": "Camille range son vin à la cave."},
    {"piece": "personnes", "sujet": "../../Léa", "fait": "Léa est la sœur de Camille."},
    {"piece": "moi", "sujet": "moi", "fait": "x"},
]}
r = appel(action="retenir", texte="Ma sœur Léa habite Lyon, mon mot de passe est tulipe42 et je range mon vin à la cave.")
raisons = [e["pourquoi"] for e in r["ecartes"]]
verif("mot de passe, telephone et adresse jamais retenus", raisons[:3] == ["donnee sensible"] * 3, r)
verif("un nom absent du message n'est pas retenu (rien d'invente)", raisons[3] in ("sujet absent du message", "ne vient pas du message"), r)
verif("piece inconnue refusee", raisons[4] == "piece inconnue", r)
verif("fait trop court refuse", "fait trop court ou trop long" in raisons, r)
verif("un fait vrai est retenu, et un sujet piege ne sort pas du dossier", [x["sujet"] for x in r["retenu"]] == ["../../Léa"]
      and os.path.exists(os.path.join(MEM, "personnes", "lea.md")) and not os.path.exists(os.path.join(D, "Léa.md"))
      and not os.path.exists(os.path.join(D, "lea.md")), r)
verif("rien d'autre n'est range", sorted(os.listdir(os.path.join(MEM, "personnes"))) == ["lea.md", "medor.md"]
      and not os.path.exists(os.path.join(MEM, "moi")), os.listdir(MEM))

# --- au plus 3 faits par message
REPONSE = {"faits": [{"piece": "lieux", "sujet": "lieu%d" % i, "fait": "Camille connaît bien le lieu%d et son marché." % i} for i in range(5)]}
r = appel(action="retenir", texte="Je connais bien lieu0, lieu1, lieu2, lieu3 et lieu4, et leur marché.")
verif("au plus 3 faits", len(r["retenu"]) == 3 and len(os.listdir(os.path.join(MEM, "lieux"))) == 3, r)

# --- a blanc : rien n'est ecrit (sert au banc de mesure)
REPONSE = {"faits": [{"piece": "projets", "sujet": "cabane", "fait": "Camille construit une cabane dans son jardin."}]}
r = appel(action="retenir", a_blanc="oui", texte="Je construis une cabane dans mon jardin.")
verif("a blanc : propose sans ranger", len(r["retenu"]) == 1 and not os.path.exists(os.path.join(MEM, "projets")), r)

# --- le modele repond n'importe quoi, ou ne repond pas : la conversation continue
REPONSE = "Je ne sais pas trop."
r = appel(action="retenir", texte="Je construis une cabane dans mon jardin.")
verif("reponse sans JSON : rien retenu, pas d'erreur", r["ok"] and r["retenu"] == [], r)
r = appel(lm="http://127.0.0.1:1/v1", action="retenir", texte="Je construis une cabane dans mon jardin.")
verif("modele eteint : rien retenu, pas d'erreur", r["ok"] and r["retenu"] == [] and "erreur" in r, r)
# la description d'une photo n'est pas « dite » par l'utilisateur
n = len(DEMANDES)
REPONSE = {"faits": []}
appel(action="retenir", texte="Regarde ma photo\n--- contenu de la photo x.jpg (decrite par le modele de vision) ---\nUn compteur, je vois 01482.")
verif("la photo n'est pas envoyee au greffier", len(DEMANDES) == n + 1 and "compteur" not in DEMANDES[-1]["messages"][1]["content"], DEMANDES[-1])

# --- ecrire, lister, lire
r = appel(action="ecrire", piece="preferences", fait="Camille boit son café sans sucre.")
t = lire("preferences", "mes_preferences")
verif("ecrire dans les preferences", r["ok"] and "sans sucre" in t and "**Faits :**" in t, r)
r = appel(action="ecrire", piece="moi", sujet="moi", fait="Camille est née à Dijon.")
verif("ecrire sur moi", r["ok"] and os.path.exists(os.path.join(MEM, "moi", "moi.md")), r)
r = appel(action="ecrire", piece="moi", fait="Le code PIN de Camille est 4321.")
verif("ecrire refuse un secret", r["ok"] is False and "sensible" in r["phrase_pour_utilisateur"], r)
r = appel(action="lister")
verif("lister", r["ok"] and {"piece": "personnes", "sujet": "medor", "faits": 2} in r["fiches"] and "medor" in r["phrase_pour_utilisateur"], r)
r = appel(action="lire", sujet="Médor")
verif("lire une fiche", r["ok"] and "chien" in r["phrase_pour_utilisateur"] and "neige" in r["phrase_pour_utilisateur"]
      and "(1" not in r["phrase_pour_utilisateur"][:40], r)
r = appel(action="lire", sujet="licorne")
verif("lire : rien sur ce sujet", r["ok"] and r["faits"] == [], r)
# une fiche existante (bloc suivi d'un autre bloc) : le fait est ajoute AVANT le bloc suivant
h = open(os.path.join(MEM, "preferences", "mes_preferences.md"), "a", encoding="utf-8")
h.write("**Hypothèses :**\n- Camille aime peut-être le thé.\n")
h.close()
appel(action="ecrire", piece="preferences", fait="Camille déteste les réveils à cinq heures.")
t = lire("preferences", "mes_preferences")
verif("ajout avant le bloc suivant", t.index("cinq heures") < t.index("**Hypothèses :**") and "peut-être le thé" in t, t)

# --- oublier : essai a blanc, puis pour de bon
r = appel(action="oublier", texte="Médor neige")
verif("oublier : essai a blanc", r["ok"] and "ESSAI" in r["phrase_pour_utilisateur"] and len(r["a_oublier"]) == 1
      and lire("personnes", "medor").count("\n- ") == 2, r)
r = appel(action="oublier", texte="Médor neige", confirmer="oui")
t = lire("personnes", "medor")
verif("oublier : le fait est retire, l'autre reste", r["ok"] and len(r["oublie"]) == 1 and "neige" not in t and "chien" in t, t)
r = appel(action="oublier", texte="licorne")
verif("oublier : rien a oublier", r["ok"] and r["oublie"] == [], r)
r = appel(action="oublier", texte="de la")
verif("oublier : mots trop vagues refuses", r["ok"] is False, r)
r = appel(action="danser")
verif("action inconnue", r["ok"] is False and "retenir" in r["phrase_pour_utilisateur"], r)

# --- le journal des faits retenus (lu par la page d'accueil), le menage du fichier de demande, le verrou
def journal():
    with open(os.path.join(MEM, ".retenu.jsonl"), encoding="utf-8") as h:
        return [json.loads(l) for l in h.read().splitlines() if l.strip()]


j = journal()
verif("journal : un fait par ligne, date en millisecondes", len(j) >= 5 and all(isinstance(x["quand"], int) and x["fait"] for x in j), j)
verif("journal : le fait oublie n'y est plus", not any("neige" in x["fait"] for x in j), j)
verif("journal : 50 lignes au plus", len(j) <= 50, len(j))
verif("un essai a blanc n'ecrit pas au journal", not any("cabane" in x["fait"] for x in j), j)
f = os.path.join(D, "demande_fond.json")
with open(f, "w", encoding="utf-8") as h:
    json.dump({"action": "lister"}, h)
r = subprocess.run([sys.executable, os.path.join(ICI, "memoire.py"), "--fichier", f, "--menage"], capture_output=True,
                   env=dict(os.environ, ARCHI_BASE=D, ARCHI_SANS_ENV="1", PYTHONIOENCODING="utf-8"))
verif("--menage : la demande est effacee apres lecture", r.returncode == 0 and not os.path.exists(f), r.stdout[-200:])
verif("aucun verrou ne traine", not os.path.exists(os.path.join(MEM, ".verrou_memoire")), os.listdir(MEM))
verif("aucun fichier temporaire ne traine", not [x for p, _, fs_ in os.walk(MEM) for x in fs_ if x.endswith(".tmp")])
os.mkdir(os.path.join(MEM, ".verrou_memoire"))   # un verrou oublie, vieux : il ne bloque pas
vieux = __import__("time").time() - 300
os.utime(os.path.join(MEM, ".verrou_memoire"), (vieux, vieux))
r = appel(action="ecrire", piece="lieux", sujet="Dijon", fait="Camille aime marcher au bord du lac.")
verif("un vieux verrou oublie ne bloque pas", r["ok"] and not os.path.exists(os.path.join(MEM, ".verrou_memoire")), r)

print(f"{ok} OK, {ko} ECHEC")
sys.exit(1 if ko else 0)
