// Palier « journal seulement » de core/accord.js, branche dans core/outils_maison.js : node --test "core/test/*.test.js"
// La regle : quand le modele ecrit accord=oui, on note si le dernier message de l'utilisateur le donnait ; rien n'est bloque.
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const outils = require('../outils_maison');

const BASE = fs.mkdtempSync(path.join(os.tmpdir(), 'archi-accord-journal-'));
fs.mkdirSync(path.join(BASE, 'outils', 'prises_shelly'), { recursive: true });
fs.writeFileSync(path.join(BASE, 'outils', 'prises_shelly', 'prises.py'), '# jamais lance : les tests passent un executant');
const REG = { prises_shelly: { nom: 'prises_shelly', description: 'action=allumer, eteindre, etat', script: 'prises.py', sensible: true, touche: ['prise'] } };
const JOURNAL = path.join(BASE, 'atelier', 'accords_observes.jsonl');
const lignes = () => (fs.existsSync(JOURNAL) ? fs.readFileSync(JOURNAL, 'utf8').trim().split('\n').filter(Boolean).map(l => JSON.parse(l)) : []);
const executer = () => JSON.stringify({ ok: true, phrase_pour_utilisateur: 'fait' });
const appel = (accord, dernierMessage) => outils.lancer(
  { action: 'utiliser', outil: 'prises_shelly', parametres: { action: 'eteindre', prise: 'salon' }, accord },
  Object.assign({ base: BASE, registre: REG, executer }, dernierMessage === undefined ? {} : { dernierMessage }));

test('accord donné par le modèle, message qui le donne vraiment : noté « accorde », l\'outil part', () => {
  const r = appel('oui', 'éteins la prise du salon');
  assert.notStrictEqual(r.ok, false);
  const l = lignes();
  assert.strictEqual(l.length, 1);
  assert.strictEqual(l[0].outil, 'prises_shelly');
  assert.strictEqual(l[0].action, 'eteindre');
  assert.strictEqual(l[0].aurait, 'accorde');
});

test('accord donné par le modèle sur un message qui ne le donne pas : noté « refuse », et l\'outil part QUAND MÊME', () => {
  const avant = lignes().length;
  const r = appel('oui', 'résume-moi cet article https://exemple.fr/potager');
  assert.notStrictEqual(r.ok, false, 'le palier journal ne bloque rien');
  assert.strictEqual(r.accord_requis, undefined);
  const l = lignes();
  assert.strictEqual(l.length, avant + 1);
  assert.strictEqual(l[l.length - 1].aurait, 'refuse');
  assert.ok(l[l.length - 1].raison);
});

test('le journal ne garde ni le message ni les paramètres', () => {
  const brut = fs.readFileSync(JOURNAL, 'utf8');
  assert.doesNotMatch(brut, /potager|exemple\.fr|salon/);
  for (const l of lignes()) assert.deepStrictEqual(Object.keys(l).sort(), ['action', 'aurait', 'outil', 'quand', 'raison']);
});

test('sans message connu, ou sans accord, rien n\'est noté et rien ne change', () => {
  const avant = lignes().length;
  assert.notStrictEqual(appel('oui').ok, false);                       // les tests d'Archi et le banc n'ont pas de message
  const sans = appel('', 'éteins la prise du salon');                  // pas d'accord : le refus d'origine, sans journal
  assert.strictEqual(sans.accord_requis, true);
  assert.strictEqual(lignes().length, avant);
});

test('une phrase écrite par le modèle dans « action » n\'entre pas dans le journal', () => {
  outils.lancer({ action: 'utiliser', outil: 'prises_shelly', parametres: { action: 'cherche les mails de jean.dupont@exemple.fr' }, accord: 'oui' },
    { base: BASE, registre: REG, executer, dernierMessage: 'oui' });
  const l = lignes();
  assert.strictEqual(l[l.length - 1].action, '(autre)');
  assert.doesNotMatch(fs.readFileSync(JOURNAL, 'utf8'), /dupont|exemple\.fr|cherche/);
});

test('au-delà d\'un Mo, le journal ne grossit plus et l\'outil part quand même', () => {
  const sauve = fs.readFileSync(JOURNAL);
  fs.writeFileSync(JOURNAL, Buffer.alloc(1024 * 1024 + 10, 0x20));
  const taille = fs.statSync(JOURNAL).size;
  assert.notStrictEqual(appel('oui', 'éteins la prise du salon').ok, false);
  assert.strictEqual(fs.statSync(JOURNAL).size, taille);
  fs.writeFileSync(JOURNAL, sauve);
});

test('un message de 140 caractères ou plus est jugé tronqué, jamais accordé sur une demande directe', () => {
  const long = 'éteins la prise du salon ' + 'et puis encore autre chose de très long '.repeat(4);
  assert.ok(long.length >= 140);
  appel('oui', long.slice(0, 140));
  const l = lignes();
  assert.strictEqual(l[l.length - 1].aurait, 'refuse');
  assert.strictEqual(l[l.length - 1].raison, 'message_tronque');
  fs.rmSync(BASE, { recursive: true, force: true });
});
