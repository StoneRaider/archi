# Sécurité et vie privée

## Principes
- **Local d'abord** : modèle, mémoire et outils tournent sur le PC. Les sorties sont Telegram (si on l'utilise),
  le tunnel HTTPS vers l'appli, et OpenStreetMap : Nominatim pour trouver une adresse donnée au planificateur,
  et les tuiles de carte pour les PDF de lieux.
- **Rien n'écoute le réseau** : n8n, le portail et le serveur mails/agenda n'écoutent que `127.0.0.1`. La télémétrie
  de n8n est coupée dans le `.env`.
- **Aperçu puis accord** avant tout envoi, toute action physique, toute suppression et tout téléchargement.
  Les outils l'imposent par une étape obligatoire (essai à blanc, puis `confirmer=oui` ; outils `sensibles` :
  `accord=oui`). Soyons honnêtes : c'est le modèle qui remplit ces champs. Ils l'obligent à poser la question et laissent une trace,
  mais un modèle trompé peut les remplir d'emblée : ce n'est pas une validation humaine hors du modèle. Les autres
  protections réduisent le risque : seul ton chat Telegram est écouté, l'appli exige la clé, le contenu
  extérieur (photo, PDF lu, texte rendu par un outil) est balisé, la liste des actions différées est fermée et la prise du PC est interdite dans le code.
  Une action différée sur une prise demande en plus `accord=oui` au planificateur.
  Prochaine étape : un bouton Telegram « Oui / Non » géré par n8n, hors du modèle.
- **Contenu extérieur ≠ consigne** : un PDF, un mail ou une page web est balisé, et l'agent ne doit pas obéir à
  ce qu'il contient (protection contre l'injection de prompt).
- **Pas de nom inventé** : le vérificateur signale ce qui ne vient d'aucune source.

## Ce qui ne va jamais dans un dépôt
Clés d'API, tokens (Telegram, n8n), `.env`, `secret.xml`, `cle*.txt`, pickles, identifiants n8n, adresse du
tunnel, numéro de chat Telegram, le vrai château (`memoire/`), les journaux, les mails, les positions GPS réelles
(celles des tests sont des points publics de Paris ou des points arbitraires « loin »).
`outils_depot/verifier_depot.py` les cherche à chaque envoi (GitHub Actions, workflow « Tests et secrets ») et fait
échouer le build s'il en trouve. Il n'affiche jamais la valeur trouvée. Les mots personnels de l'auteur (nom, lieux)
sont dans un fichier local ignoré par git (`.local/mots_perso.txt`) : ils ne sont vérifiés que sur son PC, avant
l'envoi. Les positions GPS se vérifient à la main.

## Le portail : ce qui sort du PC, et rien d'autre
`portail/portail.js` (Node seul, sans dépendance) ouvre **deux portes distinctes**, toutes deux sur `127.0.0.1` :

| Porte | Port | Pour qui | Ce qu'elle sert |
|---|---|---|---|
| Page d'accueil | `ARCHI_PORTAIL_PORT` (5680) | le navigateur du PC | la discussion, l'état, le QR code |
| Porte du téléphone | `ARCHI_PORTE_PORT` (5681) | le tunnel HTTPS | une liste blanche, et rien d'autre |

Le tunnel vise la porte du téléphone, jamais n8n ni la page d'accueil. Cette porte ne connaît que :

| Demande | Condition |
|---|---|
| `POST /webhook/telephone-archi` et `/webhook/telephone-boite` | la clé de l'appli, vérifiée **par le portail**, en temps constant, avant n8n |
| `POST` du webhook Telegram | seulement si un bot est branché : le chemin **et** le jeton secret de cette installation, vérifiés par le portail |
| `GET /telephone` | page d'installation de l'appli, sans aucun secret |
| `GET /Archi.apk` | l'appli |

Tout le reste répond 404 : l'éditeur n8n, son API, ses identifiants et la page d'accueil ne sont pas derrière cette
porte. Elle ne se fie à aucun en-tête pour décider : même un relais mal réglé ne lui fait rien servir de plus.
`portail/test/portail.test.js` le vérifie de bout en bout, et `verifier_archi.bat` le revérifie sur le PC installé.

**Ce que la porte retient** : l'heure, la méthode, le chemin (seulement s'il est dans la liste blanche) et le résultat
de chaque passage, dans `donnees/etat/porte.log`. Jamais la clé, les en-têtes, le contenu ni l'adresse de l'appelant.
La page d'accueil s'en sert pour cocher en direct les étapes du téléphone : page ouverte, appli téléchargée, appli
branchée. Juste après le branchement, l'appli appelle la porte pour vérifier la liaison : la porte contrôle la clé
et répond elle-même, sans réveiller l'agent.

**Telegram** : n8n donne à Telegram un jeton secret calculé à partir des identifiants du workflow et du nœud.
Dans un dépôt public, ces identifiants sont connus de tous. `n8n/importer_workflows.py` tire donc au hasard, à
l'installation, l'identifiant du nœud et celui du webhook : le chemin et le jeton sont propres à chaque PC.

La **page d'accueil** n'est servie qu'au navigateur du PC. Elle n'accepte que ses propres appels : même origine et
en-tête maison. Une page web piégée ouverte dans le même navigateur ne peut donc ni lire la clé, ni parler à Archi
à ta place, y compris en faisant pointer son nom de domaine sur `127.0.0.1`.

**Le QR code** contient l'adresse du tunnel et la clé de l'appli.
- Il est caché par défaut sur la page d'accueil et se recache au bout de 2 minutes : une capture d'écran ou une
  vidéo de démonstration ne le publie pas.
- La clé est placée après le `#` du lien : le navigateur du téléphone ne l'envoie jamais sur le réseau, et la page
  l'efface de la barre d'adresse.
- Avant de se brancher, l'appli affiche l'adresse et un **code de 4 caractères**. La page d'accueil du PC affiche
  les mêmes. S'ils diffèrent, le lien ne vient pas de ton PC : on annule. L'appli dit aussi quand un branchement
  existant va être remplacé, et refuse une adresse qui n'est pas en lettres simples (pas de sosie en Unicode).
- Pour changer la clé : vide `ARCHI_CLE_TELEPHONE` dans le `.env`, relance `installation.bat`, puis rescanne.

**Fermer la fenêtre « Archi » ferme tout** : le portail surveille le lanceur. S'il disparaît, il arrête le tunnel
et le serveur, puis s'arrête. L'adresse publique ne reste pas ouverte derrière toi.

**Ce que voit le tunnel** : par défaut, c'est un tunnel Cloudflare « rapide », sans compte. Le trafic entre le
téléphone et le PC est chiffré, mais le chiffrement se termine chez Cloudflare, qui pourrait donc lire les
messages. C'est le prix du « sans compte ». Pour un chiffrement de bout en bout, utilise Tailscale Funnel
(`tailscale funnel 5681`) et mets son adresse dans `WEBHOOK_URL` : le tunnel rapide n'est alors plus lancé.
Sans tunnel (`ARCHI_TUNNEL=non`), Archi marche sur le PC seul.

## La mémoire
- **Tout est local** : c'est le modèle de LM Studio qui relève les faits, et les fiches sont des fichiers Markdown dans
  `chateau/memoire`. Rien ne part ailleurs.
- **Seul ton propre message est lu par le greffier** : ni la description d'une photo, ni une page web, ni un fichier.
  Un contenu venu de l'extérieur ne peut donc pas écrire dans la mémoire.
- **Ce qui n'est jamais retenu tout seul** : mot de passe, code, numéro de carte, IBAN, clé, adresse postale, numéro de
  téléphone. Le filtre est dans le code (`outils/memoire/memoire.py`), après la réponse du modèle.
- **Rien d'inventé** : un fait n'est rangé que s'il reprend des mots de ton message, et le nom d'une personne ou d'un
  lieu doit y figurer. Trois faits au plus par message, sans doublon.
- **Tu gardes la main** : « oublie… » montre d'abord ce qui serait effacé, puis efface après ton accord. Tu peux aussi
  ouvrir, corriger ou supprimer les fiches à la main. `ARCHI_MEMOIRE=non` dans le `.env` coupe la mémoire automatique.

## La voix
- **Tout est local** : ta voix est transcrite sur le PC (whisper.cpp), la réponse est dite par un serveur local
  (Pocket TTS). Aucun son ne part vers un service en ligne.
- **Le serveur de voix n'écoute que `127.0.0.1`**, et il n'est pas derrière la porte du téléphone : le tunnel ne le voit pas.
- **Ce qui est gardé** : les fichiers de travail (la question, la réponse) sont effacés aussitôt ; si un traitement est
  interrompu, ils le sont au message suivant. En revanche n8n range
  l'historique de ses exécutions, sons compris, dans sa base locale (`donnees\n8n`), et l'efface de lui-même au bout de
  quelques jours (14 par défaut). Cette base ne quitte pas le PC.
- **Aucun clonage** : Archi utilise une voix du catalogue de Pocket TTS, et le modèle qu'il télécharge est la version
  « sans clonage de voix ».
- **Le micro de la page d'accueil** ne s'ouvre que sur ton clic, et reste ouvert jusqu'à ce que tu le refermes. Ce
  qu'il entend est transcrit sur le PC et s'écrit dans la ligne de saisie : rien ne part vers l'agent avant « fin de
  transmission » ou la touche Entrée. Pendant qu'Archi réfléchit ou parle, il n'écoute pas.
- **La page d'accueil ne charge rien depuis Internet** : ses polices (Fraunces et Nunito, licence OFL, dans
  `portail/polices`) et ses scripts viennent du PC.

## L'installation
- **Rien pour tout Windows** : Python, Node.js, n8n, le tunnel et ffmpeg sont posés dans le dossier d'Archi.
- **Téléchargements vérifiés** : uv, Node.js, cloudflared, ffmpeg, whisper.cpp, son modèle et Pocket TTS sont pris dans une version précise, et leur
  empreinte SHA-256 est comparée à celle écrite dans `installer/installer.ps1`. Un fichier différent est refusé.
- **Le `.env` gagne** : les variables `N8N_…` ou `WEBHOOK_URL` d'un autre n8n du PC sont retirées de la fenêtre
  d'Archi. Elles ne changent pas son comportement en silence.
- **Le code des workflows** tourne dans le « task runner » de n8n, un processus séparé.

## Limites connues
- L'appli publiée est un build « debug », signé par une clé créée à chaque fabrication. Une version signée par une
  clé stable est la prochaine étape : aujourd'hui, une nouvelle version ne s'installe pas par-dessus l'ancienne.
- n8n n'a pas de compte propriétaire tant que tu n'as pas ouvert son éditeur. Il n'écoute que `127.0.0.1` et
  n'est pas derrière le tunnel, mais crée ce compte si tu utilises l'éditeur.
- Les modèles de LM Studio, le modèle de voix que Pocket TTS télécharge lui-même, et les paquets Python et npm ne sont
  pas vérifiés par empreinte.

## Appli
- La clé partagée est comparée en temps constant côté n8n, par empreinte sha256, avec 16 caractères au minimum.
- L'appli refuse une adresse qui n'est pas en `https://`, et exclut ses réglages de la sauvegarde Android (`allowBackup=false`).
- Elle est stockée dans les préférences privées de l'appli, jamais dans le code ni dans les journaux.
- HTTPS obligatoire : l'appli n'autorise pas le trafic en clair.
- Branchement par QR code (`archi://brancher`) : rien n'est enregistré sans l'accord donné dans l'appli.
