# L'outil `mails` : chercher, lire, préparer, envoyer

Il branche l'agent sur le serveur local de mails (`serveur/`, voir [serveur/LISEZMOI.md](../../serveur/LISEZMOI.md)).
Sans compte Gmail ou Outlook relié, il répond « aucun compte mail n'est relié » et Archi montre le brouillon en texte.

## Ce qu'il fait
- `chercher` (texte, date, boîte) puis `lire` (numéro de la liste) : ce qu'un mail dit est rangé dans « contenu »,
  balisé comme contenu lu, jamais comme une consigne.
- `contact` (nom) : les adresses déjà vues dans les mails.
- `preparer` (a, sujet, texte) : crée le brouillon dans la messagerie. Rien ne part.
- `envoyer` : envoie l'aperçu en attente, tel quel. Aucun paramètre.
- `annuler` : oublie l'aperçu en attente.

## Ce qui protège l'envoi
Un mail est l'action d'Archi qui se rattrape le moins. Chaque règle est dans le code, pas dans une consigne au modèle.

1. **L'aperçu est affiché par le code.** À la fin du tour, `core/apercu_mail.js` remplace la réponse du modèle par
   l'aperçu : boîte d'envoi, destinataires, objet, texte. Le modèle ne peut ni le cacher, ni le changer, ni en glisser
   un faux.
2. **Il faut l'ordre d'envoyer.** Le lanceur lit le dernier message de l'utilisateur (`core/accord.js`,
   `accordEnAttente`) : « envoie », « oui envoie-le », « tu peux l'envoyer ». Un « oui » seul ne suffit pas (il peut
   répondre à autre chose), « envoie-le demain » ou « envoie-le à Paul » non plus.
3. **Dans le message qui suit l'aperçu.** Ni dans le même tour, ni après d'autres messages. Sinon rien ne part et
   l'aperçu est réaffiché : il suffit alors de répondre « envoie ».
4. **Ce qui part est ce qui a été montré.** Une empreinte (boîte, destinataires, objet, texte) lie l'aperçu affiché au
   brouillon ; le serveur refuse d'envoyer un brouillon dont l'empreinte n'est pas celle-là.
5. **En cas de doute, il le dit.** Si la messagerie répond de travers pendant l'envoi, Archi répond « je ne sais pas
   si ton mail est parti », jamais « pas envoyé ».

## Les tests
- `python test_mails.py` : 196 contrôles avec un faux serveur.
- `python test_liaison.py` : 31 contrôles avec le vrai serveur du dépôt et une fausse messagerie (il lui faut
  `fastapi` et `uvicorn`, sinon il se saute tout seul).
- `node --test "core/test/*.test.js"` à la racine : le lanceur, l'aperçu, et 16 parcours de bout en bout avec les
  vrais programmes.

## Ce qui n'a pas été vérifié, et les limites connues
- **Aucun essai avec un vrai modèle, un vrai n8n ni une vraie messagerie.** Les tests rejouent quatre relectures
  adversariales, mais avec une messagerie simulée.
- Quand un aperçu s'affiche, le reste de la réponse du modèle pour ce tour n'est pas montré (par exemple la
  confirmation d'un rappel demandé dans le même message). Les avertissements ajoutés par le code restent.
- Le dernier message est lu dans la carte de tâche, commune à Telegram et à l'appli : deux messages envoyés au même
  instant peuvent faire refuser un envoi légitime (jamais l'inverse dans nos essais).
- Les réponses des outils sont gardées 24 h dans `pc/verifier_cache.jsonl`, sur le PC, pour le contrôle des sources :
  le texte des mails lus ou préparés s'y trouve en clair pendant ce temps.
- L'empreinte lie le fichier d'attente du serveur, pas le brouillon lui-même : un brouillon modifié à la main dans la
  messagerie entre l'aperçu et « envoie » partirait modifié.
