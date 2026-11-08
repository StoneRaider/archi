# Le serveur Python d'Archi : mails et agenda

Un petit serveur local (FastAPI, `127.0.0.1:8765`, jamais exposé hors du PC) que n8n appelle pour :
- **chercher** et **lire** des mails (Gmail, Outlook/Hotmail) ;
- **trouver l'adresse d'un contact** ;
- **préparer un mail, puis l'envoyer** : deux appels séparés. Le premier montre un aperçu, le second envoie
  seulement après l'accord, et l'aperçu expire au bout de 2 h ;
- **trier les mails non lus**. Le modèle local classe chaque mail (important, notification ou pub). Les pubs vont dans
  le dossier « Tri auto » (rien n'est jeté par défaut), et un **brouillon** de réponse est préparé si une vraie personne
  attend une réponse. Rien n'est envoyé tout seul ;
- **l'agenda Google** (`agenda.py`) : ajouter, lister, chercher.

Le rangement des mails dans des dossiers (`outils/ranger_mails`) utilise les mêmes connexions.

## Installer (15 min)
```bash
cd serveur
python -m venv venv
venv\Scripts\python -m pip install -r requirements.txt
```
Tout ce que le serveur garde (jetons de connexion, journal du tri, mémoire des expéditeurs) va dans
`serveur/donnees/`, ou dans le dossier `ARCHI_SERVEUR_DONNEES`. Ce dossier n'est jamais publié.

### Gmail et agenda Google
1. Sur console.cloud.google.com : crée un projet, puis active « Gmail API » et « Google Calendar API ».
2. « Écran de consentement OAuth » : type externe, et ajoute ton adresse comme utilisateur test.
3. « Identifiants » › créer un ID client OAuth de type **Application de bureau** › télécharger le JSON.
4. Range ce fichier sous le nom `serveur/donnees/google_client.json` (ou indique son chemin dans `ARCHI_GOOGLE_CLIENT`). Sans lui, Gmail répond « non branché », et le reste marche.
5. Au premier appel, le navigateur s'ouvre une fois pour te connecter. Le jeton est ensuite gardé dans `donnees/`.

### Outlook / Hotmail
1. Sur portal.azure.com › « Inscriptions d'applications » › nouvelle inscription. Choisis le type de compte
   « comptes Microsoft personnels » (ou ton organisation).
2. Authentification › ajouter une plateforme « Applications mobiles et de bureau », avec l'URI `http://localhost`.
3. Autorisations d'API › Microsoft Graph, déléguées : `Mail.ReadWrite`, `Mail.Send`.
4. Mets l'« ID d'application (client) » dans `ARCHI_OUTLOOK_CLIENT_ID`. Pour un compte d'organisation, mets aussi
   `ARCHI_OUTLOOK_TENANT` (`consumers` par défaut, pour les comptes personnels).

### Lancer
`lancer_archi.bat` le démarre tout seul (avec `serveur/venv` s'il existe). À la main :
```bash
cd serveur
venv\Scripts\python archi_server.py
```
Pour vérifier : ouvre `http://127.0.0.1:8765/sante` dans ton navigateur.

## Réglages (variables d'environnement)
| Variable | Rôle | Par défaut |
|---|---|---|
| `ARCHI_SERVEUR_DONNEES` | dossier des jetons et des journaux | `serveur/donnees` |
| `ARCHI_LM_URL`, `ARCHI_MODELE` | LM Studio et le modèle | `http://127.0.0.1:1234/v1`, `openai/gpt-oss-20b` |
| `ARCHI_TRI_ACTION` | `tri_auto` (ranger) ou `corbeille` (jeter) | `tri_auto` |
| `ARCHI_FUSEAU` | fuseau de l'agenda | `Europe/Paris` |
| `ARCHI_UTILISATEUR` | prénom utilisé dans les consignes du modèle | « l'utilisateur » |

Règles de tri facultatives : copie `regles_expediteurs.exemple.json` en `donnees/regles_expediteurs.json`
(expéditeurs protégés, mots et expéditeurs commerciaux).

Sécurité : le serveur n'écoute que `127.0.0.1` et refuse tout appel venu d'un navigateur (en-têtes `Origin` ou
`Sec-Fetch-Site`) ou d'une adresse non locale. Une page web ouverte ne peut donc pas lui faire envoyer un mail.
