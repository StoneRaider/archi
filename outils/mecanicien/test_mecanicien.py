"""Tests du mecanicien et de son moteur de recettes, avec un faux modele et un faux Internet. Aucun acces au reseau."""
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import contextlib

ICI = os.path.dirname(os.path.abspath(__file__))
D = tempfile.mkdtemp(prefix="mecanicien_")
os.environ.update(ARCHI_BASE=D, ARCHI_MECANICIEN_SUR_PLACE="1", ARCHI_UTILISATEUR="Camille", ARCHI_LM_URL="http://127.0.0.1:9/v1")
sys.path.insert(0, ICI)
import recette as moteur  # noqa: E402
import mecanicien as meca  # noqa: E402

ok = ko = 0
socket_vrai = socket.getaddrinfo


def interdit(*a, **k):
    raise AssertionError("acces reseau pendant les tests")


socket.getaddrinfo = interdit
moteur.OUVREUR.open = interdit


def verif(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
    else:
        ko += 1
        print("ECHEC :", nom, str(detail)[:400])


def silence(f, *a):
    with contextlib.redirect_stdout(io.StringIO()):
        return f(*a)


# ---------------------------------------------------------------- 1. le moteur : la calculatrice
calc = lambda e, v=None: moteur.calculer(e, v or {})
verif("calcul simple", calc("2 + 3 * 4") == 14)
verif("calcul avec un nom", calc("c * 9 / 5 + 32", {"c": 100}) == 212)
verif("calcul avec un nombre ecrit en texte (virgule)", calc("x * 2", {"x": "1,5"}) == 3.0)
verif("fonctions permises", calc("round(sqrt(2), 2)") == 1.41 and calc("max(1, 5, 3)") == 5)
for mauvais in ("__import__('os')", "x.real", "'a' * 3", "[1, 2]", "lambda: 1", "open('f')", "x if x else 1", "(1).bit_length()",
                "a[0]", "round(1, ndigits=2)", "pi()", "True + 1", "{1: 2}"):
    try:
        moteur.verifier_calcul(mauvais, {"x", "a"})
        verif("calcul refuse : " + mauvais, False)
    except moteur.Erreur:
        verif("calcul refuse : " + mauvais, True)
for nom, e, v in (("division par zero", "1 / x", {"x": 0}), ("puissance geante", "10 ** 1000", {}), ("pas un nombre", "x + 1", {"x": "abc"})):
    try:
        calc(e, v)
        verif("calcul qui n'aboutit pas : " + nom, False)
    except moteur.Erreur:
        verif("calcul qui n'aboutit pas : " + nom, True)

# ---------------------------------------------------------------- 2. le moteur : relire une recette
BONNE = {"nom": "meteo_ville", "titre": "Météo d'une ville", "quoi": "Donne la température d'une ville.", "mode_d_emploi": "ville = le nom.",
         "parametres": [{"nom": "ville", "description": "la ville", "type": "texte"}],
         "hotes": ["geo.exemple.org", "meteo.exemple.org"],
         "etapes": [{"type": "api", "url": "https://geo.exemple.org/search?name={ville}", "garder": {"lat": "results.0.latitude", "lieu": "results.0.name"},
                     "si_vide": "Je ne trouve pas {ville}."},
                    {"type": "api", "url": "https://meteo.exemple.org/v1?lat={lat}", "garder": {"temp": "current.t"}},
                    {"type": "calcul", "garder": {"f": "temp * 9 / 5 + 32", "f2": "round(f)"}}],
         "phrase": "À {lieu}, il fait {temp:1} °C ({f2} F).",
         "essais": [{"parametres": {"ville": "Lyon"}, "doit_contenir": "Lyon"}]}
verif("une bonne recette passe", moteur.verifier_recette(BONNE) == [], moteur.verifier_recette(BONNE))


def avec(**changes):
    r = json.loads(json.dumps(BONNE))
    for k, v in changes.items():
        if k.startswith("e0_"):
            r["etapes"][0][k[3:]] = v
        else:
            r[k] = v
    return moteur.verifier_recette(r)


verif("http refuse", avec(e0_url="http://geo.exemple.org/search?name={ville}"))
verif("site non declare refuse", avec(e0_url="https://autre.exemple.org/search?name={ville}"))
verif("nom de site qui change refuse", avec(e0_url="https://{ville}.exemple.org/x", hotes=["x.exemple.org", "meteo.exemple.org"]))
verif("adresse IP refusee", avec(hotes=["127.0.0.1", "meteo.exemple.org"], e0_url="https://127.0.0.1/x"))
verif("site local refuse", avec(hotes=["nas.local", "meteo.exemple.org"], e0_url="https://nas.local/x"))
verif("site sans point refuse", avec(hotes=["localhost", "meteo.exemple.org"], e0_url="https://localhost/x"))
verif("identifiants dans le lien refuses", avec(hotes=["exemple.org", "meteo.exemple.org"], e0_url="https://moi:secret@exemple.org/x"))
verif("le meme lien sans identifiants passe", not avec(hotes=["exemple.org", "meteo.exemple.org"], e0_url="https://exemple.org/x"), avec(hotes=["exemple.org", "meteo.exemple.org"], e0_url="https://exemple.org/x"))
verif("autre port refuse", avec(e0_url="https://geo.exemple.org:8080/x"))
verif("trou inconnu dans un lien refuse", avec(e0_url="https://geo.exemple.org/search?name={pays}"))
verif("trou inconnu dans la phrase refuse", avec(phrase="Il fait {humidite}."))
verif("chemin bizarre refuse", avec(e0_garder={"lat": "results[0]"}))
verif("trop de sites refuse", avec(hotes=["a.exemple.org", "b.exemple.org", "c.exemple.org", "d.exemple.org"]))
verif("nom d'outil invalide refuse", avec(nom="Meteo Ville!"))
verif("type d'etape inconnu refuse", avec(etapes=[{"type": "programme", "garder": {"x": "1"}}]))

# ---------------------------------------------------------------- 3. le moteur : suivre une recette (faux Internet)
PAGES = {"https://geo.exemple.org/search?name=Saint%20%C3%89tienne": {"results": [{"latitude": 45.43, "name": "Saint-Étienne"}]},
         "https://meteo.exemple.org/v1?lat=45.43": {"current": {"t": 12.34}},
         "https://geo.exemple.org/search?name=Nullepart": {"results": []}}
VUS = []


def faux_site(url):
    VUS.append(url)
    if url not in PAGES:
        raise moteur.Erreur("le site répond 404")
    return json.dumps(PAGES[url]).encode("utf-8")


r = moteur.executer(BONNE, {"ville": "Saint Étienne"}, faux_site)
verif("recette suivie : la phrase est remplie", r["ok"] and r["phrase_pour_utilisateur"] == "À Saint-Étienne, il fait 12,3 °C (54 F).", r)
verif("le parametre est encode dans le lien", VUS and VUS[0].endswith("Saint%20%C3%89tienne"), VUS)
r = moteur.executer(BONNE, {"ville": "Nullepart"}, faux_site)
verif("reponse vide : la phrase si_vide", r["ok"] is False and r["phrase_pour_utilisateur"] == "Je ne trouve pas Nullepart.", r)
r = moteur.executer(BONNE, {}, faux_site)
verif("parametre manquant : il le dit", r["ok"] is False and "ville" in r["phrase_pour_utilisateur"], r)
r = moteur.executer(BONNE, {"ville": "Paris & co/../x?y=1"}, faux_site)
verif("un parametre ne peut pas changer le lien", VUS[-1].startswith("https://geo.exemple.org/search?name=Paris%20%26%20co%2F..%2Fx%3Fy%3D1"), VUS[-1])
casse = dict(BONNE, hotes=["geo.exemple.org"])
r = moteur.executer(casse, {"ville": "Lyon"}, faux_site)
verif("une recette abimee n'est pas suivie", r["ok"] is False and "refusée" in r["phrase_pour_utilisateur"] and len(VUS) == 4, (r, VUS))
verif("le moteur ne leve jamais d'exception", moteur.executer(None, None)["ok"] is False)
try:
    moteur.SansRedirection().redirect_request(None, None, 302, "", {}, "https://ailleurs.org")
    verif("redirection refusee", False)
except moteur.Erreur:
    verif("redirection refusee", True)
socket.getaddrinfo = lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
try:
    moteur.lire_api("https://piege.exemple.org/x", ["piege.exemple.org"])
    verif("un site qui pointe vers le PC est refuse", False)
except moteur.Erreur as x:
    verif("un site qui pointe vers le PC est refuse", "interne" in str(x), x)
socket.getaddrinfo = interdit
verif("extraire : valeur simple seulement", moteur.extraire({"a": {"b": [1, 2]}}, "a.b") is None and moteur.extraire({"a": [5]}, "a.0") == 5)

# le moteur en ligne de commande, comme outils_maison le lance (une recette de calcul, sans Internet)
outil = os.path.join(D, "essai_cli")
os.makedirs(outil)
shutil.copy(os.path.join(ICI, "recette.py"), outil)
with open(os.path.join(outil, "recette.json"), "w", encoding="utf-8") as h:
    json.dump({"nom": "pourboire", "titre": "Pourboire", "quoi": "Calcule un pourboire.", "mode_d_emploi": "montant en euros.",
               "parametres": [{"nom": "montant", "description": "l'addition", "type": "nombre"}], "hotes": [],
               "etapes": [{"type": "calcul", "garder": {"p": "montant * 0.1"}}], "phrase": "Laisse {p:2} € de pourboire."}, h)
with open(os.path.join(outil, "demande.json"), "w", encoding="utf-8") as h:
    json.dump({"montant": "42,50"}, h)
p = subprocess.run([sys.executable, os.path.join(outil, "recette.py"), "--fichier", os.path.join(outil, "demande.json")],
                   capture_output=True, cwd=outil, env=dict(PYTHONIOENCODING="utf-8", SYSTEMROOT=os.environ.get("SYSTEMROOT", "")))
try:
    sortie = json.loads(p.stdout.decode("utf-8").strip().splitlines()[-1])
except (ValueError, IndexError):
    sortie = {"brut": p.stdout, "err": p.stderr}
verif("le moteur en ligne de commande", sortie.get("ok") and sortie.get("phrase_pour_utilisateur") == "Laisse 4,25 € de pourboire.", sortie)

# ---------------------------------------------------------------- 4. le mecanicien : faux modele, faux Internet
REPONSES = []
DEMANDES = []


def faux_modele(corps):
    DEMANDES.append(corps)
    r = REPONSES.pop(0) if REPONSES else {"faisable": False, "pourquoi_pas": "plus de reponse"}
    return {"choices": [{"message": {"content": json.dumps(r, ensure_ascii=False)}}]}


meca.APPEL = faux_modele
PAGES["https://api.wheretheiss.at/v1/satellites/25544"] = {"latitude": 12.5, "longitude": -40.25, "velocity": 27600.4}
meca.OUVRIR = faux_site
ISS = {"faisable": True, "pourquoi_pas": "", "nom": "Position ISS", "titre": "Position de la station spatiale",
       "quoi": "Dit où est la station spatiale.", "mode_d_emploi": "Sans paramètre.", "parametres": [],
       "hotes": ["https://api.wheretheiss.at/"],
       "etapes": [{"type": "api", "url": "https://api.wheretheiss.at/v1/satellites/25544",
                   "garder": [{"nom": "lat", "valeur": "latitude"}, {"nom": "lon", "valeur": "longitude"}], "si_vide": "Je n'ai pas la position."}],
       "phrase": "La station spatiale est au-dessus de {lat:1}, {lon:1}.",
       "essais": [{"parametres": [], "doit_contenir": "station spatiale"}]}
os.makedirs(os.path.join(D, "outils", "planificateur"))
shutil.copy(os.path.join(ICI, "..", "planificateur", "planificateur.py"), os.path.join(D, "outils", "planificateur"))
with open(os.path.join(D, "outils", "registre.json"), "w", encoding="utf-8") as h:
    json.dump({"memoire": {"nom": "memoire", "script": "memoire.py"}}, h)


def annonces():
    try:
        with open(os.path.join(D, "planificateur", "annonces.json"), encoding="utf-8") as h:
            return [a["texte"] for a in json.load(h)]
    except OSError:
        return []


def demande(**d):
    return silence(meca.traiter, d)


r = demande()
verif("atelier vide", r["ok"] and "vide" in r["phrase_pour_utilisateur"], r)
r = demande(action="idee", texte="savoir où est la station spatiale")
verif("une idee est notee, sans rien fabriquer", r["ok"] and r["numero"] == 1 and not DEMANDES, r)
r = demande(action="vas-y", numero=1)
verif("un synonyme ne fait jamais construire", r["ok"] is False and not DEMANDES, r)
# premiere recette fausse (site non declare), puis corrigee : le mecanicien recommence avec le probleme
FAUSSE = dict(ISS, hotes=[])
REPONSES[:] = [FAUSSE, ISS]
r = demande(action="construire", numero=1)
etat = meca.lire_etat()
i = etat["idees"][0]
verif("construire : l'outil est teste", r["ok"] and i["etat"] == "teste" and i["nom"] == "position_iss", i)
verif("une recette refusee est renvoyee au modele avec le probleme", len(DEMANDES) == 2 and "problèmes" in DEMANDES[1]["messages"][-1]["content"],
      DEMANDES[-1]["messages"][-1] if DEMANDES else None)
verif("le schema de reponse est impose au modele", DEMANDES[0].get("response_format", {}).get("type") == "json_schema")
verif("les essais sont gardes pour la page", i["essais"] and i["essais"][0]["reussi"] and "12,5" in i["essais"][0]["phrase"], i.get("essais"))
verif("l'utilisateur est prevenu que c'est pret", any("prêt et testé" in a and "valide la 1" in a and a.startswith("Camille,") for a in annonces()), annonces())
verif("rien n'est installe avant le valide", "position_iss" not in json.load(open(os.path.join(D, "outils", "registre.json"), encoding="utf-8")))
r = demande(action="voir", numero=1)
verif("voir : les sites lus et les essais", r["ok"] and "api.wheretheiss.at" in r["phrase_pour_utilisateur"], r)
r = demande(action="construire", numero=1)
verif("construire deux fois la meme : refuse", r["ok"] is False, r)

r = demande(action="valider", numero=1)
reg = json.load(open(os.path.join(D, "outils", "registre.json"), encoding="utf-8"))
verif("valider : l'outil entre au registre", r["ok"] and "position_iss" in reg and reg["position_iss"]["script"] == "recette.py", r)
verif("le registre d'avant est garde", [f for f in os.listdir(os.path.join(D, "atelier")) if f.startswith("registre_avant_")])
verif("l'outil installe a son moteur et sa recette", sorted(os.listdir(os.path.join(D, "outils", "position_iss"))) == ["recette.json", "recette.py"])
verif("l'outil installe porte la marque du mecanicien", reg["position_iss"]["mecanicien"]["hotes"] == ["api.wheretheiss.at"]
      and "MODE D EMPLOI" in reg["position_iss"]["description"], reg["position_iss"])
r = demande(action="valider", numero=1)
verif("valider deux fois : refuse", r["ok"] is False, r)

# un nom deja pris : le mecanicien en choisit un autre, il n'ecrase jamais
REPONSES[:] = [dict(ISS, nom="memoire")]
demande(action="construire", texte="un autre outil de position de la station")
i2 = meca.lire_etat()["idees"][-1]
verif("un nom deja pris n'est jamais ecrase", i2["etat"] == "teste" and i2["nom"] == "memoire_2", i2)

# pas faisable : il le dit
REPONSES[:] = [{"faisable": False, "pourquoi_pas": "Il faut un compte bancaire.", "nom": "", "titre": "", "quoi": "", "mode_d_emploi": "",
                "parametres": [], "hotes": [], "etapes": [], "phrase": "", "essais": []}]
demande(action="construire", texte="regarder mon compte en banque")
i3 = meca.lire_etat()["idees"][-1]
verif("pas faisable : l'idee le dit, sans rien fabriquer", i3["etat"] == "impossible" and "compte" in i3["message"], i3)

# toujours rate : trois essais au plus, puis « rate »
DEMANDES.clear()
REPONSES[:] = [FAUSSE, FAUSSE, FAUSSE, FAUSSE]
demande(action="construire", texte="encore la station mais mal")
i4 = meca.lire_etat()["idees"][-1]
verif("trois tentatives au plus, puis rate", i4["etat"] == "rate" and len(DEMANDES) == 3, (i4, len(DEMANDES)))

# modele eteint
meca.APPEL = None
demande(action="construire", texte="une idee quand le modele dort")
i5 = meca.lire_etat()["idees"][-1]
verif("modele eteint : rate, avec la raison", i5["etat"] == "rate" and "modèle" in i5["message"], i5)
meca.APPEL = faux_modele

# retirer : seulement un outil du mecanicien, et rien n'est efface
r = demande(action="retirer", nom="memoire")
verif("retirer un outil d'origine : refuse", r["ok"] is False and "memoire" in json.load(open(os.path.join(D, "outils", "registre.json"), encoding="utf-8")), r)
r = demande(action="retirer", nom="position_iss")
reg = json.load(open(os.path.join(D, "outils", "registre.json"), encoding="utf-8"))
verif("retirer : l'outil sort du registre", r["ok"] and "position_iss" not in reg, r)
verif("retirer : son dossier est garde de cote", not os.path.exists(os.path.join(D, "outils", "position_iss"))
      and os.listdir(os.path.join(D, "atelier", "_retires")))
r = demande(action="abandonner", numero=2)
verif("abandonner une idee", r["ok"] and meca.lire_etat()["idees"][1]["etat"] == "abandonne", r)
r = demande(action="supprimer")
verif("action inconnue refusee", r["ok"] is False and "inconnue" in r["phrase_pour_utilisateur"], r)

# une fabrication interrompue ne reste pas « en construction » pour toujours
etat = meca.lire_etat()
etat["idees"].append({"n": 99, "titre": "coupee", "quoi": "x", "etat": "construction", "debut": "2026-01-01T10:00:00"})
meca.ecrire_json(meca.atelier("atelier.json"), etat)
demande(action="etat")
verif("une fabrication interrompue passe « ratee »", next(x for x in meca.lire_etat()["idees"] if x["n"] == 99)["etat"] == "rate")

# ---------------------------------------------------------------- 5. la tournee : des idees a partir de ce qui a rate
DEMANDES.clear()
avant = len(annonces())
r = silence(meca.tournee)
verif("tournee sans rien de rate : pas d'appel au modele, pas d'annonce",
      r["ok"] and r["idees"] == [] and not DEMANDES and len(annonces()) == avant, r)
with open(meca.atelier("rates.jsonl"), "w", encoding="utf-8") as h:
    h.write(json.dumps({"quand": 1000, "type": "inconnu", "outil": "meteo"}) + "\n")
    h.write(json.dumps({"quand": 1001, "type": "inconnu", "outil": "meteo"}) + "\n")
    h.write("ligne abimee\n")
DEMANDES.clear()
REPONSES[:] = [{"idees": [{"titre": "Météo d'une ville", "quoi": "Donne la météo d'une ville avec Open-Meteo."}]}]
avant = len(annonces())
r = silence(meca.tournee)
verif("tournee : une idee nee de ce qui a rate", r["ok"] and len(r["idees"]) == 1 and "meteo" in DEMANDES[0]["messages"][-1]["content"], r)
verif("tournee : l'utilisateur est prevenu", len(annonces()) == avant + 1 and "construis la" in annonces()[-1], annonces()[-1:])
DEMANDES.clear()
r = silence(meca.tournee)
verif("tournee suivante : ce qui a deja ete lu ne revient pas", not DEMANDES and r["idees"] == [], r)
verif("aucun verrou ne traine", not os.path.exists(meca.atelier(".verrou_atelier")))

with open(os.path.join(ICI, "outil.json"), encoding="utf-8") as h:
    o = json.load(h)
verif("outil.json : construire, valider et retirer demandent l'accord", sorted(o["sensible_si"]["action"]) == ["construire", "retirer", "valider"])

socket.getaddrinfo = socket_vrai
shutil.rmtree(D, ignore_errors=True)
print(f"{ok} OK, {ko} ECHEC")
sys.exit(1 if ko else 0)
