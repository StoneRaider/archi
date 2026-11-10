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
Le tunnel HTTPS du téléphone ne mène pas à n8n. Il mène au **portail** (`portail/portail.js`, Node seul, sans
dépendance), qui applique une liste blanche. Depuis Internet, seuls passent :

| Demande | Condition |
|---|---|
| `POST /webhook/telephone-archi` et `/webhook/telephone-boite` | la clé de l'appli, vérifiée **par le portail**, en temps constant, avant n8n |
| `POST /webhook/…/webhook` (Telegram) | seulement si un bot est branché ; n8n vérifie le jeton secret de Telegram |
| `GET /telephone` | page d'installation de l'appli, sans aucun secret |
| `GET /Archi.apk` | l'appli |

Tout le reste répond 404 : l'éditeur n8n, son API, ses identifiants et la page d'accueil ne sont pas joignables
de l'extérieur, même avec l'adresse du tunnel. `portail/test/portail.test.js` le vérifie de bout en bout.

La **page d'accueil** (`http://127.0.0.1:5680`) n'est servie qu'au navigateur du PC. Elle n'accepte que ses
propres appels : même origine et en-tête maison. Une page web piégée ouverte dans le même navigateur ne peut donc
ni lire la clé, ni parler à Archi à ta place, y compris en faisant pointer son nom de domaine sur `127.0.0.1`.

**Le QR code** contient l'adresse du tunnel et la clé de l'appli. La clé est placée après le `#` du lien : le
navigateur du téléphone ne l'envoie jamais sur le réseau, elle passe seulement du QR code à l'appli. L'appli
affiche l'adresse et demande un accord avant de s'y brancher : un lien piégé ne peut pas la rediriger en douce.

**Ce que voit le tunnel** : par défaut, c'est un tunnel Cloudflare « rapide », sans compte. Le trafic entre le
téléphone et le PC est chiffré, mais le chiffrement se termine chez Cloudflare, qui pourrait donc lire les
messages. C'est le prix du « sans compte ». Pour un chiffrement de bout en bout, utilise Tailscale Funnel et
mets son adresse dans `WEBHOOK_URL` : le tunnel rapide n'est alors plus lancé. Sans tunnel (`ARCHI_TUNNEL=non`),
Archi marche sur le PC seul.

## Appli
- La clé partagée est comparée en temps constant côté n8n, par empreinte sha256, avec 16 caractères au minimum.
- L'appli refuse une adresse qui n'est pas en `https://`, et exclut ses réglages de la sauvegarde Android (`allowBackup=false`).
- Elle est stockée dans les préférences privées de l'appli, jamais dans le code ni dans les journaux.
- HTTPS obligatoire : l'appli n'autorise pas le trafic en clair.
- Branchement par QR code (`archi://brancher`) : rien n'est enregistré sans l'accord donné dans l'appli.
