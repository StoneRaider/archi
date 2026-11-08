# Workflows optionnels

Les workflows de la version complète d'Archi, nettoyés. `lancer_archi.bat` les importe tout seul au premier
lancement (`n8n/importer_workflows.py`), avec des ID fixes : les liens entre eux et les identifiants du `.env` marchent
sans réglage. Tu peux aussi les importer à la main (Workflows > Import from file), mais il faudra alors re-choisir les
workflows liés dans les nœuds « Call n8n Workflow Tool ».

| Fichier | Ce qu'il fait |
|---|---|
| `hunter_osint.json` | **Hunter**, l'enquêteur OSINT, branché sur l'agent de la démo (`enquete_osint`). Il enquête sur des entreprises, des sites, des domaines, des IP, des arnaques, des photos (indices et métadonnées), des personnalités publiques, ton empreinte numérique ou la veille géopolitique. Avec un particulier, il se limite à vérifier son identité, repérer une arnaque et trouver des profils **publics** : jamais son adresse, son téléphone ni sa vie privée, et jamais de recoupement de lieu ou d'habitudes entre ses comptes (règle dans ses consignes). Il n'a pas d'outil de géolocalisation d'IP, et la position d'une photo n'est donnée qu'à la commune. Il range une fiche sourcée dans le château. |
| `osint_outils.json` | Les sources publiques de Hunter : registres d'entreprises, archives web, sous-domaines, pseudo, métadonnées d'une photo envoyée en fichier, crises récentes. |
| `vision.json` | Décrit une image (modèle de vision local), pour Hunter et l'agent. |
| `videos_et_pages.json` | Lit une page web (lecteur local, puis Tavily), regarde une vidéo YouTube, ou lance la récolte d'une chaîne. |
| `navigateur.json` | Pilote un navigateur Edge à part (Playwright) : ouvrir, lire, remplir. Il ne tape **jamais** de mot de passe ni de carte, et ne clique **jamais** sur un bouton final (payer, envoyer, valider). Il surveille aussi des pages deux fois par jour. |
| `monteur.json` | Monte une vidéo (temps forts d'une soirée ou souvenirs) avec ffmpeg et Whisper : MP4, sous-titres et projet DaVinci. |
| `brief.json` | Le brief du jour sur Telegram (8 h par défaut, `ARCHI_BRIEF_CRON`) (`serveur/brief.py`) : alertes, météo, agenda, mails importants, anniversaires, relances, actualité. |

## Pièces 3D

| Fichier | Ce qu'il fait |
|---|---|
| `catalogues_3d.json` | Cherche d'abord une pièce **existante** sur Printables, envoie 3 photos sur Telegram, puis télécharge le STL choisi. |
| `impression_3d.json` | **Conçoit** une pièce simple : le modèle local écrit un plan, assemblé en OpenSCAD depuis un catalogue de formes. Il en fait un STL, que `audit_stl.py` contrôle (cotes, volume, pièce fermée). Puis il envoie un **aperçu PNG sur Telegram**. Le STL final n'est fabriqué qu'après ton accord (« valider »). |

Pour imprimer ensuite : découpe le STL avec ton logiciel (OrcaSlicer, PrusaSlicer…), puis demande à Archi
« envoie piece.gcode à l'imprimante » et « lance l'impression » (outil `imprimante_3d`, essai à blanc puis accord).

## Installer
1. Installe OpenSCAD (openscad.org). Si `openscad` n'est pas dans le PATH, mets son chemin dans `ARCHI_OPENSCAD` du `.env`.
2. Copie `audit_stl.py` dans `<ARCHI_BASE>/impression3d/` (par défaut `~/.n8n-files/impression3d/`).
3. Importe les deux fichiers dans n8n. Les identifiants « Bot Telegram Archi » et « LM Studio (local) » sont déjà
   reliés, et le chat Telegram vient de `ARCHI_TELEGRAM_CHAT_ID`.
4. Pour qu'Archi s'en serve, ajoute dans le workflow principal un nœud **Call n8n Workflow Tool** par workflow,
   relié à l'agent. Sa description doit dire quand l'utiliser : « concevoir une pièce 3D », « chercher une pièce 3D
   existante ».

Les chemins et le modèle viennent du `.env` (`ARCHI_BASE`, `ARCHI_LM_URL`, `ARCHI_OPENSCAD`). Ces workflows n'ont
encore été essayés que sur le PC de l'auteur, avec sa propre installation.
