// Les aiguillages des outils branches le 21/11 (agenda, recherche_web, image_lien, monteur) : node --test "core/test/*.test.js"
// Un aiguillage ajoute une consigne au message quand il reconnait la demande. Ici : les nouveaux se declenchent sur leurs
// demandes, pas sur les autres, et les anciens (rappel, lien a lire, oui) gardent leur comportement.
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

test('aiguillages : l\'agenda', () => {
  for (const m of ['Qu\'est-ce que j\'ai dans mon agenda demain ?', 'Ajoute dentiste jeudi 18h à mon agenda', 'Mets un rendez-vous dans le calendrier demain 9h', 'mon AGENDA de la semaine']) {
    assert.ok(a(m, AGENDA), m);
    assert.ok(!a(m, RAPPEL), 'pas la consigne du rappel pour : ' + m);
  }
  for (const m of ['Quelle heure est-il ?', 'Raconte-moi une blague', 'Allume le radiateur']) assert.ok(!a(m, AGENDA), m);
});

test('aiguillages : un rappel reste un rappel', () => {
  for (const m of ['Rappelle-moi demain 9h d\'appeler le garagiste', 'Dans 20 min, sors le gâteau', 'Tous les lundis à 9h, sortir les poubelles',
    'Préviens-moi demain matin', 'Rappelle-moi mon rendez-vous chez le dentiste demain 9h']) {
    assert.ok(a(m, RAPPEL), m);
    assert.ok(!a(m, AGENDA), m);
  }
});

test('aiguillages : la recherche sur le web', () => {
  for (const m of ['Cherche sur internet le prix du gaz', 'Recherche sur le web les horaires de la piscine d\'Dijon', 'Trouve-moi en ligne la date de sortie du film',
    'Quelles sont les actualités sur le budget ?', 'Regarde sur le net s\'il neige à Gérardmer']) assert.ok(a(m, WEB), m);
  for (const m of ['Cherche dans mes mails la facture', 'Trouve le PDF du bail', 'Quelle est la capitale de l\'Australie ?', 'Cherche des vidéos sur le paillage']) assert.ok(!a(m, WEB), m);
});

test('aiguillages : une image donnee par son lien', () => {
  for (const m of ['Regarde https://exemple.fr/photos/chalet.jpg et dis-moi ce que tu vois', 'c\'est quoi https://exemple.org/a/b.PNG', 'https://exemple.fr/i.webp?taille=2',
    'Que dit https://exemple.fr/affiche.jpeg ?']) assert.ok(a(m, IMAGE), m);
  for (const m of ['Résume https://exemple.fr/article', 'Lis https://exemple.fr/photo.jpg.html', 'J\'ai une photo en .jpg sur mon PC']) assert.ok(!a(m, IMAGE), m);
  assert.ok(a('Résume https://exemple.fr/article', LIEN), 'un lien a lire reste un lien a lire');
});

test('aiguillages : le monteur video', () => {
  for (const m of ['Où en est le montage ?', 'Lance le monteur', 'Monte-moi la vidéo de la soirée d\'hier', 'Monte les temps forts de la soirée', 'Arrête le montage']) assert.ok(a(m, MONTEUR), m);
  for (const m of ['Le prix du gaz monte encore', 'Monte le chauffage', 'Résume cette vidéo YouTube']) assert.ok(!a(m, MONTEUR), m);
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
