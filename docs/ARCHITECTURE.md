# Architecture d'Archi

## Un tour de conversation
1. **Entrée.** Un message arrive par Telegram (déclencheur n8n, seulement depuis les chats de `ARCHI_TELEGRAM_CHAT_ID`)
   ou par l'appli (webhook `telephone-archi`).
   Pour l'appli, le nœud *Porte* vérifie la clé partagée en temps constant. Si une photo est jointe, il la fait
   décrire par le modèle de vision local.
2. **Contexte** (`core/contexte.js`). Il assemble, à chaque message :
   - les faits durables du château (`memoire/preferences/*.md`, blocs « **Faits :** ») ;
   - cinq règles fixes : sources, contenu extérieur, plus tard, capacités, accord ;
   - jusqu'à trois notes de la bibliothèque, trouvées par mots-clés (score titre ×3, corps ×1), sans base vectorielle ;
   - la liste des outils du registre ;
   - les **aiguillages** : si le message ressemble à une demande connue, une consigne précise y est ajoutée.
3. **Agent.** Nœud Agent de n8n, avec gpt-oss-20b servi par LM Studio (API compatible OpenAI), une mémoire courte
   de 10 échanges et **un seul outil**, `outils_maison`. Avec un seul outil générique, le prompt reste court,
   et un nouvel outil n'oblige pas à republier le workflow.
4. **Lanceur** (`core/outils_maison.js`). Il refuse tout nom absent du registre, exige `accord=oui` pour un outil
   `sensible`, puis lance le script Python avec un délai maximal. Il lit la dernière ligne JSON du script
   (`ok`, `phrase_pour_utilisateur`, éventuellement `document` ou `fichier`) et nettoie le fichier de demande.
5. **Vérificateur** (`core/verifier_reponse.js`). Il signale tout nom de personne, mail ou numéro absent des
   résultats d'outils (du tour ou des dernières 24 h), du message ou du château. Il n'efface rien et ne plante
   jamais : en cas de pépin, la réponse passe telle quelle.
6. **Sortie.** La réponse part sur Telegram, ou en JSON `{texte}` vers l'appli.

## Un outil maison
```
outils/<nom>/
  outil.json   description lue par l'agent (« MODE D'EMPLOI »), paramètres, timeout_s, sensible, touche
  <nom>.py     reçoit --fichier demande.json, écrit UNE ligne JSON à la fin
  tests.json   résumé des tests passés chez moi (date, nombre)
```
Dans ce dépôt, seul le planificateur fournit ses tests rejouables (`test_planificateur.py`, 90 tests). Pour les
autres outils, `tests.json` résume les essais faits sur mon PC avec du vrai matériel ; leurs tests rejouables
viendront ensuite.
Un outil reste « en construction » tant que ses tests ne passent pas. Il n'est inscrit au registre
qu'après l'accord de l'utilisateur.

Les garde-fous sont **dans le code de l'outil**, car un modèle de 20 milliards de paramètres ne lit pas toujours
ses consignes. Exemple avec `prises_shelly` et `planificateur` :
- essai à blanc par défaut, et l'action réelle seulement avec `confirmer=oui` ;
- extinction automatique à 180 minutes (720 au plus) ;
- liste blanche des actions différées, et une action ratée de plus d'une heure (PC éteint) n'est pas rejouée ;
- la prise du PC est refusée dans les deux sens.

## L'appli Android (`appli/`)
Elle est écrite en Java, sans bibliothèque externe. Elle propose :
- une sphère animée pour parler ou écrire, avec pièces jointes (photo, document) ;
- un widget et le rôle d'assistant numérique d'Android ;
- une « boîte » (webhook `telephone-boite`, clé vérifiée) qui envoie la position et reçoit les annonces du
  planificateur (rappels à l'heure ou à l'arrivée sur un lieu). Le déclencheur « Chaque minute » de n8n réveille
  le planificateur et envoie les rappels sur Telegram ;
- des actions locales sur le téléphone (appel, SMS, minuteur, itinéraire, musique), lancées seulement quand le PC
  les demande.

L'APK ne contient **aucune** adresse ni clé : la classe `Reglages` les demande au premier lancement.

## Ce qui n'est pas dans ce dépôt
Ma version personnelle compte une vingtaine d'outils : mails Gmail et Outlook, impression 3D avec aperçu
et accord, caméras locales, OSINT sur des lieux publics, voix (whisper.cpp et Piper), synchronisation chiffrée
du château entre deux PC. Ils touchent à des comptes ou à des données personnelles, donc ils restent privés.
L'architecture est la même.
