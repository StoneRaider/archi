# email_orchestrator.py

import json
import re
import requests
import os
from datetime import datetime
from email.utils import parseaddr

from gmail_tool import *
from outlook_tool import *
from calendar_tool import *
from memory_engine import update_contact
from business_scoring import compute_business_score
from reglages import chemin, LM_URL, MODELE, UTILISATEUR

# ===== RÉGLAGES =====
# "tri_auto"  = range les mails inintéressants dans le dossier Tri auto
# "corbeille" = les met à la corbeille (récupérables ~30 jours)
# Par defaut : tri_auto (rien n'est jete, tout se retrouve dans « Tri auto »). ARCHI_TRI_ACTION=corbeille pour jeter.
ACTION_NON_INTERESSANT = os.environ.get("ARCHI_TRI_ACTION", "tri_auto")
NB_MAILS_PAR_BOITE = 50
# ====================

LM_STUDIO_URL = LM_URL
MODEL_NAME = MODELE

LOG_FILE = chemin("tri_journal.txt")
STATS_FILE = chemin("tri_stats.json")

NO_REPLY_PATTERNS = [
    "no-reply", "noreply", "ne-pas-repondre", "nepasrepondre",
    "newsletter", "notification", "info@", "news@", "mailer"
]


def ensure_data_dir():
    pass   # le dossier de donnees est cree par reglages.py


def log(message):
    ensure_data_dir()
    line = f"[{datetime.now():%H:%M:%S}] {message}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def save_stats(stats):
    ensure_data_dir()
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=4, ensure_ascii=False)


def load_rules():
    """regles de l'utilisateur : donnees/regles_expediteurs.json (voir regles_expediteurs.exemple.json)"""
    try:
        with open(chemin("regles_expediteurs.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def ask_llm(prompt):
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "Tu es Archi, l'assistant de " + UTILISATEUR + ". Tu tries ses mails."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2
    }
    r = requests.post(LM_STUDIO_URL, json=payload, timeout=300)
    return r.json()["choices"][0]["message"]["content"]


def extract_json(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("Pas de JSON dans la réponse")
    return json.loads(match.group(0))


def clean_address(sender):
    """'Boutique <promo@example.com>' -> 'promo@example.com'"""
    return parseaddr(sender)[1].strip().lower()


def is_protected(sender, rules):
    return any(p.lower() in sender for p in rules.get("protected_senders", []))


def is_commercial(e, rules, sender):
    subject = e["subject"].lower()
    by_keyword = any(k.lower() in subject for k in rules.get("commercial_keywords", []))
    by_sender = any(s.lower() in sender for s in rules.get("commercial_senders", []))
    return by_keyword or by_sender


def is_no_reply(sender):
    return any(p in sender for p in NO_REPLY_PATTERNS)


def mark_read(e):
    if e["source"] == "Gmail":
        mark_as_read(e["id"])
    else:
        mark_as_read_outlook(e["id"])


def remove_mail(e):
    """Lit le mail puis le range ou le jette selon le réglage."""
    mark_read(e)
    if ACTION_NON_INTERESSANT == "corbeille":
        if e["source"] == "Gmail":
            delete_email(e["id"])
        else:
            delete_email_outlook(e["id"])
        return "Corbeille"
    else:
        if e["source"] == "Gmail":
            move_to_tri_auto(e["id"])
        else:
            move_to_tri_auto_outlook(e["id"])
        return "Tri auto"


def process_once():

    delete_archi_drafts()
    rules = load_rules()


    stats = {"processed": 0, "important": 0, "retirés": 0, "drafts": 0, "erreurs": 0}

    emails = get_unread_emails(NB_MAILS_PAR_BOITE)
    try:
        emails += get_unread_emails_outlook(NB_MAILS_PAR_BOITE)
    except Exception as err:
        log(f"Erreur Outlook : {err}")

    for e in emails:
        stats["processed"] += 1
        sender = clean_address(e["from"])
        protected = is_protected(sender, rules)
        log(f"Traitement : {e['subject'][:70]} ({e['source']})")

        try:
            # 1) Barrière rapide par mots-clés
            if not protected and is_commercial(e, rules, sender):
                dest = remove_mail(e)
                stats["retirés"] += 1
                log(f"   -> Pub (mots-clés) : {dest}")
                continue

            # 2) L'IA lit et classe
            prompt = f"""
Classe ce mail et réponds STRICTEMENT en JSON, sans texte autour :
{{
  "category": "important" ou "notification" ou "pub",
  "priority": 1 à 5,
  "needs_response": true ou false,
  "response": "texte de réponse si besoin, sinon vide"
}}

Règles :
- "pub" = publicité, promo, newsletter commerciale, bons plans.
- "notification" = réseaux sociaux, alertes automatiques, suggestions, annonces.
- "important" = une vraie personne, l'administration, la banque, les impôts,
  l'URSSAF, les factures, les contrats, les réservations.
- needs_response = true UNIQUEMENT si une vraie personne attend une réponse.

From: {sender}
Subject: {e['subject']}
Content: {e['snippet'][:1500]}
"""
            analysis = extract_json(ask_llm(prompt))
            category = analysis.get("category", "important")
            if protected:
                category = "important"

            update_contact(sender, analysis.get("priority", 3))

            if category in ("pub", "notification"):
                dest = remove_mail(e)
                stats["retirés"] += 1
                log(f"   -> {category} : {dest}")
                continue

            # 3) Mail important
            stats["important"] += 1
            if analysis.get("needs_response") and sender and not is_no_reply(sender):
                body = analysis.get("response", "")
                if e["source"] == "Gmail":
                    create_draft_gmail(sender, "Re: " + e["subject"], body)
                else:
                    create_draft_outlook(sender, "Re: " + e["subject"], body)
                stats["drafts"] += 1
                log("   -> IMPORTANT : brouillon créé")
            else:
                log("   -> IMPORTANT : lu, pas de réponse nécessaire")
            mark_read(e)

        except Exception as err:
            stats["erreurs"] += 1
            log(f"   -> Erreur sur ce mail (on passe au suivant) : {err}")

    save_stats(stats)
    log(f"Fin traitement : {stats}")
    return stats


def nettoyage_complet(pause_secondes=10, max_passages=200):
    """Traite la boîte en boucle jusqu'à ce qu'il n'y ait plus rien à faire."""
    import time
    total = {"processed": 0, "important": 0, "retirés": 0, "drafts": 0, "erreurs": 0}
    erreurs_de_suite = 0

    for passage in range(1, max_passages + 1):
        log(f"===== PASSAGE {passage} =====")
        try:
            stats = process_once()
        except Exception as err:
            erreurs_de_suite += 1
            log(f"Erreur sur le passage {passage} : {err}")
            if erreurs_de_suite >= 3:
                log("3 erreurs d'affilée : arrêt de sécurité.")
                break
            time.sleep(pause_secondes)
            continue

        erreurs_de_suite = 0
        for cle in total:
            total[cle] += stats.get(cle, 0)

        if stats.get("processed", 0) == 0:
            log("Plus rien à traiter : boîte propre !")
            break

        time.sleep(pause_secondes)

    log(f"BILAN TOTAL : {total}")
    return total