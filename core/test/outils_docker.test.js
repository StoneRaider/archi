// Les outils qui ont besoin de la boite Docker ne sont montres au modele que si ARCHI_DOCKER=oui
// (essai du 24/11 : sans Docker, un poeme partait chez Presenton).
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

function outilsVus(docker) {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'archi-docker-'));
  fs.mkdirSync(path.join(base, 'outils'), { recursive: true });
  fs.writeFileSync(path.join(base, 'outils', 'registre.json'), JSON.stringify({
    meteo: { nom: 'meteo', description: 'la meteo', parametres: [] },
    presentation: { nom: 'presentation', besoin: 'docker', description: 'un PowerPoint', parametres: [] },
    ancien: { nom: 'globe', besoin: 'docker', description: 'le globe', parametres: [] },
  }));
  const env = Object.assign({}, process.env, { ARCHI_BASE: base, ARCHI_DOCKER: docker, ARCHI_ENV: path.join(base, 'absent.env') });
  try {
    return execFileSync(process.execPath, ['-e', "process.stdout.write(require('./core/contexte').construire({ texte: 'salut' }).outils)"],
      { cwd: path.join(__dirname, '..', '..'), env, encoding: 'utf8' });
  } finally { fs.rmSync(base, { recursive: true, force: true }); }
}

test('sans la boite Docker, ni presentation ni globe ne sont proposes au modele', () => {
  const t = outilsVus('');
  assert.ok(t.includes('- meteo'), t);
  assert.ok(!t.includes('presentation') && !t.includes('globe'), t);
});

test('avec ARCHI_DOCKER=oui, ils reviennent', () => {
  const t = outilsVus('oui');
  assert.ok(t.includes('- presentation') && t.includes('- globe') && t.includes('- meteo'), t);
});
