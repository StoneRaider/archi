# prises_shelly.py - outil maison d'Archi : les prises connectees Shelly Plug M Gen3 de J, en local sur le WiFi
# (API "RPC" des Shelly Gen3, sans le cloud Shelly).
#   python prises_shelly.py --fichier demande.json
#   demande.json : {"action": "...", "prise": "radiateur" | "pc", ...}
#     etat      : allumee ou eteinte, puissance (W), energie consommee (kWh), temperature de la prise ; toutes si pas de prise
#     allumer   : prise=radiateur, duree_min (defaut 180, max 720) : la prise s'eteint toute seule apres ce delai
#                 (securite chauffage) ; sans_limite=oui pour ne pas en mettre ; confirmer=oui sinon ESSAI A BLANC
#     eteindre  : prise=radiateur, confirmer=oui sinon ESSAI A BLANC
# Regle fixe : la prise du PC ne s'allume ni ne s'eteint JAMAIS depuis Archi (Archi tourne sur ce PC : couper = arracher
# la prise). Le rallumage a distance du PC se fait depuis l'appli Shelly du telephone (BIOS "Restore on AC Power Loss").
# Les prises sont decrites dans prises.json (nom, adresse IP, coupure autorisee ou non).

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ICI = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(ICI, "prises.json")
DUREE_DEFAUT = 180
DUREE_MAX = 720


class Erreur(Exception):
    pass


def repondre(ok, phrase, **extra):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(dict(ok=ok, phrase_pour_utilisateur=phrase, **extra), ensure_ascii=False))


def oui(v):
    return v is True or str(v).strip().lower() in {"true", "oui", "1", "yes"}


def config():
    try:
        with open(CONFIG, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        raise Erreur("Je ne trouve pas la liste des prises (prises.json).")


def trouver(cfg, nom):
    nom = str(nom or "").strip().lower()
    if not nom:
        raise Erreur("Dis-moi quelle prise : " + " ou ".join(cfg) + ".")
    for cle, p in cfg.items():
        if nom == cle or nom in [a.lower() for a in p.get("alias", [])] or nom in cle:
            return cle, p
    raise Erreur(f"Je ne connais pas la prise « {nom} ». Prises connues : {', '.join(cfg)}.")


def rpc(ip, methode, **params):
    q = urllib.parse.urlencode({k: (str(v).lower() if isinstance(v, bool) else v) for k, v in params.items()})
    url = f"http://{ip}/rpc/{methode}" + (f"?{q}" if q else "")
    try:
        with urllib.request.urlopen(url, timeout=6) as r:
            return json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise Erreur("la prise demande un mot de passe (protection de l'accès local activée dans l'appli Shelly)")
        raise Erreur(f"la prise a répondu une erreur {e.code}")
    except (urllib.error.URLError, OSError):
        raise Erreur(f"la prise ne répond pas à l'adresse {ip} (débranchée, hors WiFi, ou adresse changée)")


def lire(cle, p):
    s = rpc(p["ip"], "Switch.GetStatus", id=0)
    etat = {
        "prise": cle,
        "allumee": bool(s.get("output")),
        "puissance_w": round(float(s.get("apower") or 0), 1),
        "energie_kwh": round(float((s.get("aenergy") or {}).get("total") or 0) / 1000, 2),
        "temperature_c": (s.get("temperature") or {}).get("tC"),
        "extinction_auto_dans_min": None,
    }
    if s.get("timer_duration") and s.get("timer_started_at") is not None:
        etat["extinction_auto_dans_min"] = round(float(s["timer_duration"]) / 60)
    return etat


def phrase_etat(e):
    if e["allumee"]:
        t = f"La prise {e['prise']} est allumée, elle consomme {e['puissance_w']:g} watts"
        if e.get("extinction_auto_dans_min"):
            t += f" (extinction automatique prévue, minuteur de {e['extinction_auto_dans_min']} minutes)"
    else:
        t = f"La prise {e['prise']} est éteinte"
    return t + "."


def act_etat(d):
    cfg = config()
    noms = [trouver(cfg, d.get("prise"))[0]] if d.get("prise") else list(cfg)
    etats, phrases = [], []
    for n in noms:
        try:
            e = lire(n, cfg[n])
            etats.append(e)
            phrases.append(phrase_etat(e))
        except Erreur as x:
            phrases.append(f"La prise {n} : {x}.")
    return repondre(bool(etats), " ".join(phrases), etats=etats)


def act_allumer_eteindre(d, allumer):
    cfg = config()
    cle, p = trouver(cfg, d.get("prise"))
    if not p.get("pilotable", False):
        return repondre(False, f"Je ne touche jamais à la prise {cle} : {p.get('pourquoi', 'règle fixe')}.")
    duree = None
    if allumer and not oui(d.get("sans_limite")):
        try:
            duree = int(float(d.get("duree_min") or DUREE_DEFAUT))
        except ValueError:
            raise Erreur("La durée doit être un nombre de minutes, par exemple 60.")
        duree = max(1, min(DUREE_MAX, duree))
    verbe = "allumer" if allumer else "éteindre"
    if not oui(d.get("confirmer")):
        return repondre(True, f"PAS ENCORE FAIT (essai à blanc) : je vais {verbe} la prise {cle}"
                        + (f", avec extinction automatique dans {duree} minutes" if duree else "")
                        + ". Rien n'a bougé. Pour le faire, rappelle l'outil avec confirmer=oui quand J a dit oui.", essai_a_blanc=True)
    params = {"id": 0, "on": allumer}
    if duree:
        params["toggle_after"] = duree * 60
    rpc(p["ip"], "Switch.Set", **params)
    e = lire(cle, p)
    if e["allumee"] != allumer:
        return repondre(False, f"J'ai demandé d'{verbe} la prise {cle}, mais elle n'a pas changé d'état.", etat=e)
    phrase = f"C'est fait : la prise {cle} est {'allumée' if allumer else 'éteinte'}."
    if allumer and duree:
        phrase += f" Elle s'éteindra toute seule dans {duree} minutes."
    return repondre(True, phrase, etat=e)


ALIAS = {"état": "etat", "statut": "etat", "conso": "etat", "consommation": "etat", "allume": "allumer",
         "on": "allumer", "eteins": "eteindre", "éteindre": "eteindre", "éteins": "eteindre", "off": "eteindre"}


def main():
    pa = argparse.ArgumentParser()
    pa.add_argument("--fichier", required=True)
    a = pa.parse_args()
    try:
        with open(a.fichier, encoding="utf-8-sig") as f:
            d = json.load(f)
    except Exception:
        return repondre(False, "La demande est illisible.")
    act = str(d.get("action") or "").strip().lower()
    act = ALIAS.get(act, act)
    if act in ("", "etat") and (d.get("duree_min") or oui(d.get("sans_limite"))):
        act = "allumer"  # une duree n'a de sens que pour allumer : Archi oublie parfois action=allumer
    act = act or "etat"
    try:
        if act == "etat":
            return act_etat(d)
        if act in ("allumer", "eteindre"):
            return act_allumer_eteindre(d, act == "allumer")
        return repondre(False, f"Je ne connais pas « {act} ». Choix : etat, allumer, eteindre.")
    except Erreur as x:
        return repondre(False, str(x)[:1].upper() + str(x)[1:] + ".")


if __name__ == "__main__":
    main()
