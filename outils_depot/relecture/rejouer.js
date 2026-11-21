// rejouer.js - rejoue la relecture adversariale (tout.js, puis la sonde neuve sonde2.js) contre le coeur de ce depot.
//
//   node outils_depot/relecture/rejouer.js [dossier des essais] [--ecarts]
//
// Le dossier des essais n'est pas dans le depot (ce sont des phrases d'essai, pas du code) : par defaut
// %ARCHI_RELECTURE%, sinon <dossier personnel>/transposition_archi/relecture_essais. S'il manque, le script le dit et
// sort avec le code 2. Aucun modele n'est charge : ce ne sont que des fonctions pures sur du texte.
'use strict';
const cp = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const args = process.argv.slice(2);
const dossier = args.find(a => !a.startsWith('--')) || process.env.ARCHI_RELECTURE || path.join(os.homedir(), 'transposition_archi', 'relecture_essais');
if (!fs.existsSync(path.join(dossier, 'tout.js'))) { console.error('Dossier des essais introuvable : ' + dossier); process.exit(2); }
const crochet = path.join(__dirname, 'crochet.js');
const env = Object.assign({}, process.env, { NODE_OPTIONS: ((process.env.NODE_OPTIONS || '') + ' --require "' + crochet.replace(/\\/g, '/') + '"').trim() });
let code = 0;
for (const [script, options] of [['tout.js', args.includes('--ecarts') ? ['--ecarts'] : []], ['sonde2.js', args.includes('--ecarts') ? [] : ['--court']]]) {
  if (!fs.existsSync(path.join(dossier, script))) continue;
  console.log('=== ' + script + ' contre core/ ===');
  const r = cp.spawnSync(process.execPath, [script].concat(options), { cwd: dossier, env, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
  process.stdout.write((r.stdout || '') + (r.stderr || ''));
  if (r.status !== 0) code = 1;
}
process.exit(code);
