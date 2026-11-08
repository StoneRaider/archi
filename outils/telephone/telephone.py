# -*- coding: utf-8 -*-
"""telephone.py - Archi commande le telephone de J (appli Archi).
Usage : python telephone.py --fichier demande.json   (outil maison d'Archi)
L'outil ne fait rien sur le PC : il verifie et met en forme l'ordre, l'ecrit dans pc\\telephone\\actions\\<jeton>.json,
et renvoie telephone_jeton. Le noeud « Voix » du workflow telephone joint l'ordre a la reponse ; l'appli l'execute.
Si la demande vient de Telegram, rien ne l'execute : la phrase le dit.

Actions (champ "action") :
  youtube     recherche=...                      -> cherche la video (yt-dlp) et l'appli la lance dans YouTube
  musique     commande=lire|pause|suivant|precedent|chercher, recherche=...   (lecteur du telephone)
  sms         a=nom ou numero, texte=...         -> l'appli demande confirmation a l'ecran avant d'envoyer
  whatsapp    a=nom ou numero, texte=...         -> WhatsApp s ouvre avec le texte pret ; J choisit le contact et appuie sur Envoyer
  appel       a=nom ou numero                    -> l'appli appelle (il faut appuyer sur « Appeler »)
  secours     numero=112|15|17|18 (defaut 112), message=...  -> composeur ouvert sur le numero (Android exige le doigt de J)
  lampe       etat=on|off
  alarme      heure=7:30, libelle=...
  minuteur    minutes=10 (ou secondes), libelle=...
  navigation  destination=..., mode=voiture|pied|velo|transports
  ouvrir      appli=Spotify
  volume      niveau=0-100 | plus | moins | muet
  web         url=... ou requete=... (recherche)
  agenda      titre=..., debut=AAAA-MM-JJTHH:MM, duree_min=60, lieu=...
  reglages    panneau=wifi|bluetooth|son|batterie|ecran|general
  photo       (ouvre l'appareil photo)
  arreter     (coupe ce qui joue : musique, video)
Repond UNE ligne JSON {"ok", "phrase_pour_utilisateur", "telephone_jeton", ...}.
"""
import json
import os
import re
import secrets
import sys
import time
from datetime import datetime
from urllib.parse import quote

ICI = os.path.dirname(os.path.abspath(__file__))
BASE = os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files")
SORTIE = os.path.join(BASE, "pc", "telephone", "actions")
GARDER_S = 2 * 86400
URGENCES = {"112": "le 112 (urgences européennes)", "15": "le 15 (SAMU)", "17": "le 17 (police)", "18": "le 18 (pompiers)",
            "114": "le 114 (urgences par SMS)"}


def sortir(d):
    print(json.dumps(d, ensure_ascii=False))
    sys.exit(0)


def texte(demande, *cles, defaut=""):
    for k in cles:
        v = demande.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return defaut


def nombre(v, defaut=None):
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return defaut


def chercher_video(recherche):
    """yt-dlp (deja dans le venv pour la recolte YouTube) : la premiere video qui correspond. Sans telechargement."""
    try:
        from yt_dlp import YoutubeDL
    except Exception:
        return None
    try:
        with YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True, "socket_timeout": 12}) as y:
            info = y.extract_info(f"ytsearch1:{recherche}", download=False)
        e = (info or {}).get("entries") or []
        if not e:
            return None
        v = e[0]
        return {"id": v.get("id"), "titre": v.get("title"), "chaine": v.get("uploader") or v.get("channel"),
                "duree_s": v.get("duration")}
    except Exception:
        return None


def ecrire(ordre):
    jeton = secrets.token_hex(6)
    ordre = {"jeton": jeton, "heure": datetime.now().isoformat(timespec="seconds"), **ordre}
    try:
        os.makedirs(SORTIE, exist_ok=True)
        maintenant = time.time()
        for f in os.listdir(SORTIE):
            p = os.path.join(SORTIE, f)
            try:
                if f.endswith(".json") and maintenant - os.path.getmtime(p) > GARDER_S:
                    os.remove(p)
            except Exception:
                pass
        with open(os.path.join(SORTIE, jeton + ".json"), "w", encoding="utf-8") as f:
            json.dump(ordre, f, ensure_ascii=False)
    except Exception as e:
        return jeton, str(e)[:120]
    return jeton, ""


def repondre(ordre, phrase, extra=None):
    jeton, err = ecrire(ordre)
    res = {"ok": True, "telephone_jeton": jeton, "ordre": ordre, "phrase_pour_utilisateur": phrase,
           "note": "l'ordre s'execute dans l'appli telephone d'Archi ; depuis Telegram il ne se passe rien"}
    if err:
        res["erreur_fichier"] = err
    if extra:
        res.update(extra)
    sortir(res)


def refuser(phrase, **extra):
    sortir({"ok": False, "phrase_pour_utilisateur": phrase, **extra})


def normaliser_action(a):
    a = (a or "").strip().lower()
    a = a.replace("é", "e").replace("è", "e").replace("ê", "e")
    table = {
        "youtube": "youtube", "video": "youtube", "yt": "youtube",
        "musique": "musique", "music": "musique", "lecteur": "musique", "chanson": "musique",
        "sms": "sms", "message": "sms", "texto": "sms", "ecrire": "sms",
        "whatsapp": "whatsapp", "whats app": "whatsapp", "wa": "whatsapp", "watsap": "whatsapp", "watsapp": "whatsapp",
        "appel": "appel", "appeler": "appel", "telephoner": "appel", "call": "appel",
        "secours": "secours", "urgence": "secours", "urgences": "secours", "samu": "secours", "police": "secours", "pompiers": "secours",
        "lampe": "lampe", "torche": "lampe", "flash": "lampe", "lumiere": "lampe",
        "alarme": "alarme", "reveil": "alarme",
        "minuteur": "minuteur", "timer": "minuteur", "compte a rebours": "minuteur", "chrono": "minuteur",
        "navigation": "navigation", "itineraire": "navigation", "gps": "navigation", "aller": "navigation", "route": "navigation",
        "ouvrir": "ouvrir", "lancer": "ouvrir", "appli": "ouvrir", "application": "ouvrir",
        "volume": "volume", "son": "volume",
        "web": "web", "recherche": "web", "chercher": "web", "google": "web", "site": "web", "page": "web",
        "agenda": "agenda", "rendez-vous": "agenda", "calendrier": "agenda", "evenement": "agenda",
        "reglages": "reglages", "parametres": "reglages", "wifi": "reglages", "bluetooth": "reglages",
        "photo": "photo", "appareil photo": "photo", "camera": "photo",
        "arreter": "arreter", "stop": "arreter", "couper": "arreter", "pause": "musique",
    }
    return table.get(a, a)


def main():
    args = sys.argv[1:]
    demande = {}
    if "--fichier" in args:
        demande = json.load(open(args[args.index("--fichier") + 1], encoding="utf-8"))
    elif args:
        try:
            demande = json.loads(args[0])
        except Exception:
            demande = {"action": "web", "requete": " ".join(args)}
    if isinstance(demande.get("parametres"), dict):
        demande = {**demande, **demande["parametres"]}
    action = normaliser_action(texte(demande, "action", "commande_telephone", "quoi"))

    if action == "youtube":
        q = texte(demande, "recherche", "requete", "video", "titre", "q")
        if not q:
            refuser("Quelle vidéo veux-tu voir sur YouTube, BOSS ?")
        v = chercher_video(q)
        if v and v.get("id"):
            repondre({"action": "youtube", "recherche": q, "video_id": v["id"], "titre": v.get("titre")},
                     f"Je lance sur YouTube : {v.get('titre') or q}" + (f", de {v['chaine']}" if v.get("chaine") else "") + ".",
                     {"video": v})
        repondre({"action": "youtube", "recherche": q}, f"J'ouvre YouTube sur la recherche « {q} ».")

    if action == "musique":
        c = texte(demande, "commande", "sous_action", "etat", defaut="lire").lower()
        c = c.replace("é", "e")
        c = {"play": "lire", "jouer": "lire", "lecture": "lire", "reprendre": "lire", "next": "suivant", "prev": "precedent",
             "previous": "precedent", "avant": "precedent", "cherche": "chercher", "recherche": "chercher", "stop": "pause", "arreter": "pause"}.get(c, c)
        q = texte(demande, "recherche", "titre", "artiste", "requete")
        if q and c in ("lire", "chercher"):
            repondre({"action": "musique", "commande": "chercher", "recherche": q}, f"Je lance « {q} » dans le lecteur du téléphone.")
        if c not in ("lire", "pause", "suivant", "precedent"):
            refuser("Pour la musique je sais : lire, pause, suivant, précédent, ou chercher un titre.")
        mots = {"lire": "je relance la musique", "pause": "je mets en pause", "suivant": "morceau suivant", "precedent": "morceau précédent"}
        repondre({"action": "musique", "commande": c}, mots[c].capitalize() + ".")

    if action == "arreter":
        repondre({"action": "musique", "commande": "pause"}, "Je coupe.")

    if action == "sms":
        a = texte(demande, "a", "destinataire", "contact", "qui", "numero")
        t = texte(demande, "texte", "message", "contenu")
        if not a:
            refuser("À qui dois-je envoyer le SMS ?")
        if not t:
            refuser(f"Qu'est-ce que je dis à {a} dans le SMS ?")
        repondre({"action": "sms", "a": a, "texte": t[:600]},
                 f"SMS pour {a} prêt sur ton téléphone : « {t[:120]}{'…' if len(t) > 120 else ''} ». Confirme à l'écran pour l'envoyer.")

    # 06/11/2026 : WhatsApp. L'appli Archi ouvre WhatsApp avec le message deja ecrit (lien wa.me, action web
    # que l'appli sait deja faire) ; J choisit le contact (sauf si on a son numero) et appuie lui-meme sur Envoyer.
    # Archi ne peut ni envoyer seul, ni lire les messages WhatsApp.
    if action == "whatsapp":
        a = texte(demande, "a", "destinataire", "contact", "qui", "numero")
        t = texte(demande, "texte", "message", "contenu")
        if not t:
            refuser("Qu'est-ce que je mets dans le message WhatsApp" + (f" pour {a}" if a else "") + " ?")
        t = t[:1500]
        chiffres = re.sub(r"[\s.\-()]", "", a or "")
        if re.fullmatch(r"\+?\d{6,15}", chiffres):
            num = chiffres.lstrip("+")
            if num.startswith("00"):
                num = num[2:]
            elif num.startswith("0") and len(num) == 10:      # numero francais 06... -> 336...
                num = "33" + num[1:]
            url = f"https://wa.me/{num}?text={quote(t)}"
            phrase = f"J'ouvre WhatsApp avec ton message pour {a} : « {t[:120]}{'…' if len(t) > 120 else ''} ». Appuie sur Envoyer."
        else:
            url = f"https://wa.me/?text={quote(t)}"
            qui = f"choisis {a}" if a else "choisis le contact"
            phrase = (f"J'ouvre WhatsApp avec ton message prêt : « {t[:120]}{'…' if len(t) > 120 else ''} ». "
                      f"Dans WhatsApp, {qui}, puis appuie sur Envoyer.")
        repondre({"action": "web", "url": url, "appli": "whatsapp", "a": a, "texte": t}, phrase,
                 {"limite": "Archi prepare et ouvre ; c'est J qui choisit le contact et appuie sur Envoyer. Archi ne lit pas WhatsApp."})

    if action == "appel":
        a = texte(demande, "a", "destinataire", "contact", "qui", "numero")
        if not a:
            refuser("Qui dois-je appeler ?")
        if re.sub(r"\D", "", a) in URGENCES:
            action = "secours"
            demande["numero"] = re.sub(r"\D", "", a)
        else:
            repondre({"action": "appel", "a": a}, f"Je prépare l'appel de {a} : appuie sur « Appeler » sur ton téléphone pour le lancer.")

    if action == "secours":
        n = re.sub(r"\D", "", texte(demande, "numero", "a", "service", defaut="112")) or "112"
        if n not in URGENCES:
            n = "112"
        m = texte(demande, "message", "situation")
        repondre({"action": "secours", "numero": n, "message": m},
                 f"J'ouvre {URGENCES[n]} sur ton téléphone : appuie sur le bouton vert pour lancer l'appel. "
                 "Reste calme, dis où tu es et ce qui se passe, et ne raccroche pas le premier.")

    if action == "lampe":
        e = texte(demande, "etat", "valeur", defaut="on").lower()
        on = e not in ("off", "eteindre", "éteindre", "eteins", "éteins", "non", "0", "false", "arret", "arrêt")
        repondre({"action": "lampe", "etat": "on" if on else "off"}, "J'allume la lampe." if on else "J'éteins la lampe.")

    if action == "alarme":
        h = texte(demande, "heure", "a", "quand")
        m = re.match(r"^\s*(\d{1,2})\s*(?:[:hH]\s*(\d{1,2})?)?\s*$", h or "")
        if not m:
            refuser("À quelle heure veux-tu l'alarme ? Par exemple « 7 h 30 ».")
        hh, mm = int(m.group(1)), int(m.group(2) or 0)
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            refuser("Cette heure n'existe pas.")
        lib = texte(demande, "libelle", "titre", "pour", defaut="Archi")
        repondre({"action": "alarme", "heure": hh, "minute": mm, "libelle": lib[:60]}, f"Alarme réglée à {hh} h {mm:02d}.")

    if action == "minuteur":
        s = nombre(demande.get("secondes"))
        mn = nombre(demande.get("minutes"))
        if s is None and mn is None:
            mn = nombre(texte(demande, "duree", "temps"))
        total = int(s if s is not None else (mn or 0) * 60)
        if total <= 0 or total > 24 * 3600:
            refuser("Combien de temps pour le minuteur ? Par exemple « 10 minutes ».")
        lib = texte(demande, "libelle", "titre", "pour", defaut="Archi")
        if total % 60 == 0:
            dit = f"{total // 60} minute{'s' if total >= 120 else ''}"
        else:
            dit = f"{total // 60} min {total % 60} s" if total >= 60 else f"{total} secondes"
        repondre({"action": "minuteur", "secondes": total, "libelle": lib[:60]}, f"Minuteur lancé : {dit}.")

    if action == "navigation":
        d = texte(demande, "destination", "vers", "ou", "où", "lieu", "adresse")
        if not d:
            refuser("Où veux-tu aller ?")
        mode = texte(demande, "mode", defaut="voiture").lower()
        mode = {"a pied": "pied", "à pied": "pied", "marche": "pied", "velo": "velo", "vélo": "velo", "bus": "transports", "train": "transports",
                "transport": "transports", "transports": "transports"}.get(mode, "voiture" if mode not in ("pied", "velo", "transports") else mode)
        repondre({"action": "navigation", "destination": d, "mode": mode}, f"Je lance l'itinéraire vers {d}.")

    if action == "ouvrir":
        a = texte(demande, "appli", "application", "nom", "quoi_ouvrir")
        if not a:
            refuser("Quelle appli dois-je ouvrir ?")
        repondre({"action": "ouvrir", "appli": a}, f"J'ouvre {a}.")

    if action == "volume":
        v = texte(demande, "niveau", "valeur", "volume").lower()
        v = v.replace("é", "e")
        if v in ("plus", "monter", "augmenter", "fort", "+"):
            repondre({"action": "volume", "niveau": "plus"}, "Je monte le son.")
        if v in ("moins", "baisser", "diminuer", "doucement", "-"):
            repondre({"action": "volume", "niveau": "moins"}, "Je baisse le son.")
        if v in ("muet", "silence", "couper", "0", "zero"):
            repondre({"action": "volume", "niveau": 0}, "Son coupé.")
        if v in ("max", "maximum", "fond"):
            repondre({"action": "volume", "niveau": 100}, "Son au maximum.")
        n = nombre(v.replace("%", ""))
        if n is None:
            refuser("Le son : plus, moins, muet, ou un pourcentage.")
        n = int(max(0, min(100, n)))
        repondre({"action": "volume", "niveau": n}, f"Son à {n} %.")

    if action == "web":
        u = texte(demande, "url", "adresse", "lien")
        q = texte(demande, "requete", "recherche", "q")
        if u:
            if not re.match(r"^https?://", u, re.I):
                u = "https://" + u
            repondre({"action": "web", "url": u}, f"J'ouvre {u} sur ton téléphone.")
        if not q:
            refuser("Que dois-je chercher sur le web ?")
        repondre({"action": "web", "requete": q}, f"J'ouvre la recherche « {q} » sur ton téléphone.")

    if action == "agenda":
        t = texte(demande, "titre", "quoi", "evenement")
        deb = texte(demande, "debut", "quand", "date", "heure")
        if not t or not deb:
            refuser("Pour l'agenda il me faut un titre et un début (AAAA-MM-JJTHH:MM).")
        try:
            dt = datetime.fromisoformat(deb.replace(" ", "T")[:16])
        except Exception:
            refuser(f"Je ne comprends pas la date « {deb} » : donne-la sous la forme AAAA-MM-JJTHH:MM.")
        duree = int(nombre(demande.get("duree_min"), 60) or 60)
        repondre({"action": "agenda", "titre": t[:120], "debut_ms": int(dt.timestamp() * 1000), "duree_min": duree,
                  "lieu": texte(demande, "lieu", "ou", "où")[:120]},
                 f"J'ouvre l'agenda du téléphone avec « {t} » le {dt:%d/%m à %H:%M} ; tu valides à l'écran.")

    if action == "reglages":
        p = texte(demande, "panneau", "quoi", "reglage", defaut="general").lower()
        p = p.replace("é", "e")
        p = {"wi-fi": "wifi", "internet": "wifi", "reseau": "wifi", "bt": "bluetooth", "audio": "son", "volume": "son",
             "pile": "batterie", "energie": "batterie", "luminosite": "ecran", "affichage": "ecran"}.get(p, p)
        if p not in ("wifi", "bluetooth", "son", "batterie", "ecran", "general"):
            p = "general"
        repondre({"action": "reglages", "panneau": p}, f"J'ouvre les réglages ({p}).")

    if action == "photo":
        repondre({"action": "photo"}, "J'ouvre l'appareil photo.")

    refuser("Je ne sais pas faire ça sur le téléphone. Je sais : YouTube, musique, SMS, WhatsApp (message prêt, tu appuies sur Envoyer), "
            "appel, secours, lampe, alarme, minuteur, itinéraire, ouvrir une appli, volume, web, agenda, réglages, photo.", action_inconnue=action)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        sortir({"ok": False, "phrase_pour_utilisateur": "Je n'ai pas réussi à préparer l'ordre pour le téléphone.", "erreur": repr(e)[:200]})
