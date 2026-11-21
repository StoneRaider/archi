// Les aiguillages des outils branches le 21/11 (agenda, recherche_web, image_lien, monteur) : node --test "core/test/*.test.js"
// Un aiguillage ajoute une consigne au message quand il reconnait la demande. Ici : les nouveaux se declenchent sur leurs
// demandes, pas sur les autres, et les anciens (rappel, lien a lire, oui) gardent leur comportement.
// Les phrases « a tort » viennent de la relecture adversariale du 21/11 (122 phrases).
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const path = require('path');
const contexte = require('../contexte');

const A = contexte.chargerAiguillages(path.join(__dirname, '..', '..', 'config', 'aiguillages.json'));
const consignes = message => contexte.aiguiller(message, A).split('[CONSIGNE ARCHI] ').slice(1).map(c => c.trim());
const a = (message, debut) => consignes(message).some(c => c.startsWith(debut));

const AGENDA = "L'agenda : outil agenda", RAPPEL = 'Rappel ou tache PLUS TARD', WEB = 'Une information recente : outil recherche_web';
const IMAGE = 'Un lien vers une image : outil image_lien', MONTEUR = 'Le monteur video : outil monteur', LIEN = 'Un lien a lire ou a resumer';

test('aiguillages : les fichiers se chargent, et aucun motif n\'est invalide', () => {
  assert.ok(A.length >= 20);
});

test('aiguillages : l\'agenda de l\'utilisateur', () => {
  for (const m of ['Qu\'est-ce que j\'ai dans mon agenda demain ?', 'Ajoute dentiste jeudi 18h à mon agenda', 'Mets un rendez-vous dans le calendrier demain 9h',
    'mon AGENDA de la semaine', 'Regarde mon agenda', 'Est-ce que j\'ai quelque chose à l\'agenda ce soir ?', 'Note dans mon agenda : coiffeur vendredi 10h']) {
    assert.ok(a(m, AGENDA), m);
    assert.ok(!a(m, RAPPEL), 'pas la consigne du rappel pour : ' + m);
  }
});

test('aiguillages : « agenda » ou « calendrier » dans une phrase ordinaire ne declenche pas l\'outil', () => {
  for (const m of ['Quelle heure est-il ?', 'Allume le radiateur', 'c\'est quoi l\'agenda politique du gouvernement ?', 'le calendrier lunaire dit quoi pour planter les tomates',
    'les enfants ont ouvert le calendrier de l\'avent', 'quel est le calendrier de la Ligue 1', 'tu crois qu\'il a un agenda caché ?', 'le calendrier grégorien date de quand ?',
    'écris un mail à Paul pour lui envoyer le calendrier des congés', 'imprime-moi un calendrier 2027 en PDF', 'fais un pdf du calendrier des poubelles',
    'mon agenda papier est tombé dans l\'eau']) assert.ok(!a(m, AGENDA), m);
});

test('aiguillages : un rappel reste un rappel, meme quand il parle d\'un agenda ou d\'un calendrier', () => {
  for (const m of ['Rappelle-moi demain 9h d\'appeler le garagiste', 'Dans 20 min, sors le gâteau', 'Tous les lundis à 9h, sortir les poubelles',
    'Préviens-moi demain matin', 'Rappelle-moi mon rendez-vous chez le dentiste demain 9h',
    'rappelle-moi de regarder mon agenda demain 9h', 'note dans le calendrier de l\'avent qu\'il reste 3 chocolats, et rappelle-le-moi demain',
    'rappelle-moi dans 20 min de sortir le calendrier des poubelles', 'tous les lundis rappelle-moi de vider mon agenda papier',
    'rappelle-moi demain à 10h d\'appeler le garage, c\'est noté dans leur agenda', 'préviens-moi demain quand le calendrier de la Ligue 1 sort',
    'rappelle-moi d\'acheter un agenda 2027 demain 14h', 'mets-moi un rappel dans 2 heures : envoyer le calendrier des congés à Paul',
    'quand j\'arrive au bureau rappelle-moi de synchroniser l\'agenda', 'Rappelle-moi jeudi 18h de prendre mon agenda',
    'pense à me dire demain d\'imprimer le calendrier vaccinal du chien', 'rappelle-moi dans 10 min de fermer Google Agenda',
    'Dans 30 minutes rappelle-moi le calendrier de collecte', 'annule le rappel sur le calendrier des impôts', 'quels sont mes rappels ? et mon agenda ?',
    'rappelle-moi demain 8h : RDV dentiste (pas dans l\'agenda, juste un rappel)', 'rappelle-moi de regarder mon AGENDA demain 9h',
    'rappelle-moi demain 9h de voir l\'agenda.']) {
    assert.ok(a(m, RAPPEL), m);
    assert.ok(!a(m, AGENDA), 'pas la consigne de l\'agenda pour : ' + m);
  }
});

test('aiguillages : la recherche sur le web', () => {
  for (const m of ['Cherche sur internet le prix du gaz', 'Recherche sur le web les horaires de la piscine d\'Dijon', 'Trouve-moi en ligne la date de sortie du film',
    'Regarde sur le net s\'il neige à Gérardmer', 'cherche sur Google le prix du cuivre', 'fais une recherche web sur le prix du cuivre', 'recherche internet : prix du cuivre',
    'Archi, cherche sur internet la météo de demain']) assert.ok(a(m, WEB), m);
  for (const m of ['Cherche dans mes mails la facture', 'Trouve le PDF du bail', 'Quelle est la capitale de l\'Australie ?', 'Cherche des vidéos sur le paillage',
    'regarde, j\'ai commandé en ligne', 'je regarde un film en ligne ce soir', 'tu as des dernières nouvelles de maman ?', 'quelles sont les dernières nouvelles de mon imprimante ?',
    'je trouve que sur le net les gens sont méchants', 'les actualités m\'angoissent, parlons d\'autre chose', 'cherche dans ta mémoire ce que je t\'ai dit sur internet',
    'recherche dans mes PDF le contrat signé en ligne', 'je cherche un stage, ma candidature est en ligne']) assert.ok(!a(m, WEB), m);
  assert.match(consignes('Cherche sur internet le prix du gaz').find(c => c.startsWith(WEB)), /vie privee d'un particulier : la, refuse/);
});

test('aiguillages : une image donnee par son lien, quand on demande de la regarder', () => {
  for (const m of ['Regarde https://exemple.fr/photos/chalet.jpg et dis-moi ce que tu vois', 'c\'est quoi https://exemple.org/a/b.PNG', 'https://exemple.fr/i.webp?taille=2',
    'Que dit https://exemple.fr/affiche.jpeg ?', 'regarde https://exemple.fr/chat.png.', 'https://exemple.fr/chat.png, tu vois quoi ?',
    'décris (https://exemple.fr/chat.png)']) assert.ok(a(m, IMAGE), m);
  for (const m of ['Résume https://exemple.fr/article', 'Lis https://exemple.fr/photo.jpg.html', 'J\'ai une photo en .jpg sur mon PC',
    'envoie https://exemple.fr/a.jpg par mail à Paul', 'télécharge https://exemple.fr/logo.png sur le PC', 'ouvre le lien https://exemple.fr/plan.png dans le navigateur',
    'mets https://exemple.fr/fond.jpg en fond d\'écran']) assert.ok(!a(m, IMAGE), m);
  assert.ok(a('Résume https://exemple.fr/article', LIEN), 'un lien a lire reste un lien a lire');
});

test('aiguillages : le monteur video', () => {
  for (const m of ['Où en est le montage ?', 'Lance le monteur', 'Monte-moi la vidéo de la soirée d\'hier', 'Monte les temps forts de la soirée', 'Arrête le montage',
    'lance un montage vidéo', 'Monte-nous les souvenirs des vacances']) assert.ok(a(m, MONTEUR), m);
  for (const m of ['Le prix du gaz monte encore', 'Monte le chauffage', 'Résume cette vidéo YouTube', 'le montage du meuble Ikea est pénible',
    'où est la notice de montage de la K2 Pro ?', 'explique-moi le montage financier d\'une SCI', 'monte-moi le chauffage pour la soirée', 'monte le volume de la vidéo',
    'monte-nous une soirée sympa samedi', 'je cherche un monteur de pneus', 'combien coûte le montage des pneus neige ?', 'le montage de la buse est tordu',
    'monte les vidéos dans le grenier s\'il te plaît', 'démonte le montage de la prise', 'j\'ai vu un super montage sur YouTube, cherche la vidéo']) assert.ok(!a(m, MONTEUR), m);
});

test('aiguillages : apres un essai a blanc, le oui redit confirmer=oui pour l\'agenda et le monteur', () => {
  const c = consignes('oui').find(x => x.startsWith('L\'utilisateur vient de dire oui'));
  assert.ok(c);
  assert.match(c, /pour une prise \(prises_shelly\), l'agenda ou le monteur, ajoute confirmer=oui/);
});

test('aiguillages : la vie privee d\'un particulier ne se cherche pas non plus par recherche_web', () => {
  const c = consignes('Trouve l\'adresse de mon voisin Paul').find(x => x.startsWith('Coordonnees ou vie privee'));
  assert.ok(c);
  assert.match(c, /ni recherche_web/);
});
