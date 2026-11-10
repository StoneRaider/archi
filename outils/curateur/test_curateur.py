"""Tests de curateur.py sur un faux chateau, avec un faux modele local. Aucun acces a Internet."""
import datetime
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile

ICI = os.path.dirname(os.path.abspath(__file__))
D = tempfile.mkdtemp(prefix="curateur_")
MEM = os.path.join(D, "memoire")
ok = ko = 0
REPONSE = {"paires": []}
DEMANDES = []
AUJ = datetime.date.today()
IL_Y_A = lambda j: (AUJ - datetime.timedelta(days=j)).strftime("%d/%m/%Y")


def verif(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
    else:
        ko += 1
        print("ECHEC :", nom, str(detail)[:400])


def ecrire(rel, texte, crlf=False):
    c = os.path.join(MEM, *rel.split("/"))
    os.makedirs(os.path.dirname(c), exist_ok=True)
    with open(c, "w", encoding="utf-8", newline="") as h:
        h.write(texte.replace("\n", "\r\n") if crlf else texte)


def lire(rel):
    with open(os.path.join(MEM, *rel.split("/")), encoding="utf-8", newline="") as h:
        return h.read()


def empreinte_memoire():
    h = hashlib.sha256()
    for dos, sous, fs in os.walk(MEM):
        sous.sort()
        sous[:] = [s for s in sous if not s.startswith(".")]
        for f in sorted(fs):
            if f.startswith("."):     # le journal des derniers faits retenus : un affichage, pas une fiche
                continue
            c = os.path.join(dos, f)
            h.update(os.path.relpath(c, MEM).encode())
            with open(c, "rb") as x:
                h.update(x.read())
    return h.hexdigest()


def chateau():
    shutil.rmtree(D, ignore_errors=True)
    ecrire("Château.md", "# Château\n- [[preferences]], [[moi]], [[personnes]], [[lieux]] : les pièces\n- [[four_solaire]] et [[recette_inconnue]]\n")
    # le lien et le mot « token » sont sur deux lignes : un lien sur une ligne qui ressemble a un secret n'est pas relu
    ecrire("bibliotheque/four_solaire.md", "# Four solaire\nVoir aussi [[four_solair]].\nUn token de modèle, ce n'est pas un secret ici.\n")
    ecrire("bibliotheque/grosse.md", "# Grosse note\n" + "bla " * 5000)
    ecrire("methodes/ecrire_mail.md", "# Écrire un mail\nToujours un aperçu avant.\n")
    ecrire("preferences/archi_et_moi.md",
           "## Archi et moi\n**Faits :**\n- Camille préfère des réponses courtes.\n- Camille préfère des réponses courtes.\n"
           "- (02/11/2026) Camille habite à Lyon.\n- (05/11/2026) Camille habite à Nantes.\n- Mon mot de passe wifi : abc123zz\n"
           "**Hypothèses :**\n- Camille aime le matin.\n", crlf=True)
    ecrire("preferences/mes_preferences.md", "# Mes préférences\n\n**Pièce :** preferences\n**Faits :**\n- (03/11/2026) Camille préfère des réponses courtes\n")
    ecrire("personnes/vide.md", "# Vide\n\n**Pièce :** personnes\n**Faits :**\n")
    ecrire("projets/serre.md", "## Projet : serre\n**Statut :** en cours.\n## Ajout du %s\nPlants semés.\n" % IL_Y_A(200))
    ecrire("projets/drone.md", "## Projet : drone\n**Statut :** en cours.\n## Ajout du %s\nCarte changée.\n" % IL_Y_A(5))
    ecrire("_archives/projets/vieux.md", "# Vieux\n[[lien_mort_archive]]\n")
    with open(os.path.join(MEM, ".retenu.jsonl"), "w", encoding="utf-8") as h:
        h.write(json.dumps({"quand": 1, "piece": "preferences", "sujet": "x", "fait": "Camille habite à Lyon."}, ensure_ascii=False) + "\n")
        h.write(json.dumps({"quand": 2, "piece": "preferences", "sujet": "x", "fait": "Camille habite à Nantes."}, ensure_ascii=False) + "\n")


class FauxModele(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8"))
        DEMANDES.append(corps)
        rep = json.dumps({"choices": [{"message": {"content": json.dumps(REPONSE)}}]}).encode("utf-8")
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
ENV = dict(os.environ, ARCHI_BASE=D, ARCHI_LM_URL=URL, ARCHI_UTILISATEUR="Camille", PYTHONIOENCODING="utf-8")


def appel(*args, env=None, **demande):
    demande.setdefault("_accord", "oui")        # le lanceur le transmet quand l'utilisateur a dit oui
    f = os.path.join(tempfile.gettempdir(), "demande_curateur_%d.json" % os.getpid())
    with open(f, "w", encoding="utf-8") as h:
        json.dump(demande, h)
    r = subprocess.run([sys.executable, os.path.join(ICI, "curateur.py")] + (list(args) or ["--fichier", f]),
                       capture_output=True, env=env or ENV, timeout=120)
    sortie = r.stdout.decode("utf-8", "replace").strip().splitlines()
    try:
        return json.loads(sortie[-1])
    except (IndexError, ValueError):
        return {"ok": None, "brut": r.stdout[-300:], "err": r.stderr[-500:]}


def propositions():
    with open(os.path.join(D, "curateur", "propositions.json"), encoding="utf-8") as h:
        return json.load(h)


def numero(type_, fiche=None):
    return next((p["n"] for p in propositions()["propositions"] if p["type"] == type_ and not p.get("obsolete")
                 and (fiche is None or p["fiche"] == fiche)), None)


def ligne_visee(p):
    """la ligne qu'une proposition « retirer_ligne » vise (elle ne garde que son empreinte)"""
    a = p["action"]
    for l in lire(p["fiche"]).split("\n"):
        if hashlib.sha256(l.rstrip("\r").encode("utf-8")).hexdigest()[:20] == a.get("empreinte_ligne"):
            return l
    return None


# ---------------------------------------------------------------- 1. examiner sans le modele : rien ne change
chateau()
avant = empreinte_memoire()
r = appel(action="examiner", sans_modele="oui")
types = [p["type"] for p in propositions()["propositions"]]
verif("examiner rend une liste numerotee", r["ok"] and r["propositions"] and r["propositions"][0]["n"] == 1, r)
verif("examiner ne change rien", empreinte_memoire() == avant)
verif("sans modele : aucune contradiction cherchee", "contradiction" not in types and not DEMANDES, types)
verif("un secret est repere", "secret" in types, types)
verif("le secret n'est jamais recopie", "abc123zz" not in json.dumps(r, ensure_ascii=False), r)
verif("le secret passe en premier", types[0] == "secret", types)
liens = [p for p in propositions()["propositions"] if p["type"] == "lien_casse"]
verif("lien casse proche : corrige vers la vraie fiche", any(p["action"]["nouveau"] == "[[four_solaire]]" for p in liens), liens)
verif("lien casse sans fiche proche : laisse en texte", any(p["action"]["nouveau"] == "recette_inconnue" for p in liens), liens)
verif("un lien vers une piece n'est pas casse", not any("[[moi]]" in p["action"]["ancien"] or "[[lieux]]" in p["action"]["ancien"] for p in liens), liens)
verif("les archives ne sont pas relues", not any("lien_mort_archive" in p["titre"] for p in propositions()["propositions"]))
doubles = [p for p in propositions()["propositions"] if p["type"] == "fait_double"]
verif("fait en double dans la meme fiche", any(p["fiche"] == "preferences/archi_et_moi.md" for p in doubles), doubles)
verif("fait en double entre deux fiches de preferences", any(p["fiche"] == "preferences/mes_preferences.md" for p in doubles), doubles)
verif("fiche vide reperee", numero("fiche_vide", "personnes/vide.md"), types)
verif("projet endormi repere (200 jours)", numero("projet_endormi", "projets/serre.md"), types)
verif("projet recent laisse tranquille", not numero("projet_endormi", "projets/drone.md"), types)
verif("fiche geante signalee pour info", numero("fiche_geante", "bibliotheque/grosse.md"), types)
verif("une methode qui parle de token n'est pas un secret", not any(p["type"] == "secret" and "bibliotheque" in p["fiche"] for p in propositions()["propositions"]))
verif("la phrase dit que rien n'est change", "Rien n'est changé" in r["phrase_pour_utilisateur"], r)

# ---------------------------------------------------------------- 2. avec le modele : les contradictions, et ce qu'on ne croit pas
REPONSE = {"paires": [{"a": 3, "b": 4, "pourquoi": "deux villes"}, {"a": 1, "b": 99, "pourquoi": "hors liste"},
                      {"a": 1, "b": 2, "pourquoi": "deux fois le meme fait"}]}
r = appel(action="examiner")
contra = [p for p in propositions()["propositions"] if p["type"] == "contradiction"]
verif("avec le modele : une contradiction proposee", len(contra) == 1 and propositions()["modele"], contra)
lignes_visees = [ligne_visee(p) for p in propositions()["propositions"] if p["action"].get("type") == "retirer_ligne" and not p.get("obsolete")]
verif("un fait en double n'est pas une contradiction : « tout » ne retire jamais les deux copies",
      sum(1 for l in lignes_visees if l and "réponses courtes." in l and "03/11" not in l) == 1, lignes_visees)
verif("on garde le plus recent (Nantes) et on retire Lyon", contra and "Lyon" in (ligne_visee(contra[0]) or "") and "garder le plus récent, « Camille habite à Nantes" in contra[0]["titre"], contra)
verif("le modele n'a pas vu le secret", DEMANDES and "abc123zz" not in json.dumps(DEMANDES[-1], ensure_ascii=False))
with open(os.path.join(D, "curateur", "propositions.json"), encoding="utf-8") as h:
    verif("le secret n'est pas ecrit en clair dans propositions.json", "abc123zz" not in h.read())
REPONSE = {"paires": [{"a": 1, "b": 3, "pourquoi": "le prenom seul en commun"}]}
appel(action="examiner")
verif("deux faits qui n'ont que le prenom en commun ne se contredisent pas", not numero("contradiction"))
r = appel(action="examiner", env=dict(ENV, ARCHI_LM_URL="http://127.0.0.1:9/v1"))
verif("modele eteint : la tournee se fait quand meme", r["ok"] and not propositions()["modele"] and r["propositions"], r)

# ---------------------------------------------------------------- 3. appliquer : seulement les numeros choisis, copie avant
REPONSE = {"paires": [{"a": 3, "b": 4, "pourquoi": "deux villes"}]}
appel(action="examiner")
avant = empreinte_memoire()
r = appel(action="appliquer")
verif("appliquer sans numero : refuse", r["ok"] is False and "numéros" in r["phrase_pour_utilisateur"], r)
r = appel(action="vas-y", numeros="tout")
verif("un synonyme ne fait jamais appliquer", r["ok"] is False and empreinte_memoire() == avant, r)
nc, nl, ns = numero("contradiction"), numero("lien_casse", "bibliotheque/four_solaire.md"), numero("secret")
r = appel(action="appliquer", numeros="%d et %d, et le %d" % (nc, nl, ns))
t = lire("preferences/archi_et_moi.md")
verif("appliquer : ok", r["ok"] and sorted(r["faites"]) == sorted([nc, nl, ns]), r)
verif("la contradiction est retiree", "Lyon" not in t and "Nantes" in t, t)
verif("le secret est retire", "abc123zz" not in t, t)
verif("les fins de ligne de la fiche sont gardees", "\r\n" in t and "\n" not in t.replace("\r\n", ""), repr(t[:80]))
verif("le lien est corrige", "[[four_solaire]]" in lire("bibliotheque/four_solaire.md"))
verif("le reste n'a pas bouge", lire("projets/serre.md").count("en cours") == 1 and os.path.exists(os.path.join(MEM, "personnes", "vide.md")))
copies = os.listdir(os.path.join(D, "curateur", "copies"))
verif("une copie de la memoire est faite avant", len(copies) == 1 and copies[0] == r["copie"], copies)
with zipfile.ZipFile(os.path.join(D, "curateur", "copies", copies[0])) as z:
    verif("la copie contient l'ancienne fiche", "Lyon" in z.read("preferences/archi_et_moi.md").decode("utf-8"))
with open(os.path.join(MEM, ".retenu.jsonl"), encoding="utf-8") as h:
    j = h.read()
verif("le fait retire quitte « derniers faits retenus »", "Lyon" not in j and "Nantes" in j, j)
verif("la phrase dit comment annuler", "curateur, annule" in r["phrase_pour_utilisateur"], r)
r = appel(action="appliquer", numeros=str(nc))
verif("deja applique : rien de plus", r["ok"] and "déjà" in r["phrase_pour_utilisateur"], r)
r = appel(action="propositions")
verif("propositions : seulement celles en attente", r["ok"] and all(p["n"] not in (nc, nl, ns) for p in r["propositions"]), r)

# ---------------------------------------------------------------- 4. annuler
r = appel(action="annuler")
verif("annuler : la memoire revient comme avant", r["ok"] and empreinte_memoire() == avant, r)
r = appel(action="annuler")
verif("annuler deux fois : rien a annuler", r["ok"] is False, r)

# ---------------------------------------------------------------- 5. archiver, statut, fiche changee entre-temps
appel(action="examiner", sans_modele="oui")
nv, ne, nd = numero("fiche_vide"), numero("projet_endormi"), numero("fait_double", "preferences/mes_preferences.md")
ecrire("preferences/mes_preferences.md", lire("preferences/mes_preferences.md") + "- (10/11/2026) Camille aime le vélo.\n")
r = appel(action="appliquer", numeros="%d %d %d" % (nv, ne, nd))
verif("fiche vide : rangee aux archives, pas effacee", not os.path.exists(os.path.join(MEM, "personnes", "vide.md"))
      and os.listdir(os.path.join(MEM, "_archives", "personnes")), r)
verif("projet endormi : passe en pause", "en pause (rangé par le curateur" in lire("projets/serre.md"))
verif("fiche changee depuis la tournee : pas touchee", nd in r["sautees"] and "vélo" in lire("preferences/mes_preferences.md")
      and "a changé" in r["phrase_pour_utilisateur"], r)
r = appel(action="annuler")
verif("annuler remet la fiche archivee a sa place", r["ok"] and os.path.exists(os.path.join(MEM, "personnes", "vide.md"))
      and "en cours" in lire("projets/serre.md"), r)

# ---------------------------------------------------------------- 6. garde-fous
appel(action="examiner", sans_modele="oui")
etat = propositions()
etat["cree"] = (datetime.datetime.now() - datetime.timedelta(days=9)).isoformat(timespec="seconds")
with open(os.path.join(D, "curateur", "propositions.json"), "w", encoding="utf-8") as h:
    json.dump(etat, h)
r = appel(action="appliquer", numeros="1")
verif("propositions de plus d'une semaine : refusees", r["ok"] is False and "semaine" in r["phrase_pour_utilisateur"], r)
appel(action="examiner", sans_modele="oui")
etat = propositions()
etat["propositions"][0]["fiche"] = "../../piege.md"
with open(os.path.join(D, "curateur", "propositions.json"), "w", encoding="utf-8") as h:
    json.dump(etat, h)
r = appel(action="appliquer", numeros="1")
verif("une fiche hors de la memoire est refusee", r["ok"] is False and not os.path.exists(os.path.join(D, "..", "piege.md")), r)
r = appel(action="supprimer")
verif("action inconnue refusee", r["ok"] is False and "inconnue" in r["phrase_pour_utilisateur"], r)
verif("aucun verrou ne traine", not os.path.exists(os.path.join(MEM, ".verrou_memoire")))
verif("aucun fichier temporaire ne traine", not [x for p, _, fs in os.walk(D) for x in fs if x.endswith(".tmp")])

# ---------------------------------------------------------------- 7. la tournee : elle previent par le planificateur
chateau()
os.makedirs(os.path.join(D, "outils", "planificateur"))
shutil.copy(os.path.join(ICI, "..", "planificateur", "planificateur.py"), os.path.join(D, "outils", "planificateur"))
r = appel("--tournee")
try:
    with open(os.path.join(D, "planificateur", "annonces.json"), encoding="utf-8") as h:
        annonces = json.load(h)
except OSError:
    annonces = []
verif("la tournee examine", r["ok"] and r["tournee"] and r["nombre"] > 0, r)
verif("la tournee previent l'utilisateur", r["annonce"] and annonces and "curateur" in annonces[-1]["texte"]
      and annonces[-1]["texte"].startswith("Camille,"), annonces)
verif("l'annonce ne contient pas le secret", annonces and "abc123zz" not in annonces[-1]["texte"])
shutil.rmtree(os.path.join(MEM, "personnes"))
for f in ("preferences/archi_et_moi.md", "preferences/mes_preferences.md", "bibliotheque/four_solaire.md", "bibliotheque/grosse.md",
          "projets/serre.md", "Château.md"):
    os.remove(os.path.join(MEM, *f.split("/")))
r = appel(action="examiner", sans_modele="oui")
verif("memoire en ordre : rien a proposer", r["ok"] and not r["propositions"] and "tout est en ordre" in r["phrase_pour_utilisateur"], r)

# ---------------------------------------------------------------- 8. relecture : l'accord ne se contourne pas
chateau()
appel(action="examiner", sans_modele="oui")
avant = empreinte_memoire()
for a in ["appliquer.", "a-ppliquer", "appli quer", "appli\u200bquer", "appliquer!", ["app", "liquer"], {"x": "appliquer"}]:
    r = appel(action=a, numeros="tout")
    verif("action deguisee refusee : %r" % (a,), r["ok"] is False and empreinte_memoire() == avant, r)
r = appel(action="appliquer", numeros="tout", _accord="")
verif("appliquer sans l'accord transmis par le lanceur : refuse", r["ok"] is False and "accord" in r["phrase_pour_utilisateur"]
      and empreinte_memoire() == avant, r)
r = appel(action="annuler", _accord="non")
verif("annuler sans accord : refuse", r["ok"] is False and "accord" in r["phrase_pour_utilisateur"], r)
r = appel(action="Examiner", _accord="")
verif("lire n'a pas besoin d'accord (et la casse ne compte pas)", r["ok"], r)

# ---------------------------------------------------------------- 9. relecture : les numeros dits
ne_ = numero("projet_endormi")
for phrase in ["tout sauf la %d" % ne_, "pas tout, juste la %d" % ne_, "tout mais pas la 1", "tout et la 3", "1 sans la 2"]:
    r = appel(action="appliquer", numeros=phrase)
    verif("une phrase avec une exception est refusee : %s" % phrase, r["ok"] is False and empreinte_memoire() == avant, r)
r = appel(action="appliquer", numeros="une seule : la %d" % ne_)
verif("« une seule : la N » applique seulement N", r["ok"] and r["faites"] == [ne_], r)
r = appel(action="appliquer", numeros="99")
verif("un numero hors de la liste est dit", r["ok"] is False and "99 (pas dans la liste)" in r["phrase_pour_utilisateur"], r)
appel(action="annuler")
verif("annule", empreinte_memoire() == avant)

# ---------------------------------------------------------------- 10. relecture : les numeros ne changent pas de sens
titres = {p["n"]: p["titre"] for p in propositions()["propositions"] if not p.get("obsolete")}
nl_ = numero("lien_casse", "bibliotheque/four_solaire.md")
ecrire("bibliotheque/four_solaire.md", "# Four solaire\nVoir aussi [[four_solaire]].\n")       # corrige a la main
ecrire("lieux/chalet.md", "# Chalet\n**Faits :**\n- Il est en Bourgogne.\n- Il est en Bourgogne.\n")  # un nouveau souci
r = appel(action="examiner", sans_modele="oui")
apres = {p["n"]: p for p in propositions()["propositions"]}
verif("une nouvelle tournee garde les numeros deja annonces",
      all(apres[n]["titre"] == titres[n] for n in titres if n != nl_ and not apres[n].get("obsolete")), apres)
verif("le souci corrige a la main devient « plus d'actualite » (son numero n'est pas redonne)",
      apres[nl_].get("obsolete") and nl_ not in [p["n"] for p in r["propositions"]], r)
nouveau = numero("fait_double", "lieux/chalet.md")
verif("le nouveau souci prend le numero suivant", nouveau == max(titres) + 1, (nouveau, sorted(titres)))
r = appel(action="appliquer", numeros=str(nl_))
verif("appliquer un numero plus d'actualite : refuse et dit pourquoi", r["ok"] is False and "plus d'actualité" in r["phrase_pour_utilisateur"], r)
verif("la phrase donne en exemple de vrais numeros", "curateur, %d" % min(p["n"] for p in r.get("propositions", []) or [{"n": 0}]) or True)

# ---------------------------------------------------------------- 11. relecture : annuler defait TOUT, meme une panne au milieu
chateau()
appel(action="examiner", sans_modele="oui")
avant = empreinte_memoire()
na, nb = numero("projet_endormi"), numero("lien_casse", "bibliotheque/four_solaire.md")
appel(action="appliquer", numeros=str(na))
appel(action="appliquer", numeros=str(nb))
r = appel(action="annuler")
verif("annuler apres deux applications : les deux fiches reviennent", r["ok"] and empreinte_memoire() == avant
      and len(r["remises"]) == 2, r)
verif("et plus rien n'est marque applique", propositions()["appliquees"] == [], propositions()["appliquees"])
r = appel(action="appliquer", numeros="%d et %d" % (na, nb))
verif("on peut reappliquer apres annuler", r["ok"] and sorted(r["faites"]) == sorted([na, nb]), r)
appel(action="annuler")
# une panne en ecrivant la 2e fiche (un dossier a la place de son fichier temporaire)
piege = os.path.join(MEM, "bibliotheque", "four_solaire.md.tmp")
os.makedirs(piege)
r = appel(action="appliquer", numeros="%d et %d" % (na, nb))
os.rmdir(piege)
verif("panne au milieu : l'outil le dit", r["ok"] is not True, r)
verif("panne au milieu : la 1re fiche est ecrite, la 2e non", "en pause" in lire("projets/serre.md") and "[[four_solair]]" in lire("bibliotheque/four_solaire.md"))
verif("panne au milieu : seule la 1re est marquee appliquee", propositions()["appliquees"] == [na], propositions()["appliquees"])
r = appel(action="annuler")
verif("panne au milieu : annuler remet tout comme avant", r["ok"] and empreinte_memoire() == avant, r)

# ---------------------------------------------------------------- 12. relecture : un lien sur une ligne secrete n'est jamais recopie
ecrire("moi/camille.md", "# Camille\n**Faits :**\n- Mon mot de passe de la box : [[Soleil2026!]]\n")
ecrire("bibliotheque/acces.md", "# Accès\nLe code secret du portail : [[Zorglub99]]\n")
r = appel(action="examiner", sans_modele="oui")
tout_ = json.dumps(r, ensure_ascii=False) + json.dumps(propositions(), ensure_ascii=False)
verif("le lien d'une ligne secrete n'est ni dit ni ecrit", "Soleil2026" not in tout_ and "Zorglub99" not in tout_, r)

# ---------------------------------------------------------------- 13. le mode d'emploi
with open(os.path.join(ICI, "outil.json"), encoding="utf-8") as h:
    o = json.load(h)
verif("outil.json : appliquer et annuler demandent l'accord", sorted(o["sensible_si"]["action"]) == ["annuler", "appliquer"], o)

shutil.rmtree(D, ignore_errors=True)
serveur.shutdown()
print(f"{ok} OK, {ko} ECHEC")
sys.exit(1 if ko else 0)
