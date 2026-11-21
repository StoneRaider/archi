// mesure_promesses.js - compte, raison par raison, ce que core/promesses.js signale sur les essais de la relecture.
//
//   node --require ./outils_depot/relecture/crochet.js outils_depot/relecture/mesure_promesses.js [dossier des essais]
//
// Sert a decider quelles raisons peuvent etre DITES a l'utilisateur (zero avertissement a tort exige) et lesquelles
// restent au journal. Lecture seule, aucun modele.
'use strict';
const os = require('os');
const path = require('path');
const dossier = process.argv[2] || process.env.ARCHI_RELECTURE || path.join(os.homedir(), 'transposition_archi', 'relecture_essais');
const { promessesEnLAir, actesDesSteps } = require('../../core/promesses');
const journal = console.log;
console.log = () => {};
let p1, p2;
try { p1 = require(path.join(dossier, 'p1.js')); p2 = require(path.join(dossier, 'p2.js')); } finally { console.log = journal; }

function compter(nom, cas) {
  const parRaison = {}; let avecEchec = 0, signales = 0;
  for (const [s, rep] of cas) {
    const pas = p1.S[s];
    if (actesDesSteps(pas).some(a => a.statut === 'erreur' || a.statut === 'attente_accord')) avecEchec++;
    const r = promessesEnLAir(rep, pas);
    if (r.length) signales++;
    for (const raison of new Set(r.map(x => x.raison))) parRaison[raison] = (parRaison[raison] || 0) + 1;
  }
  journal(nom + ' : ' + cas.length + ' réponses, dont ' + avecEchec + ' après un outil en échec ou en attente d\'accord ; '
    + signales + ' signalées ' + JSON.stringify(parRaison));
}
compter('honnêtes (attendu : 0 signalée)', p1.honnetes.concat(p2.honnetes));
compter('mensonges (attendu : toutes signalées)', p2.mensonges);
