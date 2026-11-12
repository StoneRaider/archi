"""Tests du format du chateau ecrit par le greffier (memoire.py) : une chose = une fiche, liens de l'ontologie,
fiches curees (Synthese), fiches ecrites a la main, oubli qui nettoie aussi resumes et index, reglages .greffier.json.
Sur un faux chateau, avec un faux modele local."""
import datetime
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading

ICI = os.path.dirname(os.path.abspath(__file__))
ok = ko = 0
REPONSE = {"faits": []}
DEMANDES = []


class FauxModele(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8"))
        DEMANDES.append(corps)
        rep = json.dumps({"choices": [{"message": {"content": json.dumps(REPONSE, ensure_ascii=False)}}]}).encode("utf-8")
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


def nouveau_chateau():
    d = tempfile.mkdtemp(prefix="chateau_")
    return d, os.path.join(d, "memoire")


def ecrire(chemin, texte):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", encoding="utf-8", newline="\n") as h:
        h.write(texte)


def lire(chemin):
    with open(chemin, encoding="utf-8") as h:
        return h.read()


def appel(base, **d):
    f = os.path.join(base, "d.json")
    with open(f, "w", encoding="utf-8") as h:
        json.dump(d, h)
    r = subprocess.run([sys.executable, os.path.join(ICI, "memoire.py"), "--fichier", f], capture_output=True,
                       env=dict(os.environ, ARCHI_BASE=base, ARCHI_LM_URL=URL, ARCHI_MODELE="faux", ARCHI_UTILISATEUR="Camille",
                                ARCHI_SANS_ENV="1", PYTHONIOENCODING="utf-8"))
    return json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])


def verif(nom, cond, detail=""):
    global ok, ko
    ok, ko = (ok + 1, ko) if cond else (ok, ko + 1)
    if not cond:
        print("ECHEC", nom, str(detail)[:500])


def fait(piece, sujet, texte, relation="", avec=""):
    return {"piece": piece, "sujet": sujet, "fait": texte, "relation": relation, "avec": avec}


AUJ = datetime.date.today().strftime("%d/%m/%Y")

# ---------------------------------------------------------------- une chose = une fiche
B, MEM = nouveau_chateau()
ecrire(os.path.join(MEM, "personnes", "laurent_martin.md"), "---\ntype: personne\npiece: personnes\nstatut: reference\nmaj: 2026-01-01\n"
       "alias: [\"mon père\", \"papa\"]\nresume: \"Laurent Martin, le père de Camille.\"\n---\n## Ajout du 01/01/2026\n**Faits :**\n- Il vit à Annecy.\n")
ecrire(os.path.join(MEM, "personnes", "tom_durand.md"), "---\ntype: personne\npiece: personnes\nstatut: actif\nmaj: 2026-01-01\nalias: []\nresume: \"Tom\"\n---\n**Faits :**\n- Collègue.\n")
ecrire(os.path.join(MEM, "personnes", "tom_petit.md"), "---\ntype: personne\npiece: personnes\nstatut: actif\nmaj: 2026-01-01\nalias: []\nresume: \"Tom\"\n---\n**Faits :**\n- Voisin.\n")

REPONSE = {"faits": [fait("personnes", "mon père", "Le père de Camille adore la pêche à la mouche.", "famille", "moi")]}
r = appel(B, action="retenir", texte="Mon père adore la pêche à la mouche.")
t = lire(os.path.join(MEM, "personnes", "laurent_martin.md"))
verif("un autre nom (alias) : la fiche qui existe", r["retenu"] and r["retenu"][0]["fiche"] == "laurent_martin" and "pêche à la mouche" in t
      and not os.path.exists(os.path.join(MEM, "personnes", "mon_pere.md")), r)
verif("l'en-tete est garde, sa date mise a jour", t.startswith("---\ntype: personne\npiece: personnes\nstatut: reference\nmaj: %s\n"
                                                                 % datetime.date.today().isoformat()) and 'alias: ["mon père", "papa"]' in t, t)
verif("lien de l'ontologie vers la fiche de l'utilisateur", "- famille :: [[profil]]" in t and "- fait_partie_de :: [[Personnes]]" in t, t)
verif("le modele connait les fiches deja la, avec leurs autres noms",
      "laurent_martin (mon père, papa)" in DEMANDES[-1]["messages"][0]["content"], DEMANDES[-1]["messages"][0]["content"][-400:])

REPONSE = {"faits": [fait("personnes", "Laurent", "Laurent, le père de Camille, a pris sa retraite.")]}
r = appel(B, action="retenir", texte="Mon père Laurent a pris sa retraite.")
verif("un nom plus court : la fiche au nom complet", r["retenu"] and r["retenu"][0]["fiche"] == "laurent_martin"
      and lire(os.path.join(MEM, "personnes", "laurent_martin.md")).count("## Ajout du %s (greffier)" % AUJ) == 1, r)

REPONSE = {"faits": [fait("moi", "moi", "Le père de Camille s'est mis au golf.", "famille", "moi")]}
r = appel(B, action="retenir", texte="Mon père s'est mis au golf.")
verif("un fait sur un proche range par erreur dans « moi » : chez le proche (autre nom « mon père »)",
      r["retenu"] and r["retenu"][0]["fiche"] == "laurent_martin" and "golf" in lire(os.path.join(MEM, "personnes", "laurent_martin.md")), r)
REPONSE = {"faits": [fait("moi", "moi", "Camille a commencé le golf.", "famille", "moi")]}
r = appel(B, action="retenir", texte="J'ai commencé le golf.")
verif("un fait sur l'utilisateur reste chez lui, sans lien vers lui-meme", r["retenu"] and r["retenu"][0]["fiche"] == "profil"
      and "famille :: [[profil]]" not in lire(os.path.join(MEM, "moi", "profil.md")), r)

REPONSE = {"faits": [fait("personnes", "Tom", "Tom joue de la guitare avec Camille.")]}
r = appel(B, action="retenir", texte="Tom joue de la guitare avec moi.")
verif("deux fiches possibles : rien n'est cree au hasard", r["retenu"] == [] and "plusieurs fiches" in r["ecartes"][0]["pourquoi"]
      and not os.path.exists(os.path.join(MEM, "personnes", "tom.md")), r)

REPONSE = {"faits": [fait("lieux", "laurent_martin", "Laurent Martin vit dans un chalet.")]}
r = appel(B, action="retenir", texte="Mon père Laurent Martin vit dans un chalet.")
verif("meme nom dans une autre piece : la fiche qui existe", r["retenu"] and r["retenu"][0]["piece"] == "personnes"
      and not os.path.exists(os.path.join(MEM, "lieux", "laurent_martin.md")), r)

# ---------------------------------------------------------------- les liens
REPONSE = {"faits": [fait("projets", "serre", "Camille construit une serre à Annecy.", "situe_a", "Annecy"),
                     fait("personnes", "Léa", "Léa est la sœur de Camille.", "famille", "Paris")]}
r = appel(B, action="retenir", texte="Je construis une serre à Annecy, et Léa est ma sœur.")
serre = lire(os.path.join(MEM, "projets", "serre.md"))
lea = lire(os.path.join(MEM, "personnes", "lea.md"))
verif("lien vers une chose nommee dans le message (fiche a creer plus tard)", "- situe_a :: [[annecy]]" in serre, serre)
verif("lien vers une chose absente du message : pas de lien invente", "Paris" not in lea and "famille ::" not in lea, lea)
REPONSE = {"faits": [fait("projets", "cabane", "Camille construit une cabane avec Tom.", "pirate", "moi")]}
r = appel(B, action="retenir", texte="Je construis une cabane, c'est mon projet.")
verif("relation hors ontologie : refusee par le schema, sinon voir_aussi", "voir_aussi :: [[profil]]" in lire(os.path.join(MEM, "projets", "cabane.md"))
      or "pirate" not in lire(os.path.join(MEM, "projets", "cabane.md")), lire(os.path.join(MEM, "projets", "cabane.md")))
verif("index de piece cree et complete", "- [[serre]] :" in lire(os.path.join(MEM, "projets", "Projets.md"))
      and "- [[cabane]] :" in lire(os.path.join(MEM, "projets", "Projets.md")))
cat = lire(os.path.join(MEM, "catalogue.md"))
verif("catalogue au format de l'Archi d'origine", "- `personnes/laurent_martin` · reference · %s · alias : mon père, papa · " % datetime.date.today().isoformat() in cat
      and "## projets" in cat and "`projets/serre` · actif ·" in cat, cat)

# ---------------------------------------------------------------- une fiche curee (Synthese + Historique)
ecrire(os.path.join(MEM, "projets", "voilier.md"), "---\ntype: projet\npiece: projets\nstatut: actif\nmaj: 2026-01-01\nalias: []\nresume: \"Voilier\"\n---\n"
       "# Voilier\n\n## Synthèse (à jour au 01/01/2026)\n**Faits :**\n- Coque poncée.\n**Hypothèses :**\n- Aucune\n**Prochaines étapes :**\n- Peindre.\n\n"
       "---\n# Historique\n\n## Ajout du 01/01/2026\n**Faits :**\n- Coque poncée.\n")
REPONSE = {"faits": [fait("projets", "voilier", "Camille a acheté une voile neuve pour le voilier.")]}
appel(B, action="retenir", texte="J'ai acheté une voile neuve pour mon voilier.")
v = lire(os.path.join(MEM, "projets", "voilier.md"))
syn = v.split("# Historique")[0]
verif("fiche curee : le fait entre dans la Synthese (lue en premier)", "voile neuve" in syn and syn.index("voile neuve") < syn.index("**Hypothèses :**"), v)
verif("fiche curee : et l'historique en garde la trace a la fin", v.rstrip().split("## Ajout du %s (greffier)" % AUJ)[-1].count("voile neuve") == 1
      and v.index("# Historique") < v.rindex("voile neuve"), v)

# ---------------------------------------------------------------- une fiche ecrite a la main, sans en-tete
ecrire(os.path.join(MEM, "projets", "drone.md"), "## Projet : drone\n**Statut :** en cours.\n")
REPONSE = {"faits": [fait("projets", "drone", "Le drone de Camille vole vingt minutes.")]}
appel(B, action="retenir", texte="Mon drone vole vingt minutes maintenant.")
dr = lire(os.path.join(MEM, "projets", "drone.md"))
verif("fiche sans en-tete : elle en recoit un, son texte est garde", dr.startswith("---\ntype: projet\npiece: projets\n") and "**Statut :** en cours." in dr
      and "vingt minutes" in dr, dr)

# ---------------------------------------------------------------- oublier nettoie resume, titre et index
REPONSE = {"faits": [fait("personnes", "Rex", "Rex est le chien de Camille.", "animal", "moi")]}
appel(B, action="retenir", texte="Mon chien s'appelle Rex.")
verif("nouvelle fiche : resume et index parlent du fait", "Rex est le chien" in lire(os.path.join(MEM, "personnes", "rex.md")).split("---")[1]
      and "Rex est le chien" in lire(os.path.join(MEM, "personnes", "Personnes.md")))
r = appel(B, action="oublier", texte="Rex chien", confirmer="oui")
rex, ix = lire(os.path.join(MEM, "personnes", "rex.md")), lire(os.path.join(MEM, "personnes", "Personnes.md"))
verif("oubli : plus rien du fait, ni dans la fiche, ni dans l'index, ni dans le catalogue", r["ok"] and "le chien" not in rex and "le chien" not in ix
      and "- [[rex]]" in ix and "le chien" not in lire(os.path.join(MEM, "catalogue.md")), rex + ix)

# ---------------------------------------------------------------- reglages du chateau (.greffier.json)
B2, MEM2 = nouveau_chateau()
ecrire(os.path.join(MEM2, ".greffier.json"), json.dumps({"fiches_uniques": {"moi": "camille_martin", "preferences": "gouts"}, "catalogue": False}))
REPONSE = {"faits": [fait("moi", "moi", "Camille est infirmière de nuit."), fait("preferences", "moi", "Camille déteste le café froid.")]}
appel(B2, action="retenir", texte="Je suis infirmière de nuit et je déteste le café froid.")
verif("fiches uniques choisies par le chateau", os.path.exists(os.path.join(MEM2, "moi", "camille_martin.md"))
      and os.path.exists(os.path.join(MEM2, "preferences", "gouts.md")))
verif("catalogue laisse a son propre fabricant", not os.path.exists(os.path.join(MEM2, "catalogue.md")))
REPONSE = {"faits": [fait("passions", "voile", "Camille fait de la voile tous les étés."), fait("travail", "hôpital", "Camille travaille à l'hôpital de Lyon.")]}
r = appel(B2, action="retenir", texte="Je fais de la voile tous les étés et je travaille à l'hôpital de Lyon.")
verif("pieces passions et travail", os.path.exists(os.path.join(MEM2, "passions", "voile.md")) and os.path.exists(os.path.join(MEM2, "travail", "hopital.md")), r)
verif("rien n'est ecrit hors des pieces du greffier", sorted(d for d in os.listdir(MEM2) if not d.startswith(".")) == ["moi", "passions", "preferences", "travail"],
      os.listdir(MEM2))

print(f"{ok} OK, {ko} ECHEC")
sys.exit(1 if ko else 0)
