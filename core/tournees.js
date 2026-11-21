// tournees.js - le reveil des tournees du curateur (dimanche 10 h) et du mecanicien (mercredi et dimanche 10 h 30).
// Appele chaque minute par le noeud « Reveil planificateur » de n8n (et en ligne de commande : node core/tournees.js).
// Il RATTRAPE une tournee manquee : si le PC etait eteint a l'heure, la tournee part des qu'Archi tourne depuis 5 minutes
// (le temps que le modele local soit charge). A la toute premiere fois, il ne lance rien : il note l'heure, et la
// premiere tournee sera celle du prochain creneau.
// Les tournees partent en arriere-plan (python ... --tournee) ; elles previennent l'utilisateur par une annonce.
// Fichier : <base>\atelier\tournees.json. ARCHI_TOURNEES=non les coupe.
// Depuis le 21/11 : le tour du trader (simulation), chaque jour a 18 h. ARCHI_TRADER_AUTO=non coupe ce tour-la seulement ;
// « trader, arrete » le coupe aussi (le trader a l'arret ne fait pas de tour, et n'annonce rien).
'use strict';
const cp = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
require('./env').charger();

// [jour (0 = dimanche, 3 = mercredi), heure, minute]
const CRENEAUX = { curateur: [[0, 10, 0]], mecanicien: [[3, 10, 30], [0, 10, 30]], trader: [0, 1, 2, 3, 4, 5, 6].map(j => [j, 18, 0]) };
const SCRIPTS = { curateur: ['curateur', 'curateur.py'], mecanicien: ['mecanicien', 'mecanicien.py'], trader: ['trader', 'trader.py'] };
// une tournee qu'un reglage du .env peut couper seule
const COUPEES = { trader: () => String(process.env.ARCHI_TRADER_AUTO || 'oui').trim().toLowerCase() === 'non' };
const EVEILLE_MIN = 5 * 60000;     // Archi doit tourner depuis 5 minutes
const ABSENCE = 3 * 60000;         // plus de 3 minutes sans reveil : Archi etait arrete

/** le dernier creneau passe (Date), au plus 8 jours en arriere */
function dernierCreneau(creneaux, maintenant) {
  let meilleur = null;
  for (let j = 0; j <= 8; j++) {
    const jour = new Date(maintenant.getFullYear(), maintenant.getMonth(), maintenant.getDate() - j);
    for (const [js, h, m] of creneaux) {
      if (jour.getDay() !== js) continue;
      const t = new Date(jour.getFullYear(), jour.getMonth(), jour.getDate(), h, m, 0, 0);
      if (t <= maintenant && (!meilleur || t > meilleur)) meilleur = t;
    }
  }
  return meilleur;
}

function lire(f) {
  try { const x = JSON.parse(fs.readFileSync(f, 'utf8')); return x && typeof x === 'object' && !Array.isArray(x) ? x : null; } catch (e) { return null; }
}

function ecrire(f, x) {
  fs.mkdirSync(path.dirname(f), { recursive: true });
  fs.writeFileSync(f + '.tmp', JSON.stringify(x, null, 1));
  fs.renameSync(f + '.tmp', f);
}

function lancerPython(script) {
  cp.spawn(process.env.ARCHI_PY || (process.platform === 'win32' ? 'python' : 'python3'), [script, '--tournee'],
    { cwd: path.dirname(script), detached: true, stdio: 'ignore', windowsHide: true }).unref();
}

/** options = {base, maintenant, lancer} (pour les tests) ; rend {lancees: [noms], raison} */
function reveiller(options = {}) {
  if (String(process.env.ARCHI_TOURNEES || 'oui').toLowerCase() === 'non') return { lancees: [], raison: 'coupees' };
  const base = options.base || process.env.ARCHI_BASE || path.join(os.homedir(), '.n8n-files');
  const maintenant = options.maintenant || new Date();
  const lancer = options.lancer || lancerPython;
  const f = path.join(base, 'atelier', 'tournees.json');
  // un seul reveil a la fois (deux appels de n8n qui se croisent ne lancent pas deux fois la meme tournee)
  const verrou = path.join(base, 'atelier', '.verrou_tournees');
  try {
    fs.mkdirSync(path.dirname(verrou), { recursive: true });
    fs.mkdirSync(verrou);
  } catch (x) {
    // Math.abs : un verrou date du futur (horloge revenue en arriere) ne reste pas « occupe » pour toujours
    try { if (Math.abs(Date.now() - fs.statSync(verrou).mtimeMs) < 60000) return { lancees: [], raison: 'occupe' }; } catch (y) { return { lancees: [], raison: 'occupe' }; }
    try { fs.rmdirSync(verrou); fs.mkdirSync(verrou); } catch (y) { return { lancees: [], raison: 'occupe' }; }
  }
  try {
    return reveillerSousVerrou(f, base, maintenant, lancer);
  } finally {
    try { fs.rmdirSync(verrou); } catch (x) {}
  }
}

function reveillerSousVerrou(f, base, maintenant, lancer) {
  const iso = maintenant.toISOString();
  // une date notee plus tard que maintenant (l'horloge est revenue en arriere) ne compte pas : sinon plus rien ne partirait
  const date = v => { const x = Date.parse(v || '') || 0; return x > maintenant.getTime() ? 0 : x; };
  let e = lire(f);
  if (!e) {                                  // la premiere fois : rien tout de suite
    ecrire(f, { premiere: iso, vu: iso, depuis: iso, curateur: iso, mecanicien: iso });
    return { lancees: [], raison: 'premiere fois' };
  }
  const vu = date(e.vu);
  if (!vu || maintenant - vu > ABSENCE || !date(e.depuis)) e.depuis = iso;     // Archi vient de (re)demarrer
  e.vu = iso;
  // une tournee ajoutee par une nouvelle version d'Archi (le trader, 21/11) : comme a la toute premiere fois, rien tout
  // de suite, la premiere sera celle du prochain creneau
  for (const nom of Object.keys(CRENEAUX)) if (!(nom in e)) e[nom] = iso;
  const aLancer = [];
  if (maintenant - date(e.depuis) >= EVEILLE_MIN) {
    for (const nom of Object.keys(CRENEAUX)) {
      if (COUPEES[nom] && COUPEES[nom]()) continue;      // coupee : son creneau n'est pas consomme, elle reprendra au reglage suivant
      const creneau = dernierCreneau(CRENEAUX[nom], maintenant);
      if (!creneau || date(e[nom]) >= creneau.getTime()) continue;
      e[nom] = iso;
      const script = path.join(base, 'outils', ...SCRIPTS[nom]);
      if (fs.existsSync(script)) aLancer.push([nom, script]);
    }
  }
  // l'etat est ecrit AVANT de lancer : s'il ne peut pas l'etre, rien ne part (sinon la tournee repartirait chaque minute)
  ecrire(f, e);
  const lancees = [];
  for (const [nom, script] of aLancer) {
    try { lancer(script); lancees.push(nom); } catch (x) { /* la tournee attendra le prochain creneau */ }
  }
  return { lancees, raison: lancees.length ? 'creneau passe' : 'rien a faire' };
}

module.exports = { reveiller, dernierCreneau, CRENEAUX };

if (require.main === module) {
  let r;
  try { r = reveiller(); } catch (x) { r = { lancees: [], raison: 'erreur : ' + String(x.message || x).slice(0, 100) }; }
  process.stdout.write(JSON.stringify(r));
}
