// crochet.js - fait jouer les essais de la relecture adversariale contre le coeur de CE depot.
// Les fichiers d'essais (hors depot) appellent « ../pieces/promesses », « ../pieces/accord », « ../pieces/texte » :
// ce crochet, charge par « node --require », renvoie ces trois noms vers core/. Les autres pieces (ordres.js, qui n'est
// pas dans le coeur) restent celles du dossier d'essais. Rien n'est ecrit sur le disque.
'use strict';
const path = require('path');
const fs = require('fs');
const Module = require('module');
const COEUR = path.join(__dirname, '..', '..', 'core');
const origine = Module._resolveFilename;
Module._resolveFilename = function (demande, parent, ...reste) {
  const m = /(?:^|[\\/])pieces[\\/](promesses|accord|texte)(?:\.js)?$/.exec(String(demande));
  if (m) {
    const cible = path.join(COEUR, m[1] + '.js');
    if (fs.existsSync(cible)) return cible;
  }
  return origine.call(this, demande, parent, ...reste);
};
