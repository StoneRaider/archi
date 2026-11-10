// Tests du logo dans le texte : partout ou le mot « Archi » est ecrit, la page pose le dessin du logo.
//   node --test portail/test/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const L = require('../logo.js');

const mots = t => L.decouper(t).filter(x => typeof x !== 'string').map(x => x.archi);

test('logo : le mot « Archi » est repere, quelle que soit sa casse, et le reste du texte est garde tel quel', () => {
  assert.deepEqual(L.decouper('Salut, je suis Archi.'), ['Salut, je suis ', { archi: 'Archi' }, '.']);
  assert.deepEqual(L.decouper('Archi, annule'), [{ archi: 'Archi' }, ', annule']);
  assert.deepEqual(L.decouper("La sphère d'Archi"), ["La sphère d'", { archi: 'Archi' }]);
  assert.deepEqual(L.decouper('ARCHI et archi'), [{ archi: 'ARCHI' }, ' et ', { archi: 'archi' }]);
  assert.deepEqual(mots('« Archi » réfléchit… Archi ! Archi ? (Archi) Archi: Archi; Archi'), ['Archi', 'Archi', 'Archi', 'Archi', 'Archi', 'Archi', 'Archi']);
  assert.deepEqual(mots('Archi. Fin.'), ['Archi']);
  // remis bout a bout, c'est le texte d'origine
  for (const t of ['Bonjour Archi, ça va ?', 'rien ici', '', 'Archi', 'Archi Archi']) {
    assert.equal(L.decouper(t).map(x => (typeof x === 'string' ? x : x.archi)).join(''), t);
  }
  assert.deepEqual(L.decouper(''), []);
  assert.deepEqual(L.decouper(null), []);
  assert.deepEqual(L.decouper('Bonjour Camille.'), ['Bonjour Camille.']);
});

test('logo : pas dans un autre mot, un nom de fichier, un chemin, une adresse', () => {
  for (const t of ['architecte', 'archiduc', 'archiépiscopal', 'Archie', 'anarchie', 'archi-agent-local', 'mon-archi', 'Archi.apk', 'archi_demo.json',
    'C:\\Users\\moi\\essai_archi\\Archi\\chateau', 'essai/Archi/lancer_archi.bat', '@archi', 'moi@Archi', 'https://archi.exemple', 'Archi2', 'ArchiSphere']) {
    assert.deepEqual(mots(t), [], t);
  }
  // deux appels de suite : la recherche repart du debut (pas d'etat garde entre deux textes)
  assert.deepEqual(mots('Archi'), ['Archi']);
  assert.deepEqual(mots('Archi'), ['Archi']);
});
