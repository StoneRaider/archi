// texte.js - le texte ramene a une forme comparable, pour les trois pieces (promesses, accord, ordres).
// Port de concours_fable/intendant/texte.py (net) et de `norm` (archi-agent-local/core/verifier_reponse.js).
//
// Pourquoi : en JavaScript, \b et \w ne connaissent que a-z, 0-9 et _. Sur « programmé », « éteinte », « à nouveau »,
// un \b ecrit apres la lettre accentuee ne se declenche pas. Toutes les expressions des pieces sont donc ecrites sans
// accents et appliquees a net(texte). Quand l'accent porte le sens (« Programmé » est un participe, « Programme » un
// imperatif ou un nom), on lit minuscules(texte), accents gardes, avec FIN_DE_MOT a la place de \b.
//
// Aucune fonction ne leve d'exception : null, un objet, un nombre deviennent une chaine (vide dans le doute).
'use strict';

const LIGATURES = { 'œ': 'oe', 'Œ': 'Oe', 'æ': 'ae', 'Æ': 'Ae', 'ß': 'ss' };

/** N'importe quelle valeur, en chaine. Un objet, null, undefined, un symbole : chaine vide (jamais « [object Object] »). */
function chaine(x) {
  if (typeof x === 'string') return x;
  if (typeof x === 'number' && Number.isFinite(x)) return String(x);
  return '';
}

/** Apostrophes, espaces et tirets unifies ; caracteres invisibles retires ; ligatures depliees. Les accents restent. */
function unifier(x) {
  let t = chaine(x);
  try { t = t.normalize('NFC'); } catch (e) { /* une chaine mal formee reste telle quelle */ }
  return t
    .replace(/[\u200b-\u200d\u2060\ufeff\u00ad]/g, '')                 // invisibles (espace sans chasse, cesure)
    .replace(/[’‘\u02bc\u2032`\u00b4]/g, "'")            // ’ ‘ \u02bc \u2032 ` \u00b4
    .replace(/[\u2010-\u2015\u2212]/g, '-')                             // tirets typographiques et signe moins
    .replace(/[\u00a0\u202f\u2000-\u200a\u3000]/g, ' ')                 // espaces insecables et fines
    .replace(/[œŒæÆß]/g, c => LIGATURES[c]);
}

const sansAccents = t => t.normalize('NFD').replace(/[\u0300-\u036f]/g, '');

/** Minuscules, sans accents, apostrophes et espaces unifies, espaces multiples reduits : la forme ou \b est sur. */
function net(x) {
  return sansAccents(unifier(x)).toLowerCase().replace(/\s+/g, ' ').trim();
}

/** Comme net(), mais les retours a la ligne sont gardes (un par ligne) : pour lire un document ligne par ligne. */
function netLignes(x) {
  return unifier(x).split(/\r?\n|\r/).map(net).join('\n');
}

/** Minuscules, apostrophes et espaces unifies, ACCENTS GARDES : pour distinguer « noté » de « note ». */
function minuscules(x) {
  return unifier(x).toLowerCase().replace(/\s+/g, ' ').trim();
}

/** A ecrire a la place de \b apres une lettre accentuee (dans une expression appliquee a minuscules()). */
const FIN_DE_MOT = '(?![a-z0-9\\u00e0-\\u00ff])';

/** Borne une entree AVANT toute expression reguliere. Au-dela de `max` caracteres, on garde le debut et, si `queue`
 *  est donne, aussi la fin (les deux bouts d'un long document), separes par un retour a la ligne. */
function borner(x, max, queue) {
  const t = chaine(x);
  if (t.length <= max) return t;
  const q = Math.min(queue || 0, max);
  return q ? t.slice(0, max - q) + '\n' + t.slice(t.length - q) : t.slice(0, max);
}

/** Ramene a quelques caracteres les suites qui font ramer une expression reguliere : blancs, lignes vides, ponctuation
 *  repetee (« a.....a », « ?!?!?! », « , , , »). A appeler sur un texte deja borne. Chaque passe est lineaire : une
 *  classe de caracteres suivie d'un +, sans rien derriere qui puisse echouer. */
function resserrer(x) {
  return chaine(x)
    .replace(/\r\n?/g, '\n')
    .replace(/[^\S\n]+/g, ' ')                                             // blancs (hors retours a la ligne) -> un espace
    .replace(/ ?\n ?/g, '\n')
    .replace(/\n{3,}/g, '\n\n')                                            // lignes vides -> une seule
    .replace(/[.!?;:,*_()[\]{}<>#|=+~"«»-]{4,}/g, m => m.slice(0, 3))      // ponctuation collee -> 3 signes
    .replace(/(?:[.!?;:,*_()[\]{}<>#|=+~"«»-] ){4,}/g, m => m.slice(0, 6)); // ponctuation espacee -> 3 signes
}

module.exports = { net, netLignes, minuscules, unifier, chaine, borner, resserrer, FIN_DE_MOT };
