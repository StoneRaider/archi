# recette.py - le MOTEUR des outils fabriques par le mecanicien d'Archi (10/11/2026).
# Le mecanicien n'ecrit PAS de programme : il ecrit une RECETTE (recette.json), que ce moteur fixe et teste suit pas a pas.
# Aucun code invente par le modele n'est jamais execute.
#   python recette.py --fichier demande.json     (appele par outils_maison, dans le dossier de l'outil installe)
# Une recette :
#   {"nom", "titre", "quoi", "mode_d_emploi",
#    "parametres": [{"nom", "description", "type": "texte"|"nombre", "exemple"}],      au plus 4
#    "hotes": ["api.exemple.org"],                                                      au plus 3 sites publics, sans cle
#    "etapes": [                                                                        au plus 4, dans l'ordre
#       {"type": "api", "url": "https://api.exemple.org/v1?q={ville}", "garder": {"temp": "current.temperature"},
#        "si_vide": "Je ne trouve pas {ville}."},
#       {"type": "calcul", "garder": {"f": "temp * 9 / 5 + 32"}}],
#    "phrase": "A {ville}, il fait {temp:1} degres ({f:0} F).",
#    "essais": [{"parametres": {"ville": "Lyon"}, "doit_contenir": "Lyon"}]}
# Regles dures (dans ce moteur) : https seulement, vers les sites declares, jamais une adresse interne ; 10 s et 1 Mo par
# appel, pas de redirection ; un calcul n'accepte que des nombres, + - * / // % **, des parentheses et quelques fonctions
# (round, abs, min, max, sqrt...) ; la phrase ne fait que remplacer des {noms}. Le moteur ne lit ni n'ecrit aucun fichier
# autre que sa recette, et ne lit aucun reglage d'Archi.
import argparse
import ast
import http.client
import ipaddress
import json
import math
import os
import re
import socket
import ssl
import sys
import threading
import time
import unicodedata
import urllib.parse

NOM = re.compile(r"^[a-z][a-z0-9_]{2,30}$")
NOM_VALEUR = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
HOTE = re.compile(r"^(?=.{4,80}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")
HOTES_INTERDITS = (".local", ".lan", ".home", ".internal", ".localhost", ".intranet", ".corp", ".arpa")
CHEMIN = re.compile(r"^[A-Za-z0-9_\-]{1,40}(\.[A-Za-z0-9_\-]{1,40}){0,7}$")
TROU = re.compile(r"\{([a-z][a-z0-9_]{0,30})(?::([0-4]))?\}")
MAX_PARAMS, MAX_HOTES, MAX_ETAPES, MAX_GARDER = 4, 3, 4, 6
MAX_OCTETS = 1000000
DELAI = 10
FONCTIONS = {"round": round, "abs": abs, "min": min, "max": max, "sqrt": math.sqrt, "floor": math.floor, "ceil": math.ceil,
             "log": math.log, "log10": math.log10, "exp": math.exp, "sin": math.sin, "cos": math.cos, "tan": math.tan,
             "radians": math.radians, "degrees": math.degrees, "pi": None}
OPERATEURS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
              ast.Div: lambda a, b: a / b, ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b}


class Erreur(Exception):
    pass


def plat(t):
    t = unicodedata.normalize("NFD", str(t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------- les calculs : une petite calculatrice, rien de plus
def verifier_calcul(expr, connus):
    """leve Erreur si l'expression sort de la calculatrice ; rend les noms qu'elle utilise"""
    if not isinstance(expr, str) or not expr.strip() or len(expr) > 200:
        raise Erreur("calcul vide ou trop long")
    try:
        arbre = ast.parse(expr, mode="eval")
    except SyntaxError:
        raise Erreur("calcul illisible : %s" % expr[:60])
    noms = set()
    for n in ast.walk(arbre):
        if isinstance(n, (ast.Expression, ast.Load)) or type(n) in OPERATEURS or isinstance(n, (ast.Pow, ast.USub, ast.UAdd)):
            continue
        if isinstance(n, ast.BinOp) or isinstance(n, ast.UnaryOp):
            continue
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            continue
        if isinstance(n, ast.Name):
            if n.id not in FONCTIONS and n.id not in connus:
                raise Erreur("le calcul utilise « %s », qui n'existe pas encore" % n.id[:30])
            noms.add(n.id)
            continue
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FONCTIONS and FONCTIONS[n.func.id] and not n.keywords:
            continue
        raise Erreur("le calcul contient quelque chose qui n'est pas permis (%s)" % type(n).__name__)
    return noms


GRAND = 1e300                    # au-dela, un calcul enchaine pourrait remplir la memoire (entiers sans limite)


def borne(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) > GRAND:
        raise Erreur("nombre trop grand")
    return v


def calculer(expr, valeurs):
    def ev(n):
        return borne(ev_brut(n))

    def ev_brut(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name):
            if n.id == "pi":
                return math.pi
            v = valeurs.get(n.id)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                v = nombre(v)
            if v is None:
                raise Erreur("« %s » n'est pas un nombre" % n.id)
            return v
        if isinstance(n, ast.UnaryOp):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow):
                if abs(b) > 100 or abs(a) > 1e6:
                    raise Erreur("puissance trop grande")
                return a ** b
            return OPERATEURS[type(n.op)](a, b)
        if isinstance(n, ast.Call):
            args = [ev(a) for a in n.args]
            if n.func.id == "round" and len(args) == 2:
                if abs(args[1]) > 15:           # round(entier, -1e9) calculerait 10**(10**9) : sans fin
                    raise Erreur("arrondi trop grand")
                args = [float(args[0]), int(args[1])]
            return FONCTIONS[n.func.id](*args)
        raise Erreur("calcul refusé")
    try:
        r = ev(ast.parse(expr, mode="eval"))
    except (ZeroDivisionError, ValueError, OverflowError, TypeError) as e:
        raise Erreur("le calcul n'a pas abouti (%s)" % type(e).__name__)
    if isinstance(r, complex) or (isinstance(r, float) and (math.isnan(r) or math.isinf(r))):
        raise Erreur("le calcul n'a pas abouti")
    return r


ALPHABETS = ("LATIN ", "GREEK ", "CYRILLIC ")


def lettre_permise(c):
    """un chiffre, ou une vraie lettre latine, grecque ou cyrillique (Łódź, Plzeň, Москва, Đà Nẵng). Pas de sosies de
    ponctuation : ǀ ǃ (lettres « Lo »), ː (« Lm »), pleine chasse et lettres mathematiques n'ont pas ces noms."""
    if "0" <= c <= "9":
        return True
    return unicodedata.category(c) in ("Lu", "Ll") and unicodedata.name(c, "").startswith(ALPHABETS)


def propre(v):
    """un texte lu sur un site : court, sur une ligne, sans signes de commande. Il finit dans une phrase que l'agent
    repete : il ne doit pas pouvoir y glisser une consigne bien formee (a=b, {...}, [[...]], retour a la ligne)."""
    s = unicodedata.normalize("NFC", re.sub(r"\s+", " ", str(v)))     # « e » + accent separe -> « é »
    s = "".join(c for c in s if lettre_permise(c) or c in " .,'’-()/°%+")
    return re.sub(r"\s+", " ", s).strip()[:80]


def nombre(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        s = str(v).strip().replace(" ", "").replace(" ", "").replace(",", ".")
        return float(s) if s else None
    except ValueError:
        return None


# ---------------------------------------------------------------- les trous {nom} des liens et de la phrase
def trous(texte):
    return [m.group(1) for m in TROU.finditer(str(texte or ""))]


def remplir(texte, valeurs, pour_lien=False):
    def un(m):
        v = valeurs.get(m.group(1), "")
        if m.group(2) is not None and nombre(v) is not None:
            n = int(m.group(2))
            v = ("%." + str(n) + "f") % nombre(v)
            v = v if pour_lien else v.replace(".", ",")
        elif isinstance(v, float) and v.is_integer():
            v = str(int(v))
        elif isinstance(v, float) and not pour_lien:
            v = ("%.2f" % v).rstrip("0").rstrip(".").replace(".", ",")
        v = str(v)
        return urllib.parse.quote(v, safe="") if pour_lien else v[:200]
    return TROU.sub(un, str(texte))


def extraire(objet, chemin):
    for morceau in chemin.split("."):
        if isinstance(objet, list) and re.fullmatch(r"-?\d{1,4}", morceau):
            i = int(morceau)
            objet = objet[i] if -len(objet) <= i < len(objet) else None
        elif isinstance(objet, dict):
            objet = objet.get(morceau)
        else:
            return None
        if objet is None:
            return None
    if isinstance(objet, (dict, list)):
        return None          # on ne garde que des valeurs simples
    return objet


# ---------------------------------------------------------------- relire une recette AVANT de la suivre
def verifier_recette(r):
    """la liste des problemes (vide = la recette est bonne). Appele par le mecanicien, et a chaque lancement."""
    P = []
    if not isinstance(r, dict):
        return ["la recette n'est pas un objet"]
    if not NOM.match(str(r.get("nom") or "")):
        P.append("nom invalide (minuscules, chiffres, _ ; 3 à 31 caractères)")
    for k, n in (("titre", 60), ("quoi", 200), ("mode_d_emploi", 500), ("phrase", 400)):
        if not isinstance(r.get(k), str) or not r[k].strip() or len(r[k]) > n:
            P.append("%s manquant ou trop long" % k)
    params = r.get("parametres") if isinstance(r.get("parametres"), list) else None
    if params is None or len(params) > MAX_PARAMS:
        P.append("parametres : une liste de %d au plus" % MAX_PARAMS)
        params = []
    connus = set()
    for p in params:
        if not isinstance(p, dict) or not NOM_VALEUR.match(str(p.get("nom") or "")) or p.get("type", "texte") not in ("texte", "nombre"):
            P.append("paramètre invalide : %s" % str(p)[:60])
            continue
        connus.add(p["nom"])
    hotes = r.get("hotes") if isinstance(r.get("hotes"), list) else None
    if hotes is None or len(hotes) > MAX_HOTES:
        P.append("hotes : une liste de %d sites au plus" % MAX_HOTES)
        hotes = []
    for h in hotes:
        h = str(h)
        if not HOTE.match(h) or h.endswith(HOTES_INTERDITS) or re.fullmatch(r"[\d.]+", h):
            P.append("site refusé : %s" % h[:60])
    etapes = r.get("etapes") if isinstance(r.get("etapes"), list) else None
    if not etapes or len(etapes) > MAX_ETAPES:
        P.append("etapes : de 1 à %d" % MAX_ETAPES)
        etapes = []
    for i, e in enumerate(etapes):
        if not isinstance(e, dict) or e.get("type") not in ("api", "calcul"):
            P.append("étape %d : type api ou calcul" % (i + 1))
            continue
        garder = e.get("garder")
        if not isinstance(garder, dict) or not garder or len(garder) > MAX_GARDER:
            P.append("étape %d : garder doit nommer 1 à %d valeurs" % (i + 1, MAX_GARDER))
            continue
        if e["type"] == "api":
            url = str(e.get("url") or "")
            u = urllib.parse.urlsplit(TROU.sub("x", url))
            try:
                port = u.port
            except ValueError:
                port = -1
            if u.scheme != "https" or (u.hostname or "") not in hotes or u.username or u.password or port not in (None, 443) or len(url) > 400:
                P.append("étape %d : le lien doit être en https vers un site déclaré" % (i + 1))
            if "{" in (u.hostname or "") or TROU.search(url.split("?")[0].split("//", 1)[-1].split("/")[0]):
                P.append("étape %d : le nom du site ne peut pas changer" % (i + 1))
            for t in trous(url):
                if t not in connus:
                    P.append("étape %d : {%s} n'existe pas encore" % (i + 1, t))
            for k, ch in garder.items():
                if not NOM_VALEUR.match(str(k)) or not CHEMIN.match(str(ch)):
                    P.append("étape %d : garder %s invalide" % (i + 1, str(k)[:30]))
        else:
            for k, expr in garder.items():
                if not NOM_VALEUR.match(str(k)):
                    P.append("étape %d : nom %s invalide" % (i + 1, str(k)[:30]))
                    continue
                try:
                    verifier_calcul(expr, connus)
                except Erreur as x:
                    P.append("étape %d : %s" % (i + 1, x))
                connus.add(k)            # un calcul peut se servir du precedent
        if "si_vide" in e and (not isinstance(e["si_vide"], str) or len(e["si_vide"]) > 200):
            P.append("étape %d : si_vide trop long" % (i + 1))
        connus.update(k for k in garder if NOM_VALEUR.match(str(k)))
    for t in trous(r.get("phrase")):
        if t not in connus:
            P.append("la phrase utilise {%s}, qui n'existe pas" % t)
    if hotes and not any(isinstance(e, dict) and e.get("type") == "api" for e in etapes):
        P.append("des sites déclarés, mais aucune étape ne les utilise")
    return P


# ---------------------------------------------------------------- suivre la recette
class ConnexionVerifiee(http.client.HTTPSConnection):
    """https vers l'adresse DEJA verifiee : pas de seconde resolution du nom (qui pourrait viser le reseau local).
    Le certificat reste verifie pour le nom du site. Pas de proxy, pas de redirection (http.client n'en suit aucune)."""

    def __init__(self, hote, ip, delai):
        super().__init__(hote, 443, timeout=delai, context=ssl.create_default_context())
        self._ip = ip
        self._sockets = []

    def connect(self):
        s = socket.create_connection((self._ip, 443), self.timeout)
        self._sockets.append(s)
        # la poignee de main se fait apres : la minuterie peut la couper aussi
        try:
            t = self._context.wrap_socket(s, server_hostname=self.host, do_handshake_on_connect=False)
        except BaseException:
            s.close()
            raise
        self._sockets.append(t)
        try:
            t.do_handshake()
        except BaseException:
            t.close()                   # rien ne reste ouvert jusqu'au ramasse-miettes
            raise
        self.sock = t

    def couper(self):
        """appele par la minuterie : coupe net, meme au milieu d'une lecture"""
        for s in self._sockets:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


NAT64 = ipaddress.ip_network("64:ff9b::/96")
NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")


def adresse_permise(ip):
    """une adresse publique ; une IPv4 cachee dans une IPv6 (::ffff:a.b.c.d, ::a.b.c.d, NAT64, 6to4, Teredo)
    est jugee comme une IPv4"""
    a = ipaddress.ip_address(ip)
    if not a.is_global:
        return False
    if a.version == 6:
        if a in NAT64_LOCAL:
            return False
        cachees = [a.ipv4_mapped, a.sixtofour]
        if a in NAT64 or (int(a) >> 32) == 0:
            cachees.append(ipaddress.IPv4Address(int(a) & 0xFFFFFFFF))
        if a.teredo:
            cachees.append(a.teredo[1])
        if any(v is not None and not v.is_global for v in cachees):
            return False
    return True


def lire_reponse(rep, regler_delai, debut):
    """lit par morceaux, avec un delai TOTAL (un site qui envoie un octet toutes les 9 s est coupe a DELAI)"""
    morceaux, total = [], 0
    while True:
        reste = DELAI - (time.monotonic() - debut)
        if reste <= 0:
            raise Erreur("le site est trop lent")
        regler_delai(reste)
        m = rep.read1(65536)
        if not m:
            return b"".join(morceaux)
        total += len(m)
        if total > MAX_OCTETS:
            raise Erreur("réponse trop grosse")
        morceaux.append(m)


def lire_site(u, ips, fabrique, debut):
    """une adresse verifiee apres l'autre ; une minuterie coupe tout a DELAI (connexion, poignee de main, en-tetes, corps)"""
    courante, coupe = [None], []

    def couper():
        coupe.append(1)
        c = courante[0]
        if c is not None and hasattr(c, "couper"):
            c.couper()

    minuterie = threading.Timer(max(0.05, DELAI - (time.monotonic() - debut)), couper)
    minuterie.daemon = True
    minuterie.start()
    try:
        c = None
        for ip in ips:                      # la suivante si la connexion echoue (une IPv6 sans route, par exemple)
            reste = DELAI - (time.monotonic() - debut)
            if reste <= 0 or coupe:
                raise Erreur("le site est trop lent")
            c = fabrique(u.hostname, ip, reste)
            courante[0] = c
            try:
                c.connect()
                break
            except (OSError, ValueError, AttributeError):    # coupee par la minuterie en pleine poignee de main : ssl
                # peut lever ValueError (socket fermee) ou AttributeError (objet ssl pas encore pret)
                c.close()
                c = None
                if coupe:
                    raise Erreur("le site est trop lent")
        if c is None:
            raise Erreur("site injoignable (%s)" % u.hostname)
        try:
            c.request("GET", (u.path or "/") + ("?" + u.query if u.query else ""),
                      headers={"User-Agent": "Archi-mecanicien/1.0", "Accept": "application/json"})
            s = c.sock                      # AVANT getresponse : http.client la met a None si le site ferme la connexion
            rep = c.getresponse()
            if 300 <= rep.status < 400:
                raise Erreur("le site renvoie ailleurs : refusé")
            if rep.status != 200:
                raise Erreur("le site répond %d" % rep.status)
            brut = lire_reponse(rep, s.settimeout if s is not None else (lambda x: None), debut)
            if coupe:
                # coupee par la minuterie en plein corps : la lecture rend 0 octet sans erreur, ce n'est pas la fin
                raise Erreur("le site est trop lent")
            reste = getattr(rep, "length", None)
            if isinstance(reste, int) and not isinstance(reste, bool) and reste > 0:
                raise Erreur("le site a coupé avant la fin de sa réponse")    # moins d'octets qu'annonce
            return brut
        except Erreur:
            raise
        except (OSError, http.client.HTTPException, ValueError, AttributeError) as e:    # AttributeError : ssl coupe
            # par la minuterie au milieu d'une lecture
            raise Erreur("le site est trop lent" if coupe else "site injoignable (%s)" % type(e).__name__)
        finally:
            c.close()
    finally:
        minuterie.cancel()


def lire_api(url, hotes, ouvrir=None, connexion=None):
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or (u.hostname or "") not in hotes or u.port not in (None, 443) or u.username or u.password:
        raise Erreur("site non déclaré")
    if ouvrir is None:
        debut = time.monotonic()
        try:
            infos = socket.getaddrinfo(u.hostname, 443, type=socket.SOCK_STREAM)
        except OSError:
            raise Erreur("site injoignable (%s)" % u.hostname)
        ips = list(dict.fromkeys(i[4][0].split("%")[0] for i in infos))
        if not ips:
            raise Erreur("site injoignable (%s)" % u.hostname)
        for ip in ips:
            if not adresse_permise(ip):
                raise Erreur("adresse interne refusée")
        brut = lire_site(u, ips[:4], connexion or ConnexionVerifiee, debut)
    else:
        brut = ouvrir(url)              # les tests : un faux site
    if len(brut) > MAX_OCTETS:
        raise Erreur("réponse trop grosse")
    try:
        return json.loads(brut.decode("utf-8", "replace"))
    except ValueError:
        raise Erreur("le site ne répond pas en JSON")


def executer(recette, demande, ouvrir=None):
    """rend {ok, phrase_pour_utilisateur} ; ne leve jamais d'exception"""
    try:
        P = verifier_recette(recette)
        if P:
            raise Erreur("recette refusée : " + P[0])
        valeurs = {}
        manque, noms_manquants = [], []
        for p in recette["parametres"]:
            v = demande.get(p["nom"]) if isinstance(demande, dict) else None
            v = "" if v is None else re.sub(r"\s+", " ", str(v)).strip()[:100]
            if not v:
                manque.append("%s (%s)" % (p["nom"], str(p.get("description") or "")[:80]))
                noms_manquants.append(p["nom"])
                continue
            if p.get("type") == "nombre":
                if nombre(v) is None:
                    # pas_un_nombre / manque : le lanceur redit la phrase lui-meme (des noms verifies, rien de lu sur un site)
                    return {"ok": False, "pas_un_nombre": [p["nom"]],
                            "phrase_pour_utilisateur": "Il me faut un nombre pour %s." % p["nom"]}
                v = nombre(v)
            valeurs[p["nom"]] = v
        if manque:
            return {"ok": False, "manque": noms_manquants, "phrase_pour_utilisateur": "Il me manque : %s." % ", ".join(manque)}
        for e in recette["etapes"]:
            if e["type"] == "api":
                rep = lire_api(remplir(e["url"], valeurs, pour_lien=True), recette["hotes"], ouvrir)
                for k, ch in e["garder"].items():
                    v = extraire(rep, ch)
                    if v is None:
                        return {"ok": False, "phrase_pour_utilisateur": remplir(e.get("si_vide") or "Je n'ai pas trouvé la réponse.", valeurs)}
                    valeurs[k] = v if isinstance(v, (int, float)) and not isinstance(v, bool) else propre(v)
            else:
                for k, expr in e["garder"].items():
                    valeurs[k] = calculer(expr, valeurs)
        return {"ok": True, "phrase_pour_utilisateur": remplir(recette["phrase"], valeurs)}
    except Erreur as x:
        return {"ok": False, "phrase_pour_utilisateur": "L'outil n'a pas pu répondre : %s." % x}
    except Exception as x:   # le moteur ne plante jamais devant l'utilisateur
        return {"ok": False, "phrase_pour_utilisateur": "L'outil n'a pas pu répondre (%s)." % type(x).__name__}


def main(recette_json=None):
    """recette_json : la recette d'un outil installe (son lanceur outil_recette.py passe la sienne : le moteur reste ici,
    en un seul exemplaire, et une correction du moteur vaut pour tous les outils deja installes)"""
    pa = argparse.ArgumentParser()
    pa.add_argument("--fichier")
    a = pa.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ici = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(recette_json or os.path.join(ici, "recette.json"), encoding="utf-8") as h:
            recette = json.load(h)
        demande = {}
        if a.fichier:
            with open(a.fichier, encoding="utf-8-sig") as h:
                demande = json.load(h)
        r = executer(recette, demande if isinstance(demande, dict) else {})
        if recette.get("hotes"):
            r["source"] = "lu sur : " + ", ".join(recette["hotes"])
    except (OSError, ValueError) as x:
        r = {"ok": False, "phrase_pour_utilisateur": "La recette de cet outil est illisible (%s)." % type(x).__name__}
    print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()
