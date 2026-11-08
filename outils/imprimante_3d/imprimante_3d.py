# imprimante_3d.py - outil maison d'Archi : piloter N'IMPORTE QUELLE imprimante 3D du reseau local.
# Trois familles : Klipper/Moonraker (Creality K1/K2, Voron, Sovol, Elegoo Neptune 4...), OctoPrint, PrusaLink.
#
#   python imprimante_3d.py --fichier demande.json
#   demande.json : {"action": "etat" | "fichiers" | "envoyer" | "lancer" | "pause" | "reprendre" | "annuler",
#                   "fichier": "piece.gcode" (envoyer : chemin local ; lancer : nom sur l'imprimante),
#                   "confirmer": "oui"}
# Repond UNE ligne JSON : {"ok", "phrase_pour_utilisateur", ...}
#
# Reglages (fichier .env) : ARCHI_IMPRIMANTE_TYPE = moonraker | octoprint | prusalink,
#   ARCHI_IMPRIMANTE_IP, ARCHI_IMPRIMANTE_PORT (facultatif), ARCHI_IMPRIMANTE_CLE (cle API OctoPrint / PrusaLink).
#
# GARDE-FOUS DANS LE CODE :
#   - imprimante du reseau LOCAL seulement (adresse privee) ;
#   - « lancer », « annuler » et « envoyer » : ESSAI A BLANC sans confirmer=oui (l'outil est aussi « sensible » :
#     il faut l'accord de l'utilisateur) ; « etat », « fichiers », « pause » et « reprendre » sont directs ;
#   - jamais d'ordre de chauffe ni de G-code libre : seulement les actions ci-dessus ;
#   - fichiers .gcode / .bgcode / .3mf de 200 Mo au plus ; la cle API n'est jamais affichee.
import argparse
import ipaddress
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

EXTENSIONS = (".gcode", ".bgcode", ".3mf", ".gco", ".g")
TAILLE_MAX = 200 * 1024 * 1024


class Erreur(Exception):
    pass


def repondre(ok, phrase, **extra):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(dict(ok=ok, phrase_pour_utilisateur=phrase, **extra), ensure_ascii=False))


def oui(v):
    return v is True or str(v or "").strip().lower() in {"oui", "true", "1", "yes"}


def reglages():
    t = (os.environ.get("ARCHI_IMPRIMANTE_TYPE") or "moonraker").strip().lower()
    if t not in ADAPTATEURS:
        raise Erreur("Type d'imprimante inconnu (ARCHI_IMPRIMANTE_TYPE) : moonraker, octoprint ou prusalink.")
    ip = (os.environ.get("ARCHI_IMPRIMANTE_IP") or "").strip()
    if not ip:
        raise Erreur("Je ne connais pas l'adresse de l'imprimante : mets ARCHI_IMPRIMANTE_IP dans le .env.")
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        raise Erreur("ARCHI_IMPRIMANTE_IP n'est pas une adresse valable (ex. 192.168.1.50).")
    if not a.is_private or a.is_loopback:
        raise Erreur("Je ne pilote qu'une imprimante du reseau local (adresse privee).")
    port = os.environ.get("ARCHI_IMPRIMANTE_PORT") or {"moonraker": "7125", "octoprint": "80", "prusalink": "80"}[t]
    return t, f"http://{ip}:{int(port)}", (os.environ.get("ARCHI_IMPRIMANTE_CLE") or "").strip()


def http(methode, url, cle_entete=None, cle=None, corps=None, type_corps=None, timeout=15):
    h = {"User-Agent": "Archi/1.0"}
    if cle_entete and cle:
        h[cle_entete] = cle
    if type_corps:
        h["Content-Type"] = type_corps
    req = urllib.request.Request(url, data=corps, headers=h, method=methode)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            brut = r.read()
            return json.loads(brut.decode("utf-8")) if brut[:1] in (b"{", b"[") else {}
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise Erreur("L'imprimante refuse la cle API (ARCHI_IMPRIMANTE_CLE dans le .env).")
        if e.code == 409:
            raise Erreur("L'imprimante refuse : elle est occupee ou pas prete (erreur 409).")
        raise Erreur(f"L'imprimante a repondu une erreur {e.code}.")
    except (urllib.error.URLError, OSError):
        raise Erreur("L'imprimante ne repond pas (eteinte, hors WiFi, ou mauvaise adresse).")


def multipart(champ, nom, contenu, extra=None):
    b = "----archi" + uuid.uuid4().hex
    parts = []
    for k, v in (extra or {}).items():
        parts.append(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    parts.append(f"--{b}\r\nContent-Disposition: form-data; name=\"{champ}\"; filename=\"{nom}\"\r\n"
                 f"Content-Type: application/octet-stream\r\n\r\n".encode() + contenu + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={b}"


def nom_sur(n):
    n = os.path.basename(str(n or "").replace("\\", "/")).strip()
    if not n or not n.lower().endswith(EXTENSIONS) or n.startswith("."):
        raise Erreur("Donne le nom d'un fichier .gcode, .bgcode ou .3mf.")
    return n


# ---------------------------------------------------------------- Klipper / Moonraker
class Moonraker:
    def __init__(self, base, cle):
        self.b, self.cle = base, cle

    def _g(self, chemin):
        return http("GET", self.b + chemin, "X-Api-Key", self.cle)

    def _p(self, chemin, corps=None, type_corps=None, timeout=15):
        return http("POST", self.b + chemin, "X-Api-Key", self.cle, corps, type_corps, timeout)

    def etat(self):
        s = self._g("/printer/objects/query?print_stats&display_status&extruder&heater_bed")["result"]["status"]
        ps, ds = s.get("print_stats", {}), s.get("display_status", {})
        return {"etat": ps.get("state", "?"), "fichier": ps.get("filename", ""), "progression": round(100 * float(ds.get("progress") or 0)),
                "buse": round(float(s.get("extruder", {}).get("temperature") or 0)), "plateau": round(float(s.get("heater_bed", {}).get("temperature") or 0))}

    def fichiers(self):
        L = self._g("/server/files/list?root=gcodes").get("result", [])
        return [f.get("path") for f in sorted(L, key=lambda x: -float(x.get("modified") or 0))][:15]

    def envoyer(self, nom, contenu):
        corps, t = multipart("file", nom, contenu, {"root": "gcodes"})
        self._p("/server/files/upload", corps, t, timeout=600)

    def lancer(self, nom):
        self._p("/printer/print/start?filename=" + urllib.parse.quote(nom))

    def pause(self):
        self._p("/printer/print/pause")

    def reprendre(self):
        self._p("/printer/print/resume")

    def annuler(self):
        self._p("/printer/print/cancel")


# ---------------------------------------------------------------- OctoPrint
class OctoPrint:
    def __init__(self, base, cle):
        if not cle:
            raise Erreur("OctoPrint a besoin d'une cle API : ARCHI_IMPRIMANTE_CLE dans le .env (Reglages > API).")
        self.b, self.cle = base, cle

    def _r(self, m, chemin, corps=None, t=None, timeout=15):
        return http(m, self.b + chemin, "X-Api-Key", self.cle, corps, t, timeout)

    def _cmd(self, chemin, d):
        return self._r("POST", chemin, json.dumps(d).encode(), "application/json")

    def etat(self):
        j = self._r("GET", "/api/job")
        try:
            p = self._r("GET", "/api/printer")
            buse = round(float(p["temperature"]["tool0"]["actual"]))
            plateau = round(float(p["temperature"]["bed"]["actual"]))
        except Exception:
            buse = plateau = None
        return {"etat": j.get("state", "?"), "fichier": ((j.get("job") or {}).get("file") or {}).get("name") or "",
                "progression": round(float((j.get("progress") or {}).get("completion") or 0)), "buse": buse, "plateau": plateau}

    def fichiers(self):
        L = self._r("GET", "/api/files/local").get("files", [])
        return [f.get("path") or f.get("name") for f in sorted(L, key=lambda x: -float(x.get("date") or 0))][:15]

    def envoyer(self, nom, contenu):
        corps, t = multipart("file", nom, contenu)
        self._r("POST", "/api/files/local", corps, t, timeout=600)

    def lancer(self, nom):
        self._cmd("/api/files/local/" + urllib.parse.quote(nom), {"command": "select", "print": True})

    def pause(self):
        self._cmd("/api/job", {"command": "pause", "action": "pause"})

    def reprendre(self):
        self._cmd("/api/job", {"command": "pause", "action": "resume"})

    def annuler(self):
        self._cmd("/api/job", {"command": "cancel"})


# ---------------------------------------------------------------- PrusaLink (MK4, MINI, XL, Core One)
class PrusaLink:
    def __init__(self, base, cle):
        if not cle:
            raise Erreur("PrusaLink a besoin de sa cle API : ARCHI_IMPRIMANTE_CLE dans le .env (ecran > Reglages > Reseau).")
        self.b, self.cle = base, cle

    def _r(self, m, chemin, corps=None, t=None, timeout=15):
        return http(m, self.b + chemin, "X-Api-Key", self.cle, corps, t, timeout)

    def _job(self):
        try:
            return self._r("GET", "/api/v1/job")
        except Erreur:
            return {}

    def etat(self):
        s = self._r("GET", "/api/v1/status")
        p, j = s.get("printer", {}), s.get("job") or {}
        return {"etat": p.get("state", "?"), "fichier": (self._job().get("file") or {}).get("display_name", ""),
                "progression": round(float(j.get("progress") or 0)), "buse": p.get("temp_nozzle"), "plateau": p.get("temp_bed")}

    def fichiers(self):
        L = self._r("GET", "/api/v1/files/usb").get("children", [])
        return [f.get("display_name") or f.get("name") for f in L][:15]

    def envoyer(self, nom, contenu):
        url = self.b + "/api/v1/files/usb/" + urllib.parse.quote(nom)
        req = urllib.request.Request(url, data=contenu, method="PUT",
                                     headers={"X-Api-Key": self.cle, "Content-Type": "application/octet-stream", "Overwrite": "?1"})
        try:
            urllib.request.urlopen(req, timeout=600).read()
        except urllib.error.HTTPError as e:
            raise Erreur(f"L'imprimante a refuse le fichier (erreur {e.code}).")
        except (urllib.error.URLError, OSError):
            raise Erreur("L'imprimante ne repond pas.")

    def lancer(self, nom):
        self._r("POST", "/api/v1/files/usb/" + urllib.parse.quote(nom))

    def _id(self):
        i = self._job().get("id")
        if i is None:
            raise Erreur("Aucune impression en cours.")
        return str(i)

    def pause(self):
        self._r("PUT", f"/api/v1/job/{self._id()}/pause")

    def reprendre(self):
        self._r("PUT", f"/api/v1/job/{self._id()}/resume")

    def annuler(self):
        self._r("DELETE", f"/api/v1/job/{self._id()}")


ADAPTATEURS = {"moonraker": Moonraker, "octoprint": OctoPrint, "prusalink": PrusaLink}
ACTIONS = ("etat", "fichiers", "envoyer", "lancer", "pause", "reprendre", "annuler")
# TOUT alias d'envoyer / lancer / annuler doit aussi figurer dans sensible_si de outil.json (test_imprimante_3d le verifie)
ALIAS = {"statut": "etat", "ou en est": "etat", "liste": "fichiers", "imprimer": "lancer", "demarrer": "lancer",
         "start": "lancer", "televerser": "envoyer", "upload": "envoyer", "stop": "annuler", "arreter": "annuler"}


def phrase_etat(e):
    t = f"Imprimante : {e['etat']}"
    if e.get("fichier"):
        t += f", « {e['fichier']} » à {e.get('progression', 0)} %"
    if e.get("buse") is not None:
        t += f", buse {e['buse']} °C, plateau {e.get('plateau')} °C"
    return t + "."


def agir(d, imp=None):
    a = str(d.get("action") or "etat").strip().lower()
    a = ALIAS.get(a, a)
    if a not in ACTIONS:
        raise Erreur("Actions : " + ", ".join(ACTIONS) + ".")
    if imp is None:
        t, base, cle = reglages()
        imp = ADAPTATEURS[t](base, cle)
    if a == "etat":
        e = imp.etat()
        return phrase_etat(e), e
    if a == "fichiers":
        L = imp.fichiers()
        return ("Fichiers sur l'imprimante : " + ", ".join(L) + ".") if L else "Aucun fichier sur l'imprimante.", {"fichiers": L}
    if a in ("pause", "reprendre"):
        getattr(imp, a)()
        return ("Impression en pause." if a == "pause" else "Impression reprise."), {}
    if a == "envoyer":
        chemin = str(d.get("fichier") or "")
        nom = nom_sur(chemin)
        if not os.path.isfile(chemin):
            raise Erreur(f"Je ne trouve pas le fichier « {nom} » sur le PC.")
        taille = os.path.getsize(chemin)
        if taille > TAILLE_MAX:
            raise Erreur("Fichier trop gros (200 Mo au plus).")
        if not oui(d.get("confirmer")):
            return (f"PAS ENCORE FAIT : j'enverrais « {nom} » ({taille // 1024} Ko) à l'imprimante. Redis-moi avec confirmer=oui."), {"essai": True}
        with open(chemin, "rb") as f:
            imp.envoyer(nom, f.read())
        return f"« {nom} » est sur l'imprimante. Pour l'imprimer : lancer avec ce nom (après ton accord).", {"fichier": nom}
    if a == "lancer":
        nom = nom_sur(d.get("fichier"))
        e = imp.etat()
        if str(e.get("etat", "")).lower() in ("printing", "paused", "busy"):
            raise Erreur("L'imprimante est déjà occupée : " + phrase_etat(e))
        if not oui(d.get("confirmer")):
            return (f"PAS ENCORE FAIT : je lancerais l'impression de « {nom} ». Vérifie que le plateau est libre et propre, "
                    "puis redis-moi avec confirmer=oui."), {"essai": True}
        imp.lancer(nom)
        return f"Impression de « {nom} » lancée. Je peux te dire où elle en est (etat).", {"fichier": nom}
    # annuler
    if not oui(d.get("confirmer")):
        return "PAS ENCORE FAIT : j'annulerais l'impression en cours (elle sera perdue). Redis-moi avec confirmer=oui.", {"essai": True}
    imp.annuler()
    return "Impression annulée.", {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fichier", required=True)
    a = ap.parse_args()
    try:
        with open(a.fichier, encoding="utf-8-sig") as f:
            d = json.load(f)
    except Exception:
        return repondre(False, "La demande est illisible.")
    if isinstance(d.get("parametres"), dict):
        d = {**d, **d["parametres"]}
    try:
        phrase, extra = agir(d)
        repondre(not extra.get("essai", False), phrase, **extra)
    except Erreur as e:
        repondre(False, str(e))
    except Exception as e:
        repondre(False, f"Problème imprévu avec l'imprimante ({type(e).__name__}).")


if __name__ == "__main__":
    main()
