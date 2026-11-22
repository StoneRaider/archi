// verifier_reponse.js - garde-fou contre les noms, adresses et numeros inventes.
// Appele par le noeud « Verifier » du workflow (Telegram et appli) juste avant l'envoi de la reponse.
// Entree (stdin, JSON) : {"reponse": "...", "steps": [intermediateSteps de l'agent], "msg": "message de J", "profil": "..."}
// Sortie (stdout, une ligne JSON) : {"reponse": "<reponse, avec un avertissement ajoute si besoin>", "alertes": [...]}
// Principe : un nom de personne (Prenom Nom), une adresse mail ou un numero de telephone qui n'apparait
// ni dans un resultat d'outil (de ce tour ou des 24 dernieres heures), ni dans le message de J,
// ni dans le chateau, est signale « a verifier ». Le script ne supprime rien et n'echoue jamais :
// en cas de pepin, il rend la reponse telle quelle.
const fs = require('fs');
const path = require('path');
require('./env').charger();   // les reglages du .env : le processus de n8n qui nous lance ne les transmet pas
const BASE = path.join(process.env.ARCHI_BASE || path.join(require('os').homedir(), '.n8n-files'), '/');
const CACHE = path.join(BASE, 'pc', 'verifier_cache.jsonl');   // resultats d'outils recents (24 h), pour les tours sans outil
const CONNUS = path.join(BASE, 'pc', 'verifier_connus.txt');   // noms a ne jamais signaler (un par ligne)
const MEM = BASE + 'memoire/';
const DUREE_CACHE = 24 * 3600 * 1000;

const norm = s => String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[’']/g, "'").replace(/\s+/g, ' ');
const digits = s => String(s || '').replace(/\D/g, '').replace(/^00/, '');

// Mots courants en debut de phrase ou de ligne qui prennent une majuscule sans etre un prenom.
const STOP = new Set(('si le la les un une et ou mais donc or ni car pour voici voila je tu il elle on nous vous ils elles ce cet cette ces au aux du des de en dans sur avec sans par oui non bon bonne ok alors merci salut attention resume liste tableau nom poste pays source sources date email mail objet madame monsieur contexte proposition pourquoi comment quand ou qui que quoi boss archi remarque important note etape etapes titre role fonction contact telephone adresse ville lieu lien page voir lire envoyer ecrire autres autre chaque tous toutes tout toute premier premiere deuxieme troisieme dernier derniere nouveau nouvelle ancien ancienne grand grande petit petite permanent permanente representative representant ambassadeur ambassadrice ministre president presidente directeur directrice docteur dr sir dame mr mrs ms mme m h e the of and to in for at republique republic royaume kingdom etats etat states state emirats emirates nations conseil council union federation federale federal democratique populaire islamique arabe sud nord est ouest south north east west new san los las saint sainte st ste mont port fort cote ile iles cap haute haut bas basse grand grande nouvelle nouveau').split(' '));
const PARTICULES = new Set(['de', 'du', 'des', 'la', 'le', 'van', 'von', 'al', 'el', 'bin', 'ben', 'ibn', 'da', 'di', 'der', 'den', 'ter', 'af', 'abu', 'y']);

let ENTREE = null; // gardee pour rendre la reponse telle quelle si main() plante
let ALERTES_AVANT = []; // ce que le rattrapage d'un appel ecrit en texte a note (core/appel_en_texte.js)
function lireEntree() { try { ENTREE = JSON.parse(fs.readFileSync(0, 'utf8') || '{}'); } catch (e) { ENTREE = {}; } return ENTREE; }

function cacheLire() {
  const out = []; const now = Date.now();
  try {
    for (const l of fs.readFileSync(CACHE, 'utf8').split(/\r?\n/)) {
      if (!l.trim()) continue;
      try { const o = JSON.parse(l); if (now - o.t < DUREE_CACHE) out.push(o); } catch (e) {}
    }
  } catch (e) {}
  return out;
}
function cacheEcrire(anciens, textes) {
  try {
    const now = Date.now();
    const lignes = anciens.map(o => JSON.stringify(o));
    for (const t of textes) if (t && t.trim()) lignes.push(JSON.stringify({ t: now, s: String(t).slice(0, 30000) }));
    fs.mkdirSync(path.dirname(CACHE), { recursive: true });
    fs.writeFileSync(CACHE, lignes.join('\n') + '\n', 'utf8');
  } catch (e) {}
}
function nomsDuChateau() {
  const noms = [];
  const marcher = d => {
    let ents = []; try { ents = fs.readdirSync(d, { withFileTypes: true }); } catch (e) { return; }
    for (const e of ents) {
      if (e.name.startsWith('.') || /^crypte$/i.test(e.name)) continue; // jamais la Crypte
      if (e.isDirectory()) marcher(path.join(d, e.name));
      else if (e.name.endsWith('.md')) noms.push(e.name.replace(/\.md$/, '').replace(/[_-]+/g, ' '));
    }
  };
  marcher(MEM);
  return noms;
}
// premiers mots qui annoncent un lieu, une institution ou une chose, pas une personne
const GENERIQUES = new Set(('golfe mer ocean océan mont monts lac col cap baie ile île iles îles detroit détroit canal riviere rivière fleuve vallee vallée '
  + 'massif plateau desert désert foret forêt parc pont port gare aeroport aéroport rue avenue boulevard place quai chemin route autoroute '
  + 'saint sainte saints porte pointe pic aiguille glacier '
  + 'republique république royaume etat état etats états emirats émirats union nations conseil assemblee assemblée senat sénat ministere ministère '
  + 'banque universite université ecole école institut agence office musee musée hopital hôpital centre cour tribunal prefecture préfecture mairie '
  + 'groupe societe société compagnie fondation association federation fédération organisation comite comité commission parlement gouvernement '
  + 'nord sud est ouest grand grande petit petite haute haut bas basse nouvelle nouveau vieux vieille premier premiere première '
  + 'operation opération projet programme plan accord traite traité guerre bataille crise sommet festival coupe championnat grand-prix '
  + 'lundi mardi mercredi jeudi vendredi samedi dimanche janvier fevrier février mars avril mai juin juillet aout août septembre octobre novembre decembre décembre')
  .split(/\s+/).map(w => w.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()));

function connus() {
  try { return fs.readFileSync(CONNUS, 'utf8').split(/\r?\n/).map(s => s.trim()).filter(s => s && !s.startsWith('#')); } catch (e) { return []; }
}

// ---- candidats dans la reponse ----
function candidatsNoms(texte) {
  const res = new Set();
  const T = "(?:[A-ZÀ-ÝŒ][A-Za-zà-ÿœ'’.]*(?:-[A-Za-zÀ-ÿœ'’.]+)*)";   // Jean-Pierre, Al-Khatib, Jae-hoon, Villeneuve-Exemple
  const P = "(?:de|du|des|la|le|van|von|al|el|bin|ben|ibn|da|di|der|den|ter|abu|y)";
  const re = new RegExp("(?:^|[\\s(«\"'*|:,;>-])(" + T + "(?:[ ](?:" + P + "[ ])?" + T + "){1,3})", "g");
  let m;
  while ((m = re.exec(texte))) {
    const avant = texte.slice(0, m.index + m[0].length - m[1].length).replace(/[\s*_«"'(]+$/, '');
    const debutPhrase = avant === '' || /[.!?:;\n]$|^[-•*\d.)]+$/.test(avant.slice(-1)) || /\n[-•*\d.) ]*$/.test(texte.slice(0, m.index + 1));
    let toks = m[1].split(' ');
    // un point au milieu = fin de phrase (« Telegram. Dis-moi ») : on coupe la ; « J. Dupont » ou « M. Durand » restent entiers
    const fin = toks.findIndex((t, k) => k < toks.length - 1 && /[.!?:;]$/.test(t) && t.replace(/[.!?:;]+$/, '').length > 2);
    if (fin >= 0) toks = toks.slice(0, fin + 1);
    toks[toks.length - 1] = toks[toks.length - 1].replace(/[.,;:!?]+$/, '');
    toks = toks.filter(Boolean);
    while (toks.length && STOP.has(norm(toks[0]).replace(/[.:]/g, ''))) toks.shift();          // « Si J » -> « J »
    while (toks.length && STOP.has(norm(toks[toks.length - 1]).replace(/[.:]/g, ''))) toks.pop();
    const pleins = toks.filter(t => !PARTICULES.has(norm(t)));
    if (pleins.length < 2) continue;                       // il faut au moins Prenom + Nom
    if (toks.slice(0, 2).some(t => GENERIQUES.has(norm(t)))) continue;           // Golfe Persique, Mer Rouge, Mont Blanc, Conseil de sécurité...
    if (pleins.some(t => /\d/.test(t))) continue;
    if (toks.every(t => t === t.toUpperCase())) continue; // sigles (ONU, GCC...)
    res.add(JSON.stringify({ nom: toks.join(' '), debutPhrase: debutPhrase && toks.length === m[1].split(' ').length }));
  }
  return [...res].map(j => JSON.parse(j));
}
const candidatsMails = texte => [...new Set((texte.match(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g) || []))];
const candidatsTels = texte => [...new Set((texte.match(/(?:\+|00)\s?\d[\d\s().-]{7,}\d|\b0\d(?:[\s.-]?\d{2}){4}\b/g) || []).map(s => s.trim()))].filter(s => digits(s).length >= 9);

function present(nom, corpusN) {
  const n = norm(nom);
  if (corpusN.includes(n)) return true;
  const toks = n.split(' ').filter(t => t.length >= 2 && !PARTICULES.has(t));
  if (toks.length < 2) return true;
  // « Dupont, Marie » ou « M. Dupont (Marie) » : le nom de famille est dans le corpus,
  // et le prenom se trouve a moins de 60 caracteres de lui.
  const famille = toks[toks.length - 1], prenoms = toks.slice(0, -1);
  let i = -1;
  while ((i = corpusN.indexOf(famille, i + 1)) >= 0) {
    const fen = corpusN.slice(Math.max(0, i - 60), i + famille.length + 60);
    if (prenoms.every(p => fen.includes(p))) return true;
  }
  return false;
}
function telPresent(tel, numsCorpus) {
  const d = digits(tel);
  return numsCorpus.some(c => c === d || d.endsWith(c) || c.endsWith(d));
}

// Garde-fou « plus tard » : Archi n'annonce pas « C'est programmé » si le planificateur ne l'a pas dit lui-meme
// dans ce tour. Vu a l'essai reel : le modele a repondu « (C'est programmé) » sans avoir appele l'outil.
const PROMESSE = /c'est programme|je te (le |la |les )?rappell?erai|je te previendrai|je t'avertirai/;
const CONFIRMATION = /c'est programme|rappel[^.]{0,40}(ajoute|enregistre|programme)/;
function promesseSansPlanificateur(reponse, obs) {
  if (!PROMESSE.test(norm(reponse))) return false;
  return !obs.some(o => CONFIRMATION.test(norm(o)));
}

function main(inp) {
  const propre = t => String(t || '').replace(/[\u2010\u2011\u2012\u2013\u2212]/g, '-').replace(/[\u00a0\u202f\u2009]/g, ' ');
  const reponse = propre(inp.reponse);
  const steps = Array.isArray(inp.steps) ? inp.steps : [];
  // L'apercu d'un mail prepare dans ce tour est affiche par le code (core/apercu_mail.js), quoi qu'ait ecrit le modele :
  // toutes les sorties de cette fonction passent par ici. Sans mail prepare, la reponse ne change pas d'un caractere.
  const rendre = (texte, lignes) => {
    let m = { reponse: texte, alertes: [] };
    try { m = require('./apercu_mail').montrer(texte, steps); } catch (e) { m = { reponse: texte, alertes: [] }; }
    // Quand l'apercu remplace la reponse du modele, ce que CE programme avait ajoute dessous (« À vérifier : … ») reste :
    // c'est du code, pas du modele. Seulement si le tout tient dans un message.
    if (m.reponse !== texte && texte.startsWith(reponse) && texte.length > reponse.length) {
      const ajout = texte.slice(reponse.length);
      if (m.reponse.length + ajout.length <= 4096) m.reponse += ajout;
    }
    process.stdout.write(JSON.stringify({ reponse: m.reponse, alertes: ALERTES_AVANT.concat(lignes, m.alertes) }));
  };
  // Le modele n'a rien rendu (vide, sa reflexion seule, ou l'agent de n8n arrete a sa limite d'essais) : la page ne reste
  // pas muette (core/reponse_vide.js, essai reel du 22/11). L'apercu d'un mail prepare dans ce tour passe d'abord ; sinon
  // une phrase honnete dit quels outils ont ete appeles et si leurs appels ont abouti. Elle n'annonce jamais une action.
  let secours = '';
  try {
    const RV = require('./reponse_vide');
    if (RV.estVide(inp.reponse == null ? '' : String(inp.reponse))) {
      let titres = {};
      try {
        const v = JSON.parse(fs.readFileSync(process.env.ARCHI_VITRINE || path.join(__dirname, '..', 'config', 'vitrine.json'), 'utf8'));
        for (const f of (Array.isArray(v && v.outils) ? v.outils : [])) if (f && typeof f.nom === 'string' && typeof f.titre === 'string') titres[f.nom.toLowerCase()] = f.titre;
      } catch (e) { titres = {}; }
      secours = RV.phraseDeSecours(String(inp.reponse == null ? '' : inp.reponse), steps, { titres });
    }
  } catch (e) { secours = ''; }
  if (secours) {
    let m = { reponse: '', alertes: [] };
    try { m = require('./apercu_mail').montrer('', steps); } catch (e) { m = { reponse: '', alertes: [] }; }
    process.stdout.write(JSON.stringify({ reponse: m.reponse || secours, alertes: ALERTES_AVANT.concat(['[journal] reponse vide du modele' + (m.reponse ? '' : ' : phrase de secours')], m.alertes || []) }));
    return;
  }
  if (!reponse.trim()) { rendre(reponse, []); return; }
  // Seules les REPONSES des outils comptent : ce qu'Archi a tape dans sa requete (toolInput) reste sa propre invention.
  const obs = steps.map(s => { const o = s && s.observation; return typeof o === 'string' ? o : JSON.stringify(o || ''); });
  const anciens = cacheLire();
  const corpus = propre([inp.msg || '', inp.profil || ''].concat(obs, anciens.map(o => o.s), nomsDuChateau(), connus()).join('\n'));
  const corpusN = norm(corpus);
  const numsCorpus = [...new Set((corpus.match(/(?:\+|00)?\s?\d[\d\s().-]{7,}\d/g) || []).map(digits).filter(d => d.length >= 9))];

  const alertes = [];
  for (const c of candidatsNoms(reponse)) {
    if (present(c.nom, corpusN)) continue;
    // « Appelle Jean Dupont » en debut de phrase : le premier mot est peut-etre un verbe, on juge le reste
    const toks = c.nom.split(' ');
    if (c.debutPhrase && toks.length >= 3) { const court = toks.slice(1).join(' '); if (!present(court, corpusN)) alertes.push(court); continue; }
    alertes.push(c.nom);
  }
  for (const m of candidatsMails(reponse)) if (!corpusN.includes(norm(m))) alertes.push(m);
  const tels = candidatsTels(reponse);
  for (const t of tels) if (!telPresent(t, numsCorpus)) alertes.push(t);
  // meme numero recopie sur plusieurs lignes d'un tableau
  const parNum = {}; for (const t of (reponse.match(/(?:\+|00)\s?\d[\d\s().-]{7,}\d/g) || [])) { const d = digits(t); parNum[d] = (parNum[d] || 0) + 1; }
  const repete = Object.entries(parNum).filter(([, k]) => k >= 3).map(([d]) => tels.find(t => digits(t) === d) || d);
  for (const r of repete) if (!alertes.includes(r)) alertes.push(r + ' (même numéro répété ' + parNum[digits(r)] + ' fois)');

  cacheEcrire(anciens, obs);

  let sortie = reponse;
  if (promesseSansPlanificateur(reponse, obs)) {
    alertes.push('promesse sans planificateur');
    sortie += "\n\n⚠️ À vérifier : je n'ai pas appelé le planificateur à l'instant, donc rien de nouveau n'est programmé. Si c'est un nouveau rappel, redemande-le-moi.";
    rendre(sortie, alertes);
    return;
  }
  if (alertes.length) {
    const liste = alertes.slice(0, 12);
    const reste = alertes.length > 12 ? ' et ' + (alertes.length - 12) + ' autres' : '';
    if (/^\s*\[TEXTE\]/i.test(reponse)) {
      sortie += '\n\n⚠️ Vérification automatique : je n\'ai trouvé ni dans mes outils ni dans ton message : ' + liste.join(' ; ') + reste + '. À vérifier avant usage, c\'est peut-être inventé.';
    } else {
      // Reponse dite a voix haute : un nom seul (« Charles de Gaulle ») n'est plus relu en « À vérifier » : c'etait un
      // doublon penible a ecouter (retour de J, 13/11). Il reste dans « alertes » (journal). Seules les coordonnees
      // (mail, numero) sans source sont signalees, sans etre recitees.
      const coords = alertes.filter(a => /@/.test(a) || digits(a).length >= 9).length;   // un numero ecrit par paires espacees n'a pas 4 chiffres colles
      if (coords) sortie += '\n\nÀ vérifier : ' + (coords > 1 ? coords + ' coordonnées sans source.' : 'une coordonnée sans source.');
    }
  }
  // Palier « journal seulement » (core/promesses.js) : ce que la piece AURAIT signale (« j'ai eteint la prise » sans outil
  // reussi, outil en attente d'accord, outil en echec) part dans « alertes », lues dans les executions de n8n. Rien n'est
  // dit a l'utilisateur : la reponse ne change pas d'un caractere. Pose APRES le bloc « if (alertes.length) », qui recopie
  // les alertes sous une reponse [TEXTE].
  //
  // Depuis le 21/11, UNE partie est dite a l'utilisateur : la reponse annonce une action comme faite alors que l'outil de
  // cette action, appele dans ce tour, a echoue ou attend encore l'accord (promessesADire). Mesure avant de l'activer :
  // 0 avertissement a tort sur 388 reponses honnetes (213 de la relecture, 40 et 135 de deux sondes neuves), 41 mensonges
  // releves sur 60. « aucun outil appele » reste au journal (1 a 4 avertissements a tort sur 40). Pose lui aussi APRES le
  // bloc « if (alertes.length) ». Reglage ARCHI_PROMESSES : « dit » (defaut), « journal » (rien n'est dit), « eteint ».
  const mode = String(process.env.ARCHI_PROMESSES || 'dit').trim().toLowerCase();
  if (mode !== 'eteint') {
    try {
      const promesses = require('./promesses');
      for (const m of promesses.promessesEnLAir(reponse, steps)) alertes.push('[journal] promesse en l air : ' + m.famille + ' (' + m.raison + ')');
      if (mode !== 'journal') {
        const dites = promesses.promessesADire(reponse, steps);
        const phrase = dites.length ? promesses.avertissement(dites) : '';
        if (phrase) {
          sortie += '\n\n' + phrase;
          for (const m of dites) alertes.push('promesse en l air dite : ' + m.famille + ' (' + m.raison + ')');
        }
      }
    } catch (e) { /* la piece ne doit jamais empecher la reponse de partir */ }
  }
  // Un etat qui change ne se reprend pas de la conversation (core/reverifier.js, essai reel du 21/11) : le message demandait
  // un outil d'etat (monteur, agenda, recherche, image), le tour ne contient AUCUN appel d'outil, et la reponse affirme
  // quand meme quelque chose. EN JOURNAL SEULEMENT par defaut : la relecture independante du 21/11 a compte 58
  // avertissements a tort sur 77 echanges honnetes (« c'est quoi le monteur video ? », « mon frere est monteur video »,
  // « bien sur, quel jour ? ») et 52 reponses de memoire manquees sur 58. Le dire a l'utilisateur ferait plus de bruit
  // que de bien ; la ligne « [journal] outil non interroge » se lit dans les executions de n8n. Reglage ARCHI_REVERIF :
  // « journal » (defaut), « dit » (l'avertissement sous la reponse, a ses risques), « eteint ».
  const reverif = String(process.env.ARCHI_REVERIF || 'journal').trim().toLowerCase();
  if (reverif !== 'eteint') {
    try {
      const R = require('./reverifier');
      const oublies = R.outilsNonInterroges(typeof inp.msg === 'string' ? inp.msg : '', steps, reponse);
      for (const o of oublies) alertes.push('[journal] outil non interroge : ' + o.outil);
      const phrase = reverif === 'dit' && oublies.length ? R.avertissement(oublies) : '';
      if (phrase && !sortie.includes('⚠️ À vérifier : je n\'ai pas interrogé')) sortie += '\n\n' + phrase;
    } catch (e) { /* jamais d'obstacle a la reponse */ }
  }
  rendre(sortie, alertes);
}
// Le modele a ecrit l'appel d'outil au lieu de le lancer (core/appel_en_texte.js) : l'appel part, avec les memes controles
// que dans l'agent, puis le modele ecrit la phrase ; tous les controles ci-dessus portent ensuite sur cette phrase.
async function demarrer() {
  const inp = lireEntree();
  // « Archi : … » : le modele imite sa propre reponse gardee en memoire courte (essai reel du 22/11) ; la page et la voix
  // disent deja qui parle
  // (pas quand on lui demande son nom : « Archi : un assistant local… » est alors la reponse)
  if (typeof inp.reponse === 'string' && /^\s*archi\s*:\s*\S/i.test(inp.reponse)
    && !/\b(?:ton nom|comment tu t'appelles|tu t'appelles|qui es[- ]tu|t'es qui)\b/i.test(String(inp.msg || ''))) inp.reponse = inp.reponse.replace(/^\s*archi\s*:\s*/i, '');
  try {
    const r = await require('./appel_en_texte').rattraper(inp);
    if (r) {
      ENTREE = Object.assign({}, inp, { reponse: r.reponse, steps: r.steps });
      ALERTES_AVANT = r.alertes;
    } else {
      // une consigne destinee au modele recopiee telle quelle (« rappelle-le avec accord=oui ») ne part pas
      const phrase = require('./appel_en_texte').consigneRecopiee(inp.reponse, inp.steps, inp.msg);
      if (phrase) { ENTREE = Object.assign({}, inp, { reponse: phrase }); ALERTES_AVANT = ['[journal] consigne du modele recopiee : remplacee']; }
    }
  } catch (e) { /* le rattrapage ne bloque jamais la reponse */ }
  main(ENTREE);
}
demarrer().catch(e => { try { process.stdout.write(JSON.stringify({ reponse: String((ENTREE || {}).reponse || ''), alertes: [], erreur: String(e.message || e) })); } catch (e2) { process.stdout.write(JSON.stringify({ reponse: '', alertes: [] })); } });
