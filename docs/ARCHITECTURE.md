# Architecture d'Archi

## Les pièces
| Pièce | Rôle | Écoute |
|---|---|---|
| LM Studio | sert gpt-oss-20b et le modèle de vision (API compatible OpenAI) | `127.0.0.1` |
| n8n | l'agent, ses workflows, le réveil du planificateur | `127.0.0.1` |
| `portail/portail.js` | la page d'accueil du PC, et la seule porte ouverte au tunnel du téléphone | `127.0.0.1` |
| tunnel HTTPS | relie le téléphone au portail (Cloudflare sans compte par défaut) | sortant |
| `serveur/` | mails et agenda (FastAPI), appelé par n8n | `127.0.0.1` |
| `chateau\` | la mémoire (fiches Markdown) et les outils maison | fichiers |

`lancer_archi.bat` démarre le tout dans l'ordre : cerveau, portail, tunnel, serveur, puis n8n.
`installation.bat` pose ces pièces sur un PC vide ([INSTALLATION.md](INSTALLATION.md)).

## Un tour de conversation
1. **Entrée.** Un message arrive par Telegram (déclencheur n8n, seulement depuis les chats de `ARCHI_TELEGRAM_CHAT_ID`),
   par l'appli (webhook `telephone-archi`) ou par la page d'accueil du PC, qui passe par ce même webhook.
   Le portail vérifie la clé avant de transmettre à n8n.
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
6. **Sortie.** La réponse part sur Telegram, ou en JSON `{texte}` vers l'appli et la page d'accueil.

## Un outil maison
```
outils/<nom>/
  outil.json   description lue par l'agent (« MODE D'EMPLOI »), paramètres, timeout_s, sensible, touche
  <nom>.py     reçoit --fichier demande.json, écrit UNE ligne JSON à la fin
  tests.json   résumé des tests passés chez moi (date, nombre)
```
Plusieurs outils fournissent leurs tests rejouables (planificateur, mémoire, trader, caméras, imprimante 3D…). Pour
les autres, `tests.json` résume les essais faits sur mon PC avec du vrai matériel.

**Le trader est une simulation.** `outils/trader` gère un portefeuille **fictif** avec les vrais prix publics des
cryptos : aucun compte, aucune clé, aucun ordre réel, et pas de code pour en passer. C'est le modèle local qui décide,
dans des règles écrites dans le programme (liste fermée d'actifs, ni levier ni vente à découvert, part maximale par
actif, coupe-circuit de la semaine). On ne lui dicte pas d'ordre, et il ne donne jamais de conseil.

**La vitrine.** `config/vitrine.json` donne à la page d'accueil le nom lisible de chaque outil, ce qu'il lui faut
(« à brancher »), les outils branchés directement sur l'agent (les enquêtes de Hunter, la lecture d'une page web, les
vidéos YouTube, le navigateur, Wikipédia : la liste `OUTILS_AGENT` de `n8n/fabriquer_workflow.py`) et les projets en cours de
développement. Archi s'en sert aussi pour dire la liste de ses outils.
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

L'APK ne contient **aucune** adresse ni clé. La classe `Reglages` les reçoit du QR code de la page d'accueil
(lien `archi://brancher`, avec accord dans l'appli), ou les demande au premier lancement.

## Ce qui n'est pas dans ce dépôt
Mon château, mes comptes et mes clés. Les outils qui touchent à des comptes (mails, agenda) ou à du matériel
(caméras, prises, imprimante 3D) sont ici, mais débranchés : chacun y met ses propres accès dans le `.env`.
Deux choses de ma version personnelle restent à venir : la voix (whisper.cpp et synthèse locale) et la
synchronisation chiffrée du château entre deux PC.
