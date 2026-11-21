// rejoue_banc.js - repasse dans core/promesses.js les reponses REELLES des modeles, enregistrees par le banc d'Archi.
//
//   node outils_depot/relecture/rejoue_banc.js [dossier du banc] [--textes]
//   (par defaut : %ARCHI_BANC%, sinon <dossier personnel>/banc_archi ; sous-dossiers resultats, resultats_passe1, confirmation)
//
// Sans modele, sans carte graphique : lecture seule des .json du banc. Pour chaque epreuve, le texte final du modele et
// la liste de ses appels d'outils passent dans promessesEnLAir. Limite : le banc ne garde que le NOM des appels, pas la
// reponse de l'outil. Chaque appel est donc compte comme reussi (sauf l'epreuve outil_en_panne) : c'est le cas le plus
// favorable au modele, donc celui ou une alerte affichee est la plus sure. Chaque ligne affichee se relit a la main.
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { promessesEnLAir } = require('../../core/promesses');

const args = process.argv.slice(2);
const BANC = args.find(a => !a.startsWith('--')) || process.env.ARCHI_BANC || path.join(os.homedir(), 'banc_archi');
const TEXTES = args.includes('--textes');

function pas(appel, epreuve) {
  const m = String(appel).split(':');
  if (m[0] !== 'outils_maison') return { action: { tool: m[0], toolInput: { action: m[1] || '' } }, observation: 'texte rendu par l\'outil' };
  if (!m[1]) return { action: { tool: 'outils_maison', toolInput: '{"action":"liste"}' }, observation: '{"ok":true,"outils":[]}' };
  return { action: { tool: 'outils_maison', toolInput: JSON.stringify({ action: 'utiliser', outil: m[1], parametres: { action: m[2] || '' } }) },
    observation: JSON.stringify({ ok: epreuve !== 'outil_en_panne', phrase_pour_utilisateur: 'x' }) };
}

let reponses = 0, signalees = 0, sansAppel = 0;
const parRaison = {}, deja = new Set();
for (const d of ['resultats', 'resultats_passe1', 'confirmation']) {
  const dossier = path.join(BANC, d);
  let fichiers = [];
  try { fichiers = fs.readdirSync(dossier).filter(f => f.endsWith('.json')); } catch (e) { console.log('(dossier absent : ' + dossier + ')'); }
  for (const f of fichiers) {
    let j = null;
    try { j = JSON.parse(fs.readFileSync(path.join(dossier, f), 'utf8')); } catch (e) { continue; }
    for (const e of (((j || {}).cerveau || {}).epreuves) || []) {
      if (typeof e.texte !== 'string' || !e.texte.trim()) continue;
      reponses++;
      const appels = Array.isArray(e.appels) ? e.appels : [];
      if (!appels.length) sansAppel++;
      const manques = promessesEnLAir(e.texte, appels.map(a => pas(a, e.cle)));
      if (!manques.length) continue;
      signalees++;
      for (const r of new Set(manques.map(m => m.raison))) parRaison[r] = (parRaison[r] || 0) + 1;
      const cle = e.cle + '|' + e.texte;
      if (deja.has(cle)) continue;
      deja.add(cle);
      console.log('[' + d + '/' + f + ' / ' + e.cle + '] ' + manques.map(m => m.famille + ' (' + m.raison + ')').join(' ; ') + ' · appels : ' + JSON.stringify(appels));
      if (TEXTES) console.log('   réponse : ' + JSON.stringify(e.texte.slice(0, 300)));
    }
  }
}
console.log('\n' + reponses + ' réponses rejouées (dont ' + sansAppel + ' sans aucun appel d\'outil), ' + signalees + ' signalées (' + deja.size
  + ' différentes) ' + JSON.stringify(parRaison));
