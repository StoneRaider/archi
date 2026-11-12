# Démo d'Archi : le guide du jury

Archi est un agent IA **entièrement local** : le modèle, l'orchestration, la mémoire, la voix et les outils
tournent sur le PC. Ce guide permet de l'installer sur un PC Windows neuf et de le tester en une dizaine de minutes,
une fois l'installation terminée.

## 1. Télécharger

Sur la page [Releases](../../../releases/latest) du dépôt :

| Fichier | Ce que c'est |
|---|---|
| `Archi-1.0.zip` | La démo complète (le dépôt + l'appli Android déjà compilée). C'est le seul fichier nécessaire. |
| `Archi.apk` | La même appli Android, à part. Facultatif : la page d'accueil du PC la propose par QR code. |

Les deux sont fabriqués par GitHub Actions (workflow `publication.yml`) à partir du code de ce dépôt, après
le contrôle « aucun secret ni donnée personnelle » et les tests. Rien n'est ajouté à la main.

## 2. Ce qu'il faut

- Windows 10 ou 11, 64 bits, une connexion Internet pour l'installation ;
- une carte graphique de 16 Go de mémoire vidéo (12 Go au minimum) ; testé sur AMD Radeon RX 9070 ;
- environ 25 Go de place libre (dont 16 Go pour les modèles : gpt-oss-20b et un modèle de vision) ;
- aucun compte à créer, aucune clé API. Telegram est facultatif.

## 3. Installer : un double-clic

1. Extraire `Archi-1.0.zip` (clic droit › « Extraire tout »).
2. Double-cliquer sur **`installation.bat`**. Il demande un prénom et si l'on veut Telegram (répondre non suffit).
3. Attendre 15 à 40 minutes selon la connexion. Si Windows affiche « Windows a protégé votre ordinateur » :
   « Informations complémentaires », puis « Exécuter quand même » (le fichier n'est pas signé par un éditeur).

Ce qu'il fait, dans l'ordre : Python, Node.js 22, n8n, ffmpeg, le tunnel du téléphone et la voix, tous **dans le
dossier d'Archi** (versions fixes, empreintes SHA-256 vérifiées) ; LM Studio par `winget` s'il manque, puis les modèles ;
le fichier `.env` avec des clés tirées au hasard sur ce PC ; les workflows importés et activés dans n8n.
Le bilan est écrit dans `installation.txt`.

À la fin, la page d'accueil d'Archi s'ouvre dans le navigateur. Les fois suivantes : le raccourci **Archi** du Bureau.

Pour tout contrôler de bout en bout (programmes, ports, workflows, vraie question au modèle, voix) :
double-cliquer sur **`verifier_archi.bat`**.

## 4. Tester en 10 minutes

À écrire (ou à dire au micro) sur la page d'accueil :

| On dit | Ce qu'on doit voir |
|---|---|
| « Quels outils as-tu ? » | La liste de ses outils, en français lisible |
| « Rappelle-moi dans 2 minutes de boire un verre d'eau » | « C'est programmé », puis le rappel qui arrive sur la page 2 minutes plus tard |
| « Mon chien s'appelle Médor » | La réponse, puis « Retenu » : une fiche Markdown créée dans `chateau\memoire` |
| (après avoir relancé Archi) « Comment s'appelle mon chien ? » | « Médor » : la mémoire a survécu au redémarrage |
| « Que sais-tu sur moi ? » | Tout ce qu'il a retenu |
| Clic sur le micro, puis parler, puis « fin de transmission » | La phrase transcrite sur le PC (whisper.cpp), puis une réponse écrite **et parlée** |
| « Résume-moi la page Wikipédia de la tour Eiffel » | Un outil appelé, une réponse sourcée |
| « Fais un tour de trader » | Un tour du trader **en simulation** (1 000 $ fictifs, vrais prix publics, aucun ordre réel) |

Avec un téléphone Android : scanner le QR code de la page d'accueil, installer l'appli, toucher « Brancher l'appli ».
La page du PC coche chaque étape en direct. Ensuite on peut écrire, parler ou envoyer une photo depuis le téléphone :
elle est décrite par le modèle de vision **du PC**.

## 5. Ce qui est vérifiable

- **Local** : débrancher Internet après l'installation ; Archi continue de répondre sur le PC
  (seuls le téléphone, qui passe par le tunnel, et les outils qui lisent le web en ont besoin).
- **Reproductible** : chaque version est fabriquée par GitHub Actions ; les tests tournent à chaque envoi
  (`node --test core/test portail/test`, et les suites Python de chaque outil, voir le README).
- **Pas de secret** : `python outils_depot/verifier_depot.py .` passe avant chaque publication.
- **Appli signée** : l'empreinte de la clé de l'appli est donnée dans [appli/SIGNATURE.md](../appli/SIGNATURE.md)
  (`apksigner verify --print-certs Archi.apk`).
- **Garde-fous dans le code** : voir [SECURITE.md](SECURITE.md) et le tableau « Ce qui rend Archi différent » du README.

## 6. Désinstaller

Fermer la fenêtre d'Archi, puis supprimer le dossier `Archi` du dossier personnel. Seul LM Studio est installé
pour tout Windows (il se désinstalle depuis les Paramètres, s'il n'était pas déjà là).

## Le matériel

Ce que changerait une carte de 32 Go (deux modèles chargés à la fois, contexte de 64k) est décrit dans
[MATERIEL.md](MATERIEL.md).
