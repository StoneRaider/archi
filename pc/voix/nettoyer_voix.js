// nettoyer_voix.js - appele par le noeud « Nettoyer pour Piper » d'Archi_Telegram (texte sur l'entree standard).
// Nettoyer pour Piper v2 : transforme la reponse d'Archi en francais "a dire a voix haute".
// Chiffres, dates, heures, montants, pourcentages, sigles, emojis, ponctuation et retours a la ligne.
const brut = (globalThis.__TEST__ !== undefined) ? globalThis.__TEST__ : require('fs').readFileSync(0, 'utf8');

const U = ['zéro','un','deux','trois','quatre','cinq','six','sept','huit','neuf','dix','onze','douze','treize','quatorze','quinze','seize','dix-sept','dix-huit','dix-neuf'];
const D = ['', '', 'vingt', 'trente', 'quarante', 'cinquante', 'soixante', 'soixante', 'quatre-vingt', 'quatre-vingt'];
function cent(n) { // 0..99
  if (n < 20) return U[n];
  const d = Math.floor(n / 10), u = n % 10;
  if (d === 7 || d === 9) return D[d] + (u === 1 && d === 7 ? ' et ' : '-') + U[10 + u];
  if (u === 0) return d === 8 ? 'quatre-vingts' : D[d];
  if (u === 1 && d !== 8) return D[d] + ' et un';
  return D[d] + '-' + U[u];
}
function mille(n) { // 0..999
  const c = Math.floor(n / 100), r = n % 100;
  let s = '';
  if (c > 0) s = (c === 1 ? 'cent' : U[c] + ' cent' + (r === 0 ? 's' : ''));
  if (r > 0) s += (s ? ' ' : '') + cent(r);
  return s || 'zéro';
}
function lettres(n) {
  n = Math.floor(Math.abs(n));
  if (n === 0) return 'zéro';
  const parts = [];
  const md = Math.floor(n / 1e9), mi = Math.floor(n / 1e6) % 1000, k = Math.floor(n / 1000) % 1000, r = n % 1000;
  if (md) parts.push(mille(md) + (md > 1 ? ' milliards' : ' milliard'));
  if (mi) parts.push(mille(mi) + (mi > 1 ? ' millions' : ' million'));
  if (k) parts.push(k === 1 ? 'mille' : mille(k).replace(/(cent|vingt)s$/, '$1') + ' mille');
  if (r) parts.push(mille(r));
  return parts.join(' ');
}
const MOIS = ['janvier','février','mars','avril','mai','juin','juillet','août','septembre','octobre','novembre','décembre'];
const jour = j => (+j === 1 ? 'premier' : lettres(+j));
function annee(a) { return lettres(+a); }
function nb(txt) { // "1 234,56" / "3.9" / "1.234.567" -> mots
  let t = txt.replace(/[\s\u202f\u00a0]/g, '');
  if (/^-?\d{1,3}(\.\d{3})+(,\d+)?$/.test(t)) t = t.replace(/\./g, '');   // 1.234.567 = milliers
  t = t.replace(',', '.');                                                   // virgule ou point = decimales
  const neg = t.startsWith('-');
  const [e, d] = t.replace('-', '').split('.');
  let s = (neg ? 'moins ' : '') + lettres(+e);
  if (d && /^\d+$/.test(d) && +d > 0) {
    const dd = d.replace(/0+$/, '');
    s += ' virgule ' + (dd.length <= 2 && dd[0] !== '0' ? lettres(+dd) : dd.split('').map(c => U[+c]).join(' '));
  }
  return s;
}

let t = brut;
t = t.replace(/^\s*\[?\s*(texte|vocal)\s*\]?\s*:?\s*/i, '');            // etiquette
t = t.replace(/```[\s\S]*?```/g, ' ');                                   // blocs de code
t = t.replace(/\[(.*?)\]\(.*?\)/g, '$1');                                // liens markdown
t = t.replace(/https?:\/\/\S+|www\.\S+/g, ' ');                           // liens
t = t.replace(/[\w.+-]+@([\w-]+)\.[\w.]+/g, (m, dom) => 'une adresse ' + dom); // mails
t = t.replace(/\b[A-Z]:\\\S+/g, ' ');                                    // chemins Windows
t = t.replace(/\.(md|json|txt|csv|py|js|wav|mp3|pdf|ogg)\b/gi, '');
t = t.replace(/\p{Extended_Pictographic}|\p{Emoji_Modifier}|‍|️/gu, ' '); // emojis
t = t.replace(/^\s*(RE|TR|FW|Fwd)\s*:\s*/gim, '');                        // RE: TR:
t = t.replace(/\b(RE|TR|FW|Fwd)\s*:\s*/g, '');

// titres et listes (avant les nombres, sinon "1." devient "un.")
t = t.replace(/^\s*#+\s*(.*)$/gm, '$1.');
t = t.replace(/^\s*(?:[-•*]|\d+[.)])\s+/gm, '');
t = t.replace(/\bRDV\b/g, 'rendez-vous').replace(/\bSMS\b/g, 'texto');
// dates
t = t.replace(/\b(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{1,2}):(\d{2}))?/g, (m, a, mo, j, h, mi) =>
  `${jour(j)} ${MOIS[+mo - 1] || mo} ${annee(a)}` + (h ? ` à ${heure(h, mi)}` : ''));
t = t.replace(/\b(\d{1,2})\/(\d{1,2})\/(\d{2,4})\b/g, (m, j, mo, a) =>
  `${jour(j)} ${MOIS[+mo - 1] || mo} ${annee(a.length === 2 ? '20' + a : a)}`);
t = t.replace(/\b(\d{1,2})\/(\d{1,2})\b/g, (m, j, mo) => (+mo >= 1 && +mo <= 12 && +j <= 31) ? `${jour(j)} ${MOIS[+mo - 1]}` : `${lettres(+j)} sur ${lettres(+mo)}`);
t = t.replace(/\b1er\b/g, 'premier');
// heures
function heure(h, mi) {
  const hh = +h, mm = +(mi || 0);
  let s = hh === 0 ? 'minuit' : hh === 12 ? 'midi' : (hh === 1 ? 'une heure' : lettres(hh).replace(/un$/, 'une') + ' heures');
  if (mm) s += ' ' + (mm === 1 ? 'une' : lettres(mm));
  return s;
}
t = t.replace(/\b(\d{1,2})\s?[hH:]\s?(\d{2})\b/g, (m, h, mi) => heure(h, mi));
t = t.replace(/\b(\d{1,2})\s?h\b/g, (m, h) => heure(h, 0));
// montants, pourcentages, unites
const NUM = '(-?\\d{1,3}(?:[\\s\\u202f\\u00a0.]\\d{3})+(?:,\\d+)?|-?\\d+(?:[.,]\\d+)?)';
t = t.replace(new RegExp(NUM + '\\s?(?:€|EUR\\b|euros?\\b)', 'g'), (m, n) => {
  const c = n.replace(/[\s  ]/g, '').replace(/\.(?=\d{3}\b)/g, '').replace(',', '.');
  const [e, d] = c.split('.');
  let s = nb(e) + (Math.abs(+e) > 1 ? ' euros' : ' euro');
  if (d && +d.padEnd(2, '0').slice(0, 2) > 0) s += ' ' + lettres(+d.padEnd(2, '0').slice(0, 2));
  return s;
});
t = t.replace(new RegExp('\\$\\s?' + NUM + '|' + NUM + '\\s?\\$', 'g'), (m, a, b) => nb(a || b) + ' dollars');
t = t.replace(/CHF\s?(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s?CHF/g, (m, a, b) => nb(a || b) + ' francs suisses');
t = t.replace(new RegExp(NUM + '\\s?%', 'g'), (m, n) => nb(n) + ' pour cent');
t = t.replace(new RegExp(NUM + '\\s?°C?', 'g'), (m, n) => nb(n) + ' degrés');
t = t.replace(new RegExp(NUM + '\\s?km\\b', 'g'), (m, n) => nb(n) + ' kilomètres');
t = t.replace(/(\d)\s?[x×]\s?(?=\d)/g, '$1 sur ');                 // dimensions 51 x 20 -> 51 sur 20
const UNITES = { 'mm': 'millimètres', 'cm': 'centimètres', 'm': 'mètres', 'kg': 'kilos', 'g': 'grammes', 'kWh': 'kilowattheures',
  'kW': 'kilowatts', 'W': 'watts', 'V': 'volts', 'Go': 'gigaoctets', 'Mo': 'mégaoctets', 'min': 'minutes', 's': 'secondes', 'l': 'litres', 'L': 'litres' };
for (const [u, mot] of Object.entries(UNITES))
  t = t.replace(new RegExp(NUM + '\\s?' + u + '(?![\\wÀ-ÿ])', 'g'), (m, n) => nb(n) + ' ' + mot);
t = t.replace(/\bn°\s?(\d+)/gi, (m, n) => 'numéro ' + lettres(+n));
t = t.replace(/\b(\d+)(?:er|ère|e|ème)\b/g, (m, n) => +n === 1 ? 'premier' : lettres(+n) + 'ième');
t = t.replace(new RegExp(NUM, 'g'), (m, n) => nb(n));                   // tout autre nombre
// symboles et abreviations
t = t.replace(/&/g, ' et ').replace(/\+/g, ' plus ').replace(/=/g, ' égale ').replace(/~/g, ' environ ');
t = t.replace(/\s[-–—]\s/g, ', ').replace(/→|=>|->/g, ', puis ');
t = t.replace(/[«»"“”]/g, ' ');
t = t.replace(/\(([^)]*)\)/g, ', $1,');
const ABR = { 'M\\.': 'monsieur', 'Mme': 'madame', 'Mlle': 'mademoiselle', 'Dr': 'docteur', 'etc\\.': 'et cetera', 'cf\\.': 'voir',
  'env\\.': 'environ', 'approx\\.': 'environ', 'tél\\.?': 'téléphone', 'vs\\.?': 'contre', 'ex\\.': 'par exemple', 'p\\.ex\\.': 'par exemple' };
for (const [k, v] of Object.entries(ABR)) t = t.replace(new RegExp('(^|\\s)' + k + '(?=\\s|$)', 'g'), '$1' + v);
t = t.replace(/[\[\]{}]/g, ' ');
// mots tout en MAJUSCULES (plus de 3 lettres) : Piper les epele ou les lit en anglais -> minuscules
t = t.replace(/\b([A-ZÀ-Ý]{4,})\b/g, m => m.charAt(0) + m.slice(1).toLowerCase());
t = t.replace(/[*_`>|#\\]/g, ' ').replace(/\//g, ' ');
// retours a la ligne = fin de phrase (sinon tout s'enchaine sans respirer)
t = t.split(/\n+/).map(l => l.trim()).filter(Boolean)
  .map(l => /[.!?:;,]$/.test(l) ? l.replace(/[:;,]$/, '.') : l + '.').join(' ');
t = t.replace(/\s*:\s*/g, ', ').replace(/\s*;\s*/g, '. ');
t = t.replace(/\.{2,}|…/g, '.').replace(/\s+([.,!?])/g, '$1').replace(/([.,!?])(?=[^\s\d])/g, '$1 ');
t = t.replace(/,\s*,+/g, ',').replace(/\.\s*,/g, '.').replace(/,\s*\./g, '.').replace(/\s+/g, ' ').trim();

// mots composes (rendez-vous, peut-etre, vingt-six) : la voix Pocket les prononce mal avec le tiret -> espace
t = t.replace(/([A-Za-zÀ-ÿ])-(?=[A-Za-zÀ-ÿ])/g, '$1 ');
t = t.replace(/(^|[.!?]\s+)([a-zà-ÿ])/g, (m, a, b) => a + b.toUpperCase());
if (!t) t = "Désolé, je n'ai pas de réponse.";
if (globalThis.__TEST__ !== undefined) globalThis.__OUT__ = t; else process.stdout.write(t);
