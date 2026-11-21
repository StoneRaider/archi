// Les regles fixes du prompt (core/contexte.js) : node --test "core/test/*.test.js"
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

process.env.ARCHI_BASE = fs.mkdtempSync(path.join(os.tmpdir(), 'archi_regles_'));   // jamais le vrai chateau
const contexte = require('../contexte');
const profil = contexte.construire({ texte: 'salut' }).profil;
const regles = profil.split('\n').filter(l => l.startsWith('- RÈGLE '));

test('regles : « je ne sais pas » est dans le prompt, avec quoi faire a la place', () => {
  const r = regles.find(l => l.startsWith('- RÈGLE JE NE SAIS PAS'));
  assert.ok(r);
  assert.match(r, /tu ne devines pas/);
  assert.match(r, /appelle l'outil qui le sait/);
  assert.match(r, /« je ne sais pas »/);
  assert.match(r, /culture générale/);      // sans cette phrase, un petit modele refuserait de dire la capitale de l'Australie
});

test('regles : « c\'est fait » seulement si l\'outil le dit ; un echec ou un essai a blanc se disent', () => {
  const r = regles.find(l => l.startsWith('- RÈGLE ACCORD'));
  assert.match(r, /qu'après la réponse d'un outil qui dit que c'est fait/);
  assert.match(r, /PAS ENCORE FAIT/);
  assert.match(r, /ce n'est pas fait/);
});

test('regles : sept regles, et un prompt qui reste court (reactivite)', () => {
  assert.strictEqual(regles.length, 7);
  // 2 178 caracteres le 21/11 (environ 620 de plus qu'avant la regle « je ne sais pas ») ;chaque caractere ici est relu par le modele a CHAQUE message
  assert.ok(regles.join('\n').length < 2600, String(regles.join('\n').length));
});
