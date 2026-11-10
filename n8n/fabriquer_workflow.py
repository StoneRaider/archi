# Fabrique n8n/archi_demo.json (le workflow a importer dans n8n). Relancer apres toute modif :
#   python n8n/fabriquer_workflow.py
# Deux entrees, un meme cerveau :
#   Telegram (bot cree par chacun avec @BotFather)  -> Contexte -> Agent -> Verifier -> reponse Telegram
#   Appli Android (webhook /telephone-archi, cle)   -> Porte (cle + photo) -> Contexte -> Agent -> Verifier -> reponse JSON
import json, os, uuid

ICI = os.path.dirname(os.path.abspath(__file__))

# --- code partage des noeuds Code (n8n doit autoriser child_process, fs, path, os : voir .env.example) ---
APPEL_NODE = r"""
const cp = require('child_process');
const path = require('path');
const DEPOT = $env.ARCHI_DEPOT;
function appelNode(script, entree) {
  const out = cp.execFileSync('node', [path.join(DEPOT, 'core', script)], {
    input: JSON.stringify(entree), timeout: 30000, windowsHide: true,
  }).toString('utf8').trim().split(/\r?\n/).pop();
  return JSON.parse(out);
}
"""

CONTEXTE = APPEL_NODE + r"""
const e = $input.first().json;
const c = appelNode('contexte.js', { texte: e.texte || '', source: e.source || 'telegram', lat: e.lat, lon: e.lon });
// La memoire : un greffier (le modele local) releve ce que l'utilisateur vient d'apprendre de durable a Archi et le range
// en fiche (outils/memoire/memoire.py, action retenir). Il travaille EN ARRIERE-PLAN : la reponse ne l'attend pas.
try {
  const dit = String(e.entendu || e.texte || '');
  if (dit && String($env.ARCHI_MEMOIRE || 'oui').toLowerCase() !== 'non') {
    const fs = require('fs'), os = require('os');
    const BASE = $env.ARCHI_BASE || path.join(os.homedir(), '.n8n-files');
    const script = path.join(BASE, 'outils', 'memoire', 'memoire.py');
    if (fs.existsSync(script)) {
      const f = path.join(os.tmpdir(), 'archi_memoire_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8) + '.json');
      fs.writeFileSync(f, JSON.stringify({ action: 'retenir', texte: dit }));
      cp.spawn($env.ARCHI_PY || 'python', [script, '--fichier', f, '--menage'], { detached: true, stdio: 'ignore', windowsHide: true }).unref();
    }
  }
} catch (x) { /* la memoire ne doit jamais empecher Archi de repondre */ }
return [{ json: Object.assign({}, e, c) }];
"""

TELEGRAM_ENTREE = r"""
const m = $input.first().json.message || {};
let texte = m.text || m.caption || (m.location ? '' : '(message sans texte)');
// liste blanche : seul le chat de l'utilisateur parle a Archi (ARCHI_TELEGRAM_CHAT_ID). Les autres : aucune reponse.
const autorise = String($env.ARCHI_TELEGRAM_CHAT_ID || '').split(',').map(s => s.trim()).filter(Boolean);
const chat = String((m.chat || {}).id || '');
if (!autorise.includes(chat)) return [];
// trombone > Position : la position va au planificateur (rappels « quand j'arrive a... », « retiens cet endroit : ici »)
if (m.location) {
  const cp = require('child_process'), fs = require('fs'), os = require('os'), path = require('path');
  const BASE = $env.ARCHI_BASE || path.join(os.homedir(), '.n8n-files');
  const f = path.join(os.tmpdir(), 'archi_position_' + Date.now() + '.json');
  let phrase = "je n'ai pas pu noter la position";
  try {
    fs.writeFileSync(f, JSON.stringify({ lat: m.location.latitude, lon: m.location.longitude,
      precision_m: m.location.horizontal_accuracy || 0, source: 'telegram' }));
    const out = cp.execFileSync($env.ARCHI_PY || 'python', [path.join(BASE, 'outils', 'planificateur', 'planificateur.py'), '--position', '--fichier', f],
      { timeout: 30000, windowsHide: true }).toString('utf8').trim().split(/\r?\n/).pop();
    phrase = JSON.parse(out).phrase_pour_utilisateur || phrase;
  } catch (e) {} finally { try { fs.unlinkSync(f); } catch (e) {} }
  texte = "Je viens de partager ma position sur Telegram. Le planificateur a repondu : « " + phrase + " » Confirme-le en une phrase.";
}
return [{ json: { texte, source: 'telegram', chat_id: chat,
  lat: m.location ? m.location.latitude : undefined, lon: m.location ? m.location.longitude : undefined } }];
"""

# L'oreille et la voix (core/voix.js : whisper.cpp et Pocket TTS, sur ce PC). Appel SANS bloquer : n8n coupe un noeud
# qui ne repond plus pendant 30 s. Jamais d'exception : en cas de souci, Archi repond par ecrit.
APPEL_VOIX = r"""
function appelVoix(entree, ms) {
  const cpV = require('child_process'), pathV = require('path');
  return new Promise(ok => {
    const p = cpV.execFile('node', [pathV.join($env.ARCHI_DEPOT, 'core', 'voix.js')],
      { timeout: ms, windowsHide: true, maxBuffer: 64 * 1024 * 1024 }, (e, out) => {
        try { ok(JSON.parse(String(out || '').trim().split(/\r?\n/).pop())); }
        catch (x) { ok({ ok: false, raison: 'erreur', detail: String((e && e.message) || x.message || '').slice(0, 150) }); }
      });
    try { p.stdin.end(JSON.stringify(entree)); } catch (x) { /* le rappel ci-dessus dira l'erreur */ }
  });
}
"""

# La porte de l'appli : cle partagee (en-tete x-archi-cle), puis voix -> texte (Whisper) ou photo -> description (vision).
PORTE = APPEL_VOIX + r"""
const crypto = require('crypto');
const it = $input.first();
const h = it.json.headers || {};
const attendue = String($env.ARCHI_CLE_TELEPHONE || '');
const recue = String(h['x-archi-cle'] || '');
const empreinte = s => crypto.createHash('sha256').update(s, 'utf8').digest();
const ok = attendue.length >= 16 && crypto.timingSafeEqual(empreinte(recue), empreinte(attendue));
if (!ok) return [{ json: { refuse: true } }];
const b = it.json.body || {};
let texte = String(b.texte || '');
const bin = it.binary || {};
// le nom des champs binaires depend de la version du noeud Webhook : on les reconnait a leur type
const cles = Object.keys(bin);
const cleImage = cles.find(k => /^image\//.test(bin[k].mimeType || ''));
const cleAudio = cles.find(k => /^audio\//.test(bin[k].mimeType || '') || /\.m4a$/i.test(bin[k].fileName || ''));
// « voix: non » : la page d'accueil a coupe son haut-parleur, inutile de fabriquer le son de la reponse
const sans_voix = String(b.voix || '').toLowerCase() === 'non';
let entendu = '';
if (cleAudio && !texte) {
  // un message vocal : le son est pose dans un fichier temporaire, transcrit sur ce PC, puis efface
  const fs = require('fs'), os = require('os'), path = require('path');
  const ext = (String(bin[cleAudio].fileName || '').toLowerCase().match(/\.(m4a|mp4|webm|ogg|oga|wav|mp3|aac)$/) || ['.m4a'])[0];
  const f = path.join(os.tmpdir(), 'archi_question_' + crypto.randomBytes(6).toString('hex') + ext);
  let t = { ok: false, raison: 'erreur_oreille' };
  try {
    fs.writeFileSync(f, await this.helpers.getBinaryDataBuffer(0, cleAudio));
    t = await appelVoix({ action: 'transcrire', fichier: f }, 240000);   // moins que le delai d'une tache n8n (300 s)
  } catch (e) { /* t garde « erreur_oreille » */ } finally { try { fs.unlinkSync(f); } catch (e) {} }
  if (!t.ok) {
    const quoi = t.raison === 'rien_entendu' ? "Je n'ai rien entendu. Tu peux répéter ?"
      : t.raison === 'voix_desactivee' ? "La voix est coupée sur ce PC (ARCHI_VOIX=non dans le fichier .env). Écris-moi ton message."
      : t.raison === 'oreille_absente'
        ? "La voix n'est pas installée sur ce PC : relance installation.bat. En attendant, écris-moi ton message."
        : "Je n'ai pas réussi à écouter ton message. Écris-le-moi, et lance verifier_archi.bat sur le PC pour voir ce qui manque.";
    return [{ json: { direct: true, texte: quoi, sans_voix } }];
  }
  texte = t.texte;
  entendu = t.texte;
}
if (cleImage) {
  const buf = await this.helpers.getBinaryDataBuffer(0, cleImage);
  const rep = await this.helpers.httpRequest({
    method: 'POST', url: ($env.ARCHI_LM_URL || 'http://127.0.0.1:1234/v1') + '/chat/completions', json: true, timeout: 180000,
    body: { model: $env.ARCHI_MODELE_VISION || 'google/gemma-3-12b', temperature: 0.2, messages: [{ role: 'user', content: [
      { type: 'text', text: "Decris precisement cette photo prise sur le terrain (objets, etat, texte lisible, mesures visibles). Pas d'hypothese sur les personnes." },
      { type: 'image_url', image_url: { url: 'data:' + bin[cleImage].mimeType + ';base64,' + buf.toString('base64') } }] }] },
  });
  const desc = (((rep.choices || [])[0] || {}).message || {}).content || '(description indisponible)';
  const nomPhoto = String(b.nom_fichier || '').replace(/[^\w .\-]/g, '_').slice(0, 60);
  texte = (texte || 'Que vois-tu sur cette photo ?') + '\n--- contenu de la photo ' + nomPhoto + ' (decrite par le modele de vision) ---\n' + desc;
} else if (cles.length && !cleAudio) {
  texte += "\n(Une piece jointe a ete envoyee, mais la demo ne lit que les photos : dis-le a l'utilisateur.)";
}
return [{ json: { texte, source: 'appli', lat: b.lat, lon: b.lon, entendu, sans_voix } }];
"""

# La reponse de l'appli et de la page d'accueil : le texte, ce qu'Archi a entendu, et sa voix (OGG en base64).
VOIX = APPEL_VOIX + r"""
const e = $input.first().json;
const p = $('Porte').first().json;
const reponse = { texte: String(e.texte || '') };
if (p.entendu) reponse.entendu = p.entendu;
if (!p.sans_voix && reponse.texte) {
  // la voix a un plafond court (45 s dans core/voix.js) : si elle traine, la reponse ecrite part quand meme
  const v = await appelVoix({ action: 'dire', texte: reponse.texte }, 90000);
  if (v.ok) { reponse.audio_ogg_base64 = v.audio_ogg_base64; reponse.texte_dit = v.texte_dit; }
  else reponse.erreur_voix = v.raison || 'erreur';
}
return [{ json: { reponse } }];
"""

APPEL_PLANIF = r"""
const cp = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const BASE = $env.ARCHI_BASE || path.join(os.homedir(), '.n8n-files');
function planificateur(args, entree) {
  let fichier = null;
  if (entree) {
    fichier = path.join(os.tmpdir(), 'archi_boite_' + Date.now() + '.json');
    fs.writeFileSync(fichier, JSON.stringify(entree));
    args = args.concat(['--fichier', fichier]);
  }
  try {
    const out = cp.execFileSync($env.ARCHI_PY || 'python', [path.join(BASE, 'outils', 'planificateur', 'planificateur.py')].concat(args),
      { timeout: 60000, windowsHide: true }).toString('utf8').trim().split(/\r?\n/).pop();
    return JSON.parse(out);
  } finally { if (fichier) try { fs.unlinkSync(fichier); } catch (e) {} }
}
"""

# L'appli passe toutes les 90 s : position -> rappels a l'arrivee sur un lieu ; annonces <- PC.
BOITE = r"""
const crypto = require('crypto');
""" + APPEL_PLANIF + r"""
const it = $input.first().json;
const attendue = String($env.ARCHI_CLE_TELEPHONE || '');
const empreinte = s => crypto.createHash('sha256').update(String(s || ''), 'utf8').digest();
if (!(attendue.length >= 16 && crypto.timingSafeEqual(empreinte((it.headers || {})['x-archi-cle']), empreinte(attendue))))
  return [{ json: { code: 403, reponse: { annonces: [] } } }];
const r = planificateur(['--boite'], it.body || {});
return [{ json: { code: 200, reponse: { annonces: r.annonces || [], suivre_position: !!r.suivre_position } } }];
"""

# Le reveil : les rappels a heure fixe partent sur Telegram.
REVEIL = APPEL_PLANIF + r"""
const chat = String($env.ARCHI_TELEGRAM_CHAT_ID || '').split(',')[0].trim();
if (!chat) return [];   // sans chat, on ne reveille pas : les rappels ne sont pas marques partis
const r = planificateur(['--tick']);
return (r.telegram || []).map(texte => ({ json: { chat_id: chat, texte } }));
"""

VERIFIER = APPEL_NODE + r"""
const a = $input.first().json;
const c = $('Contexte').first().json;
const v = appelNode('verifier_reponse.js', { reponse: a.output || '', steps: a.intermediateSteps || [], msg: c.texte, profil: c.profil });
return [{ json: { texte: v.reponse, alertes: v.alertes || [] } }];
"""

VERIFIER_APPLI = VERIFIER.replace("$('Contexte')", "$('Contexte appli')")

OUTIL = APPEL_NODE + r"""
let d = {};
try { d = JSON.parse(query); } catch (e) { d = { action: 'liste' }; }
return JSON.stringify(appelNode('outils_maison.js', d));
"""
DESC_HUNTER = ("Enquete OSINT par Hunter (workflow optionnel n8n/optionnels/hunter_osint.json) : entreprise, artisan, vendeur, "
               "site ou mail suspect (arnaque), domaine, IP, photo, personnalite publique, profils PUBLICS d'un ami perdu de vue, "
               "empreinte numerique de l'utilisateur, veille geopolitique. Jamais l'adresse, le telephone ni la vie privee d'un particulier. "
               "Mission claire avec tous les elements connus. Prend 1 a 4 minutes. Renvoie une fiche sourcee, rangee dans le chateau.")
DESC_OUTIL = ("Lance un outil maison. Entree = UN objet JSON en texte : "
              '{"action":"liste"} pour voir les outils, ou {"action":"utiliser","outil":"<nom>","parametres":{...},"accord":"oui"} ; mets accord seulement apres un oui explicite de l utilisateur dans son dernier message. '
              "Rends a l'utilisateur la phrase_pour_utilisateur du resultat.")

SYSTEME = ("=Tu es Archi, l'assistant local de {{ $env.ARCHI_UTILISATEUR || 'l utilisateur' }}. Tu tournes sur son PC, sans cloud. "
           "Reponds en francais, court, en tutoyant. Tu n'inventes jamais un resultat : seul un outil fait les choses.\n\n"
           "PROFIL ET REGLES :\n{{ $json.profil }}\n\nOUTILS MAISON (via l'outil outils_maison) :\n{{ $json.outils }}")


def noeud(nom, type_, version, x, y, params, creds=None):
    n = {"parameters": params, "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "archi-demo/" + nom)), "name": nom,
         "type": type_, "typeVersion": version, "position": [x, y]}
    if creds:
        n["credentials"] = creds
    if type_ in ("n8n-nodes-base.webhook", "n8n-nodes-base.telegramTrigger"):
        # sans webhookId, n8n range le webhook sous /webhook/<workflow>/<noeud>/<chemin> au lieu de /webhook/<chemin> :
        # l'appli et la page d'accueil recevraient un 404 (vu a l'essai reel du 10/11/2026)
        n["webhookId"] = str(uuid.uuid5(uuid.NAMESPACE_URL, "archi-demo/webhook/" + nom))
    return n


def cerveau(suffixe, x, y, cle_session):
    """Agent + modele LM Studio + memoire courte + outil maison (un jeu par entree)."""
    return [
        noeud("Agent" + suffixe, "@n8n/n8n-nodes-langchain.agent", 1.7, x, y,
              {"promptType": "define", "text": "={{ $json.texte }}",
               "options": {"systemMessage": SYSTEME, "maxIterations": 6, "returnIntermediateSteps": True}}),
        noeud("Modele local" + suffixe, "@n8n/n8n-nodes-langchain.lmChatOpenAi", 1.2, x - 80, y + 220,
              {"model": {"__rl": True, "value": "={{ $env.ARCHI_MODELE || 'openai/gpt-oss-20b' }}", "mode": "id"},
               "options": {"temperature": 0.3}},
              {"openAiApi": {"id": "ArchiLmStudio001", "name": "LM Studio (local)"}}),
        noeud("Memoire courte" + suffixe, "@n8n/n8n-nodes-langchain.memoryBufferWindow", 1.3, x + 80, y + 220,
              {"sessionIdType": "customKey", "sessionKey": cle_session, "contextWindowLength": 10}),
        noeud("outils_maison" + suffixe, "@n8n/n8n-nodes-langchain.toolCode", 1.2, x + 240, y + 220,
              {"name": "outils_maison", "description": DESC_OUTIL, "language": "javaScript", "jsCode": OUTIL}),
        noeud("enquete_osint" + suffixe, "@n8n/n8n-nodes-langchain.toolWorkflow", 2.2, x + 400, y + 220,
              {"description": DESC_HUNTER,
               "workflowId": {"__rl": True, "value": "ArchiHunter00001", "mode": "id"},
               "workflowInputs": {"mappingMode": "defineBelow",
                                  "value": {"requete": "={{ $fromAI('requete', 'La mission complete pour Hunter, avec tous les elements connus', 'string') }}"},
                                  "matchingColumns": [], "schema": [{"id": "requete", "displayName": "requete", "required": False,
                                                                     "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "string"}],
                                  "attemptToConvertTypes": False, "convertFieldsToString": False}}),
    ]


nodes = [
    noeud("Telegram", "n8n-nodes-base.telegramTrigger", 1.2, 0, 0, {"updates": ["message"], "additionalFields": {}},
          {"telegramApi": {"id": "ArchiTelegram001", "name": "Bot Telegram Archi"}}),
    noeud("Message Telegram", "n8n-nodes-base.code", 2, 220, 0, {"jsCode": TELEGRAM_ENTREE}),
    noeud("Contexte", "n8n-nodes-base.code", 2, 440, 0, {"jsCode": CONTEXTE}),
    *cerveau("", 680, 0, "={{ 'tg-' + $('Message Telegram').first().json.chat_id }}"),
    noeud("Verifier", "n8n-nodes-base.code", 2, 1000, 0, {"jsCode": VERIFIER}),
    noeud("Repondre Telegram", "n8n-nodes-base.telegram", 1.2, 1220, 0,
          {"chatId": "={{ $('Message Telegram').first().json.chat_id }}", "text": "={{ $json.texte }}",
           "additionalFields": {"appendAttribution": False}},
          {"telegramApi": {"id": "ArchiTelegram001", "name": "Bot Telegram Archi"}}),

    noeud("Appli telephone", "n8n-nodes-base.webhook", 2, 0, 520,
          {"httpMethod": "POST", "path": "telephone-archi", "responseMode": "responseNode", "options": {}}),
    noeud("Porte", "n8n-nodes-base.code", 2, 220, 520, {"jsCode": PORTE}),
    noeud("Cle valide ?", "n8n-nodes-base.if", 2, 440, 520,
          {"conditions": {"options": {"caseSensitive": True, "typeValidation": "loose"}, "combinator": "and",
                          "conditions": [{"leftValue": "={{ $json.refuse === true }}", "rightValue": "",
                                          "operator": {"type": "boolean", "operation": "false", "singleValue": True}}]},
           "looseTypeValidation": True}),
    noeud("Refuser", "n8n-nodes-base.respondToWebhook", 1.1, 660, 720,
          {"respondWith": "json", "responseBody": '={"texte":"Cle refusee."}', "options": {"responseCode": 403}}),
    noeud("Reponse directe ?", "n8n-nodes-base.if", 2, 660, 520,
          {"conditions": {"options": {"caseSensitive": True, "typeValidation": "loose"}, "combinator": "and",
                          "conditions": [{"leftValue": "={{ $json.direct === true }}", "rightValue": "",
                                          "operator": {"type": "boolean", "operation": "true", "singleValue": True}}]},
           "looseTypeValidation": True}),
    noeud("Contexte appli", "n8n-nodes-base.code", 2, 880, 600, {"jsCode": CONTEXTE}),
    *cerveau(" appli", 1100, 600, "appli"),
    noeud("Verifier appli", "n8n-nodes-base.code", 2, 1420, 600, {"jsCode": VERIFIER_APPLI}),
    noeud("Voix appli", "n8n-nodes-base.code", 2, 1640, 520, {"jsCode": VOIX}),
    noeud("Repondre appli", "n8n-nodes-base.respondToWebhook", 1.1, 1860, 520,
          {"respondWith": "json", "responseBody": "={{ JSON.stringify($json.reponse) }}", "options": {}}),

    noeud("Boite appli", "n8n-nodes-base.webhook", 2, 0, 900,
          {"httpMethod": "POST", "path": "telephone-boite", "responseMode": "responseNode", "options": {}}),
    noeud("Boite", "n8n-nodes-base.code", 2, 220, 900, {"jsCode": BOITE}),
    noeud("Repondre boite", "n8n-nodes-base.respondToWebhook", 1.1, 440, 900,
          {"respondWith": "json", "responseBody": "={{ JSON.stringify($json.reponse) }}",
           "options": {"responseCode": "={{ $json.code }}"}}),

    noeud("Chaque minute", "n8n-nodes-base.scheduleTrigger", 1.2, 0, 1120,
          {"rule": {"interval": [{"field": "minutes", "minutesInterval": 1}]}}),
    noeud("Reveil planificateur", "n8n-nodes-base.code", 2, 220, 1120, {"jsCode": REVEIL}),
    noeud("Rappel Telegram", "n8n-nodes-base.telegram", 1.2, 440, 1120,
          {"chatId": "={{ $json.chat_id }}", "text": "={{ $json.texte }}", "additionalFields": {"appendAttribution": False}},
          {"telegramApi": {"id": "ArchiTelegram001", "name": "Bot Telegram Archi"}}),
]


def lien(a, b, sortie=0, type_="main"):
    return a, b, sortie, type_


liens = [
    lien("Telegram", "Message Telegram"), lien("Message Telegram", "Contexte"), lien("Contexte", "Agent"),
    lien("Agent", "Verifier"), lien("Verifier", "Repondre Telegram"),
    lien("Appli telephone", "Porte"), lien("Porte", "Cle valide ?"), lien("Cle valide ?", "Reponse directe ?", 0),
    lien("Cle valide ?", "Refuser", 1), lien("Reponse directe ?", "Voix appli", 0),
    lien("Reponse directe ?", "Contexte appli", 1), lien("Contexte appli", "Agent appli"),
    lien("Agent appli", "Verifier appli"), lien("Verifier appli", "Voix appli"), lien("Voix appli", "Repondre appli"),
    lien("Boite appli", "Boite"), lien("Boite", "Repondre boite"),
    lien("Chaque minute", "Reveil planificateur"), lien("Reveil planificateur", "Rappel Telegram"),
]
for s in ("", " appli"):
    liens += [lien("Modele local" + s, "Agent" + s, 0, "ai_languageModel"),
              lien("Memoire courte" + s, "Agent" + s, 0, "ai_memory"),
              lien("outils_maison" + s, "Agent" + s, 0, "ai_tool"),
              lien("enquete_osint" + s, "Agent" + s, 0, "ai_tool")]

connexions = {}
for a, b, sortie, t in liens:
    c = connexions.setdefault(a, {}).setdefault(t, [])
    while len(c) <= sortie:
        c.append([])
    c[sortie].append({"node": b, "type": t, "index": 0})

wf = {"id": "ArchiDemo0000001", "name": "Archi (demo publique)", "nodes": nodes, "connections": connexions, "active": False,
      "settings": {"executionOrder": "v1"}, "pinData": {}}
noms = {n["name"] for n in nodes}
assert all(a in noms and b in noms for a, b, _, _ in liens), "lien vers un noeud inconnu"
with open(os.path.join(ICI, "archi_demo.json"), "w", encoding="utf-8") as f:
    json.dump(wf, f, ensure_ascii=False, indent=1)
print("archi_demo.json :", len(nodes), "noeuds,", len(liens), "liens")
