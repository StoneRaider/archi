# Installer Archi chez soi

Il faut compter environ 45 minutes. Le guide est écrit pour Windows 11, mais Linux et macOS marchent pareil.
Tu crées toi-même tes comptes et tes clés. Ce dépôt n'en contient aucune.

## Ce qu'il faut
- un PC avec une carte graphique de 16 Go ou plus (8 Go suffisent pour un modèle plus petit) ;
- Node.js 22 ou plus récent, Python 3.12 ou plus récent ;
- un téléphone Android (8.0 ou plus récent) et un compte Telegram.

## 1. Le cerveau : LM Studio et gpt-oss-20b (10 min)
1. Installe LM Studio (lmstudio.ai), puis télécharge `openai/gpt-oss-20b`.
2. Pour les photos, télécharge aussi un modèle de vision, par exemple `google/gemma-3-12b`.
3. Onglet Developer : démarre le serveur local sur le port 1234.
4. Vérifie avec `curl http://127.0.0.1:1234/v1/models`.

## 2. Le château et les outils (5 min)
```bash
git clone <ce dépôt> archi-agent-local
```
Copie ensuite le château d'exemple dans ton dossier personnel :
- Windows (PowerShell) : `Copy-Item -Recurse archi-agent-local\chateau_exemple\* $HOME\.n8n-files\` ;
- Linux et macOS : `mkdir -p ~/.n8n-files && cp -r archi-agent-local/chateau_exemple/* ~/.n8n-files/`.

Copie aussi les dossiers `outils/*` dans `~/.n8n-files/outils/`. Le registre d'exemple les déclare déjà.
Si tu as des prises Shelly, copie `outils/prises_shelly/prises.exemple.json` en `prises.json`, puis mets les adresses
IP de tes prises. Sans ce fichier, l'outil répond qu'il ne connaît aucune prise.
Installe enfin les modules Python des outils PDF : `python -m pip install -r outils/requirements.txt`.

Vérification : `node --test core/test/` doit afficher `pass 13`.

## 3. Le fichier `.env` : toutes tes clés au même endroit (10 min)
Copie `.env.example` en `.env`, à la racine du dépôt, puis remplis ce qui te concerne. Chaque section est commentée.
Ce fichier n'est **jamais** publié (`.gitignore`), et ses valeurs ne sont jamais affichées.
- `ARCHI_DEPOT` : le chemin du dépôt cloné ; `ARCHI_UTILISATEUR` : ton prénom.
- `ARCHI_CLE_TELEPHONE` et `ARCHI_CLE_OEIL` : deux clés de 32 caractères aléatoires, que tu crées avec
  `node -e "console.log(require('crypto').randomBytes(24).toString('base64url'))"`.
- **Telegram** :
  1. Écris à **@BotFather** : `/newbot`, un nom, puis un identifiant qui finit par `bot`.
  2. Mets le jeton qu'il te donne dans `TELEGRAM_BOT_TOKEN`.
  3. Pour ton numéro de chat : écris à ton bot, ouvre `https://api.telegram.org/bot<TOKEN>/getUpdates`, puis relève
     `chat.id` et mets-le dans `ARCHI_TELEGRAM_CHAT_ID`. **Seul ce chat parle à Archi** : un inconnu qui trouve ton bot
     ne reçoit aucune réponse.
- **Mails et agenda**, **caméras**, **Œil**, **imprimante**, **musique** : les sections 5 à 9, si tu t'en sers.

Pour vérifier sans rien afficher : `python archi_env.py` dit, section par section, ce qui est rempli et ce qui manque.

## 4. Lancer (2 min)
Double-clique sur **`lancer_archi.bat`**. Il :
1. charge le `.env` ;
2. crée tout seul dans n8n les identifiants « Bot Telegram Archi » et « LM Studio (local) » ;
3. démarre la boîte Docker (si Docker est installé), le serveur mails et agenda, puis n8n (série 1.x par défaut,
   `ARCHI_N8N_VERSION` dans le `.env` ; avec n8n 2.x, garde `NODES_EXCLUDE=[]` pour les workflows 3D).

Dans n8n (`http://127.0.0.1:5678`) : Workflows › Import from file › `n8n/archi_demo.json`. Les identifiants sont
déjà reliés. Active le workflow, puis écris « salut » à ton bot. Les rappels du planificateur partent sur ce même chat.

Si les identifiants n'ont pas pu être créés tout seuls (le lanceur le dit), crée-les à la main dans n8n (Credentials),
avec les mêmes noms :
- **OpenAI** « LM Studio (local) », base URL `http://127.0.0.1:1234/v1`, n'importe quelle clé ;
- **Telegram** « Bot Telegram Archi », avec ton jeton.

## 5. L'adresse HTTPS du PC (5 min)
L'appli et Telegram doivent joindre ton PC en **HTTPS**. Deux solutions gratuites :
- **ngrok** : `ngrok http 5678`. Ton adresse est celle en `https://…ngrok-free.app` ;
- **Tailscale Funnel** : `tailscale funnel 5678`.

Mets cette adresse dans `WEBHOOK_URL` du `.env` (avec le `/` final) : le déclencheur Telegram en a besoin.
Seuls les chemins `/webhook/...` sont utiles. Ces tunnels publient **tout** n8n : garde le compte propriétaire
de n8n protégé par un mot de passe solide, ou filtre le tunnel sur `/webhook/` (règles de trafic ngrok).

## 6. L'appli Android (10 min)
1. Onglet **Actions** du dépôt › dernière exécution « Appli Android » › artefact `archi-appli-debug`.
   Tu peux aussi la fabriquer toi-même : `cd appli && ./gradlew assembleDebug`, avec Android Studio installé.
2. Copie l'APK sur le téléphone, puis autorise l'installation depuis cette source.
3. Au premier lancement, l'appli demande :
   - l'adresse : `https://<ton-adresse>/webhook/telephone-archi` ;
   - la clé : la valeur de `ARCHI_CLE_TELEPHONE` dans ton `.env`.
4. Pour changer de serveur plus tard, fais un appui long sur le titre « ARCHI », puis choisis « Serveur Archi ».
5. Essai sur le terrain : écris « rappelle-moi dans 2 min d'arroser ». Le rappel arrive sur Telegram.
   Envoie ensuite une photo avec « qu'est-ce qui cloche ? ».
6. Rappel de lieu : dans Telegram, trombone › Position, puis « retiens cet endroit : ici, c'est la maison », puis
   « quand j'arrive à la maison, rappelle-moi le courrier ». Le rappel part à la prochaine arrivée.

## En option : la voix
Dans la démo, l'appli envoie la voix au PC, qui répond « Whisper non branché ». Dans ma version personnelle,
whisper.cpp (Vulkan) transcrit la voix et Piper lit la réponse. Ce sera ajouté ici après le concours.

## En cas de souci
| Symptôme | Cause probable |
|---|---|
| L'appli affiche « Clé refusée » | La clé de l'appli ne correspond pas à `ARCHI_CLE_TELEPHONE` (16 caractères minimum). |
| Un nœud Code affiche « Cannot find module child_process » | `NODE_FUNCTION_ALLOW_BUILTIN` n'est pas chargé dans l'environnement de n8n. |
| L'agent répond sans jamais utiliser d'outil | LM Studio n'a pas chargé gpt-oss-20b, ou le contexte est trop court (règle-le sur 16k ou plus). |
| La photo reste sans réponse | Le modèle de vision n'est pas chargé, ou `ARCHI_MODELE_VISION` ne correspond pas à son nom. |
