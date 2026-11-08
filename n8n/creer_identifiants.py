# creer_identifiants.py - cree (ou met a jour) dans n8n les identifiants d'Archi a partir du .env :
#   « Bot Telegram Archi » (TELEGRAM_BOT_TOKEN), « LM Studio (local) » (ARCHI_LM_URL),
#   « Tavily (recherche web) » (TAVILY_API_KEY) et « Hunter.io (domaines) » (HUNTERIO_API_KEY) s'ils sont remplis.
# Les identifiants ont des id fixes : le workflow archi_demo.json les trouve tout seul a l'import.
# Le jeton passe par un fichier temporaire, efface tout de suite apres l'import ; il n'est jamais affiche.
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import archi_env  # noqa: E402

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


def main():
    archi_env.charger()
    creds = identifiants(os.environ)
    fd, f = tempfile.mkstemp(prefix="archi_ident_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            json.dump(creds, h)
        version = os.environ.get("ARCHI_N8N_VERSION") or "1"   # meme serie que lancer_archi.ps1
        r = subprocess.run("npx --yes \"n8n@%s\" import:credentials --input=\"%s\"" % (version, f), shell=True,
                           capture_output=True, text=True, timeout=300)
        ok = r.returncode == 0
    except Exception as e:
        ok, r = False, None
        print("identifiants n8n : echec (%s)" % type(e).__name__)
    finally:
        try:
            os.remove(f)
        except OSError:
            pass
    noms = ", ".join(c["name"] for c in creds)
    if ok:
        print("Identifiants n8n a jour : " + noms)
    else:
        print("Identifiants n8n PAS crees automatiquement : cree-les dans n8n (Credentials) avec les memes noms : " + noms)
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        print("(pas de TELEGRAM_BOT_TOKEN dans .env : le bot Telegram n'est pas branche)")


if __name__ == "__main__":
    main()
