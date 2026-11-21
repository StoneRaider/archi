// Le tour du jour du trader (core/tournees.js) : node --test "core/test/*.test.js"
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const tournees = require('../tournees');

function chateau() {
  const B = fs.mkdtempSync(path.join(os.tmpdir(), 'archi-tour-trader-'));
  for (const [d, s] of [['curateur', 'curateur.py'], ['mecanicien', 'mecanicien.py'], ['trader', 'trader.py']]) {
    fs.mkdirSync(path.join(B, 'outils', d), { recursive: true });
    fs.writeFileSync(path.join(B, 'outils', d, s), '');
  }
  const lancees = [];
  const r = (y, mo, j, h, mi) => tournees.reveiller({ base: B, maintenant: new Date(y, mo - 1, j, h, mi), lancer: s => lancees.push(path.basename(s)) });
  return { B, lancees, r };
}

test('tour du trader : chaque jour a 18 h, une seule fois, jamais a la premiere minute d\'Archi', () => {
  const { lancees, r } = chateau();
  assert.strictEqual(r(2026, 11, 16, 17, 0).raison, 'premiere fois');       // lundi 16, 17 h
  for (let m = 1; m <= 59; m++) r(2026, 11, 16, 17, m);
  assert.deepStrictEqual(lancees, []);
  for (let m = 0; m <= 30; m++) r(2026, 11, 16, 18, m);
  assert.deepStrictEqual(lancees, ['trader.py']);
  for (let h = 19; h <= 23; h++) for (let m = 0; m < 60; m += 1) r(2026, 11, 16, h, m);
  assert.strictEqual(lancees.length, 1, 'un seul tour par jour');
  for (let m = 0; m <= 10; m++) r(2026, 11, 17, 18, m);                       // mardi : PC rallume a 18 h, 5 minutes d'attente
  assert.deepStrictEqual(lancees, ['trader.py', 'trader.py']);
});

test('tour du trader : une installation qui avait deja ses tournees ne le lance pas d\'office a la mise a jour', () => {
  const { B, lancees, r } = chateau();
  const f = path.join(B, 'atelier', 'tournees.json');
  const hier = new Date(2026, 10, 18, 12, 0).toISOString();                  // mercredi midi : curateur et mecanicien sont a jour
  fs.mkdirSync(path.dirname(f), { recursive: true });
  fs.writeFileSync(f, JSON.stringify({ premiere: hier, vu: new Date(2026, 10, 18, 19, 59).toISOString(), depuis: hier, curateur: hier, mecanicien: hier }));   // pas de « trader »
  for (let m = 0; m <= 30; m++) r(2026, 11, 18, 20, m);                       // mercredi 20 h : le creneau de 18 h est passe
  assert.deepStrictEqual(lancees, [], 'pas de rattrapage pour une tournee qui vient d\'apparaitre');
  assert.ok(JSON.parse(fs.readFileSync(f, 'utf8')).trader);
  for (let m = 0; m <= 5; m++) r(2026, 11, 19, 18, m);                        // le lendemain 18 h : le premier tour
  assert.deepStrictEqual(lancees, ['trader.py']);
});

test('tour du trader : ARCHI_TRADER_AUTO=non le coupe, sans couper le curateur', () => {
  const { lancees, r } = chateau();
  process.env.ARCHI_TRADER_AUTO = 'non';
  try {
    r(2026, 11, 21, 9, 0);                                                    // samedi
    for (let m = 1; m <= 10; m++) r(2026, 11, 21, 9, m);
    for (let m = 0; m <= 10; m++) r(2026, 11, 21, 18, m);
    assert.deepStrictEqual(lancees, []);
    for (let m = 0; m <= 10; m++) r(2026, 11, 22, 10, m);                     // dimanche 10 h : le curateur part quand meme
    assert.deepStrictEqual(lancees, ['curateur.py']);
  } finally { delete process.env.ARCHI_TRADER_AUTO; }
});

test('tour du trader : « 0 », « false », « Non », « non # coupe » le coupent aussi ; remis en route, pas de tour de rattrapage', () => {
  for (const valeur of ['0', 'false', 'False', ' Non ', 'no', 'off', 'faux', 'non # coupe', 'non;']) {
    const { lancees, r } = chateau();
    process.env.ARCHI_TRADER_AUTO = valeur;
    try {
      r(2026, 11, 16, 17, 0);
      for (let m = 1; m <= 10; m++) r(2026, 11, 16, 17, m);
      for (let m = 0; m <= 10; m++) r(2026, 11, 16, 18, m);
      assert.deepStrictEqual(lancees, [], valeur);
    } finally { delete process.env.ARCHI_TRADER_AUTO; }
  }
  const { lancees, r } = chateau();
  process.env.ARCHI_TRADER_AUTO = 'non';
  try {
    r(2026, 11, 16, 9, 0);                                                    // lundi : coupe trois jours
    for (const j of [16, 17, 18]) for (let h = 9; h <= 20; h++) for (let m = 0; m < 60; m += 2) r(2026, 11, j, h, m);
  } finally { delete process.env.ARCHI_TRADER_AUTO; }
  for (let m = 0; m <= 30; m++) r(2026, 11, 19, 10, m);                       // jeudi 10 h : remis a « oui »
  assert.deepStrictEqual(lancees.filter(x => x === 'trader.py'), [], 'pas de tour de rattrapage a 10 h');
  for (let m = 0; m <= 10; m++) r(2026, 11, 19, 18, m);
  assert.deepStrictEqual(lancees.filter(x => x === 'trader.py'), ['trader.py'], 'le tour reprend au creneau suivant');
});

test('tour du trader : Python introuvable, le reveil ne plante pas', async () => {
  const B = fs.mkdtempSync(path.join(os.tmpdir(), 'archi-tour-py-'));
  fs.mkdirSync(path.join(B, 'outils', 'trader'), { recursive: true });
  fs.writeFileSync(path.join(B, 'outils', 'trader', 'trader.py'), '');
  process.env.ARCHI_PY = path.join(B, 'python_absent.exe');
  try {
    tournees.reveiller({ base: B, maintenant: new Date(2026, 10, 16, 17, 0) });
    for (let m = 1; m <= 10; m++) tournees.reveiller({ base: B, maintenant: new Date(2026, 10, 16, 17, m) });
    assert.doesNotThrow(() => tournees.reveiller({ base: B, maintenant: new Date(2026, 10, 16, 18, 0) }));
    await new Promise(ok => setTimeout(ok, 300));      // l'erreur de lancement arrive apres coup : elle ne doit rien casser
  } finally { delete process.env.ARCHI_PY; }
});

test('tour du trader : sans l\'outil trader dans le chateau, rien ne part', () => {
  const { B, lancees, r } = chateau();
  fs.rmSync(path.join(B, 'outils', 'trader'), { recursive: true });
  r(2026, 11, 16, 17, 0);
  for (let m = 1; m <= 10; m++) r(2026, 11, 16, 17, m);
  for (let m = 0; m <= 10; m++) r(2026, 11, 16, 18, m);
  assert.deepStrictEqual(lancees, []);
});
