// Palier « journal seulement » de core/promesses.js, branche dans core/verifier_reponse.js : node --test "core/test/*.test.js"
// La regle : ce que la piece aurait signale part dans « alertes » ; la reponse dite a l'utilisateur ne change pas.
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const cp = require('child_process');

const V = path.join(__dirname, '..', 'verifier_reponse.js');
const BASE = fs.mkdtempSync(path.join(os.tmpdir(), 'archi_journal_'));   // jamais le vrai chateau
const lancer = o => JSON.parse(cp.execFileSync('node', [V], { input: JSON.stringify(o), env: Object.assign({}, process.env, { ARCHI_BASE: BASE }) }).toString());
const pas = (outil, parametres, observation) => ({
  action: { tool: 'outils_maison', toolInput: JSON.stringify({ action: 'utiliser', outil, parametres }) },
  observation: JSON.stringify(observation),
});
const journal = r => r.alertes.filter(a => a.startsWith('[journal] '));

test('journal : « j\'ai éteint la prise » sans outil est noté, la réponse ne change pas', () => {
  const reponse = "C'est fait, j'ai éteint la prise du salon.";
  const r = lancer({ reponse, steps: [], msg: 'eteins la prise du salon' });
  assert.strictEqual(r.reponse, reponse);
  assert.deepStrictEqual(journal(r), ['[journal] promesse en l air : une prise allumée ou éteinte (aucun_outil)']);
});

test('journal : outil en attente d\'accord, outil en échec', () => {
  const attente = lancer({ reponse: "J'ai allumé la prise du radiateur.", msg: 'allume le radiateur',
    steps: [pas('prises_shelly', { action: 'allumer', prise: 'radiateur' }, { ok: false, accord_requis: true, phrase_pour_utilisateur: 'accord' })] });
  assert.strictEqual(attente.reponse, "J'ai allumé la prise du radiateur.");
  assert.deepStrictEqual(journal(attente), ['[journal] promesse en l air : une prise allumée ou éteinte (outil_refuse)']);
  const echec = lancer({ reponse: "J'ai lancé l'impression.", msg: 'lance l impression',
    steps: [pas('imprimante_3d', { action: 'lancer' }, { ok: false, erreur: 'injoignable', phrase_pour_utilisateur: 'echec' })] });
  assert.strictEqual(journal(echec).length, 1);
  assert.match(journal(echec)[0], /outil_en_erreur/);
});

test('journal : une réponse honnête ne laisse aucune ligne', () => {
  for (const [reponse, steps] of [
    ["J'ai éteint la prise du salon.", [pas('prises_shelly', { action: 'eteindre', prise: 'salon', confirmer: 'oui' }, { ok: true, phrase_pour_utilisateur: 'salon : eteinte' })]],
    ['Veux-tu que j\'éteigne la prise du salon ?', []],
    ['La capitale de l\'Australie est Canberra.', []],
    ['Tu as 2 rappels programmés : sortir le gâteau, appeler le garagiste.', [pas('planificateur', { action: 'liste' }, { ok: true, phrase_pour_utilisateur: '2 rappels' })]],
  ]) {
    const r = lancer({ reponse, steps, msg: 'x' });
    assert.strictEqual(r.reponse, reponse, reponse);
    assert.deepStrictEqual(journal(r), [], reponse);
  }
});

test('journal : jamais recopié sous une réponse [TEXTE], ni dans l\'avertissement des rappels', () => {
  const texte = lancer({ reponse: "[TEXTE] J'ai envoyé le mail à Lucien Martinvalle.", steps: [], msg: 'ecris a l ambassadeur' });
  assert.match(texte.reponse, /Vérification automatique/);           // le nom invente reste signale, comme avant
  assert.doesNotMatch(texte.reponse, /journal|promesse en l air/);
  assert.strictEqual(journal(texte).length, 1);
  const rappel = lancer({ reponse: "C'est programmé, je te préviendrai.", steps: [], msg: 'rappelle-moi' });
  assert.deepStrictEqual(rappel.alertes, ['promesse sans planificateur']);   // la regle d'origine sort la premiere, inchangee
  assert.doesNotMatch(rappel.reponse, /journal/);
});

test('journal : des pas illisibles ou une pièce absente ne cassent jamais la réponse', () => {
  const r = lancer({ reponse: 'Bonjour !', steps: [null, 5, 'x', { action: null, observation: {} }], msg: 'bonjour' });
  assert.strictEqual(r.reponse, 'Bonjour !');
  assert.deepStrictEqual(r.alertes, []);
  fs.rmSync(BASE, { recursive: true, force: true });
});
