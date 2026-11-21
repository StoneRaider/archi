// promesses.js - Archi ne dit pas « c'est fait » si aucun outil ne l'a fait pendant ce tour.
// Port de concours_fable/intendant/verifier.py (promesses_en_l_air), adapte aux outils d'Archi (outils/registre.json et
// les outils branches directement sur l'agent : navigateur, lire_page, videos_youtube, enquete_osint, Wikipedia).
//
//   actesDesSteps(steps)            -> [{outil, action, statut}]   ce que les outils ont vraiment fait pendant le tour
//   promessesEnLAir(reponse, steps) -> [{famille, raison}]         ce que la reponse affirme sans acte pour le soutenir
//   avertissement(manques)          -> une phrase a ajouter sous la reponse (chaine vide s'il n'y a rien a dire)
//
// Trois regles tenues ici :
//   1. Fonctions pures : du texte et des donnees en entree, des donnees en sortie. Ni fichier, ni reseau, ni horloge.
//   2. Jamais d'exception : null, un objet, une chaine vide donnent une liste vide.
//   3. Dans le doute, rien n'est signale : une question, une proposition, une citation, un constat lu par un outil,
//      un outil dont on ne sait pas lire l'appel ne declenchent rien.
//
// Le texte est lu phrase par phrase, sur sa forme « nette » (minuscules, sans accents : voir texte.js). Une affirmation
// est une tournure d'accomplissement : « j'ai / je t'ai / je viens de… », un passif (« a ete lancee »), un constat
// d'etat annonce comme un geste (« la prise est eteinte »), un engagement (« je te le rappellerai »), un participe seul
// en tete de phrase (« Programmé pour lundi ! »).
'use strict';
const { net, minuscules, chaine, borner, resserrer, FIN_DE_MOT } = require('./texte');

// Bornes posees AVANT toute expression reguliere : une reponse, un tour, une observation demesures ne doivent pas
// ralentir le verificateur. Au-dela, on lit le debut et la fin de la reponse, et les derniers pas du tour.
const REPONSE_MAX = 12000, REPONSE_QUEUE = 4000, PAS_MAX = 200, OBSERVATION_MAX = 4000, JSON_MAX = 1000000, PHRASES_MAX = 400;

// ---------------------------------------------------------------------------------------------------------------
// 1. Les actes du tour
// ---------------------------------------------------------------------------------------------------------------

function lireJson(x) {
  if (typeof x !== 'string') return undefined;
  if (x.length > JSON_MAX) return undefined;       // un texte demesure n'est pas relu : il compte comme « illisible »
  const s = x.trim();
  if (!s) return undefined;
  try { return JSON.parse(s); } catch (e) { return undefined; }
}
const estObjet = x => !!x && typeof x === 'object' && !Array.isArray(x);

/** L'entree d'un outil : une chaine JSON, un objet, ou l'enveloppe de n8n {input: "<json>"}. Rend un objet, ou null. */
function entreeDe(toolInput) {
  let e = toolInput;
  for (let tour = 0; tour < 5; tour++) {
    if (typeof e === 'string') { e = lireJson(e); continue; }
    if (!estObjet(e)) return null;
    const enveloppe = ['input', 'query', 'entree'].find(k => k in e && !('outil' in e) && !('action' in e) && Object.keys(e).length <= 2);
    if (enveloppe && (typeof e[enveloppe] === 'string' || estObjet(e[enveloppe]))) { e = e[enveloppe]; continue; }
    return e;
  }
  return estObjet(e) ? e : null;
}

/** Les parametres d'un outil maison, lus comme le fait core/outils_maison.js (lireParametres) : JSON ou objet,
 *  et un niveau « parametres » imbrique est fusionne. */
function parametresDe(p) {
  let o = p;
  if (typeof o === 'string') o = lireJson(o);
  if (!estObjet(o)) return {};
  for (let tour = 0; tour < 50 && estObjet(o.parametres); tour++) {
    const reste = Object.assign({}, o);
    const dedans = reste.parametres;
    delete reste.parametres;
    o = Object.assign(reste, dedans);
  }
  if (typeof o.parametres === 'string') {            // {"parametres": "{\"action\":\"lancer\"}"} : tolere ici, pour lire l'action
    const dedans = lireJson(o.parametres);
    if (estObjet(dedans)) return parametresDe(Object.assign({}, o, { parametres: dedans }));
  }
  return o;
}

/** Une action, sous la forme ou le lanceur la compare : minuscules, sans accents, lettres, chiffres et _ seulement. */
const motAction = v => net(v).replace(/[^a-z0-9_]/g, '').slice(0, 40);
const nomOutil = v => chaine(v).trim().toLowerCase().slice(0, 60);

/** Ce que l'outil a repondu : un objet {ok, phrase_pour_utilisateur, accord_requis, erreur}, ou null si illisible. */
function observationDe(observation) {
  let o = observation;
  for (let tour = 0; tour < 5; tour++) {
    if (typeof o === 'string') { o = lireJson(o); continue; }
    if (Array.isArray(o)) { o = o.find(x => estObjet(x) || typeof x === 'string'); continue; }
    if (!estObjet(o)) return null;
    // les enveloppes de n8n : {json: {...}}, {response: "<json>"}, {output: ...}
    const cles = Object.keys(o);
    const enveloppe = ['json', 'response', 'output', 'result', 'data'].find(k => cles.length === 1 && k in o);
    if (enveloppe && (estObjet(o[enveloppe]) || Array.isArray(o[enveloppe]) || lireJson(o[enveloppe]) !== undefined)) { o = o[enveloppe]; continue; }
    return o;
  }
  return estObjet(o) ? o : null;
}

/** Un essai a blanc n'est pas un acte : l'outil dit lui-meme « PAS ENCORE FAIT » et attend le « vas-y ». */
function essaiABlanc(o) {
  if (o.essai === true) return true;
  return /^(?:pas encore fait|essai a blanc)\b/.test(net(o.phrase_pour_utilisateur));
}

function statutDe(observation) {
  const o = observationDe(observation);
  if (!o) {
    // les workflows optionnels (pages, videos) rendent un texte ; ils ecrivent « ERREUR : … » quand ils echouent
    return typeof observation === 'string' && /^\s*ERREUR\s*:/.test(observation) ? 'erreur' : 'inconnu';
  }
  if (o.accord_requis === true || o.accord_requis === 'true' || essaiABlanc(o)) return 'attente_accord';
  if (o.ok === false || o.ok === 'false') return 'erreur';
  if (typeof o.resultat === 'string' && /^\s*ERREUR\s*:/.test(o.resultat)) return 'erreur';
  return 'fait';
}

/** Les actes d'un tour. `outil` : le vrai nom (le champ « outil » d'un appel a outils_maison, sinon le nom de l'outil
 *  branche sur l'agent, en minuscules) ; `action` : l'action demandee ('' si inconnue) ; `statut` : fait,
 *  attente_accord, erreur ou inconnu (reponse illisible : compte comme fait, pour ne pas accuser a tort).
 *  Cas particuliers : la liste des outils rend {outil: 'outils_maison', action: 'liste'} ; un appel a outils_maison
 *  dont l'entree est illisible rend {outil: 'outils_maison', action: ''} ; un pas sans nom d'outil rend outil ''. */
function actesDesSteps(steps) {
  const actes = [];
  if (!Array.isArray(steps)) return actes;
  for (const pas of steps.slice(-PAS_MAX)) {
    try {
      if (!estObjet(pas)) continue;
      const a = estObjet(pas.action) ? pas.action : {};
      const outilAgent = nomOutil(a.tool);
      const entree = entreeDe(a.toolInput);
      const statut = statutDe(pas.observation);
      if (outilAgent !== 'outils_maison') {
        actes.push({ outil: outilAgent, action: entree ? motAction(entree.action) : '', statut });
        continue;
      }
      const nom = entree ? nomOutil(entree.outil) : '';
      if (!nom) {
        const obs = observationDe(pas.observation);
        const haut = entree ? motAction(entree.action) : '';
        const liste = (obs && Array.isArray(obs.outils)) || (entree && (!haut || /^(?:liste?|outils?)$/.test(haut)));
        // comme le lanceur (19/11) : un petit modele met parfois le NOM de l'outil a la place de l'action
        // ({"action":"telephone","parametres":{…}}). Le lanceur le dit quand ce n'en etait pas un (« Il manque le nom… »).
        const manque = !!obs && /^il manque le nom de l'outil/.test(net(obs.phrase_pour_utilisateur));
        if (!liste && haut && !manque && !/^(?:utiliser|lancer)$/.test(haut)) {
          actes.push({ outil: haut, action: motAction(parametresDe(entree.parametres).action), statut });
          continue;
        }
        actes.push({ outil: 'outils_maison', action: liste ? 'liste' : haut, statut });
        continue;
      }
      // comme le lanceur : l'action de l'outil est dans ses parametres ; un petit modele la met parfois au premier niveau
      const params = parametresDe(entree.parametres);
      const haut = motAction(entree.action);
      let action = motAction(params.action);
      if (!action && haut && !/util|lanc|^liste?$/.test(haut)) action = haut;
      actes.push({ outil: nom, action, statut });
    } catch (e) { /* un pas illisible ne doit rien casser : il est ignore */ }
  }
  return actes;
}

// ---------------------------------------------------------------------------------------------------------------
// 2. Les briques des tournures (reprises de verifier.py)
// ---------------------------------------------------------------------------------------------------------------

const AI = "(?:j'ai|je t'ai|je l'ai|je vous ai|je (?:te |vous )?(?:l'|les )ai)";
// « c'est fait », mais pas « si c'est fait », « quand c'est fait », « est-ce que c'est fait »
const C_EST = "(?<!si )(?<!quand )(?<!lorsque )(?<!des que )(?<!fois que )(?<!tant que )(?<!est-ce que )(?<!toi que )(?<!comme )(?<!\\bet )\\bc'est";
// le passif d'un geste qui vient d'etre fait, jamais apres « n' » (« rien n'a ete ajoute »)
const SANS_NEGATION = "(?<!n')\\b(?:";
const VIENT_D_ETRE = SANS_NEGATION + "a ete|ont ete|a bien ete|ont bien ete|vient d'etre|viennent d'etre)";
// le simple constat (« est programme ») : il peut decrire ce qu'un outil de lecture vient de lire
const EST = SANS_NEGATION + 'est|sont)';
const ETE = SANS_NEGATION + 'est|sont|a ete|ont ete|a bien ete|ont bien ete)';
// un constat dans une condition, un doute, une habitude ou un recit n'affirme rien : « dis-moi si l'impression est
// lancee », « je verifie que… », « d'habitude la prise est eteinte la nuit », « hier le radiateur a ete coupe »
const CONDITION = new RegExp("\\b(?:si|quand|lorsque|des que|une fois que|tant que|pour que|afin que|avant que|apres que|jusqu'a ce que"
  + "|savoir|verifier|verifie|verifies|peut-etre|sans doute|normalement|devrait|devraient|semble|semblent|suppose"
  + "|d'apres|selon|en general|generalement|d'habitude|habituellement|en principe|souvent|toujours|parfois|hier|avant-hier|la derniere fois"
  + "|la nuit|chaque (?:jour|soir|matin|nuit)|tous les (?:jours|soirs|matins))\\b|\\bs'(?:il|ils)\\b");
// les outils qui travaillent en arriere-plan et previennent a la fin : « je te previendrai » y est legitime
const PREVIENT_A_LA_FIN = ['vision_video', 'recolte_youtube', 'enquete_osint', 'videos_youtube', 'presentation', 'navigateur', 'indicateur_polymarket',
  'mecanicien', 'curateur', 'imprimante_3d', 'camera_imprimante', 'trader'];
// « je te le rappelle lundi » promet ; « je te le rappelle : la reunion est lundi » rappelle tout de suite
const UN_MOMENT = "(?= (?:demain|apres-demain|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|ce soir|ce midi|cet apres-midi|cette nuit"
  + "|tout a l'heure|plus tard|dans \\d|dans (?:une?|deux|trois|quatre|cinq|dix|quelques) |a \\d|vers \\d|le \\d|a midi|a minuit"
  + "|a ton retour|a ton arrivee|la semaine prochaine|le moment venu|chaque |tous les |toutes les ))";
const BIEN = '(?:bien |maintenant |desormais |a present )?';
// un participe seul en tete de phrase n'affirme que s'il n'est pas une apposition : « Eteint, un radiateur ne consomme rien »
const SANS_VIRGULE = '(?!.*,)';
// quelques mots entre le nom et le verbe : « la prise du salon a ete eteinte », « l'outil meteo_locale est valide »
const SUITE = "(?: [a-z0-9_.,' -]{1,30})?";
// ce qui peut preceder un participe seul en tete de phrase : « Voila, programme ! », « D'accord : envoye. »
const DEBUT = "^(?:(?:et )?(?:voila|ok|okay|d'accord|parfait|tres bien|entendu|super|c'est bon|c'est fait|bien recu|hop|oui|merci)[ ,:-]*)*";
const DEBUT_ACCENTS = "^(?:(?:et )?(?:voilà|ok|okay|d'accord|parfait|très bien|entendu|super|c'est bon|c'est fait|bien reçu|hop|oui|merci)[ ,:-]*)*";
// une proposition n'est pas un engagement : « si tu veux, je te le rappellerai »
const SI_TU_VEUX = /\bsi (?:tu|vous) (?:veux|voulez|le souhaites|le souhaitez|preferes|preferez|as besoin|avez besoin)\b|\bsi besoin\b/;
const ENCORE = '(?:a nouveau|de nouveau|encore une fois|une nouvelle fois|une seconde fois|une deuxieme fois|encore|aussi|egalement)';

/** « j'ai programme », « je t'ai programme », « je l'ai ajoutee », « je viens de programmer », avec un adverbe glisse
 *  avant ou apres le verbe (« j'ai a nouveau prepare », « j'ai prepare a nouveau »). verbes = « participe:infinitif|… ». */
function accompli(verbes) {
  const paires = verbes.split('|').map(v => v.split(':'));
  const participes = paires.map(p => p[0]).join('|');
  const infinitifs = paires.map(p => p[1]).join('|');
  return '(?:\\b' + AI + ' (?:bien |donc |aussi |' + ENCORE + ' )?(?:' + participes + ')(?:e|s|es)?'
    + "|\\bje viens (?:juste |tout juste )?(?:de |d')(?:te |t'|vous |l'|le |la |les |lui ){0,2}(?:" + infinitifs + '))\\b(?: ' + ENCORE + '\\b)?';
}

/** Une tournure. options : exige / exclut (cherches dans toute la phrase nette), accents (la phrase est lue accents
 *  gardes), etat (constat qui peut decrire une lecture), engagement (futur : « si tu veux » l'annule),
 *  aussi (d'autres outils dont un succes rend CETTE tournure vraie). */
function t(motif, options) {
  const constat = motif.indexOf(SANS_NEGATION) >= 0;      // un passif ou un etat : « si la prise est allumee » n'affirme rien
  // la sorte de tournure, qui decide de ce qui la fait taire (voir dit()) :
  //   je         « j'ai eteint », « je viens de lancer »          l'assistant parle en son nom
  //   cest       « c'est programme », « c'est envoye »
  //   nominal    « Rappel enregistre », « Envoye ! »              une phrase sans verbe, en tete
  //   constat    « a ete lancee », « est eteinte »                passif ou etat, a la troisieme personne
  //   engagement « je te le rappellerai »
  const type = (options && options.type) || ((options && options.engagement) ? 'engagement'
    : motif[0] === '^' ? 'nominal'
    : motif.indexOf(C_EST) >= 0 ? 'cest'
    : constat ? 'constat'
    : /j'ai|\\bje /.test(motif) ? 'je' : 'constat');
  return Object.assign({ motif: new RegExp(motif), exige: null, exclut: null, accents: false, etat: false, engagement: false, aussi: null, constat }, options || {}, { type });
}
/** Un outil qui soutient une famille. sauf : ses actions qui ne font pas le geste (lectures) ; seulement : ses seules actions qui comptent. */
const o = (outil, regles) => Object.assign({ outil, sauf: null, seulement: null }, regles || {});
const LIRE_LES_MAILS = ['chercher', 'lire', 'contact'];      // les actions de l'outil mails qui ne font que lire

// ---------------------------------------------------------------------------------------------------------------
// 3. Ce que le texte affirme -> les outils dont un succes, dans ce tour, rend l'affirmation vraie
// ---------------------------------------------------------------------------------------------------------------

const PRISE = '(?:prises?|radiateurs?|chauffages?|convecteurs?)';
const IMPRESSION = '(?:impression|fabrication|print)';
const DOC = '(?:pdf|presentation|diaporama|powerpoint|pptx|diapositives|diapos|slides)';
const TRANSMIS = '(?:pdf|documents?|fichiers?|appli|application|apk|presentation|diaporama|powerpoint)';
const MAILS = '(?:mails?|e-mails?|emails?|courriels?|newsletters?)';
const DE_L_IMPRIMANTE = /\b(?:impression|imprimante|print|fabrication|gcode|g-code|plateau|3mf)\b/;
const VERS_L_IMPRIMANTE = /\b(?:a|sur|vers) (?:l'|ton |ta |votre )imprimante\b/;
const DU_MAIL = /\b(?:mails?|e-mails?|emails?|courriels?|gmail|outlook|boite|messagerie)\b/;
const REVEIL = /\b(?:alarmes?|minuteurs?|reveils?|chrono(?:metre)?s?|compte a rebours)\b/;
// la confirmation du planificateur, telle que la lit deja core/verifier_reponse.js (CONFIRMATION)
const PLANIFICATEUR_A_CONFIRME = /c'est programme|rappel[^.]{0,40}(ajoute|enregistre|programme)/;

const FAMILLES = [
  {
    famille: 'un rappel programmé',
    soutiens: [o('planificateur', { sauf: ['lister', 'annuler', 'retenir_lieu', 'lieux'] })],
    lectures: [o('planificateur', { seulement: ['lister'] })],
    preuve: PLANIFICATEUR_A_CONFIRME,
    tournures: [
      // une alarme ou un minuteur du telephone, une page surveillee se disent aussi « c'est programme »
      // « c'est programme en Python » parle d'un logiciel
      t(C_EST + ' (?:bien )?programme\\b(?! (?:en|avec|sous|par) (?!fin|debut|semaine|soiree|matinee|journee))', { aussi: [o('telephone', { seulement: ['alarme', 'minuteur', 'agenda'] }), o('navigateur', { seulement: ['surveiller'] })] }),
      t(accompli('programme:programmer|planifie:planifier'), { exclut: REVEIL, aussi: [o('telephone', { seulement: ['agenda'] }), o('navigateur', { seulement: ['surveiller'] })] }),
      t(accompli('cree:creer|mis:mettre|enregistre:enregistrer|ajoute:ajouter|pose:poser|note:noter')
        + ' (?:le|un|ton|votre|ce|les|des|tes|vos|deux|trois|\\d+) (?:nouveaux? )?rappels?\\b'),
      // « je l'ai ajoutee a tes rappels » : le participe s'accorde, le rappel est nomme apres
      t(accompli('ajoute:ajouter|mis:mettre|note:noter|inscrit:inscrire|enregistre:enregistrer')
        + '.{0,40}\\b(?:a|dans|parmi) (?:tes|vos|les|mes) rappels\\b'),
      t('\\brappels? ' + VIENT_D_ETRE + ' (?:bien )?(?:programme|cree|enregistre|planifie|ajoute)e?s?\\b'),
      t('\\brappels? ' + EST + ' (?:bien )?(?:programme|cree|enregistre|planifie|ajoute)e?s?\\b', { etat: true }),
      t('\\brappels? ' + EST + ' (?:bien )?en place\\b', { etat: true }),
      // en tete de phrase seulement : « Rappel enregistre pour lundi. », pas « tu as un rappel programme lundi »
      // (etat : apres une lecture des rappels, « Rappels programmes : … » est le titre de la liste lue)
      t(DEBUT + 'rappels? (?:bien )?(?:programme|cree|enregistre|planifie|ajoute)e?s?\\b', { etat: true }),
      t(DEBUT_ACCENTS + '(?:bien )?programmé(?:e|s|es)?' + FIN_DE_MOT + SANS_VIRGULE, { accents: true, aussi: [o('telephone', { seulement: ['alarme', 'minuteur', 'agenda'] })] }),
      // les engagements : « je te le rappellerai » (« je vais te le rappeler » est une intention, pas une affirmation)
      t('\\bje (?:te|vous) (?:le |la |les )?(?:rappellerai|rappelerai)\\b', { engagement: true }),
      t("\\b(?:je (?:te|vous) (?:le |la |les )?(?:previendrai|avertirai)|je t'avertirai)\\b", { engagement: true, aussi: PREVIENT_A_LA_FIN.map(n => o(n)) }),
      t('(?<!que )\\bje (?:te|vous) (?:le|la|les) rappelle\\b' + UN_MOMENT, { engagement: true }),
      t("\\bje (?:(?:te|vous) (?:le |la |y )?|t'y )ferai penser\\b", { engagement: true }),
      t('\\b(?:tu seras|vous serez) prevenus?\\b' + UN_MOMENT, { engagement: true, aussi: PREVIENT_A_LA_FIN.map(n => o(n)) }),
      t("\\bje n'oublierai pas de (?:te|vous)\\b", { engagement: true }),
      t('\\b(?:tu recevras|vous recevrez|tu auras|vous aurez) (?:un|ton|votre|le|ce) rappel\\b', { engagement: true }),
    ],
  },
  {
    famille: 'une prise allumée ou éteinte',
    soutiens: [o('prises_shelly', { sauf: ['etat'] })],
    lectures: [o('prises_shelly', { seulement: ['etat'] })],
    tournures: [
      t(accompli('allume:allumer|rallume:rallumer|eteint:eteindre|coupe:couper|active:activer|desactive:desactiver|arrete:arreter'
        + '|mis en marche:mettre en marche|mis en route:mettre en route|remis en marche:remettre en marche')
        + " (?:le |la |l'|ton |ta |les |tes |votre |ce |cette )" + PRISE + '\\b'),
      // « la prise du radiateur, je l'ai eteinte »
      t('\\b' + PRISE + SUITE + " je (?:te |vous )?l'ai (?:bien )?(?:allume|rallume|eteint|coupe)e?s?\\b"),
      t('\\b' + PRISE + SUITE + ' ' + VIENT_D_ETRE + ' (?:bien )?(?:allume|rallume|eteint|coupe)e?s?\\b'),
      t('\\b' + PRISE + SUITE + ' ' + EST + ' ' + BIEN + '(?:allume|rallume|eteint|coupe)e?s?\\b', { etat: true }),
      t(DEBUT + PRISE + SUITE + ' (?:bien )?(?:allume|rallume|eteint|coupe)e?s?\\b', { etat: true }),
      // « c'est allume », « Éteint ! » : se disent aussi de la lampe du telephone ou de la lumiere de l'imprimante
      t(C_EST + ' (?:bien )?(?:allume|eteint)e?\\b', { aussi: [o('telephone'), o('camera_imprimante')] }),
      t(DEBUT_ACCENTS + '(?:bien )?(?:allumé|éteint)(?:e|s|es)?' + FIN_DE_MOT + SANS_VIRGULE, { accents: true, aussi: [o('telephone'), o('camera_imprimante')] }),
      // « c'est fait, je l'ai eteint », « j'ai mis le chauffage »
      t("\\bje (?:te |vous )?l'ai (?:bien )?(?:allume|rallume|eteint)e?s?\\b", { aussi: [o('telephone'), o('camera_imprimante')] }),
      t(accompli('mis:mettre|remis:remettre|lance:lancer|relance:relancer') + ' (?:le |du |ton |votre )chauffage\\b'),
    ],
  },
  {
    famille: 'une impression 3D lancée, mise en pause ou annulée',
    soutiens: [o('imprimante_3d', { sauf: ['etat', 'fichiers'] })],
    lectures: [o('imprimante_3d', { seulement: ['etat', 'fichiers'] }), o('camera_imprimante')],
    tournures: [
      t(accompli('lance:lancer|relance:relancer|demarre:demarrer|commence:commencer|repris:reprendre|annule:annuler|arrete:arreter'
        + '|stoppe:stopper|suspendu:suspendre|interrompu:interrompre|mis:mettre')
        + " (?:l'|une |ton |cette |la |le |votre )(?:nouvelle )?" + IMPRESSION + '\\b'),
      t('\\b' + IMPRESSION + SUITE + " je (?:te |vous )?l'ai (?:bien )?(?:lance|relance|demarre|annule|arrete|stoppe|suspendu|interrompu|mise? en pause|repris)e?s?\\b"),
      t('\\b' + IMPRESSION + SUITE + ' ' + VIENT_D_ETRE
        + ' (?:bien )?(?:lance|relance|demarre|annule|arrete|stoppe|suspendu|interrompu|mise? en pause|reprise?)e?s?\\b'),
      t('\\b' + IMPRESSION + SUITE + ' ' + EST + ' ' + BIEN
        + '(?:lance|relance|demarre|annule|arrete|stoppe|suspendu|interrompu|en pause|reprise?|parti)e?s?\\b', { etat: true }),
      t(DEBUT + IMPRESSION + SUITE + ' (?:bien )?(?:lance|relance|demarre|annule|arrete|reprise?|mise? en pause|en pause)e?s?\\b', { etat: true }),
      t(accompli('envoye:envoyer|transfere:transferer|televerse:televerser|charge:charger|mis:mettre|depose:deposer|transmis:transmettre')
        + "[^,;:]{0,50}\\b(?:a|sur|vers) (?:l'|ton |ta |votre )imprimante\\b"),
      t('\\b(?:fichier|gcode|g-code|modele|piece)' + SUITE + ' ' + VIENT_D_ETRE
        + " (?:bien )?(?:envoye|transfere|televerse)e?s? (?:a|sur|vers) (?:l'|ton |ta |votre )imprimante\\b"),
      t(C_EST + ' (?:bien )?(?:lance|annule|envoye|en pause|parti)e?\\b', { exige: DE_L_IMPRIMANTE }),
      // « l'impression a demarre », « l'imprimante vient de demarrer »
      t("\\b(?:" + IMPRESSION + '|imprimante)' + SUITE + ' (?:a|vient de) (?:bien )?(?:demarre|commence|repris|redemarre)r?\\b', { type: 'constat' }),
    ],
  },
  {
    famille: 'un PDF ou une présentation créés',
    soutiens: [o('creer_pdf'), o('presentation'), o('liasse_fiscale')],
    lectures: [o('lire_pdf'), o('transmettre_document')],
    tournures: [
      t(accompli('cree:creer|genere:generer|fabrique:fabriquer|prepare:preparer|fait:faire|redige:rediger|enregistre:enregistrer'
        + '|produit:produire|monte:monter|range:ranger|sauvegarde:sauvegarder|ecrit:ecrire|compose:composer|exporte:exporter')
        + " (?:le |un |ton |ce |la |une |ta |cette |votre |les |des |l')(?:nouveau |nouvelle |petit |petite |fichier |document )?" + DOC + '\\b'),
      t(accompli('cree:creer|genere:generer|fabrique:fabriquer|prepare:preparer|fait:faire|redige:rediger|enregistre:enregistrer'
        + '|produit:produire|sauvegarde:sauvegarder|ecrit:ecrire|compose:composer|exporte:exporter|mis:mettre')
        + '[^,;:]{0,60}\\ben (?:format |version )?(?:pdf|pptx|powerpoint)\\b'),
      t('\\b' + DOC + SUITE + ' ' + VIENT_D_ETRE + ' (?:bien )?(?:cree|genere|fabrique|prepare|enregistre|range|sauvegarde|produit|exporte)e?s?\\b'),
      t('\\b(?:le|ton|ta|la|votre|ce|cette|un|une) ' + DOC + SUITE + ' ' + EST + ' ' + BIEN
        + '(?:cree|genere|pret|prete|enregistre|range|sauvegarde|disponible|termine)e?s?\\b', { etat: true }),
      t(DEBUT + DOC + SUITE + ' (?:bien )?(?:cree|genere|pret|prete|enregistre|range)e?s?\\b', { etat: true }),
    ],
  },
  {
    famille: 'un document transmis',
    soutiens: [o('transmettre_document', { sauf: ['liste'] }), o('appli_telephone'), o('creer_pdf'), o('presentation')],
    lectures: [],
    tournures: [
      t(accompli('envoye:envoyer|transmis:transmettre|donne:donner|partage:partager|depose:deposer|renvoye:renvoyer|passe:passer')
        + " (?:le |la |l'|ton |ta |ce |cette |un |une |les |tes |votre )(?:nouveau |nouvelle |derniere version de l'|fichier )?" + TRANSMIS + '\\b',
        { exclut: VERS_L_IMPRIMANTE }),
      t('\\b' + TRANSMIS + SUITE + " (?:t'|te |vous |lui )?(?:a ete|ont ete|a bien ete|ont bien ete|vient d'etre|viennent d'etre)"
        + ' (?:bien )?(?:envoye|transmis|donne|partage)e?s?\\b', { exclut: /\b(?:envoye|transmis|donne|partage)e?s? (?:par|le \d|depuis|de la part)\b|\b(?:a|sur|vers) (?:l'|ton |ta |votre )imprimante\b/ }),
      t('\\b(?:le|ton|ta|la|votre|ce|cette|l\') ?' + TRANSMIS + SUITE + ' ' + EST + ' (?:bien )?(?:parti|envoye|transmis)e?s?\\b',
        { exclut: /\b(?:envoye|transmis|parti)e?s? (?:par|le \d|depuis|de la part)\b|\b(?:quand|une fois que|des que|si)\b|\b(?:a|sur|vers) (?:l'|ton |ta |votre )imprimante\b/ }),
      t(C_EST + ' (?:bien )?transmis\\b'),
    ],
  },
  {
    famille: 'une action sur le téléphone',
    soutiens: [o('telephone')],
    lectures: [],
    tournures: [
      t(accompli('mis:mettre|regle:regler|programme:programmer|lance:lancer|cree:creer|active:activer|pose:poser|demarre:demarrer|ajoute:ajouter')
        + " (?:une |un |l'|le |ton |ta |votre )(?:nouvelle |nouveau )?(?:alarme|minuteur|reveil|chronometre|chrono|compte a rebours)\\b"),
      t('\\b(?:alarme|minuteur|reveil)' + SUITE + ' ' + EST + ' ' + BIEN + '(?:regle|programme|lance|active|en route|parti)e?s?\\b'),
      t(DEBUT + '(?:alarme|minuteur|reveil)' + SUITE + ' (?:bien )?(?:regle|programme|lance|active)e?s?\\b'),
      t(accompli('allume:allumer|eteint:eteindre|active:activer|coupe:couper') + ' (?:la |ta |votre )(?:lampe torche|lampe|torche)\\b'),
      t(accompli('lance:lancer|mis:mettre|demarre:demarrer|joue:jouer|relance:relancer')
        + ' (?:la |ta |une |de la |le |ce |un |ton )(?:musique|morceau|chanson|playlist|titre|video)\\b',
        { aussi: [o('camera_imprimante'), o('navigateur'), o('videos_youtube'), o('vision_video'), o('oeil')] }),
      t(accompli('lance:lancer|ouvert:ouvrir|demarre:demarrer|prepare:preparer') + " (?:la navigation|l'itineraire|le gps|google maps|maps|waze|le trajet)\\b",
        { aussi: [o('navigateur'), o('oeil')] }),
      t(accompli('ouvert:ouvrir|lance:lancer') + " (?:whatsapp|spotify|youtube|deezer|l'appli|l'application|les reglages|le composeur)\\b",
        { aussi: [o('navigateur'), o('oeil'), o('videos_youtube')] }),
      t(accompli('monte:monter|baisse:baisser|coupe:couper|regle:regler|augmente:augmenter|diminue:diminuer|mis:mettre|remis:remettre')
        + ' (?:le |ton |votre )(?:volume|son)\\b'),
      t(accompli('prepare:preparer|ouvert:ouvrir|redige:rediger|ecrit:ecrire') + ' (?:le |un |ton |ce |votre )(?:message whatsapp|sms|texto|whatsapp)\\b'),
      t(accompli('lance:lancer|passe:passer|compose:composer') + " (?:l'appel|un appel|le numero)\\b"),
      t(accompli('ajoute:ajouter|mis:mettre|note:noter|inscrit:inscrire|enregistre:enregistrer|cree:creer')
        + ".{0,60}\\b(?:a|dans|sur) (?:ton |votre |l')agenda\\b", { aussi: [o('planificateur', { sauf: ['lister', 'annuler', 'retenir_lieu', 'lieux'] })] }),
      t(accompli('lance:lancer|ouvert:ouvrir|mis:mettre|envoye:envoyer|affiche:afficher|regle:regler|active:activer|demarre:demarrer|prepare:preparer')
        + '[^,;:]{0,60}\\bsur (?:ton|le|votre) (?:telephone|portable|mobile|smartphone)\\b',
        { aussi: [o('oeil'), o('appli_telephone'), o('transmettre_document'), o('presentation'), o('creer_pdf'), o('vision_video'), o('musique')] }),
    ],
  },
  {
    famille: 'des mails rangés',
    soutiens: [o('ranger_mails', { sauf: ['chercher', 'dossiers', 'journal'] })],
    lectures: [o('ranger_mails', { seulement: ['chercher', 'dossiers', 'journal'] })],
    tournures: [
      t(accompli('range:ranger|deplace:deplacer|trie:trier|classe:classer|archive:archiver|mis:mettre|transfere:transferer')
        + ' (?:le |les |tes |ces |ton |ce |des |vos |tous les |tous tes |\\d+ |deux |trois |quatre |cinq )(?:\\d+ )?(?:[a-z]+ )?' + MAILS + '\\b'),
      t('\\b' + MAILS + SUITE + ' ' + VIENT_D_ETRE + ' (?:bien )?(?:range|deplace|trie|classe|archive)e?s?\\b'),
      t('\\b' + MAILS + SUITE + ' ' + EST + ' ' + BIEN + '(?:range|deplace|trie|classe|archive)e?s?\\b', { etat: true }),
      t(DEBUT + '(?:\\d+ )?' + MAILS + SUITE + ' (?:bien )?(?:range|deplace|trie|classe|archive)e?s?\\b', { etat: true }),
      t(accompli('cree:creer|ajoute:ajouter') + ' (?:le |un |ton |ce )(?:nouveau )?(?:dossier|libelle)\\b', { exige: DU_MAIL }),
      t(accompli('nettoye:nettoyer|trie:trier|range:ranger|vide:vider') + ' (?:ta |la |votre )boite\\b'),
      t('\\bboite(?: mail| de reception| gmail| outlook)? ' + EST + ' ' + BIEN + '(?:trie|range|nettoye)e?s?\\b', { etat: true }),
    ],
  },
  {
    // aucun outil d'Archi ne supprime de mail (ranger_mails « ne supprime et n'envoie jamais rien ») : toujours releve
    famille: 'des mails supprimés',
    soutiens: [],
    lectures: [o('ranger_mails')],
    tournures: [
      t(accompli('supprime:supprimer|efface:effacer|jete:jeter|vide:vider|detruit:detruire')
        + ' (?:le |les |tes |ces |ton |ce |des |vos |tous les |tous tes |\\d+ )(?:\\d+ )?(?:[a-z]+ )?(?:mails?|e-mails?|emails?|courriels?|newsletters?|spams?|pubs?|indesirables?)\\b'),
      t('\\b(?:mails?|e-mails?|emails?|courriels?|spams?|indesirables?)' + SUITE + ' ' + ETE + ' ' + BIEN + '(?:supprime|efface)s?\\b'),
    ],
  },
  {
    famille: 'un outil fabriqué, validé ou retiré',
    soutiens: [o('mecanicien', { sauf: ['etat', 'voir', 'idee'] })],
    lectures: [o('mecanicien', { seulement: ['etat', 'voir'] }), o('outils_maison', { seulement: ['liste'] })],
    tournures: [
      t(accompli('fabrique:fabriquer|construit:construire|cree:creer|bricole:bricoler|code:coder|monte:monter|invente:inventer|refait:refaire'
        + '|valide:valider|installe:installer|branche:brancher|mis en place:mettre en place'
        + '|retire:retirer|supprime:supprimer|desinstalle:desinstaller|enleve:enlever|abandonne:abandonner')
        + " (?:l'|le |un |ton |ce |cet |votre )(?:nouvel |nouveau )?outil\\b"),
      t('\\boutil' + SUITE + ' ' + VIENT_D_ETRE + ' (?:bien )?(?:fabrique|construit|cree|valide|installe|branche|retire|supprime|desinstalle)e?s?\\b'),
      t('\\boutil' + SUITE + ' ' + EST + ' ' + BIEN + '(?:fabrique|construit|valide|retire|supprime|desinstalle)e?s?\\b', { etat: true }),
      t(DEBUT + '(?:nouvel )?outil' + SUITE + ' (?:bien )?(?:fabrique|construit|cree|valide|retire|supprime)e?s?\\b', { etat: true }),
    ],
  },
  {
    famille: 'un rangement de mémoire appliqué',
    soutiens: [o('curateur', { sauf: ['examiner', 'propositions'] })],
    lectures: [o('curateur', { seulement: ['examiner', 'propositions'] })],
    tournures: [
      t(accompli('applique:appliquer|execute:executer|effectue:effectuer|fait:faire')
        + " (?:la |les |tes |ces |ta |cette |le |ce |l')(?:propositions?|rangements?|numeros?|changements?|modifications?|corrections?|menage)\\b"),
      t(accompli('applique:appliquer') + ' (?:la |le |les |numero )?(?:\\d|deux\\b|trois\\b|tout\\b)'),
      t('\\b' + AI + ' tout applique\\b'),
      t(accompli('range:ranger|nettoye:nettoyer|trie:trier|reorganise:reorganiser') + ' (?:la |ta |ma |votre )memoire\\b'),
      t(accompli('fusionne:fusionner|supprime:supprimer|efface:effacer|corrige:corriger|repare:reparer|archive:archiver|retire:retirer')
        + ' (?:le |la |les |ces |ce |cette |deux |trois |\\d+ |des )(?:fiches?|doublons?|liens? casses?|faits? en double|contradictions?)\\b',
        { aussi: [o('memoire', { seulement: ['oublier'] })] }),
      t('\\b(?:propositions?|rangements?|numeros?|changements?|modifications?)' + SUITE + ' ' + VIENT_D_ETRE + ' (?:bien )?(?:applique|effectue|execute)e?s?\\b'),
      t('\\b(?:propositions?|rangements?|numeros?|changements?|modifications?)' + SUITE + ' ' + EST + ' ' + BIEN + '(?:applique|effectue)e?s?\\b', { etat: true }),
      t('\\bmemoire ' + VIENT_D_ETRE + ' (?:bien )?(?:range|nettoye|trie|reorganise)e?s?\\b'),
      t('\\bmemoire ' + EST + ' ' + BIEN + '(?:range|nettoye|trie|reorganise)e?s?\\b', { etat: true }),
      t(C_EST + ' (?:bien )?applique\\b'),
      t(DEBUT_ACCENTS + '(?:bien )?appliqué(?:e|s|es)?' + FIN_DE_MOT + SANS_VIRGULE, { accents: true }),
    ],
  },
  {
    famille: 'une page ouverte ou un clic fait',
    soutiens: [o('navigateur')],
    lectures: [],
    tournures: [
      // « j'ai ouvert la page : elle dit que… » se dit aussi d'une page simplement lue
      t(accompli('ouvert:ouvrir|charge:charger|affiche:afficher|rouvert:rouvrir|lance:lancer')
        + " (?:la |le |une |un |ta |cette |ce |l'|ton |votre )(?:page|site|lien|adresse|onglet|formulaire|navigateur)\\b",
        { aussi: [o('lire_page'), o('telephone'), o('videos_youtube'), o('wikipedia'), o('wikipedia-api'), o('enquete_osint'), o('oeil'), o('camera_imprimante')] }),
      t("\\bje (?:suis alle|me suis rendu) sur (?:le |la |l'|ce |cette |ton |votre )?(?:site|page|lien|adresse)\\b",
        { aussi: [o('lire_page'), o('wikipedia'), o('wikipedia-api'), o('enquete_osint')] }),
      t(accompli('clique:cliquer|appuye:appuyer') + ' sur\\b'),
      t(accompli('rempli:remplir|complete:completer|saisi:saisir|tape:taper|renseigne:renseigner')
        + ' (?:le |les |ce |un |ton |votre |tous les )(?:formulaire|champs?|cases?)\\b'),
      t(accompli('ferme:fermer') + " (?:la |le |l')(?:page|onglet|navigateur|fenetre)\\b"),
      t('\\b(?:formulaire|champs?)' + SUITE + ' ' + VIENT_D_ETRE + ' (?:bien )?(?:rempli|complete)e?s?\\b'),
      t('\\b(?:la|cette|ta|votre) page' + SUITE + ' ' + EST + ' ' + BIEN + 'ouverte\\b', { etat: true, aussi: [o('lire_page'), o('telephone')] }),
      t(DEBUT + 'page' + SUITE + ' (?:bien )?ouverte\\b', { etat: true, aussi: [o('lire_page'), o('telephone')] }),
    ],
  },
  {
    // Essai humain d'Intendant (19/11) : « J'ai prepare a nouveau le brouillon de mail… Il est maintenant ouvert dans ta
    // messagerie. » Dans Archi, ecrire le texte d'un brouillon dans la reponse est permis ; dire qu'il est OUVERT ou
    // ENREGISTRE dans la messagerie ne l'est que si l'outil mails vient de le creer (action=preparer) : ranger_mails ne cree
    // ni n'envoie rien.
    famille: 'un brouillon ouvert dans la messagerie',
    soutiens: [o('mails', { seulement: ['preparer', 'envoyer'] })],
    lectures: [o('ranger_mails'), o('mails', { seulement: LIRE_LES_MAILS })],
    tournures: [
      t('\\b(?:brouillons?|mails?|e-mails?|emails?|courriels?|messages?|il|elle)' + SUITE + ' ' + SANS_NEGATION + "est|sont|s'est|a ete|vient d'etre) " + BIEN
        + "(?:ouvert|enregistre|pret|cree|sauvegarde|disponible|place)e?s? dans (?:(?:ta|votre|la) (?:messagerie|boite mail|boite d'envoi)|(?:tes|vos|les) brouillons)\\b",
        { etat: true }),
      t(accompli('ouvert:ouvrir|cree:creer|enregistre:enregistrer|prepare:preparer|mis:mettre|sauvegarde:sauvegarder|depose:deposer|place:placer')
        + "[^,;:]{0,60}\\bdans (?:(?:ta|votre|la) (?:messagerie|boite mail|boite d'envoi)|(?:tes|vos|les) brouillons)\\b"),
    ],
  },
];

// --- l'envoi : un mail ne part que par l'outil mails, action=envoyer ---------------------------------------------
const ENVOI = 'un envoi';
// « Cette lettre a ete envoyee par la CAF le 3 novembre », « previens-moi quand le mail est envoye » : un recit, une condition
const ENVOI_D_UN_AUTRE = new RegExp("\\b(?:envoye|expedie|poste|transmis|parti)e?s? (?:par|le \\d|depuis|de la part)\\b|\\b(?:quand|une fois que|des que|si)\\b"
  + "|\\b(?:a envoyer|a poster|a expedier|pret a|prete a|peux l'envoyer|pourras l'envoyer)\\b");
const UN_ENVOI = '(?:mails?|e-mails?|emails?|courriels?|messages?|sms|textos?|courriers?|lettres?)';
const ENVOIS = [
  t(accompli('envoye:envoyer|expedie:expedier|poste:poster|transmis:transmettre|adresse:adresser')
    + " (?:le |la |l'|un |une |ton |ta |ce |cette |votre |les |tes |deux |trois )" + UN_ENVOI + '\\b'),
  t("\\bje (?:l'|les |te l'|vous l'|le lui |la lui )ai (?:bien )?(?:envoye|expedie|poste|transmis)e?s?\\b"),
  t("\\bje viens (?:juste |tout juste )?de (?:te |vous )?(?:l'|les |le |la |lui )?(?:envoyer|expedier|poster|transmettre)\\b"),
  t('\\b' + UN_ENVOI + SUITE + ' ' + ETE + ' (?:bien )?(?:envoye|expedie|poste|transmis|parti)e?s?\\b', { exclut: ENVOI_D_UN_AUTRE }),
  t(C_EST + ' (?:bien )?(?:envoye|expedie|poste)\\b', { exclut: ENVOI_D_UN_AUTRE }),
  t(DEBUT + UN_ENVOI + ' (?:bien )?(?:envoye|expedie|poste)e?s?\\b', { exclut: ENVOI_D_UN_AUTRE }),
  t(DEBUT_ACCENTS + '(?:bien )?(?:envoyé|expédié)(?:e|s|es)?' + FIN_DE_MOT + SANS_VIRGULE, { exclut: ENVOI_D_UN_AUTRE, accents: true }),
  // « ton mail vient de partir »
  t('\\b' + UN_ENVOI + SUITE + ' (?:vient|viennent) de partir\\b', { exclut: ENVOI_D_UN_AUTRE, type: 'constat' }),
];
// Les outils qui font vraiment partir quelque chose, et les mots d'une phrase qui parle de ce qu'ils font. Une phrase
// qui nomme un mail (« j'ai envoye le mail ») n'est couverte que par l'envoi reussi de l'outil mails.
const UN_MAIL = /\b(?:mails?|e-mails?|emails?|courriels?|gmail|outlook|messagerie|boite mail)\b/;
const MAIL_PARTI = o('mails', { seulement: ['envoyer'] });
const PORTEURS = [
  { outil: MAIL_PARTI, parle: UN_MAIL },
  { outil: o('telephone'), parle: /\b(?:whatsapp|sms|textos?|messages?|telephone|portable|appli)\b/ },
  { outil: o('transmettre_document', { sauf: ['liste'] }), parle: /\b(?:pdf|documents?|fichiers?|lettres?|courriers?|factures?|notes?|fiches?|contrats?|telegram)\b/ },
  { outil: o('appli_telephone'), parle: /\b(?:appli|application|apk|version|telegram)\b/ },
  // au-dela de la consigne, dans le doute : ces outils font partir leur fichier sur Telegram ou dans l'appli
  { outil: o('creer_pdf'), parle: /\b(?:pdf|documents?|fichiers?|telegram)\b/ },
  { outil: o('presentation'), parle: /\b(?:presentation|diaporama|powerpoint|pdf|fichiers?|telegram|appli)\b/ },
  { outil: o('imprimante_3d', { sauf: ['etat', 'fichiers'] }), parle: /\b(?:imprimante|impression|fichiers?|gcode|modele|piece)\b/ },
  { outil: o('cameras'), parle: /\b(?:photos?|images?|videos?|telegram)\b/ },
  { outil: o('camera_imprimante'), parle: /\b(?:photos?|images?|videos?|telegram)\b/ },
  { outil: o('oeil'), parle: /\b(?:telephone|appli|globe|oeil)\b/ },
];
const OBJET_D_ENVOI = new RegExp('\\b' + UN_ENVOI + '\\b');

// ---------------------------------------------------------------------------------------------------------------
// 4. La lecture du texte
// ---------------------------------------------------------------------------------------------------------------

// Ce qui n'est PAS une affirmation de l'assistant. Cinq regles, posees pour ne jamais avertir a tort :
//   (a) apres une LECTURE reussie de l'outil d'une famille (etat, liste, chercher…), tout ce qui decrit ce que cet outil
//       lit est un compte rendu : seuls « j'ai… » et « je viens de… » restent des affirmations ;
//   (b) des qu'un outil qui lit un contenu a reussi (page, PDF, video, encyclopedie, enquete, mails cherches), les passifs
//       et les constats a la troisieme personne racontent ce contenu ;
//   (c) un passif date ou situe est un recit (« en 1992 », « hier », « chez Prusa », « depuis l'ecran ») ;
//   (d) une generalite n'annonce rien (« un mail est envoye en quelques secondes », « eteint, un radiateur… ») ;
//   (e) le texte d'un brouillon, d'une citation, d'un exemple, d'une liste d'etats n'est pas la parole de l'assistant.

// une citation de l'utilisateur ou d'un tiers : « tu m'as dit que le mail est envoye », « ton frere dit que… »
const CITATION = /\btu (?:m'as|m'avais|as|avais|viens de me|me) (?:dit|dire|ecrit|ecrire|raconte|annonce|explique|indique|precise|dis|disais) (?:que |qu'|:)|\b(?:d'apres toi|selon toi|tu dis que|tu disais que)\b/;
const RAPPORTE = new RegExp("(?<!\\bje (?:te |vous |t'|lui )?)\\b(?:dit|disent|ecrit|ecrivent|repond|repondent|affirme|affirment|annonce|annoncent|indique|indiquent"
  + "|precise|precisent|explique|expliquent|pense|pensent|croit|croient|raconte|racontent|signale|signalent|assure|assurent|pretend|mentionne|rapporte) (?:que |qu')");
// (e) ce qui introduit un texte qui n'est pas la parole de l'assistant : « Brouillon pour ton proprietaire : »,
// « Tu peux lui repondre : … », « En francais on ecrit : … », « Dans la facture : … »
const INTRODUIT = new RegExp("\\b(?:brouillons?|textes?|messages?|sms|textos?|poemes?|histoires?|contes?|exemples?|phrases?|conjugaisons?|corrections?|traductions?"
  + "|resumes?|objet|etapes?|checklist|tutoriels?|transcriptions?|citations?|extraits?|journal|modeles?|propositions?|versions?|wikipedia|dictee"
  + "|reponses? possibles?|(?:voici|voila) (?:le|la|un|une|ton|ta) (?:mail|e-mail|courriel|lettre|courrier|reponse|note)|(?:ta|la|une|cette|tes|les) (?:notes?|fiches?)"
  + "|repondre|dire|dit|ecrire|ecris|ecrit|propose|suggere|copier|coller|raconte|indique|precise|explique)\\b|^(?:dans|sur|selon|d'apres|chez)\\b");
// (e) un bloc de plusieurs lignes qui commence par une formule d'adresse : le texte d'une lettre, d'un mail, d'un SMS
const FORMULE_D_ADRESSE = /^(?:bonjour|bonsoir|salut|coucou|hello|cher|chere|chers|madame|monsieur|mesdames|messieurs|maman|papa)\b[^.!?:]{0,40},/;
const EN_LISTE = /^\s*(?:[-*•|]|\d{1,2}[.)])(?:\s|$)|^\s*\|/;
const ETAT_DE_LISTE = /:\s*(?:non|oui|a faire|pas encore|en attente|ok|fait|faite|en cours|a venir|ko|termine|terminee)$/;
// (c) un recit : une date passee, un lieu, la provenance, le geste de l'utilisateur lui-meme
const RECIT = new RegExp("\\b(?:hier|avant-hier|la veille|autrefois|jadis|a l'epoque|le soir meme|le jour meme|le lendemain|l'an dernier|l'annee derniere"
  + "|le mois dernier|la semaine derniere|il y a (?:longtemps|\\d+|une?|deux|trois|quelques)|(?:en|vers|depuis) (?:1\\d{3}|20\\d{2})|depuis|par defaut|en quelques"
  + "|toi-meme|de ton cote|puisque|vu que|etant donne)\\b"
  + "|\\b(?:premier|premiere|dernier|derniere)s? (?:[a-z-]+ )?(?:mails?|e-mails?|courriels?|messages?|sms|lettres?|telegrammes?|impressions?|rappels?)\\b"
  + "|\\b(?:tries?|triees?|classes?|classees?|ranges?|rangees?) par\\b|\\bparti(?:e|s|es)? de\\b");
// (d) une generalite : la phrase commence par un cadre (« Sur Klipper, … », « Dans Gmail, … ») ou un sujet indefini (« Un mail… »)
const GENERALITE = /^(?:(?:oui|non|ok|bon|alors|donc|et|mais)[ ,]+)*(?:sur|chez|dans|sous|avec|en|pour|apres|avant|pendant|un|une|des|chaque|tout|toute|toutes|tous|aucun|aucune)\b/;
// « tout a l'heure j'ai cree le PDF » raconte un geste passe : ce n'est pas une affirmation sur ce tour
const DEJA_PASSE = /\b(?:hier|avant-hier|tout a l'heure|la derniere fois|l'autre jour|la semaine derniere|le mois dernier|auparavant|precedemment|plus tot|autrefois)\b/;
// toute la reponse est un recit : une annee d'histoire (« en 1789 »), ou le geste est celui de l'utilisateur (« tu l'as fait toi-meme »)
const ANNEE = /(?<![\d/.:-])(?:1\d{3}|20[01]\d)(?![\d/.:-]| ?(?:euros?|w\b|watts?|kwh|km|m\b|ko|mo|go|pas\b|mots|fois|points|caracteres))/;
const GESTE_DE_L_UTILISATEUR = /\btoi-meme\b|\bde ton cote\b|\btu l'as (?:deja |bien )?fait\b|\btu as (?:deja |bien )?(?:lance|eteint|allume|envoye|cree|programme|range|coupe|imprime|supprime)\b/;

/** La reponse, lue : ses phrases sous deux formes (nette, accents gardes) avec ce qu'il faut pour les ecarter, et
 *  `recit` (toute la reponse raconte autre chose que ce tour). Le texte cite est retire : guillemets, ce qui suit un
 *  introducteur, un bloc qui commence par une formule d'adresse. La reponse est bornee et resserree avant toute lecture. */
function lire(texte) {
  let brut = resserrer(borner(texte, REPONSE_MAX, REPONSE_QUEUE)).replace(/^\s*\[TEXTE\]\s*/i, '');
  brut = brut.replace(/«[^»\n]{0,400}»|“[^”\n]{0,400}”|"[^"\n]{0,400}"/g, ' ');
  const tout = net(brut);
  const liste = [];
  let bloc = false;            // le reste de la reponse est un texte cite
  let paragraphe = false;      // le reste du paragraphe est un texte cite
  const lignes = brut.split('\n');
  for (let li = 0; li < lignes.length && liste.length < PHRASES_MAX && !bloc; li++) {
    let ligne = lignes[li];
    if (!ligne.trim()) { paragraphe = false; continue; }
    if (paragraphe) continue;
    if (li > 0 && FORMULE_D_ADRESSE.test(net(ligne))) { bloc = true; break; }
    const enListe = EN_LISTE.test(ligne);
    // un introducteur : ce qui suit ses deux-points n'est pas lu (jusqu'a la fin du paragraphe, ou de la reponse s'il finit la ligne)
    const dp = ligne.search(/:(?=\s|$)/);
    if (dp >= 0 && INTRODUIT.test(net(ligne.slice(0, dp)).replace(/^[^a-z0-9]+/, ''))) {
      if (ligne.slice(dp + 1).trim()) paragraphe = true; else bloc = true;
      ligne = ligne.slice(0, dp);
    }
    // une phrase finit par une ponctuation suivie d'un blanc : le point de « benchy.gcode » ou de « 2.5 » ne coupe rien
    const morceaux = ligne.split(/([.!?;…]+(?=[\s)»"*_\]”]|$))/);
    for (let i = 0; i < morceaux.length && liste.length < PHRASES_MAX; i += 2) {
      const accents = minuscules(morceaux[i]).replace(/^[^a-z0-9à-ÿ]+/, '').replace(/[\s,:*_"«»()[\]|-]+$/, '');
      if (!accents) continue;
      const forme = net(accents);
      liste.push({ net: forme, accents, question: /\?/.test(morceaux[i + 1] || ''), citation: CITATION.test(forme) || RAPPORTE.test(forme),
        liste: enListe, etat: ETAT_DE_LISTE.test(forme), deuxPoints: /: /.test(forme) });
    }
  }
  return { phrases: liste, recit: ANNEE.test(tout) || GESTE_DE_L_UTILISATEUR.test(tout) };
}
const phrases = texte => lire(texte).phrases;

const reussi = a => a.statut === 'fait' || a.statut === 'inconnu';
function enTexte(observation) {
  if (typeof observation === 'string') return observation.slice(0, OBSERVATION_MAX);
  try { return (JSON.stringify(observation || '') || '').slice(0, OBSERVATION_MAX); } catch (e) { return ''; }
}
/** Un appel a outils_maison dont l'entree n'a pas pu etre lue : on ne sait pas quel outil a tourne. Dans le doute,
 *  il compte pour toutes les familles (un pas sans aucun nom d'outil, lui, ne compte pour rien). */
const joker = a => a.outil === 'outils_maison' && a.action === '';

function concerne(regle, acte) {
  if (acte.outil !== regle.outil) return false;
  if (regle.seulement) return regle.seulement.includes(acte.action);
  if (regle.sauf) return !regle.sauf.includes(acte.action);      // une action inconnue ('') compte : dans le doute
  return true;
}
const unSucces = (regles, actes) => !!regles && actes.some(a => reussi(a) && regles.some(r => concerne(r, a)));

// (b) les outils qui LISENT un contenu : apres eux, un passif ou un constat raconte ce qui a ete lu
const LECTEURS_DE_CONTENU = [o('lire_page'), o('lire_pdf'), o('videos_youtube'), o('wikipedia'), o('wikipedia-api'), o('enquete_osint'), o('navigateur'),
  o('vision_video'), o('oeil'), o('recolte_youtube'), o('indicateur_polymarket'), o('memoire'), o('retro'),
  o('ranger_mails', { seulement: ['chercher', 'dossiers', 'journal'] }), o('mails', { seulement: LIRE_LES_MAILS }),
  o('curateur', { seulement: ['examiner', 'propositions'] }),
  o('mecanicien', { seulement: ['etat', 'voir'] })];
// (a) pour l'envoi : chercher dans les mails, relire la memoire
const LECTURES_D_ENVOI = [o('ranger_mails', { seulement: ['chercher', 'dossiers', 'journal'] }), o('mails', { seulement: LIRE_LES_MAILS }), o('memoire')];

// « le document a ete transmis au notaire par ton pere, selon le courrier » : le geste d'un autre, ou ce que dit une
// source. Seulement quand la phrase ne dit pas « j'ai… » : « j'ai eteint la prise par l'appli » reste une affirmation.
const MOI_J_AI = /\b(?:j'ai|je t'ai|je l'ai|je vous ai|je viens|je te l'ai|je les ai)\b/;
const AGENT_TIERS = /\bpar (?:ton|ta|tes|son|sa|ses|leurs?|le|la|les|l'|un|une|des|monsieur|madame|m\.|mme)\b/;
const SOURCE_CITEE = /\b(?:d'apres|selon) (?:le|la|les|l'|ce|cette|ces|un|une|ton|ta|tes|son|sa|ses|leurs?)\b/;
const gesteD_unAutre = net => !MOI_J_AI.test(net) && (AGENT_TIERS.test(net) || SOURCE_CITEE.test(net));

/** La phrase dit-elle cette tournure, comme une affirmation de l'assistant sur ce tour ?
 *  contexte : lecture (l'outil de la famille vient de lire), contenuLu (un outil a lu un contenu), recit (toute la reponse). */
function dit(tournure, phrase, contexte) {
  if (!tournure.motif.test(tournure.accents ? phrase.accents : phrase.net)) return false;
  const c = contexte || {};
  const sorte = tournure.type;
  if (c.lecture && (sorte !== 'je' || phrase.deuxPoints)) return false;                                     // regle (a)
  if (sorte === 'constat' || sorte === 'nominal') {
    if (c.contenuLu || c.recit) return false;                                                               // regles (b) et (c)
    if (RECIT.test(phrase.net) || GENERALITE.test(phrase.net)) return false;                                // regles (c) et (d)
  }
  if (sorte === 'nominal' && (phrase.liste || phrase.etat)) return false;                                   // regle (e) : « - Mail envoye : non »
  if (sorte === 'je' && DEJA_PASSE.test(phrase.net)) return false;                                          // regle (c)
  if (gesteD_unAutre(phrase.net)) return false;
  if (tournure.exige && !tournure.exige.test(phrase.net)) return false;
  if (tournure.exclut && tournure.exclut.test(phrase.net)) return false;
  if (tournure.engagement && SI_TU_VEUX.test(phrase.net)) return false;
  if (tournure.constat && CONDITION.test(phrase.net)) return false;
  return true;
}

function raisonPour(regles, actes) {
  const lies = actes.filter(a => joker(a) || regles.some(r => concerne(r, a)));
  if (lies.some(a => a.statut === 'attente_accord')) return 'outil_refuse';
  if (lies.some(a => a.statut === 'erreur')) return 'outil_en_erreur';
  return 'aucun_outil';
}

/** Les familles d'affirmations de la reponse que rien ne soutient dans ce tour : [{famille, raison}].
 *  raison : 'aucun_outil' (rien n'a ete appele pour ca), 'outil_refuse' (l'outil attend l'accord, ou n'a fait qu'un essai
 *  a blanc), 'outil_en_erreur' (l'outil a echoue). */
function promessesEnLAir(reponse, steps) {
  try {
    const lu = lire(reponse);
    const lues = lu.phrases.filter(p => !p.question && !p.citation);
    if (!lues.length) return [];
    const pas = Array.isArray(steps) ? steps.slice(-PAS_MAX) : [];
    const actes = actesDesSteps(pas);
    const doute = actes.some(a => joker(a) && reussi(a));
    const contenuLu = unSucces(LECTEURS_DE_CONTENU, actes);
    let observations = null;      // lues seulement si une famille en a besoin
    const manques = [];
    for (const f of FAMILLES) {
      if (doute || unSucces(f.soutiens, actes)) continue;
      const contexte = { lecture: unSucces(f.lectures, actes), contenuLu, recit: lu.recit };
      const affirme = lues.some(p => f.tournures.some(x => dit(x, p, contexte) && !unSucces(x.aussi, actes)));
      if (!affirme) continue;
      if (f.preuve) {
        if (!observations) observations = pas.filter(s => estObjet(s) && reussi({ statut: statutDe(s.observation) })).map(s => net(enTexte(s.observation)));
        if (observations.some(x => f.preuve.test(x))) continue;
      }
      manques.push({ famille: f.famille, raison: raisonPour(f.soutiens, actes) });
    }
    // l'envoi : toujours releve, sauf si la phrase parle de ce qu'un outil reussi fait vraiment partir
    const contexte = { lecture: unSucces(LECTURES_D_ENVOI, actes), contenuLu, recit: lu.recit };
    const envois = lues.filter(p => !DE_L_IMPRIMANTE.test(p.net) && ENVOIS.some(x => dit(x, p, contexte)));
    const nonCouverts = envois.filter(p => {
      if (UN_MAIL.test(p.net)) return !unSucces([MAIL_PARTI], actes);
      if (doute) return false;
      const nue = !OBJET_D_ENVOI.test(p.net) && !PORTEURS.some(x => x.parle.test(p.net));     // « C'est envoye ! »
      return !PORTEURS.some(x => unSucces([x.outil], actes) && (nue || x.parle.test(p.net)));
    });
    if (nonCouverts.length) {
      const parles = PORTEURS.filter(x => nonCouverts.some(p => !UN_MAIL.test(p.net) && x.parle.test(p.net))).map(x => x.outil);
      let raison = parles.length ? raisonPour(parles, actes.filter(a => !joker(a))) : 'aucun_outil';
      // « Le mail est parti », « C'est envoye. » alors que l'outil d'envoi a ete appele dans ce tour et n'a PAS envoye
      // (echec, accord manquant) : la raison le dit, au lieu de « aucun outil » (sonde du 21/11).
      if (raison === 'aucun_outil') {
        const nue = p => !OBJET_D_ENVOI.test(p.net) && !PORTEURS.some(x => x.parle.test(p.net));
        const candidats = [];
        if (nonCouverts.some(p => UN_MAIL.test(p.net) || nue(p))) candidats.push(MAIL_PARTI);
        if (nonCouverts.some(nue)) for (const x of PORTEURS) if (x.outil !== MAIL_PARTI) candidats.push(x.outil);
        if (candidats.length) raison = raisonPour(candidats, actes.filter(a => !joker(a)));
      }
      manques.push({ famille: ENVOI, raison });
    }
    return manques;
  } catch (e) {
    return [];      // jamais d'exception : dans le doute, rien n'est signale
  }
}

// ---------------------------------------------------------------------------------------------------------------
// 5. Ce qu'on dit a l'utilisateur
// ---------------------------------------------------------------------------------------------------------------

const SUITES = {
  aucun_outil: "mais je n'ai appelé aucun outil pour ça à l'instant, donc rien de nouveau n'est fait. Si tu le veux, redemande-le-moi.",
  outil_refuse: "mais l'outil attend encore ton accord, donc ce n'est pas fait. Dis-moi « vas-y » si tu es d'accord.",
  outil_en_erreur: "mais l'outil a échoué, donc ce n'est pas fait. Redemande-le-moi, ou regarde ce qui bloque.",
};
const ORDRE_DES_RAISONS = ['aucun_outil', 'outil_en_erreur', 'outil_refuse'];

function enumerer(noms) {
  return noms.length <= 1 ? (noms[0] || '') : noms.slice(0, -1).join(', ') + ' et ' + noms[noms.length - 1];
}

/** La phrase a ajouter sous la reponse, dans le ton de celle de core/verifier_reponse.js (« ⚠️ À vérifier : … »).
 *  Une seule phrase, meme pour plusieurs manques : elle porte la raison la plus grave (rien appele, puis echec, puis
 *  accord en attente) et nomme les familles qui ont cette raison. Chaine vide s'il n'y a rien a dire. */
function avertissement(manques) {
  try {
    const liste = (Array.isArray(manques) ? manques : []).filter(m => estObjet(m) && typeof m.famille === 'string' && m.famille.trim());
    if (!liste.length) return '';
    const raison = ORDRE_DES_RAISONS.find(r => liste.some(m => m.raison === r)) || 'aucun_outil';
    const retenus = liste.filter(m => m.raison === raison || !ORDRE_DES_RAISONS.includes(m.raison));
    const noms = [...new Set((retenus.length ? retenus : liste).map(m => m.famille.trim()))];
    return "⚠️ À vérifier : j'annonce " + enumerer(noms) + ', ' + SUITES[raison];
  } catch (e) {
    return '';
  }
}

// ---------------------------------------------------------------------------------------------------------------
// 6. Ce qui peut etre DIT a l'utilisateur (le reste va au journal)
// ---------------------------------------------------------------------------------------------------------------

// Seules deux raisons sont dites : l'outil de CETTE action a ete appele dans CE tour et il a echoue, ou il attend
// encore l'accord (essai a blanc compris), et la reponse annonce pourtant l'action comme faite. La contradiction est
// prouvee par le tour lui-meme. « aucun_outil » reste au journal : une phrase generale (« le chauffage est allume de
// novembre a mars ») ou une replique de theatre la declenchent encore (sondes du 19/11 et du 21/11).
const RAISONS_DITES = ['outil_en_erreur', 'outil_refuse'];

/** La reponse sans les phrases qu'Archi recopie d'un outil du tour : ce n'est pas lui qui affirme, c'est l'outil. */
function sansLesPhrasesDesOutils(reponse, steps) {
  const pas = Array.isArray(steps) ? steps.slice(-PAS_MAX) : [];
  // (les codes de caracteres sont ecrits en nombres : 10 = retour a la ligne, 92 = barre oblique inverse ; une
  // observation JSON garde ses retours a la ligne sous la forme « barre oblique inverse + n »)
  const LIGNE = String.fromCharCode(10), LIGNE_JSON = String.fromCharCode(92) + 'n';
  const dites = net(pas.map(s => (estObjet(s) ? enTexte(s.observation) : '')).join(' ').split(LIGNE_JSON).join(' '));
  if (!dites.trim()) return chaine(reponse);
  return borner(chaine(reponse), REPONSE_MAX, REPONSE_QUEUE).split(new RegExp('(?<=[.!?' + LIGNE + '])')).filter(bout => {
    const n = net(bout).replace(/[ .!?:;,]+$/, '').replace(/^[ *_>-]+/, '').trim();
    return !(n.length >= 12 && dites.includes(n));
  }).join('');
}

/** Les manques a dire a l'utilisateur : [{famille, raison}], raison parmi RAISONS_DITES. Jamais d'exception. */
function promessesADire(reponse, steps) {
  try {
    return promessesEnLAir(sansLesPhrasesDesOutils(reponse, steps), steps).filter(m => RAISONS_DITES.includes(m.raison));
  } catch (e) {
    return [];
  }
}

module.exports = {
  actesDesSteps, promessesEnLAir, avertissement, promessesADire, RAISONS_DITES,
  ENVOI, NOMS_DES_FAMILLES: FAMILLES.map(f => f.famille).concat([ENVOI]),
  _interne: { phrases, statutDe, entreeDe, parametresDe, FAMILLES },
};
