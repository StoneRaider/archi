# Installer Archi chez soi

## Le plus simple (Windows 10 ou 11) : `installation.bat`

1. Télécharge `Archi-1.0.zip` (page Releases du dépôt) et extrais-le.
2. Double-clique sur `installation.bat`. Il installe tout dans `%USERPROFILE%\Archi` (15 à 40 minutes).
3. La page d'accueil s'ouvre : parle à Archi. Pour le téléphone, scanne le QR code de cette page.

Le [README](../README.md) détaille ce qui est installé. Le reste de cette page sert à comprendre ce que fait
l'installateur, à régler un souci, ou à installer Archi à la main (Linux, macOS).

### Ce que l'installateur pose, étape par étape
| Étape | Ce qu'il fait | Si ça coince |
|---|---|---|
| 1. Ton PC | lit la carte graphique, la mémoire vidéo et la place libre | sous 12 Go de mémoire vidéo, Archi marche mais lentement |
| 3. Fichiers | copie le dépôt dans `%USERPROFILE%\Archi` | relance avec `-Destination C:\Archi` si ton nom de session a des accents |
| 4. Python | `uv` télécharge un Python 3.12 privé, puis les modules des outils et du serveur | pare-feu : autorise `github.com` et `pypi.org` |
| 5. Node.js et n8n | Node.js 22 (zip officiel), puis `npm install n8n@1.123.92` dans `programmes\n8n` | c'est l'étape la plus longue (3 à 10 minutes) |
| 6. Tunnel et ffmpeg | `cloudflared.exe` et ffmpeg, en privé | sans tunnel, le PC marche, pas le téléphone |
| 7. Château | copie `chateau_exemple\` dans `chateau\` (jamais par-dessus un château existant) et les outils | |
| 8. `.env` | crée le fichier, deux clés aléatoires, des ports libres | tes valeurs déjà remplies sont gardées |
| 9. Cerveau | LM Studio par `winget` s'il manque, puis `lms get` des deux modèles | pas de `winget` : installe LM Studio depuis lmstudio.ai, ouvre-le une fois, relance |
| 10. n8n | crée les identifiants, importe les 10 workflows, active le principal | `installation.txt` dit lequel a échoué |

Options utiles (`installation.bat -Option`) : `-Destination <dossier>`, `-Oui` (aucune question),
`-SansCerveau` (ne touche pas à LM Studio), `-SansModeles`, `-SansLancer`.

### Les fichiers à connaître, une fois installé
| Fichier ou dossier | Rôle |
|---|---|
| `lancer_archi.bat` (raccourci « Archi » du Bureau) | démarre le cerveau, la page d'accueil, le tunnel et n8n. Fermer sa fenêtre arrête Archi. |
| `brancher_telegram.bat` | ajoute ton bot Telegram, pas à pas |
| `.env` | toutes les clés et tous les réglages, commentés. Jamais publié, jamais affiché. |
| `chateau\memoire\` | la mémoire d'Archi : des fiches Markdown que tu peux lire et corriger |
| `chateau\outils\` | les outils maison et leur registre |
| `donnees\n8n\` | la base de n8n (workflows, identifiants chiffrés) |
| `donnees\etat\` | journaux du portail et du tunnel |
| `installation.txt` | le bilan de l'installation |

### Brancher le reste (facultatif)
Chaque section du `.env` est commentée. Après un changement, relance Archi.
- **Mails et agenda** (Gmail, Outlook) : [serveur/LISEZMOI.md](../serveur/LISEZMOI.md).
- **Prises Shelly** : copie `chateau\outils\prises_shelly\prises.exemple.json` en `prises.json` et mets-y les
  adresses IP de tes prises. Sans ce fichier, l'outil répond qu'il ne connaît aucune prise.
- **Caméras, imprimante 3D, musique, Œil** : sections 6 à 9 du `.env`.
- **Boîte Docker** (globe de l'Œil, SearXNG, Presenton) : `ARCHI_DOCKER=oui` dans le `.env`, avec Docker installé.
- **Adresse fixe pour le téléphone** : mets l'adresse HTTPS de ton tunnel dans `WEBHOOK_URL` (avec le `/` final).
  Ton tunnel doit viser **le portail** (`ARCHI_PORTAIL_PORT`, 5680 par défaut), pas n8n :
  `ngrok http 5680` ou `tailscale funnel 5680`.

### En cas de souci
| Symptôme | Cause probable |
|---|---|
| La page d'accueil dit « LM Studio arrêté » | Ouvre LM Studio, onglet Developer, démarre le serveur. Archi le fait tout seul si `lms` est installé. |
| Archi répond sans jamais utiliser d'outil | Le modèle a été chargé avec un contexte trop court : relance Archi (il le charge avec 16k), ou règle `ARCHI_CONTEXTE`. |
| La photo reste sans réponse | Le modèle de vision n'est pas téléchargé, ou `ARCHI_MODELE_VISION` ne correspond pas à son nom dans LM Studio. |
| « Téléphone : pas d'adresse » | Le tunnel n'a pas pu s'ouvrir (pas d'Internet, pare-feu). Le détail est dans `donnees\etat\tunnel.log`. |
| L'appli affiche « Clé refusée » | Le PC a été réinstallé : rescanne le QR code. |
| « Le port … est déjà pris » | Un autre programme l'utilise : change `N8N_PORT` ou `ARCHI_PORTAIL_PORT` dans le `.env`. |
| Un nœud Code affiche « Cannot find module child_process » | n8n n'a pas été lancé par `lancer_archi.bat` (qui charge `NODE_FUNCTION_ALLOW_BUILTIN`). |

## À la main (Linux, macOS, ou pour tout comprendre)

Il faut compter environ 45 minutes. Tu crées toi-même tes comptes et tes clés : ce dépôt n'en contient aucune.
Il faut Node.js 22, Python 3.12 ou plus récent, et LM Studio.

### 1. Le cerveau : LM Studio et gpt-oss-20b
1. Installe LM Studio (lmstudio.ai), puis télécharge `openai/gpt-oss-20b`.
2. Pour les photos, télécharge aussi un modèle de vision, par exemple `google/gemma-3-4b`.
3. Onglet Developer : démarre le serveur local, et charge gpt-oss-20b avec un contexte de 16k ou plus.
4. Vérifie avec `curl http://127.0.0.1:1234/v1/models`.

### 2. Le château et les outils
```bash
git clone <ce dépôt> archi-agent-local && cd archi-agent-local
mkdir -p ~/.n8n-files && cp -r chateau_exemple/* ~/.n8n-files/
mkdir -p ~/.n8n-files/outils && cp -r outils/* ~/.n8n-files/outils/
python -m pip install -r outils/requirements.txt -r serveur/requirements.txt
node --test core/test portail/test
```

### 3. Le fichier `.env`
Copie `.env.example` en `.env`, à la racine du dépôt, puis remplis ce qui te concerne.
- `ARCHI_DEPOT` : le chemin du dépôt ; `ARCHI_UTILISATEUR` : ton prénom.
- `ARCHI_CLE_TELEPHONE` et `ARCHI_CLE_OEIL` : deux clés aléatoires, créées avec
  `node -e "console.log(require('crypto').randomBytes(24).toString('base64url'))"`.
- **Telegram** (facultatif) : écris `/newbot` à **@BotFather**, mets le jeton dans `TELEGRAM_BOT_TOKEN`, puis ton
  numéro de chat dans `ARCHI_TELEGRAM_CHAT_ID` (écris à ton bot, puis lis `chat.id` dans la réponse de la méthode
  `getUpdates` de l'API Telegram). **Seul ce chat parle à Archi.**

Pour vérifier sans rien afficher : `python archi_env.py` dit, section par section, ce qui est rempli.

### 4. Lancer
```bash
set -a; . ./.env; set +a                    # charge le .env dans ce terminal
python n8n/creer_identifiants.py            # identifiants « LM Studio (local) » et « Bot Telegram Archi »
python n8n/importer_workflows.py            # les 10 workflows, avec leurs ID fixes, puis active le principal
node portail/portail.js &                   # la page d'accueil : http://127.0.0.1:5680
npx n8n@1                                   # l'agent
```
Sous Windows, `lancer_archi.bat` fait tout cela.

### 5. L'adresse HTTPS du téléphone
L'appli et Telegram doivent joindre ton PC en **HTTPS**. Ouvre un tunnel vers **le portail**, pas vers n8n :
`cloudflared tunnel --url http://127.0.0.1:5680`, `ngrok http 5680` ou `tailscale funnel 5680`.
Mets l'adresse dans `WEBHOOK_URL` du `.env` (avec le `/` final), écris-la aussi dans
`donnees/etat/adresse_publique.txt` (sans le `/`), puis relance n8n : le QR code de la page d'accueil apparaît.

### 6. L'appli Android
L'APK est dans le ZIP de la page Releases (`appli/Archi.apk`) et dans la page Releases elle-même.
Pour la fabriquer : `cd appli && ./gradlew assembleDebug` (JDK 17 ou 21 et le SDK Android).
Sans QR code, l'appli demande au premier lancement l'adresse `https://<ton-adresse>/webhook/telephone-archi` et la
clé `ARCHI_CLE_TELEPHONE`. Pour changer de serveur : appui long sur le titre « ARCHI ».

## En option : la voix
Dans cette version, l'appli envoie la voix au PC, qui répond « Whisper non branché ». Dans ma version personnelle,
whisper.cpp (Vulkan) transcrit la voix et une synthèse locale lit la réponse. Ce sera ajouté ici après le concours.
