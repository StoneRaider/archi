# Sécurité et vie privée

## Principes
- **Local d'abord** : modèle, mémoire et outils tournent sur le PC. Les sorties sont Telegram (si on l'utilise),
  le tunnel HTTPS vers l'appli, et OpenStreetMap : Nominatim pour trouver une adresse donnée au planificateur,
  et les tuiles de carte pour les PDF de lieux.
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

## Appli
- La clé partagée est comparée en temps constant côté n8n, par empreinte sha256, avec 16 caractères au minimum.
- L'appli refuse une adresse qui n'est pas en `https://`, et exclut ses réglages de la sauvegarde Android (`allowBackup=false`).
- Elle est stockée dans les préférences privées de l'appli, jamais dans le code ni dans les journaux.
- HTTPS obligatoire : l'appli n'autorise pas le trafic en clair.
