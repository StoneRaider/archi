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
| 4. Python | `uv` (empreinte vérifiée) télécharge un Python 3.12 privé, puis les modules des outils et du serveur | pare-feu : autorise `github.com` et `pypi.org` |
| 5. Node.js et n8n | Node.js 22 (zip officiel), puis `npm install n8n@1.123.92` dans `programmes\n8n` | c'est l'étape la plus longue (3 à 10 minutes) |
| 6. Tunnel et ffmpeg | `cloudflared.exe` et ffmpeg, en privé | sans tunnel, le PC marche, pas le téléphone |
| 7. Château | copie `chateau_exemple\` dans `chateau\` (jamais par-dessus un château existant) et les outils | |
| 8. `.env` | crée le fichier, deux clés aléatoires, les premiers ports libres | tes valeurs déjà remplies sont gardées |
| 9. Cerveau | LM Studio par `winget` s'il manque, puis `lms get` des deux modèles | pas de `winget` : installe LM Studio depuis lmstudio.ai, ouvre-le une fois, relance |
| 10. Voix | whisper.cpp et son modèle (l'oreille, empreintes vérifiées), Pocket TTS (empreinte vérifiée) et le modèle de voix qu'il télécharge lui-même | sans la voix, Archi marche par écrit ; `-SansVoix` la saute |
| 11. n8n | crée les identifiants, importe les 10 workflows, active le principal | `installation.txt` dit lequel a échoué |

Options utiles (`installation.bat -Option`) : `-Destination <dossier>`, `-Oui` (aucune question),
`-SansCerveau` (ne touche pas à LM Studio), `-SansModeles`, `-SansVoix`, `-SansLancer`.

### Les fichiers à connaître, une fois installé
| Fichier ou dossier | Rôle |
|---|---|
| `lancer_archi.bat` (raccourci « Archi » du Bureau) | démarre le cerveau, la page d'accueil, le tunnel, la voix et n8n. Fermer sa fenêtre arrête Archi. |
| `brancher_telegram.bat` | ajoute ton bot Telegram, pas à pas |
| `verifier_archi.bat` | contrôle tout de bout en bout pendant qu'Archi tourne : programmes, cerveau, voix, liste blanche, vraie question |
| `.env` | toutes les clés et tous les réglages, commentés. Jamais publié, jamais affiché. |
| `chateau\memoire\` | la mémoire d'Archi : des fiches Markdown que tu peux lire et corriger |
| `chateau\outils\` | les outils maison et leur registre |
| `donnees\n8n\` | la base de n8n (workflows, identifiants chiffrés) |
| `donnees\etat\` | journaux du portail, du tunnel et de la porte du téléphone (`porte.log` : heures et chemins, jamais la clé ni le contenu) |
| `installation.txt` | le bilan de l'installation |

### Brancher le reste (facultatif)
Chaque section du `.env` est commentée. Après un changement, relance Archi.
- **Mails et agenda** (Gmail, Outlook) : [serveur/LISEZMOI.md](../serveur/LISEZMOI.md).
- **Prises Shelly** : copie `chateau\outils\prises_shelly\prises.exemple.json` en `prises.json` et mets-y les
  adresses IP de tes prises. Sans ce fichier, l'outil répond qu'il ne connaît aucune prise.
- **Caméras, imprimante 3D, musique, Œil** : sections 6 à 9 du `.env`.
- **Boîte Docker** (globe de l'Œil, SearXNG, Presenton) : `ARCHI_DOCKER=oui` dans le `.env`, avec Docker installé.
- **Adresse fixe pour le téléphone** : mets l'adresse HTTPS de ton tunnel dans `WEBHOOK_URL` (avec le `/` final).
  Ton tunnel doit viser **la porte du téléphone** (`ARCHI_PORTE_PORT`, 5681 par défaut), jamais n8n :
  `ngrok http 5681` ou `tailscale funnel 5681`.

### En cas de souci
| Symptôme | Cause probable |
|---|---|
| La page d'accueil dit « LM Studio arrêté » | Ouvre LM Studio, onglet Developer, démarre le serveur. Archi le fait tout seul si `lms` est installé. |
| Archi répond sans jamais utiliser d'outil | Le modèle a été chargé avec un contexte trop court : relance Archi (il le charge avec 16k), ou règle `ARCHI_CONTEXTE`. |
| La photo reste sans réponse | Le modèle de vision n'est pas téléchargé, ou `ARCHI_MODELE_VISION` ne correspond pas à son nom dans LM Studio. |
| « Téléphone : pas d'adresse » | Le tunnel n'a pas pu s'ouvrir (pas d'Internet, pare-feu). Le détail est dans `donnees\etat\tunnel.log`. |
| L'appli affiche « Clé refusée » | Le PC a été réinstallé : rescanne le QR code. |
| Archi ne retient pas ce que tu lui dis | Le greffier travaille après la réponse : attends quelques secondes, la note « Retenu » apparaît. Vérifie `ARCHI_MEMOIRE` dans le `.env` et rejoue `outils\memoire\banc_memoire.py`. |
| Archi répond « La voix n'est pas installée » | L'étape 10 a échoué ou a été sautée : relance `installation.bat` (il ne retélécharge que ce qui manque). |
| Archi répond « La voix est coupée » | `ARCHI_VOIX=non` dans le `.env` (installation avec `-SansVoix`) : mets `oui`, puis relance Archi. |
| « Réponse écrite seulement (la voix n'a pas marché) » | Le serveur de voix ne répond pas : relance Archi, puis `verifier_archi.bat`. Le détail est dans `donnees\etat\voix.log`. |
| Le micro de la page d'accueil ne s'ouvre pas | Autorise le micro pour `127.0.0.1` dans ton navigateur (icône à gauche de l'adresse). |
| L'appli dit qu'elle n'est « pas encore branchée » | Elle a été ouverte avant l'étape 2 : reviens sur la page du téléphone et touche « Brancher l'appli », ou rescanne le QR code. |
| L'appli dit que le PC « n'est plus à cette adresse » | Archi a été relancé : l'adresse du tunnel change à chaque lancement. Rescanne le QR code (ou prends une adresse fixe, plus haut). |
| Savoir où en est le téléphone | La page d'accueil coche en direct : page ouverte, appli téléchargée, appli branchée. Le détail est dans `donnees\etat\porte.log`. |
| « Le port … est déjà pris » | Un autre programme l'utilise : change `N8N_PORT`, `ARCHI_PORTAIL_PORT` ou `ARCHI_PORTE_PORT` dans le `.env`. |
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
python -m venv venv && . venv/bin/activate
python -m pip install -r outils/requirements.txt -r serveur/requirements.txt
python archi_env.py --brancher              # ce Python relira le .env tout seul : n8n ne le transmet pas aux outils
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
node portail/portail.js &                   # la page d'accueil (5680) et la porte du téléphone (5681)
npx n8n@1                                   # l'agent
```
Sous Windows, `lancer_archi.bat` fait tout cela.

### 5. L'adresse HTTPS du téléphone
L'appli et Telegram doivent joindre ton PC en **HTTPS**. Ouvre un tunnel vers **la porte du téléphone**
(port 5681), jamais vers n8n : `cloudflared tunnel --url http://127.0.0.1:5681`, `ngrok http 5681` ou `tailscale funnel 5681`.
Mets l'adresse dans `WEBHOOK_URL` du `.env` (avec le `/` final), écris-la aussi dans
`donnees/etat/adresse_publique.txt` (sans le `/`), puis relance n8n : le QR code de la page d'accueil apparaît.

### 6. L'appli Android
L'APK est dans le ZIP de la page Releases (`appli/Archi.apk`) et dans la page Releases elle-même.
Pour la fabriquer : `cd appli && ./gradlew assembleRelease` (JDK 17 ou 21 et le SDK Android). La signature est expliquee dans [appli/SIGNATURE.md](../appli/SIGNATURE.md).
Sans QR code, l'appli demande au premier lancement l'adresse `https://<ton-adresse>/webhook/telephone-archi` et la
clé `ARCHI_CLE_TELEPHONE`. Pour changer de serveur : appui long sur le titre « ARCHI ».

## La mémoire : il retient tout seul

Rien à installer : l'outil `memoire` est posé avec les autres outils maison.

- **Comment ça marche** : après chaque message, le modèle local relève en arrière-plan ce que tu apprends de durable à
  Archi, et l'outil le range dans `chateau\memoire\<pièce>\<sujet>.md` (pièces : `moi`, `personnes`, `projets`, `lieux`,
  `preferences`). À chaque message suivant, Archi relit ces fiches.
- **Le voir** : la carte « Sa mémoire » de la page d'accueil, et une note « Retenu : … » dans la discussion.
- **Le régler** : `ARCHI_MEMOIRE=non` dans le `.env` coupe la mémoire automatique (l'outil reste utilisable à la demande).
- **Le mesurer** : `python outils\memoire\banc_memoire.py` rejoue 30 phrases avec ton modèle, sans rien ranger.

## La voix : il t'écoute et te répond, sans quitter le PC

`installation.bat` pose la voix par défaut (environ 1 Go). Rien ne part vers un service en ligne.

| Brique | Rôle | Où |
|---|---|---|
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) et le modèle Whisper « small » | l'oreille : ton message vocal devient du texte | `programmes\whisper\` |
| [Pocket TTS](https://github.com/kyutai-labs/pocket-tts) (Kyutai) | la parole : la réponse est lue à voix haute | `programmes\voix\` |
| ffmpeg | convertit le son (WAV 16 kHz pour l'oreille, OGG/Opus pour l'appli et la page) | `programmes\ffmpeg\` |

- **Sur le téléphone** : touche la sphère et parle. La réponse s'affiche et se fait entendre.
- **Sur la page d'accueil du PC** : clique sur le micro, il t'écoute en continu. Ce qu'il entend s'écrit dans la ligne de
  saisie ; dis « fin de transmission » (ou appuie sur Entrée) pour envoyer, « Archi, annule » pour effacer. Reclique sur le
  micro pour le fermer. Le haut-parleur coupe ou remet la voix.
- **Les réglages** (`.env`, section 9) : `ARCHI_VOIX=non` coupe tout ; `ARCHI_WHISPER_MODELE` accepte un modèle plus gros
  (plus juste, plus lent) ; `ARCHI_VOIX_NOM` choisit une autre voix du catalogue de Pocket TTS ; `ARCHI_LANGUE` change de langue.
  Une autre voix ou une autre langue est téléchargée par Pocket TTS au lancement suivant (quelques centaines de Mo).
- **Les deux tournent sur le processeur** : la carte graphique reste au modèle de langage. Sur un processeur récent,
  l'oreille met environ 2 secondes pour une phrase, et la voix parle plus vite que le temps réel.
- **Contrôle sans micro** : `verifier_archi.bat` fait dire une phrase témoin à la voix, la fait réécouter par l'oreille et
  compare les mots.

Licences : whisper.cpp et le modèle Whisper sont sous licence MIT ; Pocket TTS est publié par Kyutai (sa licence est dans
son dossier), et la licence de chaque voix de son catalogue est donnée sur la page `kyutai/tts-voices` de Hugging Face.
Archi n'utilise qu'une voix de ce catalogue : il ne clone aucune voix.

À la main (Linux, macOS) : installe whisper.cpp et Pocket TTS, lance `pocket-tts serve --host 127.0.0.1 --port 5683
--language french`, puis remplis `ARCHI_WHISPER_EXE`, `ARCHI_WHISPER_MODELE` et `ARCHI_VOIX_PORT` dans le `.env`.
