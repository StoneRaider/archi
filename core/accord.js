// accord.js - l'accord pour une action sensible vient-il vraiment du dernier message de l'utilisateur ?
// Aujourd'hui le modele ecrit lui-meme "accord":"oui" (core/outils_maison.js). Cette piece donne au code de quoi le
// verifier, dans l'esprit de la garde d'origine d'Intendant (_DEMANDE_DE_MAIL, competences/ecrits.py).
//
//   accordDansMessage(message, { outil, action, parametres, enAttente, tronque }) -> { accorde: true|false, raison: '<code>' }
//
// DANS LE DOUTE, CETTE PIECE REFUSE (l'inverse de promesses.js). Elle accorde dans trois cas seulement :
//   oui_explicite       le message ENTIER n'est fait que de mots d'accord, de politesse et de bouche-trous
//                       (« oui », « ok vas-y », « c'est bon tu peux », « oui s'il te plait »)
//   demande_directe     le message demande CETTE action : un verbe de l'action en position d'ordre, puis ce qu'elle
//                       touche (« eteins le radiateur », « tu peux lancer l'impression ? », « curateur, 1 et 3 »),
//                       precede ou non d'un oui (« oui, allume le radiateur »)
//   demande_de_lecture  pour une action qui ne fait que lire (etat d'une prise, lire un PDF, chercher un mail), le
//                       message nomme ce qui est lu, question comprise (« que dit le PDF de la facture ? »)
// Elle refuse, avec une raison lisible dans un journal :
//   message_vide, negation (non, pas, plus, sauf, attends, laisse…), pas_maintenant (« dans 2 heures », « ce soir » pour
//   une action immediate), question, oui_et_autre_chose (« ok, resume-moi cet article »), oui_sans_demande (rien n'etait
//   en attente : voir enAttente), action_differente, action_inconnue, cible_differente (le message nomme une autre prise,
//   un autre dossier, un autre outil que les parametres), parametre_non_dit (un parametre qui aggrave : sans_limite,
//   une duree plus longue, un texte que l'utilisateur n'a pas dit), numeros_differents (ou incomparables),
//   message_tronque (appel.tronque : la carte de tache coupe a 140 caracteres), hors_sujet, outil_sans_vocabulaire.
//
// appel.enAttente : absent = on ne sait pas si une demande d'accord etait en attente (un oui compte) ; null = rien n'etait
// en attente (un oui ne compte pas) ; {outil, action} = un oui ne vaut que pour cet outil-la.
//
// Fonction pure, sans exception. Le message est borne a 1 500 caracteres et lu mot a mot : aucune expression reguliere
// ne parcourt un texte long. Le vocabulaire vient du registre (outils/registre.json) et de config/aiguillages.json.
'use strict';
const { chaine, unifier } = require('./texte');

const MESSAGE_MAX = 1500, MOTS_MAX = 240, PARAMETRE_MAX = 300, JSON_MAX = 20000;

// ---------------------------------------------------------------------------------------------------------------
// 1. Le message, lu mot a mot
// ---------------------------------------------------------------------------------------------------------------
// Une dictee n'a ni ponctuation fiable ni traits d'union : tout est compare sans eux (« vas y », « est ce que »).
// Piege du portage : sans accents, « allumé » (un constat) et « allume » (un ordre) se confondent. Le participe en « é »
// est donc marque d'un E majuscule AVANT de retirer les accents : « allumé » devient « allumE ».

// « Archi » en tete ou en queue de phrase, tel que la dictee l'entend (meme liste que pc/voix/ecoute.py)
const ARCHI = '(?:arch(?:ie|is|i|y)|a ?chi(?:er|e)?|ashi|arshi)';
const ARCHI_EN_TETE = new RegExp('^((?:dis|dit|ok|okay|hey|he|eh|salut|bonjour|bonsoir|oui|non|alors|bon|merci|stp) )?' + ARCHI + '(?= |$) ?');
const ARCHI_EN_QUEUE = new RegExp(' ' + ARCHI + '$');
// Ce qui suit ces marques n'est pas la parole de l'utilisateur : un fichier, un mail, une page, une photo joints a son
// message (core/contexte.js, baliserExterieur), sous toutes leurs graphies.
const CONTENU_JOINT = /-+ ?contenu (?:du|de la|de l'|des|de|d')|\[+\s*contenu\s*ext|\[+\s*fin\s+du\s+contenu/;

/** Le texte en mots : minuscules, sans accents (participes marques E), sans ponctuation, elisions detachees (« l' », « n' »). */
function enMots(texte) {
  let t = texte.replace(/é(?=(?:e|s|es)?(?![a-z0-9à-ÿ]))/g, 'E')
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zE0-9' ]/g, ' ').replace(/ +/g, ' ').trim();
  t = t.replace(/ ?(?:^| )fin de (?:la )?transmission(?: .*)?$/, '');
  t = t.replace(ARCHI_EN_TETE, '$1').replace(ARCHI_EN_QUEUE, '');
  t = t.replace(/(^| )n'oublie[sz]? pas (?:de |d')(?!me |nous )/g, '$1pense a ');      // « n'oublie pas d'eteindre » demande d'eteindre
  t = t.replace(/(^| )((?:re)?cr)Ee(s?)(?= |$)/g, '$1$2ee$3');                            // « crée » est un ordre (le participe est « créé »)
  t = t.replace(/^([a-z]+)E(?= |$)/, '$1e');                                              // « Allumé le radiateur », dicte pour « allumer »
  t = t.replace(/(^| )(l|d|j|n|s|m|t|c|qu)'/g, "$1$2' ").replace(/'(?! )/g, ' ');         // « l'impression » -> « l' impression »
  return t.split(' ').filter(Boolean).slice(0, MOTS_MAX);
}

/** Le message : ses mots, ceux d'avant les premiers deux-points (ce qui suit est souvent une citation), et ce qu'il est. */
function lire(message) {
  let t = typeof message === 'string' ? message : '';
  const tronque = t.length > MESSAGE_MAX;
  t = unifier(t.slice(0, MESSAGE_MAX)).toLowerCase();
  const joint = t.search(CONTENU_JOINT);
  if (joint >= 0) t = t.slice(0, joint);
  // ce qui est cite n'est pas un ordre : guillemets (fermes ou non), lignes de citation « > … »
  t = t.replace(/«[^»]*»?|“[^”]*”?|"[^"]*"?/g, ' ').replace(/(^|\n) ?>[^\n]*/g, ' ');
  const question = t.indexOf('?') >= 0;
  const dp = t.search(/:(?!\d)/);
  const mots = enMots(t);
  let avant = dp >= 0 ? enMots(t.slice(0, dp)) : mots;
  // « curateur : 1 et 3 », « oui : vas-y » : une adresse ou un oui avant les deux-points ne font pas de la suite une citation
  if (dp >= 0 && avant.length <= 2 && avant.every(x => AVANT_L_ORDRE.has(x) || EXPRESSIONS.has(x))) avant = null;
  return { mots, avant: avant || mots, coupe: !!avant && dp >= 0, question, tronque };
}

// ---------------------------------------------------------------------------------------------------------------
// 2. Les mots d'accord, de politesse, de refus
// ---------------------------------------------------------------------------------------------------------------
const table = (classe, expressions, dans) => { for (const e of expressions.split('|')) dans.set(e, classe); return dans; };
const EXPRESSIONS = new Map();
// ACCORD : suffit a lui seul
table('accord', "oui|ouais|ouai|ouaip|ouep|yes|yep|ok|okay|okey|oki|d' accord|d accord|daccord|dac|vas y|vasy|allez y|c' est bon|c est bon|c' est ok"
  + "|c' est d' accord|c' est ca|c' est parti|c' est tout bon|ca marche|ca me va|je confirme|confirme|confirmE|c' est confirmE|je valide|fais le|fais la"
  + "|fais les|fais ca|faites le|on y va|bien sur|absolument|affirmatif|banco|feu vert|je veux bien|je suis d' accord|tu peux|tu peux y aller"
  + "|tu peux le faire|tu peux faire ca|tu as mon accord|accord donnE|pas de probleme|pas de souci|sans probleme|volontiers|avec plaisir|mais oui"
  + '|si si|envoie|pourquoi pas|quand tu veux|on fait ca|on fait comme ca|faisons ca', EXPRESSIONS);
// APPUI : permis autour d'un mot d'accord, ne suffit jamais seul (« go », « super », « parfait », « allez »)
table('appui', 'ah|oh|bah|ben|bon|eh bien|et bien|alors|euh|hum|mais|et|donc|hein|voila|allez|go|super|parfait|top|nickel|impeccable|entendu|exactement'
  + '|tout a fait|carrement|ca roule|bonne idee', EXPRESSIONS);      // « si » n'en est pas : « eteins si la temperature depasse 20 » pose une condition
table('poli', "s' il te plait|s il te plait|stp|je t' en prie|maintenant|tout de suite|des maintenant|vite|merci|merci beaucoup|merci bien", EXPRESSIONS);
// REFUS : un seul suffit a refuser, ou qu'il soit
table('refus', "hors de question|pas question|tant pis|ca ira|ca suffit|on verra|je te dirai|je reflechis|en fait|finalement|une seconde|deux secondes"
  + "|une minute|deux minutes|un instant|tu reves|comme si|je sais plus|laisse tomber|plus besoin|tout seul|toute seule|moi meme|je m' en occupe"
  + "|je m' en charge|je le fais|je la fais|je les fais|je vais le faire|deja fait|c' est fait|trop tard|j' ai compris|je vois|bonne nuit|au revoir"
  + "|a demain|sous aucun pretexte|garde toi|pas la peine|a quoi bon", EXPRESSIONS);
// REPORT : pas maintenant (sauf pour une action differee, confiee au planificateur)
table('report', "plus tard|tout a l' heure|apres demain|ce soir|cette nuit|ce midi|cet apres midi|demain matin|demain soir|la prochaine fois|un de ces jours"
  + '|la semaine prochaine|le mois prochain|des que|une fois que', EXPRESSIONS);
const EXPRESSION_MAX = 5;

const REFUS_SEUL = new Set(("non nan nah nope no nein niet pas plus jamais rien aucun aucune sauf attends attendez attend patiente patientez laisse laissez refuse refusE"
  + " interdis interdit evite evitez inutile impossible doucement minute ne n' ni").split(' '));
const REPORT_SEUL = new Set('demain tantot bientot lundi mardi mercredi jeudi vendredi samedi dimanche'.split(' '));
// un mot de condition, de doute ou de recit : le message ne demande rien (« si tu allumes… », « faut-il… », « en theorie »)
const DOUTE = new Set(("si quand lorsque savoir theorie theoriquement avis capable serieusement hier comptes compte interdit pourquoi comment combien"
  + ' voulu veut vais va vont allait').split(' '));
const CONTRE_ORDRE = new Set('stop annule annules annulez annuler oublie oublies oubliez arrete arretes arretez arreter abandonne abandonnes abandonnez'.split(' '));
const UNITES = new Set('h heure heures min mn minute minutes seconde secondes jour jours semaine semaines mois instant instants'.split(' '));
const NOMBRES = { un: 1, une: 1, deux: 2, trois: 3, quatre: 4, cinq: 5, six: 6, sept: 7, huit: 8, neuf: 9, dix: 10, demi: 0.5 };

/** Range chaque mot dans une classe : accord, appui, poli, refus, report, ou '' (un mot ordinaire). Les expressions de
 *  plusieurs mots passent d'abord (« pas de probleme » est un accord, pas une negation). */
function classer(mots, differe) {
  const classes = new Array(mots.length).fill('');
  for (let i = 0; i < mots.length;) {
    let pris = 0, classe = '';
    for (let n = Math.min(EXPRESSION_MAX, mots.length - i); n >= 1 && !pris; n--) {
      const c = EXPRESSIONS.get(mots.slice(i, i + n).join(' '));
      if (c) { pris = n; classe = c; }
    }
    if (!pris) {
      const m = mots[i];
      // « dans 2 heures », « a 22 h », « vers 22h30 » : un report
      const heure = x => /^\d{1,2}h\d{0,2}$/.test(x || '');
      const nombre = x => /^\d{1,3}$/.test(x || '') || Object.prototype.hasOwnProperty.call(NOMBRES, x || '') || x === 'quelques';
      if (m === 'dans' && nombre(mots[i + 1]) && UNITES.has(mots[i + 2])) { pris = 3; classe = 'report'; }
      else if ((m === 'a' || m === 'vers') && heure(mots[i + 1])) { pris = 2; classe = 'report'; }
      else if ((m === 'a' || m === 'vers') && /^\d{1,2}$/.test(mots[i + 1] || '') && (mots[i + 2] === 'h' || mots[i + 2] === 'heures' || mots[i + 2] === 'heure')) { pris = /^\d{1,2}$/.test(mots[i + 3] || '') ? 4 : 3; classe = 'report'; }
      else if (REFUS_SEUL.has(m)) { pris = 1; classe = 'refus'; }
      else if (REPORT_SEUL.has(m)) { pris = 1; classe = 'report'; }
      else pris = 1;
    }
    for (let k = 0; k < pris; k++) classes[i + k] = classe;
    i += pris;
  }
  return classes;
}

/** Le message n'est-il fait QUE de mots d'accord, de politesse et de bouche-trous, avec au moins un vrai mot d'accord ?
 *  « merci » ne passe qu'avec un oui franc (« oui merci ») : « d'accord merci », « ok super merci » prennent conge. */
const OUI_FRANC = new Set('oui ouais ouai ouaip yes vas allez fais volontiers veux peux'.split(' '));
function ouiPur(mots, classes) {
  if (!mots.length) return false;
  let accord = false, merci = false, franc = false;
  for (let i = 0; i < mots.length; i++) {
    const c = classes[i];
    if (c !== 'accord' && c !== 'appui' && c !== 'poli') return false;
    if (c === 'accord') { accord = true; if (OUI_FRANC.has(mots[i])) franc = true; }
    if (mots[i] === 'merci') merci = true;
  }
  return accord && (!merci || franc);
}

// ---------------------------------------------------------------------------------------------------------------
// 3. Le vocabulaire de chaque outil sensible
// ---------------------------------------------------------------------------------------------------------------
const mots = s => new Set(s.split(' ').filter(Boolean));
/** Un verbe : ses formes d'ordre (« allume », « tu eteins », « que tu allumes »), ses infinitifs, et ses formes floues
 *  (« stop », « arrete »), qui ne valent ordre nu que suivies de « tout ». */
const verbe = (ordres, infinitifs, flous) => ({ ordres: mots(ordres), infinitifs: mots(infinitifs), flous: mots(flous || '') });

const ALLUMER = verbe('allume allumes allumez rallume rallumes rallumez mets mettez remets demarre demarres active actives branche relance lance chauffe',
  'allumer rallumer mettre remettre demarrer activer brancher relancer lancer chauffer');
const ETEINDRE = verbe('eteins eteint eteignez eteignes eteigne coupe coupes coupez arrete arretes arretez stoppe stop desactive debranche',
  'eteindre couper arreter stopper desactiver debrancher', 'stop arrete arretes arretez');
const PROGRAMMER = verbe('programme programmes programmez planifie planifies prevois', 'programmer planifier prevoir');
const LIRE = verbe('lis relis resume resumes ouvre montre regarde cherche trouve analyse donne dis liste affiche sors verifie filme photographie prends scanne',
  'lire relire resumer ouvrir montrer regarder chercher trouver analyser donner dire lister afficher sortir verifier filmer photographier prendre scanner');

const PRISES = { generiques: mots('prise prises shelly'), nommes: mots('radiateur radiateurs chauffage chauffages convecteur convecteurs') };
const SYNONYMES = [mots('radiateur radiateurs chauffage chauffages convecteur convecteurs')];
const SANS_LIMITE = mots('limite arret extinction continu indefiniment minuterie');      // « sans limite », « sans arret », « en continu »

/** allumer : sans_limite et une duree au-dela des 180 minutes par defaut doivent etre dits par l'utilisateur */
function aggraveLaPrise(params, m) {
  const vrai = v => v === true || /^(?:oui|true|1|vrai)$/.test(chaine(v).trim().toLowerCase());
  if (vrai(params.sans_limite) && !m.some(x => SANS_LIMITE.has(x)) && !(m.includes('toute') && m.includes('nuit'))) return true;
  const duree = Number(params.duree_min);
  if (Number.isFinite(duree) && duree > 180) {
    let dite = 0;
    for (let i = 0; i + 1 < m.length; i++) {
      const n = /^\d{1,3}$/.test(m[i]) ? Number(m[i]) : NOMBRES[m[i]];
      if (!n) continue;
      if (m[i + 1] === 'h' || m[i + 1] === 'heure' || m[i + 1] === 'heures') dite = Math.max(dite, n * 60);
      if (m[i + 1] === 'min' || m[i + 1] === 'mn' || m[i + 1] === 'minute' || m[i + 1] === 'minutes') dite = Math.max(dite, n);
    }
    if (dite < duree) return true;
  }
  return false;
}

// Pour chaque outil : generiques (les mots qui designent ce qu'il touche, sans dire lequel), nommes (des mots qui
// designent une chose precise : « radiateur »), lectures (ses actions qui ne changent rien, avec leurs mots propres),
// actions (celles qui changent quelque chose). Pour une action : verbe, objets (en plus des generiques), souple (un
// parametre dont la valeur doit etre nommee si le message nomme quelque chose), exige (un parametre dont la valeur doit
// toujours etre nommee), choix (l'action porte sur des numeros), aggrave (un parametre qui aggrave, non dit).
const OUTILS = {
  prises_shelly: {
    generiques: PRISES.generiques, nommes: PRISES.nommes,
    lectures: { etat: mots('consomme consommes consommation watt watts kwh allumE allumEe eteint eteinte etat') },
    actions: {
      allumer: { verbe: ALLUMER, souple: ['prise'], aggrave: aggraveLaPrise },
      eteindre: { verbe: ETEINDRE, souple: ['prise'] },
    },
  },
  // une action differee sur une prise (« eteins le radiateur dans 2 heures ») : l'accord vaut pour l'action finale
  planificateur: {
    generiques: PRISES.generiques, nommes: PRISES.nommes, differe: true,
    lectures: { lister: mots('rappel rappels tache taches programme programmes prevu prevus'), lieux: mots('lieu lieux') },
    actions: {},
  },
  lire_pdf: {
    generiques: mots('pdf facture factures contrat contrats courrier courriers document documents fichier fichiers scan scans lettre lettres devis releve releves'
      + ' attestation attestations bulletin bulletins avis quittance quittances papier papiers notice notices'),
    cles: ['nom'], lectures: { lire: null, liste: null }, toutEstLecture: true, actions: {},
  },
  cameras: {
    generiques: mots('camera cameras webcam webcams videosurveillance surveillance'), cles: ['camera', 'nom'],
    lectures: { liste: null, chercher: null, verifier: null, photo: mots('photo photos image images cliche cliches'), video: mots('video videos film filme filmer') },
    actions: { ajouter: { verbe: verbe('ajoute ajoutes ajoutez enregistre declare configure installe branche connecte', 'ajouter enregistrer declarer configurer installer brancher connecter') } },
  },
  retro: {
    generiques: mots('retro ingenierie retroingenierie reverse triage apk exe firmware binaire decompile decompiler desassemble desassembler decortique decortiquer'
      + ' analyse analyser analyses marche fonctionne'),
    cles: ['cible'], lectures: { triage: null, liste: null }, toutEstLecture: true, actions: {},
  },
  ranger_mails: {
    generiques: mots('mail mails email emails courriel courriels gmail outlook boite messagerie inbox indesirables spam spams brouillons newsletter newsletters pub pubs'
      + ' publicite publicites'),
    cles: ['vers', 'depuis', 'chemin', 'criteres'],
    lectures: { chercher: mots('recu recus recois arrive arrives expediteur'), dossiers: mots('dossier dossiers libelle libelles'), journal: mots('journal') },
    actions: {
      deplacer: { verbe: verbe('range ranges rangez deplace deplaces deplacez classe classes trie tries archive archives mets transfere bouge',
        'ranger deplacer classer trier archiver mettre transferer bouger'), exige: ['vers'] },
      creerdossier: { verbe: verbe('cree crees creez ajoute ajoutes fais', 'creer ajouter faire'), objets: mots('dossier dossiers libelle libelles etiquette etiquettes'),
        sansGeneriques: true, exige: ['chemin'] },
      annuler: { verbe: verbe('annule annules annulez remets defais reviens restaure', 'annuler remettre defaire revenir restaurer'), objets: mots('rangement deplacement') },
    },
  },
  imprimante_3d: {
    generiques: mots('impression impressions imprimante print gcode 3mf stl fabrication plateau piece pieces'), cles: ['fichier'],
    alias: { televerser: 'envoyer', upload: 'envoyer', imprimer: 'lancer', demarrer: 'lancer', start: 'lancer', stop: 'annuler', arreter: 'annuler' },
    lectures: { etat: null, fichiers: null },
    actions: {
      envoyer: { verbe: verbe('envoie envoies envoyez transfere televerse charge mets depose copie', 'envoyer transferer televerser charger mettre deposer copier'),
        objets: mots('fichier fichiers modele'), souple: ['fichier'] },
      lancer: { verbe: verbe('lance lances lancez imprime imprimes imprimez demarre demarres commence fabrique relance', 'lancer imprimer demarrer commencer fabriquer relancer'),
        souple: ['fichier'] },
      annuler: { verbe: verbe('annule annules annulez arrete arretes arretez stoppe stop interromps', 'annuler arreter stopper interrompre', 'stop arrete arretes arretez') },
      pause: { verbe: verbe('suspends mets mettez', 'suspendre mettre'), avec: 'pause' },
      reprendre: { verbe: verbe('reprends reprenez relance continue poursuis', 'reprendre relancer continuer poursuivre') },
    },
  },
  curateur: {
    generiques: mots('curateur memoire proposition propositions rangement rangements fiche fiches doublon doublons numero numeros'),
    lectures: { examiner: mots('tournee menage range ranger nettoie nettoyer trie trier'), propositions: null },
    actions: {
      appliquer: { verbe: verbe('applique appliques appliquez valide valides accepte acceptes prends garde execute retiens', 'appliquer valider accepter prendre garder executer retenir'),
        choix: ['numeros', 'texte'] },
      annuler: { verbe: verbe('annule annules annulez remets defais reviens restaure', 'annuler remettre defaire revenir restaurer'), objets: mots('changements changement'),
        neutres: mots('comme avant') },
    },
  },
  mecanicien: {
    generiques: mots('outil'), cles: ['nom'],
    lectures: { etat: null, voir: null, idee: null, abandonner: null },
    actions: {
      construire: { verbe: verbe('fabrique fabriques fabriquez construis construit construisez cree crees invente bricole code fais monte developpe prepare',
        'fabriquer construire creer inventer bricoler coder faire monter developper preparer'), choix: ['numero'], texteDit: 'texte', souhait: true },
      valider: { verbe: verbe('valide valides validez validE installe installes accepte garde adopte', 'valider installer accepter garder adopter'), choix: ['numero', 'texte'] },
      retirer: { verbe: verbe('retire retires retirez supprime supprimes desinstalle enleve vire efface', 'retirer supprimer desinstaller enlever virer effacer'), exige: ['nom'] },
    },
  },
};

// ---------------------------------------------------------------------------------------------------------------
// 4. Les parametres de l'appel
// ---------------------------------------------------------------------------------------------------------------
const estObjet = x => !!x && typeof x === 'object' && !Array.isArray(x);
function lireJson(x) {
  if (typeof x !== 'string' || x.length > JSON_MAX || !x.trim()) return undefined;
  try { return JSON.parse(x); } catch (e) { return undefined; }
}
/** Les parametres, JSON ou objet, un niveau « parametres » imbrique fusionne (comme core/outils_maison.js). */
function parametresDe(p) {
  let o = typeof p === 'string' ? lireJson(p) : p;
  if (!estObjet(o)) return {};
  for (let tour = 0; tour < 50; tour++) {
    const dedans = estObjet(o.parametres) ? o.parametres : lireJson(o.parametres);
    if (!estObjet(dedans)) break;
    const reste = Object.assign({}, o);
    delete reste.parametres;
    o = Object.assign(reste, dedans);
  }
  return o;
}
/** Une action, comme le lanceur la compare (sa forme « nue ») : ses seules lettres, sans accents. */
const nue = v => unifier(chaine(v).slice(0, 80)).toLowerCase().normalize('NFD').replace(/[^a-z]/g, '');

const MOTS_VIDES = mots('le la les un de du et en au a ou si ne je tu il on ce se sa mon ma ta te me y pour avec dans sans sous chez vers depuis entre mais donc tout tous toute toutes cette cela comme plus moins tres bien aussi alors'
  + ' moi toi lui elle nous vous leur mon ton son mes tes ses notre votre une des les aux que qui quoi est sont etre avoir fait faire fais outil outils'
  + ' fichier fichiers document documents users user home windows program files appdata local temp downloads telechargements bureau desktop'
  + ' gcode 3mf stl pdf json txt jpg png the and');
/** Les mots qui comptent dans la valeur d'un parametre (le nom d'une prise, d'un dossier, d'un outil), synonymes compris. */
function motsDe(valeur, profondeur) {
  const vus = new Set();
  const ajouter = v => {
    if (typeof v === 'number') v = String(v);
    if (typeof v !== 'string') return;
    let brut = v.slice(0, PARAMETRE_MAX);
    if (/[\\/]/.test(brut)) brut = brut.split(/[\\/]/).filter(Boolean).slice(-2).join(' ');      // un chemin : ses deux derniers morceaux
    for (const m of enMots(unifier(brut).toLowerCase().replace(/_/g, ' '))) {
      const mot = m.toLowerCase();
      if (mot.length >= 2 && !MOTS_VIDES.has(mot) && !/^\d+$/.test(mot) && vus.size < 16) vus.add(mot);
    }
  };
  if (estObjet(valeur) && (profondeur || 0) < 1) { for (const k of Object.keys(valeur).slice(0, 8)) ajouter(valeur[k]); } else ajouter(valeur);
  for (const groupe of SYNONYMES) if ([...vus].some(m => groupe.has(m))) for (const m of groupe) vus.add(m);
  return vus;
}
/** « pub » et « publicites », « facture » et « factures », « meteo » et « meteo_marine » : le meme nom */
const meme = (a, b) => a === b || (a.length >= 3 && b.length >= 3 && (a.startsWith(b) || b.startsWith(a)));
const nomme = (m, cibles) => cibles.size > 0 && m.some(x => { const y = x.toLowerCase(); for (const c of cibles) if (meme(y, c)) return true; return false; });

// ---------------------------------------------------------------------------------------------------------------
// 5. Les numeros (curateur, mecanicien)
// ---------------------------------------------------------------------------------------------------------------
const ORDINAUX = { premier: 1, premiere: 1, deuxieme: 2, second: 2, seconde: 2, troisieme: 3, quatrieme: 4, cinquieme: 5, sixieme: 6 };
const ORDINAUX_PLURIELS = mots('premiers premieres');
const TOUT = mots('tout toutes tous');
const AUTOUR_D_UN_CHOIX = mots("la le les l' numero numeros et ou puis juste seulement uniquement proposition propositions idee idees pour curateur mecanicien");

/** Les numeros dits dans une suite de mots : { nombres, tout, illisible, n (combien de mots de choix) }. strict : tout
 *  autre mot rend la suite illisible (pour lire ce que le modele a mis dans les parametres). */
function choixDans(m, strict) {
  const r = { nombres: new Set(), tout: false, illisible: false, n: 0 };
  for (let i = 0; i < m.length; i++) {
    const x = m[i], avant = m[i - 1] || '', apres = m[i + 1] || '';
    const chiffre = /^\d{1,3}$/.test(x) ? Number(x) : NaN;
    const lettres = Object.prototype.hasOwnProperty.call(NOMBRES, x) && x !== 'demi' ? NOMBRES[x] : NaN;
    if (!Number.isNaN(chiffre) || !Number.isNaN(lettres)) {
      const n = Number.isNaN(chiffre) ? lettres : chiffre;
      if (UNITES.has(apres)) { if (strict) r.illisible = true; continue; }                                  // « 20 minutes » : une duree
      if (ORDINAUX_PLURIELS.has(apres)) { for (let k = 1; k <= Math.min(n, 20); k++) r.nombres.add(k); r.n++; i++; continue; }      // « les deux premieres »
      if ((x === 'un' || x === 'une') && !strict && !(mots("la le numero et ou").has(avant) || apres === 'et' || apres === 'ou' || m.length === 1)) continue;       // un article
      if (avant === 'les' && !strict) { r.tout = true; r.n++; continue; }                                     // « les trois » : toutes
      r.nombres.add(n); r.n++;
    } else if (Object.prototype.hasOwnProperty.call(ORDINAUX, x)) { r.nombres.add(ORDINAUX[x]); r.n++; }
    else if (x === 'derniere' || x === 'dernier' || x === 'dernieres' || x === 'derniers') { r.illisible = true; r.n++; }
    else if (TOUT.has(x)) { r.tout = true; r.n++; }
    else if (strict && !(x === 'et' || x === 'ou' || x === 'la' || x === 'le' || x === 'les' || x === 'numero' || x === 'numeros')) r.illisible = true;
  }
  return r;
}
/** Ce que le modele veut appliquer : la premiere des cles qui porte quelque chose (curateur.py lit numeros OU texte). */
function choixVoulu(params, cles) {
  for (const k of cles) {
    let v = params[k];
    if (Array.isArray(v)) v = v.slice(0, 30).map(x => (typeof x === 'number' || typeof x === 'string') ? String(x) : '?').join(' ');
    if (typeof v === 'number') v = String(v);
    if (typeof v !== 'string' || !v.trim()) continue;
    const r = choixDans(enMots(unifier(v.slice(0, PARAMETRE_MAX)).toLowerCase()), true);
    if (!r.n) r.illisible = true;
    return r;
  }
  return null;
}
function memesNumeros(dit, voulu) {
  if (!voulu || dit.illisible || voulu.illisible) return false;
  if (dit.tout || voulu.tout) return dit.tout && voulu.tout && !dit.nombres.size && !voulu.nombres.size;
  if (dit.nombres.size !== voulu.nombres.size) return false;
  for (const n of dit.nombres) if (!voulu.nombres.has(n)) return false;
  return dit.nombres.size > 0;
}

// ---------------------------------------------------------------------------------------------------------------
// 6. La demande directe
// ---------------------------------------------------------------------------------------------------------------
// ce qui peut preceder un ordre : « oui », « et », « tu », « curateur », « bonjour »…
const AVANT_L_ORDRE = mots('et puis ensuite tu me nous toi y aussi curateur mecanicien bonjour salut bonsoir hey dis');
const AVANT_LE_SOUHAIT = ["j' aimerais bien que tu", "j' aimerais que tu", 'je veux que tu', 'je voudrais que tu', 'je voudrais bien que tu', 'il faut que tu', 'il faudrait que tu'];
// ce qui fait d'un infinitif une demande : « tu peux eteindre », « il faudrait lancer », « pense a couper »
const MARQUES = ['tu peux', 'peux tu', 'tu pourrais', 'pourrais tu', 'tu veux bien', 'tu voudrais bien', 'est ce que tu peux', 'est ce que tu pourrais', 'il faut', 'il faudrait',
  "merci d'", 'merci de', 'pense a', "ce serait bien d'", 'ce serait bien de'];
const ENTRE_MARQUE_ET_VERBE = mots('me nous moi bien donc vite juste');
// ce qui peut separer un verbe de son objet : « mets-MOI UN PEU DE chauffage », « lance L'impression »
const AVANT_L_OBJET = mots("moi nous toi lui leur donc vite bien juste encore aussi le la les l' l un une des du de d' d mon ma mes ton ta tes ce cet cette ces tout toute tous toutes peu"
  + ' nouveau nouvelle nouvel petit petite ca cela');
const PRONOMS = mots('le la les ca cela moi tout toute tous toutes');
const PREPOSITIONS = mots("dans vers sur a au aux en pour pendant de du d' des chez avec");
// des mots qui n'ajoutent rien a une demande : politesse, duree, insistance
const NEUTRES = mots("le la les l' l un une des du de d' d a au aux en et puis pour pendant dans vers sur moi toi nous me te ca cela stp merci vite bien donc alors maintenant encore"
  + ' aussi juste peu tout toute tous toutes h heure heures min mn minute minutes seconde secondes demi demie fois jusqu jusqua ce cet cette mon ma mes ton ta tes');

const finit = (m, i, expression) => { const e = expression.split(' '); if (i < e.length) return false; for (let k = 0; k < e.length; k++) if (m[i - e.length + k] !== e[k]) return false; return true; };

/** Ou le verbe de l'action est-il dit, en position de demande ? Rend { i, flou, infinitif } ou null. */
function trouverLeVerbe(m, classes, v, differe) {
  // (a) une forme d'ordre, precedee seulement de mots d'accord, de politesse et de petits mots
  let debut = 0;
  for (const s of AVANT_LE_SOUHAIT) { const e = s.split(' '); if (finit(m, e.length, s)) debut = e.length; }
  for (let i = debut; i < m.length; i++) {
    if (v.ordres.has(m[i]) || v.infinitifs.has(m[i])) return { i, flou: v.flous.has(m[i]), infinitif: v.infinitifs.has(m[i]) };
    const c = classes[i];
    if (!(c === 'accord' || c === 'appui' || c === 'poli' || AVANT_L_ORDRE.has(m[i]) || (differe && c === 'report'))) break;
  }
  // (b) un infinitif juste apres une marque de demande : « tu peux me mettre le chauffage », « il faudrait eteindre »
  for (let i = 1; i < m.length; i++) {
    if (!v.infinitifs.has(m[i])) continue;
    for (let j = i; j >= Math.max(1, i - 2); j--) {
      if (j < i && !ENTRE_MARQUE_ET_VERBE.has(m[j])) break;
      for (const marque of MARQUES) {
        if (!finit(m, j, marque)) continue;
        const avant = m[j - marque.split(' ').length - 1] || '';
        if (avant === 'si' || avant === 'que' || avant === 'quand' || avant === 'ou' || avant === 'comme' || avant === 'ne' || avant === "n'") continue;
        return { i, flou: false, infinitif: true };
      }
    }
  }
  return null;
}

/** Le message demande-t-il cette action ? Rend null, ou { nu (un ordre sans objet : « allume-la »), generique (l'objet
 *  ne dit pas lequel : « la prise »), reste (les mots dits en plus), i (la place de l'objet) }. */
function demander(m, classes, fiche, a, cibles, differe) {
  const lieu = trouverLeVerbe(m, classes, a.verbe, differe);
  if (!lieu) return null;
  if (a.avec && !m.includes(a.avec)) return null;
  const objets = x => (!a.sansGeneriques && fiche.generiques.has(x)) || (a.objets && a.objets.has(x)) || (!a.sansGeneriques && fiche.nommes && fiche.nommes.has(x));
  let i = lieu.i + 1, saute = 0, pronom = false;
  while (i < m.length && saute < 6 && AVANT_L_OBJET.has(m[i])) { if (PRONOMS.has(m[i])) pronom = true; i++; saute++; }
  // « programme l'extinction du radiateur » : l'action differee nomme son geste, puis sa cible
  if (differe && i + 1 < m.length && mots('extinction allumage arret coupure').has(m[i])) { i++; while (i < m.length && AVANT_L_OBJET.has(m[i])) i++; }
  const x = (m[i] || '').toLowerCase();
  const estChoix = !!a.choix && i < m.length && (/^\d{1,3}$/.test(x) || Object.prototype.hasOwnProperty.call(ORDINAUX, x) || TOUT.has(x) || (Object.prototype.hasOwnProperty.call(NOMBRES, x)));
  const cible = i < m.length && [...cibles].some(c => meme(x, c));
  if (i < m.length && (objets(x) || cible || estChoix)) {
    const reste = m.slice(i + 1).filter((y, k) => !NEUTRES.has(y) && classes[i + 1 + k] === '' && !/^\d{1,3}$/.test(y) && !Object.prototype.hasOwnProperty.call(NOMBRES, y) && !fiche.generiques.has(y) && !(a.objets && a.objets.has(y)));
    return { nu: false, generique: !cible && !estChoix && fiche.generiques.has(x) || (!cible && !!a.objets && a.objets.has(x)), nommeAutre: !cible && !!fiche.nommes && fiche.nommes.has(x), reste, i };
  }
  // un ordre nu : rien apres le verbe, ou un pronom, ou une preposition (« deplace-les dans Factures », « eteins-moi ca »)
  const suite = m.slice(i).filter((y, k) => !NEUTRES.has(y) && classes[i + k] === '' && !(a.neutres && a.neutres.has(y)));
  if (i >= m.length || (pronom && PREPOSITIONS.has(m[i])) || classes[i] !== '' || (a.neutres && a.neutres.has(m[i]))) {
    if (lieu.flou && !m.slice(lieu.i + 1, i).some(y => TOUT.has(y))) return null;      // « stop », « arrete » tout seuls ne disent pas quoi
    return { nu: true, generique: false, nommeAutre: false, reste: suite, i };
  }
  return null;
}

// ---------------------------------------------------------------------------------------------------------------
// 7. Le verdict
// ---------------------------------------------------------------------------------------------------------------
const oui = raison => ({ accorde: true, raison });
const non = raison => ({ accorde: false, raison });

/** Un « oui » repond-il a une demande d'accord en attente ? appel.enAttente : absent = on ne sait pas (le oui compte) ;
 *  null = rien n'etait en attente (le oui ne compte pas : « Tu veux que je t'explique ? » « oui ») ;
 *  {outil, action} = le oui ne vaut que pour cet outil-la (et cette action, si elle est donnee). */
function ouiAttendu(appel, outil, action) {
  if (!appel || !Object.prototype.hasOwnProperty.call(appel, 'enAttente') || appel.enAttente === undefined) return true;
  const e = appel.enAttente;
  if (!e || typeof e !== 'object') return false;
  if (chaine(e.outil).trim().toLowerCase() !== outil) return false;
  return !nue(e.action) || !action || nue(e.action) === action;
}

/** Les verbes et la cible d'une action differee (planificateur + prise) : ceux de son geste final. */
function actionDifferee(fiche, params) {
  const finale = parametresDe(params.outil_parametres);
  const geste = nue(finale.action);
  const ordres = new Set(PROGRAMMER.ordres), infinitifs = new Set(PROGRAMMER.infinitifs);
  for (const v of [geste === 'eteindre' ? null : ALLUMER, geste === 'allumer' ? null : ETEINDRE]) {
    if (!v) continue;
    for (const x of v.ordres) ordres.add(x);
    for (const x of v.infinitifs) infinitifs.add(x);
  }
  return { a: { verbe: { ordres, infinitifs, flous: new Set() }, souple: ['prise'] }, params: Object.assign({}, params, { prise: finale.prise }) };
}

/** { accorde, raison } : l'utilisateur vient-il, dans son dernier message, de donner son accord a cette action ? */
function accordDansMessage(message, appel) {
  try {
    const lu = lire(message);
    const ap = estObjet(appel) ? appel : {};
    const outil = chaine(ap.outil).trim().toLowerCase().slice(0, 60);
    let params = parametresDe(ap.parametres);
    const fiche = Object.prototype.hasOwnProperty.call(OUTILS, outil) ? OUTILS[outil] : null;
    // l'action que l'outil recevra : celle des parametres, comme dans le lanceur ; sinon celle du premier niveau
    let action = nue(params.action);
    if (!action) { action = nue(ap.action); if (action === 'utiliser' || action === 'utilise' || action === 'lanceroutil') action = ''; }
    if (fiche && fiche.alias && Object.prototype.hasOwnProperty.call(fiche.alias, action)) action = fiche.alias[action];
    if (fiche && fiche.differe && !Object.prototype.hasOwnProperty.call(fiche.lectures, action)) action = 'ajouter';

    const m = lu.mots;
    if (!m.length) return non('message_vide');
    const differe = !!(fiche && fiche.differe && action === 'ajouter');
    const classes = classer(m, differe);
    const pur = ouiPur(m, classes);

    // 1. un refus, ou qu'il soit dans le message : non, pas, plus, sauf, attends, laisse, je m'en occupe…
    if (classes.includes('refus')) return non('negation');

    // 2. une action qui ne fait que lire : il suffit que le message nomme ce qui est lu, question comprise
    const lecture = !!fiche && (Object.prototype.hasOwnProperty.call(fiche.lectures, action) || (fiche.toutEstLecture && !Object.prototype.hasOwnProperty.call(fiche.actions, action)));
    if (lecture) {
      if (pur && !lu.question) return ouiAttendu(ap, outil, action) ? oui('oui_explicite') : non('oui_sans_demande');
      if (m.some(x => CONTRE_ORDRE.has(x))) return non('negation');
      const propres = fiche.lectures[action];
      const cibles = new Set();
      for (const k of fiche.cles || []) for (const x of motsDe(params[k])) cibles.add(x);
      if (m.some(x => fiche.generiques.has(x) || (fiche.nommes && fiche.nommes.has(x)) || (propres && propres.has(x))) || nomme(m, cibles)) return oui('demande_de_lecture');
      const v = lu.question ? null : trouverLeVerbe(m, classes, LIRE, false);
      if (v && m.slice(v.i + 1).every((x, k) => NEUTRES.has(x) || classes[v.i + 1 + k] !== '')) return oui('demande_de_lecture');      // « lis-le », « montre »
      return non(interroge(lu, m) ? 'question' : 'hors_sujet');
    }

    // 3. un oui pur : tout le message n'est qu'accord, politesse et bouche-trous
    if (pur) {
      if (lu.question) return non('question');
      return ouiAttendu(ap, outil, action) ? oui('oui_explicite') : non('oui_sans_demande');
    }

    // 4. sinon il faut une demande directe de CETTE action
    if (!fiche) {
      // un outil sans vocabulaire connu : son nom entier dans le message, apres un verbe d'ordre en tete
      const noms = outil.split(/[^a-z0-9]+/).filter(x => x.length >= 4);
      const ordre = mots('lance lancer demarre active utilise fais ouvre ferme allume eteins mets arrete coupe envoie');
      if (noms.length && noms.every(x => m.includes(x)) && ordre.has(m[0]) && !lu.question && !classes.includes('report') && !lu.tronque && ap.tronque !== true) return oui('demande_directe');
      if (m.some(x => CONTRE_ORDRE.has(x))) return non('negation');
      return non(interroge(lu, m) ? 'question' : outil ? 'outil_sans_vocabulaire' : 'hors_sujet');
    }
    let a = fiche.actions[action];
    if (differe) { const d = actionDifferee(fiche, params); a = d.a; params = d.params; }
    // les mots d'avant les deux-points seulement : ce qui les suit est une citation (« traduis : allume le radiateur »)
    const md = lu.coupe ? lu.avant : m;
    const cd = lu.coupe ? classer(md, differe) : classes;
    const cibles = new Set();
    if (a) for (const k of (a.souple || []).concat(a.exige || [])) for (const x of motsDe(params[k])) cibles.add(x);
    const d = a ? demander(md, cd, fiche, a, cibles, differe) : null;

    // un contre-ordre (« annule », « stop », « oublie ») qui n'est pas le verbe de cette action
    if (!d && m.some(x => CONTRE_ORDRE.has(x))) return non(a ? 'action_differente' : 'negation');
    // une autre action du meme outil (« oui, eteins-le » alors que le modele allume)
    if (!d) {
      for (const autre of Object.keys(fiche.actions)) {
        if (autre === action) continue;
        const b = fiche.actions[autre];
        const propre = { verbe: { ordres: new Set([...b.verbe.ordres].filter(x => !PASSE_PARTOUT.has(x))), infinitifs: new Set([...b.verbe.infinitifs].filter(x => !PASSE_PARTOUT.has(x))), flous: new Set() },
          objets: b.objets, sansGeneriques: b.sansGeneriques, choix: b.choix, avec: b.avec };
        if (demander(md, cd, fiche, propre, new Set(), false)) return non('action_differente');
      }
    }
    if (!a) return non(interroge(lu, m) ? 'question' : 'action_inconnue');

    // les numeros dits dans le message (curateur, mecanicien)
    const dit = a.choix ? choixDans(md.map(x => x.toLowerCase()), false) : null;
    const seulementUnChoix = !!dit && dit.n > 0 && md.every((x, k) => cd[k] !== '' || AUTOUR_D_UN_CHOIX.has(x) || NEUTRES.has(x) || /^\d{1,3}$/.test(x)
      || Object.prototype.hasOwnProperty.call(NOMBRES, x) || Object.prototype.hasOwnProperty.call(ORDINAUX, x) || ORDINAUX_PLURIELS.has(x) || TOUT.has(x));
    // « j'aimerais un outil pour la meteo marine », « il me faudrait un outil qui… »
    const souhait = !!a.souhait && !d && SOUHAITS.some(s => { const e = s.split(' '); return finit(md, e.length, s) && (md[e.length] === 'outil' || (md[e.length] === 'nouvel' && md[e.length + 1] === 'outil')); });
    // « on y va pour l'impression » : un oui, puis ce que l'action touche
    let ouiPuisObjet = false;
    if (!d && !seulementUnChoix && !souhait) {
      let k = 0;
      while (k < md.length && (cd[k] === 'accord' || cd[k] === 'appui' || cd[k] === 'poli')) k++;
      const suite = md.slice(k);
      ouiPuisObjet = k > 0 && cd.slice(0, k).includes('accord') && suite.length > 0 && suite.length <= 4
        && suite.every(x => NEUTRES.has(x) || fiche.generiques.has(x) || nomme([x], cibles)) && suite.some(x => fiche.generiques.has(x) || nomme([x], cibles));
    }
    if (!d && !seulementUnChoix && !souhait && !ouiPuisObjet) {
      // un oui suivi d'autre chose (« ok, resume-moi cet article »), ou rien qui demande l'action
      if (interroge(lu, m)) return non('question');
      return non(classes.includes('accord') ? 'oui_et_autre_chose' : 'hors_sujet');
    }

    // 5. une demande directe est la : tout ce qui peut encore la faire refuser
    if (ap.tronque === true || lu.tronque) return non('message_tronque');
    if (!differe && classes.includes('report')) return non('pas_maintenant');
    if (md.some((x, k) => cd[k] === '' && DOUTE.has(x))) return non('question');
    if (lu.question && !(d && (MARQUES.some(x => md.join(' ').indexOf(x) >= 0) || !INTERROGATIFS.has(md[0])))) return non('question');
    if (lu.question && md.includes('ou')) return non('question');
    // les numeros : exactement ceux que l'utilisateur vient de choisir
    const parNumero = !!a.choix && !!dit && dit.n > 0 && !(a.texteDit && md.includes('outil'));      // « construis la 2 », pas « un outil qui compte les 3 derniers… »
    if (parNumero && !memesNumeros(dit, choixVoulu(params, a.choix))) return non('numeros_differents');
    // la cible : la prise, le dossier, l'outil nommes par les parametres
    for (const k of a.exige || []) {
      const c = motsDe(params[k]);
      if (c.size && !nomme(md, c)) return non('cible_differente');
    }
    for (const k of a.souple || []) {
      const c = motsDe(params[k]);
      if (!c.size || nomme(md, c)) continue;
      if (d && (d.nommeAutre || d.reste.length)) return non('cible_differente');      // « eteins la prise du salon », parametre « four »
    }
    // un parametre qui aggrave, ou un texte libre que l'utilisateur n'a pas dit
    if (a.aggrave && a.aggrave(params, md)) return non('parametre_non_dit');
    if (differe && chaine(params.tous_les).trim() && !md.some(x => x === 'chaque' || x === 'tous' || x === 'toutes')) return non('parametre_non_dit');
    if (a.texteDit && !parNumero) {
      // « fabrique-moi un outil qui donne la meteo marine » : le texte passe a l'outil doit reprendre les mots du message
      const c = [...motsDe(params[a.texteDit])].filter(x => x.length >= 4);
      if (!c.length || c.filter(x => nomme(md, new Set([x]))).length * 2 < c.length) return non('parametre_non_dit');
    }
    return oui('demande_directe');
  } catch (e) {
    return non('message_vide');      // jamais d'exception ; ce code dit seulement « je n'ai rien pu lire »
  }
}
// des verbes qui se disent de n'importe quelle action : ils ne suffisent pas a dire que l'utilisateur en veut une AUTRE
const PASSE_PARTOUT = mots('fais faire faites mets mettre mettez remets remettre prends prendre garde garder lance lancer lancez relance relancer execute continue valide valider');
const SOUHAITS = ["j' aimerais", "j' aimerais bien", 'je voudrais', 'je voudrais bien', 'je veux', 'il me faudrait', 'il faudrait', "j' ai besoin d'"].map(s => s + ' un').concat(
  ["j' aimerais", 'je voudrais', 'je veux', 'il me faudrait', 'il faudrait'].map(s => s + ' un nouvel'));
const INTERROGATIFS = mots("est qu' quel quelle quels quelles combien pourquoi comment ou qui faut sais as a y c' dis");
const DEBUTS_DE_QUESTION = ['est ce', "qu' est", "c' est quoi", 'quel', 'quelle', 'quels', 'quelles', 'combien', 'pourquoi', 'comment', 'ou en', 'ou est', 'ou sont', 'qui', 'faut il',
  'as tu', 'sais tu', 'y a t il', 'je me demande'];
/** Le message interroge-t-il ? Un point d'interrogation, ou une tournure de question en tete. */
function interroge(lu, m) {
  if (lu.question) return true;
  return DEBUTS_DE_QUESTION.some(d => { const e = d.split(' '); for (let k = 0; k < e.length; k++) if (m[k] !== e[k]) return false; return true; });
}

/** Le message n'est-il qu'un oui ? Vrai seulement s'il est fait tout entier de mots d'accord, de politesse et de
 *  bouche-trous, sans question ni refus. C'est tout ce dont l'approche « accord fige » a besoin (BRANCHEMENT.md) : le
 *  lanceur garde l'appel exact en attente, et un message qui n'est qu'un oui execute cet appel-la, tel quel. */
function ouiStrict(message) {
  try {
    const lu = lire(message);
    if (!lu.mots.length || lu.question || lu.tronque) return false;
    const classes = classer(lu.mots, false);
    return !classes.includes('refus') && ouiPur(lu.mots, classes);
  } catch (e) {
    return false;
  }
}

module.exports = { accordDansMessage, ouiStrict, OUTILS_CONNUS: Object.keys(OUTILS), _interne: { lire, enMots, classer, ouiPur, choixDans, parametresDe } };
