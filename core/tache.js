// tache.js - la carte de la tache en cours : ce qu'Archi est en train de faire, etape par etape (idee reprise de Brahma, sans son code).
// Un seul fichier, <etat>\tache.json, que la page d'accueil relit chaque seconde. Trois moments :
//   debut     : un message arrive (noeud Contexte du workflow)            {action:'debut', source, texte}
//   etape     : un outil maison demarre puis finit (outils_maison.js)     etapeDebut({outil, action}) -> n ; etapeFin({n, ok, phrase})
//   fin       : la reponse est prete (noeud Verifier)                     {action:'fin', ok, outils:[noms des outils utilises]}
// Les outils branches directement sur l'agent (lire_page, navigateur...) ne passent pas par ici pendant qu'ils tournent :
// la fin les ajoute a la carte, marques « apres ».
// Le pourcentage d'une etape est une ESTIMATION : la duree moyenne de cet outil lors de ses derniers passages (durees.json).
// Ce qui est note : la demande (coupee a 140 caracteres), le nom de l'outil, son action (un mot), sa reponse courte.
// Jamais ses parametres (un mail, un texte a ecrire...). Rien ne sort du PC.
// Aucune erreur ne remonte : la carte ne doit jamais faire echouer une conversation.
'use strict';
const fs = require('fs');
const path = require('path');

const MAX_ETAPES = 12;
const OUBLI_MS = 15 * 60 * 1000;   // une tache jamais finie (n8n arrete en route) n'est plus « en cours » apres 15 min

function dossierEtat(env) {
  env = env || process.env;
  if (env.ARCHI_ETAT) return env.ARCHI_ETAT;
  // ARCHI_ETAT n'arrive pas aux programmes lances par n8n : on passe par le depot
  return path.join(env.ARCHI_DEPOT || path.join(__dirname, '..'), 'donnees', 'etat');
}

const court = (x, n) => String(x == null ? '' : x).replace(/[\u0000-\u001f\u007f]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, n);
const nomOutil = x => String(x == null ? '' : x).trim().toLowerCase().replace(/[^a-z0-9_ -]/g, '').slice(0, 40);
const motAction = x => String(x == null ? '' : x).trim().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z_ -]/g, '').slice(0, 30);

function lire(f) {
  try { const x = JSON.parse(fs.readFileSync(f, 'utf8')); return x && typeof x === 'object' && !Array.isArray(x) ? x : null; } catch (e) { return null; }
}
function ecrire(f, objet) {
  // ecrit a cote puis renomme : la page ne lit jamais un fichier a moitie ecrit
  fs.mkdirSync(path.dirname(f), { recursive: true });
  const tmp = f + '.' + process.pid + '.' + Math.random().toString(36).slice(2, 8) + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(objet), 'utf8');
  try { fs.renameSync(tmp, f); } catch (e) { try { fs.unlinkSync(tmp); } catch (x) { /* rien */ } throw e; }
}

function creer(options) {
  const o = options || {};
  const etat = o.etat || dossierEtat(o.env);
  const F = path.join(etat, 'tache.json'), D = path.join(etat, 'durees.json');
  const maintenant = o.maintenant || (() => Date.now());

  /** la tache encore ouverte, ou null */
  function ouverte() {
    const t = lire(F);
    if (!t || t.fin || !Array.isArray(t.etapes)) return null;
    if (maintenant() - Number(t.debut || 0) > OUBLI_MS) return null;
    return t;
  }

  function debut(e) {
    // avant : le numero du message precedent. Il dit si un message est « le suivant » d'un autre (outils/mails : on
    // n'envoie un mail que dans le message qui suit l'affichage de son apercu). Carte absente ou illisible : vide.
    const precedent = lire(F);
    const avant = precedent && typeof precedent.id === 'string' && /^[a-z0-9]{6,20}$/.test(precedent.id) ? precedent.id : '';
    const t = { id: maintenant().toString(36) + Math.random().toString(36).slice(2, 6), avant, source: ['telegram', 'appli', 'page'].includes(e && e.source) ? e.source : 'appli',
      demande: court(e && e.texte, 140), debut: maintenant(), fin: 0, ok: null, etapes: [] };
    ecrire(F, t);
    return t.id;
  }

  function estimation(outil) {
    const d = lire(D) || {};
    const v = Number(d[outil]);
    return v > 0 ? Math.round(v) : 0;
  }

  function etapeDebut(e) {
    const t = ouverte();
    if (!t) return 0;
    const outil = nomOutil(e && e.outil) || 'liste';
    if (t.etapes.length >= MAX_ETAPES) return 0;
    const n = t.etapes.length + 1;
    t.etapes.push({ n, outil, action: motAction(e && e.action), debut: maintenant(), fin: 0, ok: null, phrase: '', estime_ms: estimation(outil), apres: false });
    ecrire(F, t);
    return n;
  }

  function etapeFin(e) {
    const t = ouverte();
    if (!t) return false;
    const x = t.etapes.find(s => s.n === Number(e && e.n));
    if (!x || x.fin) return false;
    x.fin = maintenant(); x.ok = !(e && e.ok === false); x.phrase = court(e && e.phrase, 240);
    ecrire(F, t);
    // la duree moyenne de l'outil, pour estimer la prochaine fois (moyenne glissante, les vieux passages comptent moins)
    if (x.ok) {
      const d = lire(D) || {};
      const ms = x.fin - x.debut, avant = Number(d[x.outil]);
      d[x.outil] = avant > 0 ? Math.round(avant * 0.7 + ms * 0.3) : ms;
      const noms = Object.keys(d);
      if (noms.length > 80) delete d[noms[0]];
      try { ecrire(D, d); } catch (err) { /* sans moyenne, pas de pourcentage : rien de grave */ }
    }
    return true;
  }

  function fin(e) {
    const t = ouverte();
    if (!t) return false;
    // deux messages en meme temps : la fin du premier ne ferme pas la carte du second
    if (e && e.id && String(e.id) !== String(t.id)) return false;
    // une etape restee ouverte (l'outil a ete coupe) est close ici
    for (const s of t.etapes) if (!s.fin) { s.fin = maintenant(); s.ok = false; s.phrase = s.phrase || 'interrompu'; }
    // les outils branches directement sur l'agent : vus seulement maintenant, ajoutes « apres »
    for (const nom of (Array.isArray(e && e.outils) ? e.outils : []).map(nomOutil).filter(Boolean)) {
      if (/^outils[ _-]?maison/.test(nom) || t.etapes.length >= MAX_ETAPES) continue;   // deja suivi en direct (Telegram ou appli)
      t.etapes.push({ n: t.etapes.length + 1, outil: nom, action: '', debut: 0, fin: maintenant(), ok: true, phrase: '', estime_ms: 0, apres: true });
    }
    t.fin = maintenant(); t.ok = !(e && e.ok === false);
    ecrire(F, t);
    return true;
  }

  /** ce que la page affiche : la derniere tache, avec l'heure du PC (les durees se calculent avec la meme horloge) */
  function voir() {
    const t = lire(F);
    if (!t || !Array.isArray(t.etapes)) return { tache: null, maintenant: maintenant() };
    const abandonnee = !t.fin && maintenant() - Number(t.debut || 0) > OUBLI_MS;
    return {
      maintenant: maintenant(),
      tache: {
        id: court(t.id, 20), avant: typeof t.avant === 'string' && /^[a-z0-9]{6,20}$/.test(t.avant) ? t.avant : '', source: court(t.source, 10), demande: court(t.demande, 140), debut: Number(t.debut) || 0,
        fin: Number(t.fin) || 0, ok: t.ok === null ? null : !!t.ok, en_cours: !t.fin && !abandonnee, abandonnee,
        etapes: t.etapes.slice(0, MAX_ETAPES).map(s => ({ n: Number(s.n) || 0, outil: nomOutil(s.outil), action: motAction(s.action),
          debut: Number(s.debut) || 0, fin: Number(s.fin) || 0, ok: s.ok === null ? null : !!s.ok, phrase: court(s.phrase, 240),
          estime_ms: Number(s.estime_ms) || 0, apres: !!s.apres })),
      },
    };
  }

  return { debut, etapeDebut, etapeFin, fin, voir, fichier: F };
}

/** pour le CLI et les noeuds n8n : une demande {action:'debut'|'fin'|'voir', ...} -> un objet JSON, jamais d'exception */
function traiter(demande, options) {
  try {
    const t = creer(options), d = demande || {};
    if (d.action === 'debut') return { ok: true, id: t.debut(d) };
    if (d.action === 'fin') return { ok: t.fin(d) };
    if (d.action === 'voir') return t.voir();
    return { ok: false };
  } catch (e) { return { ok: false }; }
}

module.exports = { creer, traiter, dossierEtat };

if (require.main === module) {
  let entree = {};
  try { entree = JSON.parse(fs.readFileSync(0, 'utf8') || '{}'); } catch (e) {}
  process.stdout.write(JSON.stringify(traiter(entree)));
}
