// Tests du micro continu de la page d'accueil : le mot magique « fin de transmission » et « Archi, annule ».
//   node --test portail/test/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const E = require('../ecoute.js');

test('ecoute : les phrases s ajoutent tant que le mot magique n est pas dit', () => {
  let r = E.entendre('', 'Bonjour Archi,');
  assert.deepEqual(r, { texte: 'Bonjour Archi,', envoyer: false, annuler: false });
  r = E.entendre(r.texte, ' rappelle-moi   de sortir le chien .');
  assert.deepEqual(r, { texte: 'Bonjour Archi, rappelle-moi de sortir le chien.', envoyer: false, annuler: false });
});

test('ecoute : « fin de transmission » envoie ce qui precede, sans le mot magique', () => {
  assert.deepEqual(E.entendre('Quels outils', 'as-tu ? Fin de transmission.'), { texte: 'Quels outils as-tu ?', envoyer: true, annuler: false });
  assert.deepEqual(E.entendre('Quels outils as-tu ?', 'Fin de transmission'), { texte: 'Quels outils as-tu ?', envoyer: true, annuler: false });
  // ce que Whisper ecrit vraiment
  for (const variante of ['fin de la transmission', 'Faim de transmission !', 'FIN DE TRANSMISSIONS', 'fin de transmition', 'fin  de\ntransmission…']) {
    assert.equal(E.entendre('Bonjour', variante).envoyer, true, variante);
    assert.equal(E.entendre('Bonjour', variante).texte, 'Bonjour', variante);
  }
  // ce qui est dit apres le mot magique ne part pas
  assert.equal(E.entendre('', 'Appelle Léa. Fin de transmission. Euh, attends.').texte, 'Appelle Léa.');
});

test('ecoute : le mot magique seul n envoie pas un message vide', () => {
  assert.deepEqual(E.entendre('', 'Fin de transmission.'), { texte: '', envoyer: false, annuler: false });
  assert.deepEqual(E.entendre('  ', ' fin de transmission '), { texte: '', envoyer: false, annuler: false });
});

test('ecoute : parler de transmission ne declenche rien', () => {
  for (const phrase of ['La transmission de la voiture fait du bruit.', 'À la fin de la réunion, appelle-moi.', 'C est la fin du film.']) {
    const r = E.entendre('', phrase);
    assert.equal(r.envoyer, false, phrase);
    assert.equal(r.texte, phrase.replace(/\s+/g, ' '), phrase);
  }
});

test('ecoute : « Archi, annule » jette tout ce qui attendait', () => {
  assert.deepEqual(E.entendre('Rappelle-moi de', 'non, Archi, annule.'), { texte: '', envoyer: false, annuler: true });
  assert.deepEqual(E.entendre('Bla bla', 'Archi annule'), { texte: '', envoyer: false, annuler: true });
  assert.deepEqual(E.entendre('Bla bla', 'Archi, efface ça'), { texte: '', envoyer: false, annuler: true });
  // on se reprend dans la meme phrase : seule la suite est envoyee
  assert.deepEqual(E.entendre('Appelle Tom', 'Archi, annule. Appelle plutôt Léa. Fin de transmission.'), { texte: 'Appelle plutôt Léa.', envoyer: true, annuler: false });
  // le mot magique d'abord, l'annulation ensuite : trop tard pour envoyer, on jette
  assert.equal(E.entendre('Appelle Tom', 'fin de transmission. Archi, annule').annuler, true);
  // « Archi » dans une phrase ordinaire n'annule rien
  assert.equal(E.entendre('', 'Archi, quels outils as-tu ?').annuler, false);
});
