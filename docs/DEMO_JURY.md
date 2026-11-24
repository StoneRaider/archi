# Démo d'Archi : le guide du jury

Archi est un agent IA **entièrement local** : le modèle, l'orchestration, la mémoire, la voix et les outils
tournent sur le PC. Ce guide permet de l'installer sur un PC Windows neuf et de le tester en une dizaine de minutes,
une fois l'installation terminée.

## 1. Télécharger

Sur la page [Releases](../../../releases/latest) du dépôt :

| Fichier | Ce que c'est |
|---|---|
| `Archi-1.2.zip` | La démo complète (le dépôt + l'appli Android déjà compilée). C'est le seul fichier nécessaire. |
| `Archi.apk` | La même appli Android, à part. Facultatif : la page d'accueil du PC la propose par QR code. |

Les deux sont fabriqués par GitHub Actions (workflow `publication.yml`) à partir du code de ce dépôt, après
le contrôle « aucun secret ni donnée personnelle » et les tests. Rien n'est ajouté à la main.

## 2. Ce qu'il faut

- Windows 10 ou 11, 64 bits, une connexion Internet pour l'installation ;
- une carte graphique de 16 Go de mémoire vidéo (le modèle et son contexte de 32k en prennent environ 13,5) ;
  testé sur AMD Radeon RX 9070. Avec moins (par exemple un portable à 8 Go), tout marche, mais les réponses sont lentes ;
- environ 15 Go de place libre (dont 7 Go pour le modèle Qwythos 9B, qui sert aussi pour les photos) ;
- aucun compte à créer, aucune clé API. Telegram est facultatif, la recherche sur le web aussi (clé Tavily gratuite,
  `TAVILY_API_KEY` dans `.env`).

## 3. Installer : un double-clic

1. **Débloquer le ZIP avant de l'extraire** : clic droit sur `Archi-1.2.zip` › Propriétés › cocher « Débloquer » › OK.
   Sans cela, Windows SmartScreen bloque `installation.bat` (fichier venu d'Internet, non signé par un éditeur).
   Si le navigateur retient le téléchargement, choisir « Conserver » dans sa liste des téléchargements.
   Puis extraire le ZIP (clic droit › « Extraire tout »).
2. Double-cliquer sur **`installation.bat`**. Il demande un prénom, si l'on veut Telegram (répondre non suffit) et la
   boîte à outils Docker (oui pour voir les présentations PowerPoint et le globe de l'Œil ; environ 8 Go et
   20 minutes de plus, Windows peut demander un redémarrage : relancer alors `installation.bat`).
   Si LM Studio s'ouvre et propose un modèle, le refuser : l'installateur télécharge Qwythos 9B lui-même.
3. Attendre 15 à 40 minutes selon la connexion. Si Windows affiche malgré tout « Windows a protégé votre ordinateur » :
   « Informations complémentaires », puis « Exécuter quand même ».

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
| « Regarde cette image https://images.unsplash.com/photo-1514888286974-6c03e2ca1dba?w=600 et dis-moi ce que tu vois » | La description de la photo (un chat), faite par le modèle du PC |
| « Cherche sur le web le prix du gaz aujourd'hui » | Sans clé Tavily : « la recherche sur le web n'est pas branchée ». Il ne fait pas semblant |
| « Tu as bien envoyé le mail à Paul hier soir ? » | Il ne sait pas et le dit : aucun mail n'est relié. Il n'invente pas un envoi |
| « Allume le radiateur » | Aucune prise n'est réglée sur un PC neuf : il le dit, et n'annonce rien d'allumé |

Ces quatre dernières lignes sont là exprès : Archi doit dire « je ne sais pas » ou « ce n'est pas branché » plutôt
que d'inventer. Le modèle, petit, écrit parfois l'appel d'un outil au lieu de le lancer : le code le lance alors
lui-même, avec les mêmes contrôles d'accord (`core/appel_en_texte.js`).

Avec un téléphone Android : scanner le QR code de la page d'accueil, installer l'appli, toucher « Brancher l'appli ».
La page du PC coche chaque étape en direct. Ensuite on peut écrire, parler ou envoyer une photo depuis le téléphone :
elle est décrite par le modèle **du PC**.

## 5. Ce qui est vérifiable

- **Local** : débrancher Internet après l'installation ; Archi continue de répondre sur le PC
  (seuls le téléphone, qui passe par le tunnel, et les outils qui lisent le web en ont besoin).
- **Reproductible** : chaque version est fabriquée par GitHub Actions ; les tests tournent à chaque envoi
  (`node --test "core/test/*.test.js" "portail/test/*.test.js"`, et les suites Python de chaque outil, voir le README).
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

Licence : PolyForm Noncommercial 1.0.0 (essai, étude et usage non commercial libres) ; détails dans [LICENCES.md](../LICENCES.md).
