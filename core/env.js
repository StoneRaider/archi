// env.js - charge le fichier .env d'Archi dans process.env, sans jamais ecraser une variable deja definie.
//
// Pourquoi : n8n execute le code des workflows dans un processus a part (son « task runner »), qui ne recoit
// qu'une poignee de variables (PATH, fuseau...). Les scripts du coeur, lances depuis ce code, n'heritent donc PAS
// des reglages d'Archi (ARCHI_BASE, ARCHI_PY...) : ils les relisent ici, a la source. Sans cela, ils retomberaient
// en silence sur les dossiers par defaut.
//
// Memes regles de lecture que archi_env.py : NOM=valeur, "valeur" ou 'valeur', commentaire apres « # ».
// Les valeurs ne sont jamais affichees.
'use strict';
const fs = require('fs');
const path = require('path');

const LIGNE = /^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/;

/** {nom: valeur} lu dans le fichier (objet vide s'il est absent) */
function lire(chemin) {
  const valeurs = {};
  let texte;
  try { texte = fs.readFileSync(chemin, 'utf8'); } catch (e) { return valeurs; }
  for (const brut of texte.replace(/^﻿/, '').split(/\r?\n/)) {
    if (!brut.trim() || brut.trimStart().startsWith('#')) continue;
    const m = LIGNE.exec(brut);
    if (!m) continue;
    let v = m[2];
    if (v.length >= 2 && (v[0] === '"' || v[0] === "'") && v.indexOf(v[0], 1) > 0) v = v.slice(1, v.indexOf(v[0], 1));
    else if (v.includes(' #')) v = v.split(' #')[0].trimEnd();
    valeurs[m[1]] = v;
  }
  return valeurs;
}

/**
 * Met le .env dans process.env (sans ecraser) ; rend le nombre de variables ajoutees.
 * Ne fait rien pendant les tests (node --test) ni avec ARCHI_SANS_ENV=1 : un test ne doit jamais
 * travailler dans le vrai chateau.
 */
function charger(chemin) {
  if (!chemin && (process.env.ARCHI_SANS_ENV === '1' || process.env.NODE_TEST_CONTEXT)) return 0;
  chemin = chemin || process.env.ARCHI_ENV || path.join(__dirname, '..', '.env');
  let n = 0;
  const valeurs = lire(chemin);
  for (const nom of Object.keys(valeurs)) {
    if (valeurs[nom] !== '' && process.env[nom] === undefined) { process.env[nom] = valeurs[nom]; n++; }
  }
  return n;
}

module.exports = { lire, charger };
