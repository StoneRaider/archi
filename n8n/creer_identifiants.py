# creer_identifiants.py - cree (ou met a jour) dans n8n les identifiants d'Archi a partir du .env :
#   « Bot Telegram Archi » (TELEGRAM_BOT_TOKEN), « LM Studio (local) » (ARCHI_LM_URL),
#   « Tavily (recherche web) » (TAVILY_API_KEY) et « Hunter.io (domaines) » (HUNTERIO_API_KEY) s'ils sont remplis.
# Les identifiants ont des id fixes : le workflow archi_demo.json les trouve tout seul a l'import.
# Le jeton passe par un fichier temporaire, efface tout de suite apres l'import ; il n'est jamais affiche.
import hashlib
import json
import os
import sys
import tempfile

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
sys.path.insert(0, os.path.dirname(ICI))
import archi_env  # noqa: E402
import _n8n  # noqa: E402

ID_TELEGRAM = "ArchiTelegram001"
ID_LM = "ArchiLmStudio001"


def identifiants(env):
    creds = [{"id": ID_LM, "name": "LM Studio (local)", "type": "openAiApi",
              "data": {"apiKey": "lm-studio", "url": env.get("ARCHI_LM_URL") or "http://127.0.0.1:1234/v1"}}]
    if env.get("TELEGRAM_BOT_TOKEN"):
        creds.append({"id": ID_TELEGRAM, "name": "Bot Telegram Archi", "type": "telegramApi",
                      "data": {"accessToken": env["TELEGRAM_BOT_TOKEN"]}})
    if env.get("TAVILY_API_KEY"):
        creds.append({"id": "ArchiTavily00001", "name": "Tavily (recherche web)", "type": "httpHeaderAuth",
                      "data": {"name": "Authorization", "value": "Bearer " + env["TAVILY_API_KEY"]}})
    if env.get("HUNTERIO_API_KEY"):
        creds.append({"id": "ArchiHunterIo001", "name": "Hunter.io (domaines)", "type": "httpQueryAuth",
                      "data": {"name": "api_key", "value": env["HUNTERIO_API_KEY"]}})
    return creds


def temoin():
    base = os.environ.get("ARCHI_BASE") or os.path.join(os.path.expanduser("~"), ".n8n-files")
    return os.path.join(base, ".workflows_archi_importes", "identifiants.empreinte")


def empreinte(creds):
    """empreinte (SHA-256) des identifiants : sert a savoir s'ils ont change, sans jamais les garder en clair"""
    return hashlib.sha256(json.dumps(creds, sort_keys=True).encode("utf-8")).hexdigest()


def main():
    archi_env.charger()
    creds = identifiants(os.environ)
    if "--si-change" in sys.argv:   # lancer_archi : rien a faire si le .env n'a pas bouge (n8n met 10 s a repondre)
        try:
            if open(temoin(), encoding="utf-8").read().strip() == empreinte(creds):
                return 0
        except OSError:
            pass
    fd, f = tempfile.mkstemp(prefix="archi_ident_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            json.dump(creds, h)
        code, _sortie = _n8n.lancer(["import:credentials", "--input=" + f], delai=300)   # sortie jamais affichee
        ok = code == 0
    finally:
        try:
            os.remove(f)
        except OSError:
            pass
    noms = ", ".join(c["name"] for c in creds)
    if ok:
        print("Identifiants n8n a jour : " + noms)
        try:
            os.makedirs(os.path.dirname(temoin()), exist_ok=True)
            with open(temoin(), "w", encoding="utf-8") as h:
                h.write(empreinte(creds) + "\n")
        except OSError:
            pass
    else:
        print("Identifiants n8n PAS crees automatiquement : cree-les dans n8n (Credentials) avec les memes noms : " + noms)
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        print("(pas de TELEGRAM_BOT_TOKEN dans .env : le bot Telegram n'est pas branche)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
