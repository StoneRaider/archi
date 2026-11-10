# lancer_archi.ps1 - lance Archi avec les reglages du fichier .env (lance par lancer_archi.bat ou le raccourci du Bureau).
#   1. lit .env (sans jamais afficher les valeurs) : le .env gagne sur les variables de Windows ;
#   2. reveille le cerveau (LM Studio : serveur + modele charge avec un contexte de 16k) ;
#   3. ouvre la page d'accueil locale (le portail) et, pour le telephone, un tunnel HTTPS qui ne mene QU'AU portail ;
#   4. demarre le serveur mails/agenda, puis n8n (dans cette fenetre : la fermer arrete Archi).
# Marche avec les programmes prives poses par installation.bat (dossier programmes\), sinon avec ceux du PATH.
# ASCII seulement.
param([switch]$SansServeur, [switch]$SansNavigateur, [switch]$SansTunnel)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$racine = Split-Path -Parent $MyInvocation.MyCommand.Path
$ENVF = Join-Path $racine ".env"
. (Join-Path $racine "installer\commun.ps1")
try { $Host.UI.RawUI.WindowTitle = "Archi" } catch {}
if (-not (Test-Path $ENVF)) { Dire "Pas de fichier .env : double-clique d'abord sur installation.bat (ou copie .env.example en .env)." "Red"; exit 1 }

$n = ChargerEnv
NettoyerEnvHerite | Out-Null   # le WEBHOOK_URL ou les N8N_... d'un autre n8n du PC ne se melent pas de celui d'Archi
if (-not $env:ARCHI_DEPOT) { $env:ARCHI_DEPOT = $racine }
if (-not $env:ARCHI_BASE) { $env:ARCHI_BASE = Join-Path $env:USERPROFILE ".n8n-files" }
if (-not $env:ARCHI_LM_URL) { $env:ARCHI_LM_URL = "http://127.0.0.1:1234/v1" }
$pN8n = if ($env:N8N_PORT) { [int]$env:N8N_PORT } else { 5678 }
$pPortail = if ($env:ARCHI_PORTAIL_PORT) { [int]$env:ARCHI_PORTAIL_PORT } else { 5680 }
$pServeur = if ($env:ARCHI_SERVEUR_PORT) { [int]$env:ARCHI_SERVEUR_PORT } else { 8765 }
$pPorte = if ($env:ARCHI_PORTE_PORT) { [int]$env:ARCHI_PORTE_PORT } else { $pPortail + 1 }   # la porte du telephone : la cible du tunnel
$env:N8N_PORT = "$pN8n"; $env:ARCHI_PORTAIL_PORT = "$pPortail"; $env:ARCHI_PORTE_PORT = "$pPorte"
$etat = Join-Path $racine "donnees\etat"
New-Item -ItemType Directory -Force $etat | Out-Null
$env:ARCHI_ETAT = $etat
Dire ""
Dire "   A R C H I" "Green"
Dire "Reglages charges depuis .env : $n valeurs (jamais affichees)."

# ---------------------------------------------------------------- les programmes (prives d'abord)
$prog = Join-Path $racine "programmes"
function TrouverExe([string]$dossier, [string]$nom) {
    $f = Get-ChildItem -Path (Join-Path $prog $dossier) -Recurse -Filter $nom -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($f) { return $f.FullName }
    return $null
}
$node = TrouverExe "node" "node.exe"
if ($node) { $env:PATH = (Split-Path $node) + ";" + $env:PATH } else { $node = "node" }
$ff = TrouverExe "ffmpeg" "ffmpeg.exe"
if ($ff) { $env:PATH = (Split-Path $ff) + ";" + $env:PATH }
$py = if ($env:ARCHI_PY) { $env:ARCHI_PY } else { "python" }
$n8nBin = Join-Path $prog "n8n\node_modules\n8n\bin\n8n"
$cf = Join-Path $prog "cloudflared\cloudflared.exe"

# ---------------------------------------------------------------- un seul Archi a la fois
$fichierPids = Join-Path $etat "pids.txt"
function ArreterAnciens {
    # les aides (portail, tunnel, serveur) d'un lancement precedent ferme a la croix : on ne touche qu'a celles de CE dossier
    if (-not (Test-Path $fichierPids)) { return }
    foreach ($ligne in Get-Content $fichierPids) {
        $id = 0
        if (-not [int]::TryParse($ligne.Trim(), [ref]$id)) { continue }
        try {
            $p = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction Stop
            if ($p -and $p.CommandLine -and $p.CommandLine.ToLower().Contains($racine.ToLower())) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
        } catch {}
    }
    Remove-Item $fichierPids -Force -ErrorAction SilentlyContinue
}
if (-not (PortLibre $pN8n)) {
    if (-not (PortLibre $pPortail)) {
        Dire "Archi tourne deja : j'ouvre sa page d'accueil." "Green"
        Start-Process "http://127.0.0.1:$pPortail/"
        exit 0
    }
    Dire "Le port $pN8n est deja pris par un autre programme (un autre n8n ?). Ferme-le, ou change N8N_PORT dans .env." "Red"; exit 1
}
# un seul lancement a la fois pour CE dossier (un second double-clic pendant le demarrage ne casse pas le premier)
$verrou = New-Object System.Threading.Mutex($false, ("ArchiLanceur_" + [Math]::Abs($racine.ToLower().GetHashCode())))
$tenu = $false
try { $tenu = $verrou.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $tenu = $true }
if (-not $tenu) { Dire "Archi est deja en train de demarrer dans une autre fenetre." "Yellow"; Start-Sleep -Seconds 4; exit 0 }
ArreterAnciens
if (-not (PortLibre $pPortail)) { Dire "Le port $pPortail est deja pris : change ARCHI_PORTAIL_PORT dans .env." "Red"; exit 1 }
if (-not (PortLibre $pPorte)) { Dire "Le port $pPorte est deja pris : change ARCHI_PORTE_PORT dans .env." "Red"; exit 1 }
$aides = New-Object System.Collections.Generic.List[int]
function Suivre($processus) { if ($processus) { $aides.Add($processus.Id); Add-Content -Path $fichierPids -Value $processus.Id } }

# ---------------------------------------------------------------- le cerveau : LM Studio
function CerveauRepond { try { Invoke-RestMethod -Uri "$($env:ARCHI_LM_URL.TrimEnd('/'))/models" -TimeoutSec 3 | Out-Null; return $true } catch { return $false } }
Titre "Le cerveau (LM Studio)"
$lms = TrouverLms
try {
    if (-not (CerveauRepond) -and $lms) {
        Dire "  demarrage du serveur de LM Studio..."
        Lancer $lms @("server", "start") 120 | Out-Null
        # LM Studio reprend son dernier port : on s'aligne dessus si ce n'est pas celui du .env
        try {
            $s = (Lancer $lms @("server", "status", "--json") 30).sortie | ConvertFrom-Json
            if ($s.running -and $s.port -and $env:ARCHI_LM_URL -notmatch (":" + $s.port + "(/|$)")) {
                $env:ARCHI_LM_URL = "http://127.0.0.1:$($s.port)/v1"
                ReglerEnv "ARCHI_LM_URL" $env:ARCHI_LM_URL -Forcer
                Dire "  LM Studio ecoute sur le port $($s.port) : le .env est mis a jour (relance creer_identifiants si n8n ne le voit pas)."
            }
        } catch {}
    }
    if (CerveauRepond) {
        if ($lms -and $env:ARCHI_MODELE) {
            $charges = @()
            try { $charges = @(((Lancer $lms @("ps", "--json") 30).sortie | ConvertFrom-Json) | ForEach-Object { $_.identifier; $_.modelKey }) } catch {}
            if ($charges -notcontains $env:ARCHI_MODELE) {
                $contexte = if ($env:ARCHI_CONTEXTE) { $env:ARCHI_CONTEXTE } else { "16384" }
                Dire "  chargement de $($env:ARCHI_MODELE) sur la carte graphique (contexte $contexte, 20 a 60 secondes)..."
                $r = Lancer $lms @("load", $env:ARCHI_MODELE, "--context-length", $contexte, "-y") 600 -Points
                if ($r.code -ne 0) { Dire "  ! Le modele ne s'est pas charge tout seul : il se chargera a la premiere question (plus lent)." "Yellow" }
            }
        }
        Dire "  Cerveau pret : $($env:ARCHI_MODELE)" "Green"
    } else {
        Dire "  ! LM Studio ne repond pas sur $($env:ARCHI_LM_URL) : ouvre LM Studio, onglet Developer, et demarre le serveur." "Yellow"
    }
} catch { Dire "  ! LM Studio : $($_.Exception.Message)" "Yellow" }

# ---------------------------------------------------------------- n8n : identifiants et workflows (seulement si quelque chose a change)
Titre "L'agent (n8n)"
try {
    & $py -I (Join-Path $racine "n8n\creer_identifiants.py") --si-change
    & $py -I (Join-Path $racine "n8n\importer_workflows.py")
} catch { Dire "  ! Preparation de n8n : $($_.Exception.Message)" "Yellow" }

# ---------------------------------------------------------------- le portail (page d'accueil) et le tunnel du telephone
Titre "La page d'accueil et le telephone"
Remove-Item (Join-Path $etat "adresse_publique.txt") -Force -ErrorAction SilentlyContinue
$journal = Join-Path $etat "portail.log"
$env:ARCHI_PID_LANCEUR = "$PID"   # si cette fenetre est fermee a la croix, le portail arrete le tunnel et le serveur, puis s'arrete
Suivre (Start-Process -FilePath $node -ArgumentList ('"' + (Join-Path $racine "portail\portail.js") + '"') -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $journal -RedirectStandardError "$journal.err")
Dire "  Page d'accueil : http://127.0.0.1:$pPortail/"
$adresse = ""
if ($env:WEBHOOK_URL) {
    $adresse = $env:WEBHOOK_URL.TrimEnd('/')
    Dire "  Adresse HTTPS du .env : ton tunnel doit viser la porte du telephone (port $pPorte), pas n8n."
} elseif (-not $SansTunnel -and $env:ARCHI_TUNNEL -ne "non" -and (Test-Path $cf)) {
    # tunnel Cloudflare 'rapide' : sans compte, une adresse au hasard a chaque lancement, qui ne mene qu'a la porte du telephone
    $jt = Join-Path $etat "tunnel.log"
    Remove-Item $jt -Force -ErrorAction SilentlyContinue
    # un fichier de config VIDE : sinon cloudflared suivrait les regles d'un tunnel deja regle sur ce PC (.cloudflared\config.yml)
    $cfVide = Join-Path $etat "cloudflared_vide.yml"
    [System.IO.File]::WriteAllText($cfVide, "# vide, expres : ce tunnel ne suit que --url`n", $script:utf8SansBom)
    # et sans les variables TUNNEL_... : le jeton du tunnel nomme de la boite Docker ferait ouvrir un AUTRE tunnel
    $gardes = @{}
    foreach ($k in @([Environment]::GetEnvironmentVariables("Process").Keys)) {
        if ($k -like "TUNNEL_*") { $gardes[$k] = [Environment]::GetEnvironmentVariable($k, "Process"); [Environment]::SetEnvironmentVariable($k, $null, "Process") }
    }
    try {
        Suivre (Start-Process -FilePath $cf -ArgumentList "tunnel", "--no-autoupdate", "--config", (Citer $cfVide), "--url", "http://127.0.0.1:$pPorte" `
            -WindowStyle Hidden -PassThru -RedirectStandardError $jt -RedirectStandardOutput "$jt.out")
    } finally { foreach ($k in $gardes.Keys) { [Environment]::SetEnvironmentVariable($k, $gardes[$k], "Process") } }
    Dire "  ouverture de l'adresse HTTPS du telephone..."
    for ($i = 0; $i -lt 40 -and -not $adresse; $i++) {
        Start-Sleep -Seconds 1
        # (jamais api.trycloudflare.com : c'est l'adresse du service, citee dans le journal quand Internet manque)
        try { $m = [regex]::Match((Get-Content $jt -Raw -ErrorAction Stop), 'https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com'); if ($m.Success) { $adresse = $m.Value } } catch {}
    }
    if ($adresse) { $env:WEBHOOK_URL = "$adresse/" }
    else { Dire "  ! Le tunnel ne s'est pas ouvert (pas d'Internet ?) : la page d'accueil marche, le telephone attendra." "Yellow" }
}
if ($adresse) {
    [System.IO.File]::WriteAllText((Join-Path $etat "adresse_publique.txt"), $adresse, $script:utf8SansBom)
    Dire "  Telephone : $adresse  (scanne le QR code de la page d'accueil)" "Green"
}

# ---------------------------------------------------------------- la boite Docker (oeil, SearXNG, Presenton) : seulement si demandee
if ($env:ARCHI_DOCKER -eq "oui" -and (Get-Command docker -ErrorAction SilentlyContinue)) {
    Dire "Boite Docker (oeil, SearXNG, Presenton)..."
    Push-Location (Join-Path $racine "boite_outils")
    # services facultatifs : le globe seulement si son code est la, le tunnel seulement s'il a un jeton
    $profils = @()
    if (Test-Path (Join-Path $racine "boite_outils\gods-eye-view\package.json")) { $profils += "--profile", "oeil" }
    if ($env:TUNNEL_TOKEN -and $profils.Count -gt 0) { $profils += "--profile", "tunnel" }   # le tunnel a besoin de la porte (profil oeil)
    try { docker compose --env-file $ENVF @profils up -d --build } catch { Dire "Docker : $($_.Exception.Message)" "Yellow" }
    Pop-Location
}

# ---------------------------------------------------------------- le serveur mails et agenda
if (-not $SansServeur) {
    if (PortLibre $pServeur) {
        # lance DEPUIS son dossier (ses modules sont a cote) et dans une fenetre reduite : une erreur reste visible
        $dosServeur = Join-Path $racine "serveur"
        $pyServeur = if ($env:ARCHI_SERVEUR_PY -and (Test-Path $env:ARCHI_SERVEUR_PY)) { $env:ARCHI_SERVEUR_PY } else { Join-Path $dosServeur "venv\Scripts\python.exe" }
        if (-not (Test-Path $pyServeur)) { $pyServeur = $py }
        try {
            Suivre (Start-Process -FilePath $pyServeur -ArgumentList "archi_server.py" -WorkingDirectory $dosServeur -WindowStyle Minimized -PassThru)
            Dire "  Serveur mails et agenda : 127.0.0.1:$pServeur (non branche tant que tu n'as pas ajoute tes comptes)"
        } catch { Dire "  ! Serveur mails et agenda : $($_.Exception.Message)" "Yellow" }
    } else { Dire "  ! Le port $pServeur est pris : le serveur mails et agenda n'est pas lance." "Yellow" }
}

# ---------------------------------------------------------------- n8n, dans cette fenetre
if (-not $SansNavigateur) {
    # la page d'accueil s'ouvre toute seule quand n8n repond
    $attente = "for (`$i = 0; `$i -lt 120; `$i++) { try { Invoke-WebRequest -Uri 'http://127.0.0.1:$pN8n/healthz' -UseBasicParsing -TimeoutSec 2 | Out-Null; Start-Process 'http://127.0.0.1:$pPortail/'; break } catch { Start-Sleep -Seconds 2 } }"
    Start-Process -FilePath "powershell" -ArgumentList "-NoProfile", "-WindowStyle", "Hidden", "-Command", $attente -WindowStyle Hidden
}
Dire ""
Dire "n8n demarre (30 secondes environ), puis la page d'accueil s'ouvre dans ton navigateur." "Green"
Dire "Pour ARRETER Archi : ferme cette fenetre."
Dire ""
try {
    if (Test-Path $n8nBin) {
        # n8n est suivi comme les autres aides : si cette fenetre disparait sans prevenir, le portail l'arrete aussi
        $pn = Start-Process -FilePath $node -ArgumentList (Citer $n8nBin), "start" -NoNewWindow -PassThru
        Suivre $pn
        $pn.WaitForExit()
    }
    else {
        $version = if ($env:ARCHI_N8N_VERSION) { $env:ARCHI_N8N_VERSION } else { "1" }
        npx --yes "n8n@$version"
    }
} finally {
    foreach ($id in $aides) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
    Remove-Item $fichierPids -Force -ErrorAction SilentlyContinue
}
