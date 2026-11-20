// apercu_mail.js - l'apercu d'un mail est AFFICHE par le code, jamais confie au modele.
// L'outil mails rend l'apercu du brouillon en attente : boite d'envoi, destinataires, objet, texte, et une empreinte.
// Si le modele l'oubliait, le raccourcissait, le changeait ou en glissait un faux au-dessus, l'utilisateur dirait
// « envoie » a un mail qu'il n'a pas vu. Ici, a la sortie de l'agent (core/verifier_reponse.js) :
//   1. on retrouve l'apercu encore en attente a la fin de ce tour, parmi les gestes de l'outil mails (et de lui seul) ;
//   2. on verifie que son empreinte est bien celle de ce qu'on va afficher (meme calcul que serveur/mail_commande.py) ;
//   3. la reponse du modele est REMPLACEE par l'apercu, tel quel : ce que le modele ecrit autour d'un mail en attente
//      n'est jamais montre (un faux apercu, une autre question a laquelle un « oui » repondrait) ;
//   4. on note l'empreinte affichee et le numero du message (core/tache.js) dans <base>\mails\montre.json : l'outil
//      n'envoie que cet apercu-la, et seulement dans le message qui suit (outils/mails/mails.py).
// Rien d'autre n'est ecrit. Aucune exception ne sort. Sans mail en attente, la reponse ne change pas d'un caractere.
'use strict';
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const TEXTE_MAX = 3000, ADRESSES_MAX = 5, ADRESSES_LONGUEUR = 300, SUJET_MAX = 200, MESSAGE_MAX = 4096;   // un message Telegram ; le plus long apercu que l'outil accepte en fait 4 050
const ADRESSE = /^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$/;
const EMPREINTE = /^[a-f0-9]{32}$/;
const NUMERO = /^[a-z0-9]{6,20}$/;
const BOITES = { gmail: 'Gmail', outlook: 'Outlook' };
const LANCEUR = /^outils[ _-]?maison/i;                             // le noeud du workflow qui lance les outils maison

const base = () => process.env.ARCHI_BASE || path.join(os.homedir(), '.n8n-files');

/** La meme empreinte que serveur/mail_commande.py : chaque champ precede de sa longueur en caracteres. */
function empreinteDe(boite, a, sujet, texte) {
  const ecrit = [boite, a.join(','), sujet, texte].map(x => Array.from(x).length + ':' + x).join('');
  return crypto.createHash('sha256').update(ecrit, 'utf8').digest('hex').slice(0, 32);
}

function objetDe(observation) {
  if (observation && typeof observation === 'object' && !Array.isArray(observation)) return observation;
  if (typeof observation !== 'string' || observation.length > 200000) return null;
  try { const x = JSON.parse(observation); return x && typeof x === 'object' && !Array.isArray(x) ? x : null; } catch (e) { return null; }
}

/** L'apercu porte par un geste de l'outil mails, verifie champ par champ ; null au moindre doute. */
function apercuDe(o) {
  const ap = o.apercu;
  if (!ap || typeof ap !== 'object' || typeof o.empreinte !== 'string' || !EMPREINTE.test(o.empreinte)) return null;
  if (!Object.prototype.hasOwnProperty.call(BOITES, ap.boite)) return null;
  if (!Array.isArray(ap.a) || !ap.a.length || ap.a.length > ADRESSES_MAX || !ap.a.every(x => typeof x === 'string' && ADRESSE.test(x))) return null;
  if (ap.a.join(', ').length > ADRESSES_LONGUEUR) return null;
  // l'objet tient sur une ligne : un retour a la ligne y imiterait une ligne « À : » de l'apercu
  if (typeof ap.sujet !== 'string' || !ap.sujet || ap.sujet.length > SUJET_MAX || /[\u0000-\u001f\u007f\u2028\u2029]/.test(ap.sujet)) return null;
  if (typeof ap.texte !== 'string' || !ap.texte.trim() || ap.texte.length > TEXTE_MAX) return null;
  // l'empreinte doit etre celle de CE qui sera affiche : une observation ne peut pas montrer un mail et en armer un autre
  if (empreinteDe(ap.boite, ap.a, ap.sujet, ap.texte) !== o.empreinte) return null;
  // l'alerte « adresse jamais vue » est ecrite ICI, a partir d'adresses de l'apercu : aucun texte libre ne s'affiche sous ⚠️
  const inconnues = Array.isArray(ap.inconnues) ? ap.inconnues.filter(x => typeof x === 'string' && ap.a.includes(x)) : [];
  if (Array.isArray(ap.inconnues) && inconnues.length !== ap.inconnues.length) return null;
  return { boite: ap.boite, a: ap.a.slice(), sujet: ap.sujet, texte: ap.texte, empreinte: o.empreinte,
    alerte: inconnues.length ? 'Attention : je n\'ai jamais vu ' + inconnues.join(' ni ') + ' dans tes mails. Vérifie l\'orthographe.' : '' };
}

/** L'apercu encore en attente a la fin de ce tour, ou null. Seuls comptent les gestes de l'outil mails, lances par le
 *  lanceur d'outils maison. Chaque geste dit lui-meme s'il reste un apercu en attente (« apercu_en_attente ») : un envoi
 *  reussi, une annulation ou un « preparer » rate le retirent ; un geste qui porte l'apercu (statut APERCU : preparer,
 *  rappeler, ou un envoi refuse parce que trop tot) le donne ; les autres ne changent rien. */
function apercuDesSteps(steps) { return lireLesSteps(steps).apercu; }

/** -> { apercu, incertain } ; incertain : un envoi de ce tour a peut-etre fait partir un mail, sans qu'on le sache. */
function lireLesSteps(steps) {
  let courant = null, incertain = false;
  for (const s of Array.isArray(steps) ? steps : []) {
    if (!s || !s.action || typeof s.action.tool !== 'string' || !LANCEUR.test(s.action.tool)) continue;
    const o = objetDe(s.observation);
    if (!o || o.outil !== 'mails' || typeof o.apercu_en_attente !== 'boolean') continue;
    if (o.action === 'envoyer' && o.incertain === true) incertain = true;
    if (o.apercu_en_attente === false) { courant = null; continue; }
    if (o.statut === 'APERCU') courant = apercuDe(o);
  }
  return { apercu: courant, incertain };
}

const INCERTAIN = '⚠️ Je ne sais pas si ton mail est parti : la messagerie a répondu de travers. Regarde dans tes messages envoyés '
  + 'avant de me demander de le renvoyer, sinon il pourrait partir deux fois.';

function bloc(ap) {
  return '📧 Aperçu du mail (rien n\'est parti)\nDepuis : ' + BOITES[ap.boite] + '\nÀ : ' + ap.a.join(', ') + '\nObjet : ' + ap.sujet + '\n\n' + ap.texte
    + (ap.alerte ? '\n\n⚠️ ' + ap.alerte : '') + '\n\nPour l\'envoyer, réponds : envoie. Sinon, dis-moi quoi changer.';
}

/** Le numero du message en cours (core/tache.js), ou '' si on ne le connait pas. */
function numeroEnCours() {
  try {
    const t = require('./tache').creer().voir().tache;
    return t && t.en_cours && typeof t.id === 'string' && NUMERO.test(t.id) ? t.id : '';
  } catch (e) { return ''; }
}

/** Note que cet apercu vient d'etre affiche, dans le message « tache ». */
function marquer(ap, tache, options) {
  const dossier = path.join((options && options.base) || base(), 'mails');
  const fichier = path.join(dossier, 'montre.json');
  fs.mkdirSync(dossier, { recursive: true });
  const tmp = fichier + '.' + process.pid + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify({ empreinte: ap.empreinte, tache, quand: Math.round(Date.now() / 1000) }), 'utf8');
  fs.renameSync(tmp, fichier);
}

/**
 * La reponse a rendre a l'utilisateur.
 * options : { base, tache } pour les tests (sinon ARCHI_BASE et la carte de tache).
 * -> { reponse, alertes: [lignes de journal], apercu: true|false }
 */
function montrer(reponse, steps, options) {
  const sortie = { reponse: String(reponse == null ? '' : reponse), alertes: [], apercu: false };
  let ap = null, b = '', incertain = false;
  try { const lu = lireLesSteps(steps); ap = lu.apercu; incertain = lu.incertain; b = ap ? bloc(ap) : ''; } catch (e) { ap = null; }
  if (incertain) {
    // un envoi incertain dans ce tour : on le dit, a la place de tout le reste, et AUCUN apercu n'est affiche ni marque
    // (le modele a pu re-preparer le meme mail dans la foulee : « envoie » le ferait partir une seconde fois)
    sortie.reponse = INCERTAIN;
    sortie.alertes.push('[journal] envoi de mail incertain');
    return sortie;
  }
  if (!ap || !b || b.length > MESSAGE_MAX) return sortie;
  sortie.apercu = true;
  sortie.reponse = b;
  try {
    const tache = options && Object.prototype.hasOwnProperty.call(options, 'tache') ? options.tache : numeroEnCours();
    if (typeof tache !== 'string' || !NUMERO.test(tache)) throw new Error('numero du message inconnu');
    marquer(ap, tache, options);
  } catch (e) {
    sortie.alertes.push('[journal] apercu du mail : marque non ecrite, l envoi sera refuse');
  }
  return sortie;
}

module.exports = { montrer, apercuDesSteps, empreinteDe, bloc };
