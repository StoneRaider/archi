# installer.ps1 - l'installateur d'Archi. Lance par installation.bat (double-clic).
#
# Tout s'installe dans UN dossier (par defaut %USERPROFILE%\Archi) : Python, Node.js, n8n, le tunnel et ffmpeg y sont
# PRIVES, rien n'est ajoute au PATH ni installe pour tout Windows. Seule exception : LM Studio (le cerveau), installe
# par winget s'il n'est pas deja la. Desinstaller = supprimer le dossier.
# La voix (whisper.cpp et Pocket TTS) est privee elle aussi, et tourne sur le processeur.
# Ce fichier reste en ASCII (PowerShell 5 lit mal les accents sans BOM).
#
# Options (pour les essais) :
#   -Destination <dossier>   ou installer (defaut : %USERPROFILE%\Archi)
#   -Oui                     aucune question (reponses par defaut, pas de Telegram)
#   -Prenom <prenom>         le prenom utilise par Archi (sinon : demande, ou le nom de la session Windows)
#   -Cache <dossier>         prend les telechargements dans ce dossier s'ils y sont (memes noms)
#   -SansReseau              aucun telechargement (ce qui manque est saute et signale)
#   -SansCerveau             ne touche ni a LM Studio ni aux modeles
#   -SansModeles             LM Studio oui, mais aucun modele telecharge
#   -SansLancer              ne lance pas Archi a la fin
#   -SansRaccourci           ne pose pas le raccourci sur le Bureau
#   -SansVoix                n'installe ni l'oreille (Whisper) ni la parole (Pocket TTS)
#   -PortN8n, -PortPortail, -PortPorte, -PortServeur, -PortVoix   ports imposes (0 = le premier libre)
param(
    [string]$Destination = (Join-Path $env:USERPROFILE "Archi"),
    [switch]$Oui,
    [string]$Prenom = "",
    [string]$Cache = "",
    [switch]$SansReseau,
    [switch]$SansCerveau,
    [switch]$SansModeles,
    [switch]$SansLancer,
    [switch]$SansRaccourci,
    [switch]$SansVoix,
    [int]$PortN8n = 0,
    [int]$PortPortail = 0,
    [int]$PortPorte = 0,
    [int]$PortServeur = 0,
    [int]$PortVoix = 0
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
Add-Type -AssemblyName System.IO.Compression.FileSystem

# ---------------------------------------------------------------- versions (un seul endroit)
$VERSION_ARCHI = "1.0"
$VERSION_N8N = "1.123.92"          # la serie 1.x, celle avec laquelle les workflows ont ete faits
$VERSION_NODE = "22"               # Node.js LTS (n8n 1.x demande Node 20.19 a 24)
# Les programmes telecharges : une version precise, et son empreinte SHA-256 verifiee avant usage.
$TELECHARGEMENTS = @{
    "uv.zip"          = @("https://github.com/astral-sh/uv/releases/download/0.13.7/uv-x86_64-pc-windows-msvc.zip", "0cdc5b38fe5a8168ed6a25814f5ba43c21d313dd3187314fccb37b7cec46e021")
    "node.zip"        = @("https://nodejs.org/dist/v22.23.4/node-v22.23.4-win-x64.zip", "cbc74b5e0982c9dbb41525fd8fb5dcd32fbee237863f7829072f4639a1ce5f20")
    "cloudflared.exe" = @("https://github.com/cloudflare/cloudflared/releases/download/2026.10.7/cloudflared-windows-amd64.exe", "2493dbc168923bb3e59e5e7716f71deced92992eea9acd6e9d74f84ac7751343")
    "ffmpeg.zip"      = @("https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip", "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba")
    # la voix : whisper.cpp (l'oreille, version processeur), son modele small, et Pocket TTS (la parole)
    "whisper.zip"     = @("https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-bin-x64.zip", "6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb")
    "ggml-small.bin"  = @("https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-small.bin", "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b")
    "pocket-tts.zip"  = @("https://github.com/kyutai-labs/pocket-tts/releases/download/v4.0.1/pocket-tts-3.3.0-x86_64-pc-windows-msvc.zip", "98753041f2e65744b989776f87bccb93f1f574a08afe1890c5427ec94cd6309c")
}
$VERSION_PYTHON = "3.12"
$MODELE = "openai/gpt-oss-20b"     # le cerveau (12 Go)
$VISION_GRANDE = "google/gemma-3-12b"   # 8 Go : cartes de 24 Go et plus
$VISION_PETITE = "google/gemma-3-4b"    # 3 Go : tient a cote du cerveau sur une carte de 16 Go

$SOURCE = Split-Path -Parent $PSScriptRoot            # le dossier decompresse du ZIP
$Destination = [System.IO.Path]::GetFullPath($Destination).TrimEnd('\')
$PROG = Join-Path $Destination "programmes"
$TELE = Join-Path $Destination "telechargements"
$ENVF = Join-Path $Destination ".env"
$RAPPORT = New-Object System.Collections.Generic.List[string]
$UA = @{ "User-Agent" = "Archi-installateur/1.0" }
$utf8 = New-Object System.Text.UTF8Encoding($false)

. (Join-Path $PSScriptRoot "commun.ps1")   # Dire, Titre, PortLibre, ValeurEnv, ReglerEnv, ChargerEnv, Lancer, TrouverLms
function Noter([string]$t) { $RAPPORT.Add($t) | Out-Null; Dire "  $t" }
function Souci([string]$t) { $RAPPORT.Add("SOUCI : $t") | Out-Null; Dire "  ! $t" "Yellow" }

function Demander([string]$question, [bool]$defaut = $true) {
    if ($Oui) { return $defaut }
    $suffixe = if ($defaut) { "[O/n]" } else { "[o/N]" }
    $r = Read-Host "$question $suffixe"
    if ([string]::IsNullOrWhiteSpace($r)) { return $defaut }
    return $r.Trim().ToLower().StartsWith("o")
}

# ---------------------------------------------------------------- telechargements et programmes
function EmpreinteBonne([string]$fichier, [string]$nom) {
    $attendue = $TELECHARGEMENTS[$nom][1]
    return ((Get-FileHash -Algorithm SHA256 -LiteralPath $fichier).Hash.ToLower() -eq $attendue)
}
# Telecharge un programme de la liste $TELECHARGEMENTS et verifie son empreinte. Un fichier abime n'est jamais garde.
function Telecharger([string]$nom) {
    New-Item -ItemType Directory -Force $TELE | Out-Null
    $url = $TELECHARGEMENTS[$nom][0]
    $cible = Join-Path $TELE $nom
    if ($Cache -and (Test-Path (Join-Path $Cache $nom))) { Copy-Item (Join-Path $Cache $nom) $cible -Force }
    if (Test-Path $cible) {
        if (EmpreinteBonne $cible $nom) { return $cible }
        Remove-Item $cible -Force
    }
    if ($SansReseau) { throw "pas de reseau (mode essai) pour $nom" }
    Dire "  telechargement de $nom ..."
    $tmp = "$cible.partiel"
    for ($essai = 1; $essai -le 3; $essai++) {
        try {
            Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing -Headers $UA
            if (-not (EmpreinteBonne $tmp $nom)) { Remove-Item $tmp -Force; throw "empreinte SHA-256 inattendue (fichier abime ou modifie)" }
            Move-Item $tmp $cible -Force
            return $cible
        } catch {
            if ($essai -eq 3) { throw "telechargement impossible ($nom) : $($_.Exception.Message)" }
            Start-Sleep -Seconds 3
        }
    }
}

function Decompresser([string]$zip, [string]$dossier) {
    if (Test-Path $dossier) { Remove-Item $dossier -Recurse -Force }
    New-Item -ItemType Directory -Force $dossier | Out-Null
    [System.IO.Compression.ZipFile]::ExtractToDirectory($zip, $dossier)
}

function Trouver([string]$dossier, [string]$nom) {
    $f = Get-ChildItem -Path $dossier -Recurse -Filter $nom -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($f) { return $f.FullName }
    return $null
}

function ChoisirPort([int]$impose, [int]$defaut) {
    if ($impose -gt 0) { return $impose }
    for ($p = $defaut; $p -lt $defaut + 30; $p++) { if (PortLibre $p) { return $p } }
    return $defaut
}

function CleAleatoire {
    $b = New-Object byte[] 24
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    return [Convert]::ToBase64String($b).Replace('+', '-').Replace('/', '_').TrimEnd('=')
}

# ---------------------------------------------------------------- 0. bonjour
try { Clear-Host } catch {}
Dire ""
Dire "   A R C H I   $VERSION_ARCHI" "Green"
Dire "   Un agent IA 100 % local : le modele, la memoire et les outils tournent sur CE PC." "Green"
Dire ""
Dire "Dossier d'installation : $Destination"
if (-not (Test-Path (Join-Path $SOURCE "core\contexte.js"))) {
    Dire "Je ne trouve pas les fichiers d'Archi a cote de l'installateur. Decompresse TOUT le ZIP d'abord, puis relance." "Red"; exit 1
}
if (-not [Environment]::Is64BitOperatingSystem -or [Environment]::OSVersion.Version.Major -lt 10) {
    Dire "Archi demande Windows 10 ou 11, en 64 bits." "Red"; exit 1
}
if ($Destination -match '[^\x20-\x7E]') { Souci "Le dossier d'installation contient des accents : en cas de souci, relance avec -Destination C:\Archi" }

# ---------------------------------------------------------------- 1. le materiel
Titre "1. Ton PC"
$cartes = @(); $vramGo = 0
try { $cartes = @(Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }) } catch {}
try {
    # la vraie taille de la memoire video est dans le registre (Win32_VideoController plafonne a 4 Go)
    $cle = "HKLM:\SYSTEM\ControlSet001\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    # on ecarte les puces integrees et les ecrans virtuels : leur memoire est celle du PC, partagee
    $integrees = '(?i)virtual|basic|remote|parsec|displaylink|intel\(r\) (u?hd|iris)|radeon\(tm\) graphics$|radeon\(tm\) \d+m? graphics$'
    Get-ChildItem $cle -ErrorAction SilentlyContinue | ForEach-Object {
        $p = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
        $q = $p."HardwareInformation.qwMemorySize"
        if ($q -and "$($p.DriverDesc)" -notmatch $integrees) { $go = [math]::Round([double]$q / 1GB); if ($go -gt $vramGo) { $vramGo = $go } }
    }
} catch {}
$ramGo = 0
try { $ramGo = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB) } catch {}
$libreGo = 0
try { $libreGo = [math]::Round((New-Object System.IO.DriveInfo ([System.IO.Path]::GetPathRoot($Destination))).AvailableFreeSpace / 1GB) } catch {}
Noter ("Carte(s) graphique(s) : " + $(if ($cartes) { $cartes -join ", " } else { "inconnue" }) + $(if ($vramGo) { " ; memoire video : $vramGo Go" } else { "" }))
Noter "Memoire : $ramGo Go ; place libre sur le disque : $libreGo Go"
$VISION = if ($vramGo -ge 24) { $VISION_GRANDE } else { $VISION_PETITE }
if ($vramGo -gt 0 -and $vramGo -lt 12) { Souci "Moins de 12 Go de memoire video : le cerveau (gpt-oss-20b) debordera sur le processeur. Archi marchera, mais lentement." }
if ($libreGo -gt 0 -and $libreGo -lt 25) { Souci "Moins de 25 Go libres : les modeles (environ 16 Go) risquent de ne pas tenir." }

# ---------------------------------------------------------------- 2. ce qui va etre installe
Titre "2. Ce que je vais installer"
Dire "  Dans $Destination (rien n'est installe pour tout Windows) :"
Dire "   - Python $VERSION_PYTHON et Node.js $VERSION_NODE prives, n8n $VERSION_N8N (l'orchestrateur)"
Dire "   - les outils maison d'Archi, son chateau d'exemple (sa memoire) et ses workflows"
Dire "   - un tunnel HTTPS sans compte (Cloudflare) pour le telephone, et ffmpeg"
if (-not $SansVoix) { Dire "   - la voix, en local : Whisper (il t'ecoute) et Pocket TTS (il te repond a voix haute), environ 1 Go" }
if (-not $SansCerveau) {
    Dire "  Le cerveau : LM Studio (installe par winget s'il manque) et deux modeles (environ 16 Go a telecharger) :"
    Dire "   - $MODELE (le raisonnement) et $VISION (les photos)"
}
Dire "  Duree : 15 a 40 minutes selon ta connexion. Tu peux laisser tourner."
if (-not (Demander "On y va ?" $true)) { Dire "D'accord, rien n'a ete installe."; exit 0 }
if (-not $Prenom -and -not $Oui) { $Prenom = (Read-Host "Ton prenom (Archi t'appellera comme ca ; Entree = $env:USERNAME)").Trim() }
if (-not $Prenom) { $Prenom = $env:USERNAME }
$Prenom = ($Prenom -replace '[^\p{L}\p{N} \-]', '').Trim()
if (-not $Prenom) { $Prenom = "toi" }
$veutTelegram = $false
if (-not $Oui) { $veutTelegram = Demander "Brancher aussi Telegram ? (2 minutes, guide, avec ton telephone ; tu peux le faire plus tard)" $false }

# ---------------------------------------------------------------- 3. les fichiers d'Archi
Titre "3. Les fichiers d'Archi"
New-Item -ItemType Directory -Force $Destination, $PROG | Out-Null
if ($SOURCE.TrimEnd('\') -ne $Destination) {
    $exclus = @(".git", "programmes", "donnees", "chateau", "telechargements", "node_modules", "build", ".gradle", ".local", "__pycache__", "venv")
    & robocopy $SOURCE $Destination /E /XD $exclus /XF ".env" "installation.txt" "*.pyc" /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
    if ($LASTEXITCODE -ge 8) { Dire "La copie des fichiers a echoue (robocopy $LASTEXITCODE)." "Red"; exit 1 }
    # les fichiers viennent d'un ZIP telecharge : on leve la marque 'vient d Internet', sinon Windows redemande a chaque lancement
    Get-ChildItem -Path $Destination -Recurse -File -Include *.bat, *.ps1 -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notlike "$PROG\*" } | Unblock-File -ErrorAction SilentlyContinue
    Noter "Fichiers copies dans $Destination"
} else { Noter "Installation sur place (les fichiers sont deja dans $Destination)." }
$nouveauEnv = -not (Test-Path $ENVF)
if ($nouveauEnv) { Copy-Item (Join-Path $Destination ".env.example") $ENVF -Force }
if ($veutTelegram) {
    Titre "Telegram (tout de suite : le reste de l'installation tournera ensuite sans toi)"
    try { & (Join-Path $Destination "installer\telegram.ps1") -Depot $Destination -DansInstallation }
    catch { Souci "Telegram : pas branche pour l'instant (relance brancher_telegram.bat plus tard)." }
}

# ---------------------------------------------------------------- 4. Python prive
Titre "4. Python prive (uv)"
$PY = Join-Path $PROG "python\venv\Scripts\python.exe"
try {
    $uvExe = Join-Path $PROG "python\uv.exe"
    if (-not (Test-Path $uvExe)) {
        $zip = Telecharger "uv.zip"
        Decompresser $zip (Join-Path $PROG "uv")
        New-Item -ItemType Directory -Force (Join-Path $PROG "python") | Out-Null
        Copy-Item (Trouver (Join-Path $PROG "uv") "uv.exe") $uvExe -Force
    }
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $PROG "python\versions"
    $env:UV_CACHE_DIR = Join-Path $PROG "python\cache"
    $env:UV_NO_MODIFY_PATH = "1"
    if (-not (Test-Path $PY)) {
        $r = Lancer $uvExe @("venv", "--python", $VERSION_PYTHON, "--seed", (Join-Path $PROG "python\venv")) 900 -Points
        if ($r.code -ne 0) { throw "uv venv : $($r.erreur)" }
    }
    Dire "  modules Python des outils et du serveur (PDF, mails, agenda, navigateur)..."
    $r = Lancer $uvExe @("pip", "install", "--python", $PY, "-r", (Join-Path $Destination "outils\requirements.txt"),
        "-r", (Join-Path $Destination "serveur\requirements.txt")) 1800 -Points
    if ($r.code -ne 0) { throw "uv pip : $($r.erreur)" }
    $r = Lancer $PY @("-c", "import reportlab, PIL, pypdfium2, fastapi, uvicorn, requests; print('ok')") 120
    if ($r.sortie.Trim() -ne "ok") { throw "les bibliotheques ne se chargent pas : $($r.erreur)" }
    # ce Python prive relit le .env a chaque demarrage : n8n ne transmet pas les reglages aux outils qu'il lance
    $r = Lancer $PY @("-I", (Join-Path $Destination "archi_env.py"), "--brancher") 60
    if ($r.code -ne 0) { throw "archi_env --brancher : $($r.erreur)" }
    Noter "Python pret : $PY"
} catch { Souci "Python : $($_.Exception.Message)" }

# ---------------------------------------------------------------- 5. Node.js prive et n8n
Titre "5. Node.js prive et n8n $VERSION_N8N"
$node = $null; $n8nBin = Join-Path $PROG "n8n\node_modules\n8n\bin\n8n"
try {
    $node = Trouver (Join-Path $PROG "node") "node.exe"
    if (-not $node) {
        Decompresser (Telecharger "node.zip") (Join-Path $PROG "node")
        $node = Trouver (Join-Path $PROG "node") "node.exe"
    }
    if (-not $node) { throw "node.exe introuvable" }
    $nodeDir = Split-Path $node
    $env:PATH = "$nodeDir;$env:PATH"
    Noter ("Node.js pret : " + (Lancer $node @("--version") 30).sortie.Trim())

    $versionLa = ""
    try { $versionLa = (Get-Content (Join-Path $PROG "n8n\node_modules\n8n\package.json") -Raw | ConvertFrom-Json).version } catch {}
    if ($versionLa -ne $VERSION_N8N) {
        if ($SansReseau) { throw "n8n n'est pas installe et le reseau est coupe (mode essai)" }
        Dire "  installation de n8n (3 a 10 minutes : c'est l'etape la plus longue, laisse tourner)"
        $npm = Join-Path $nodeDir "node_modules\npm\bin\npm-cli.js"
        New-Item -ItemType Directory -Force (Join-Path $PROG "n8n") | Out-Null
        $r = Lancer $node @($npm, "install", "--prefix", (Join-Path $PROG "n8n"), "n8n@$VERSION_N8N", "--no-audit", "--no-fund", "--loglevel=error") 2400 -Points
        if ($r.code -ne 0 -or -not (Test-Path $n8nBin)) {
            $fin = ($r.erreur -split "`n" | Where-Object { $_.Trim() } | Select-Object -Last 3) -join " | "
            throw "npm install n8n a echoue : $fin"
        }
    }
    Noter "n8n $VERSION_N8N pret."
} catch { Souci "Node.js / n8n : $($_.Exception.Message)" }

# ---------------------------------------------------------------- 6. le tunnel et ffmpeg
Titre "6. Tunnel HTTPS (telephone) et ffmpeg"
try {
    $cf = Join-Path $PROG "cloudflared\cloudflared.exe"
    if (-not (Test-Path $cf)) {
        $f = Telecharger "cloudflared.exe"
        New-Item -ItemType Directory -Force (Split-Path $cf) | Out-Null
        Copy-Item $f $cf -Force
    }
    $r = Lancer $cf @("--version") 30
    if ($r.code -ne 0) { throw "cloudflared ne se lance pas" }
    Noter "Tunnel pret (Cloudflare, sans compte : une adresse HTTPS s'ouvre a chaque lancement)."
} catch { Souci "Tunnel : $($_.Exception.Message) (la page d'accueil du PC marchera, mais pas le telephone)" }
$ffDir = ""
try {
    $ff = Trouver (Join-Path $PROG "ffmpeg") "ffmpeg.exe"
    if (-not $ff) {
        $zip = Telecharger "ffmpeg.zip"
        Decompresser $zip (Join-Path $PROG "ffmpeg")
        $ff = Trouver (Join-Path $PROG "ffmpeg") "ffmpeg.exe"
    }
    if (-not $ff) { throw "ffmpeg.exe introuvable dans le ZIP" }
    $ffDir = Split-Path $ff
    Noter "ffmpeg pret (cameras, videos, montage)."
} catch { Souci "ffmpeg : $($_.Exception.Message) (les outils video et cameras attendront)" }

# ---------------------------------------------------------------- 7. le chateau et les outils
Titre "7. Le chateau (la memoire d'Archi) et ses outils"
$BASE = Join-Path $Destination "chateau"
try {
    if (Test-Path (Join-Path $BASE "memoire")) {
        Noter "Chateau existant garde tel quel : $BASE"
    } else {
        New-Item -ItemType Directory -Force $BASE | Out-Null
        Copy-Item (Join-Path $Destination "chateau_exemple\*") $BASE -Recurse -Force
        Noter "Chateau d'exemple cree : $BASE\memoire (des fiches Markdown, lisibles et corrigeables a la main)"
    }
    # le code des outils est mis a jour ; leurs donnees (a cote) et un registre deja la ne sont jamais ecrases
    New-Item -ItemType Directory -Force (Join-Path $BASE "outils") | Out-Null
    & robocopy (Join-Path $Destination "outils") (Join-Path $BASE "outils") /E /XD "__pycache__" /XF "*.pyc" /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "copie des outils (robocopy $LASTEXITCODE)" }
    if (-not (Test-Path (Join-Path $BASE "outils\registre.json"))) {
        Copy-Item (Join-Path $Destination "chateau_exemple\outils\registre.json") (Join-Path $BASE "outils\registre.json") -Force
    } elseif (Test-Path $PY) {
        # reinstallation : les outils nouveaux de cette version s'ajoutent ; un outil deja inscrit n'est jamais modifie
        $r = Lancer $PY @("-I", (Join-Path $Destination "installer\completer_registre.py"), (Join-Path $Destination "chateau_exemple\outils\registre.json"), (Join-Path $BASE "outils\registre.json")) 60
        if ($r.code -eq 0 -and "$($r.sortie)".Trim()) { Noter "Nouveaux outils ajoutes au registre : $("$($r.sortie)".Trim())" }
    }
    & robocopy (Join-Path $Destination "pc") (Join-Path $BASE "pc") /E /XD "__pycache__" /XF "*.pyc" /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
    New-Item -ItemType Directory -Force (Join-Path $BASE "impression3d") | Out-Null
    Copy-Item (Join-Path $Destination "n8n\optionnels\audit_stl.py") (Join-Path $BASE "impression3d\audit_stl.py") -Force
    $nb = 0
    try { $nb = @((Get-Content (Join-Path $BASE "outils\registre.json") -Raw -Encoding UTF8 | ConvertFrom-Json).PSObject.Properties).Count } catch {}
    Noter "Outils maison inscrits au registre : $nb"
} catch { Souci "Chateau : $($_.Exception.Message)" }

# ---------------------------------------------------------------- 8. les reglages (.env)
Titre "8. Les reglages (.env)"
# installation neuve : les premiers ports libres ; reinstallation : ceux du .env (l'appli et les raccourcis les connaissent)
$dejaPorts = (-not $nouveauEnv) -and ((ValeurEnv "ARCHI_PORTAIL_PORT") -match '^\d+$') -and ((ValeurEnv "N8N_PORT") -match '^\d+$')
$pN8n = if ($dejaPorts -and $PortN8n -eq 0) { [int](ValeurEnv "N8N_PORT") } else { ChoisirPort $PortN8n 5678 }
$pPortail = if ($dejaPorts -and $PortPortail -eq 0) { [int](ValeurEnv "ARCHI_PORTAIL_PORT") } else { ChoisirPort $PortPortail 5680 }
$pServeur = if ($dejaPorts -and $PortServeur -eq 0 -and (ValeurEnv "ARCHI_SERVEUR_PORT") -match '^\d+$') { [int](ValeurEnv "ARCHI_SERVEUR_PORT") } else { ChoisirPort $PortServeur 8765 }
$pPorte = if ($dejaPorts -and $PortPorte -eq 0 -and (ValeurEnv "ARCHI_PORTE_PORT") -match '^\d+$') { [int](ValeurEnv "ARCHI_PORTE_PORT") } else { ChoisirPort $PortPorte ($pPortail + 1) }
if ($pPorte -eq $pPortail -or $pPorte -eq $pN8n) { $pPorte = ChoisirPort 0 ($pPortail + 2) }
ReglerEnv "ARCHI_UTILISATEUR" $Prenom -Forcer:$nouveauEnv
ReglerEnv "ARCHI_DEPOT" $Destination -Forcer
ReglerEnv "ARCHI_BASE" $BASE -Forcer
ReglerEnv "ARCHI_PY" $PY -Forcer
ReglerEnv "ARCHI_SERVEUR_PY" $PY -Forcer
ReglerEnv "ARCHI_CLE_TELEPHONE" (CleAleatoire)          # deux cles aleatoires, creees ici, jamais affichees
ReglerEnv "ARCHI_CLE_OEIL" (CleAleatoire)
ReglerEnv "N8N_PORT" "$pN8n" -Forcer
ReglerEnv "ARCHI_PORTAIL_PORT" "$pPortail" -Forcer
ReglerEnv "ARCHI_PORTE_PORT" "$pPorte" -Forcer
ReglerEnv "ARCHI_SERVEUR_PORT" "$pServeur" -Forcer
ReglerEnv "ARCHI_N8N_VERSION" $VERSION_N8N -Forcer
# n8n : sa base et ses identifiants restent dans le dossier d'Archi ; il n'ecoute que ce PC ; aucune telemetrie
ReglerEnv "N8N_USER_FOLDER" (Join-Path $Destination "donnees\n8n") -Forcer
ReglerEnv "N8N_LISTEN_ADDRESS" "127.0.0.1" -Forcer
# le code des workflows tourne dans le task runner de n8n (le bac a sable integre refuse desormais child_process)
ReglerEnv "N8N_RUNNERS_ENABLED" "true" -Forcer
ReglerEnv "N8N_RESTRICT_FILE_ACCESS_TO" "$BASE;$Destination" -Forcer
ReglerEnv "N8N_DIAGNOSTICS_ENABLED" "false"
ReglerEnv "N8N_VERSION_NOTIFICATIONS_ENABLED" "false"
ReglerEnv "N8N_TEMPLATES_ENABLED" "false"
ReglerEnv "N8N_PERSONALIZATION_ENABLED" "false"
ReglerEnv "N8N_HIRING_BANNER_ENABLED" "false"
# le tunnel du telephone : rapide = Cloudflare sans compte ; non = aucun ; ou remplis WEBHOOK_URL avec ton propre tunnel
ReglerEnv "ARCHI_TUNNEL" "rapide"
# la memoire : Archi retient tout seul ce que tu lui apprends de durable (oui ou non)
ReglerEnv "ARCHI_MEMOIRE" "oui"
Noter "Fichier .env pret (deux cles aleatoires, creees a la premiere installation ; aucune valeur n'est affichee). Ports : n8n $pN8n, page d'accueil $pPortail, porte du telephone $pPorte, serveur $pServeur."

# ---------------------------------------------------------------- 9. le cerveau : LM Studio et les modeles
function ModelesLa([string]$lms) {
    try { return @(((Lancer $lms @("ls", "--json") 120).sortie | ConvertFrom-Json) | ForEach-Object { $_.modelKey }) } catch { return @() }
}
# la cle du modele deja la : la cle exacte, sinon la meme sans l'editeur ('gpt-oss-20b') ; sinon rien
function CleDuModele([string[]]$la, [string]$voulu) {
    if ($la -contains $voulu) { return $voulu }
    $court = ($voulu -split "/")[-1]
    $autre = $la | Where-Object { $_ -eq $court -or $_ -like "*/$court" } | Select-Object -First 1
    if ($autre) { return $autre }
    return $null
}
$modeleFinal = $MODELE; $visionFinale = $VISION
if (-not $SansCerveau) {
    Titre "9. Le cerveau : LM Studio et ses modeles"
    try {
        $lms = TrouverLms
        if (-not $lms) {
            if ($SansReseau) { throw "LM Studio n'est pas installe et le reseau est coupe (mode essai)" }
            if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw "LM Studio n'est pas installe et winget est absent : installe LM Studio depuis lmstudio.ai, ouvre-le une fois, puis relance installation.bat" }
            Dire "  installation de LM Studio par winget (Windows peut demander ton accord)..."
            & winget install --id ElementLabs.LMStudio -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
            $exe = @((Join-Path $env:LOCALAPPDATA "Programs\LM Studio\LM Studio.exe"), "C:\Program Files\LM Studio\LM Studio.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
            if (-not $exe) { throw "LM Studio ne s'est pas installe : installe-le depuis lmstudio.ai, ouvre-le une fois, puis relance installation.bat" }
            Dire "  premier demarrage de LM Studio (sa fenetre s'ouvre : laisse-la, tu peux la reduire)..."
            Start-Process -FilePath $exe -WindowStyle Minimized
            for ($i = 0; $i -lt 60 -and -not $lms; $i++) { Start-Sleep -Seconds 3; $lms = TrouverLms }
            if (-not $lms) { throw "LM Studio est installe mais son outil 'lms' n'est pas apparu : ouvre LM Studio une fois, puis relance installation.bat" }
            Noter "LM Studio installe."
        } else { Noter "LM Studio deja la." }
        $r = Lancer $lms @("server", "start") 120
        if ($r.code -ne 0) { Souci "Le serveur de LM Studio n'a pas demarre tout seul : ouvre LM Studio, onglet Developer, et demarre le serveur." }
        $la = ModelesLa $lms
        foreach ($role in @("cerveau", "vision")) {
            $voulu = if ($role -eq "cerveau") { $MODELE } else { $VISION }
            $cle = CleDuModele $la $voulu
            if (-not $cle -and -not $SansModeles -and -not $SansReseau) {
                Dire "  telechargement du modele $voulu (plusieurs Go : la barre de progression est celle de LM Studio)"
                & $lms get $voulu --gguf -y
                if ($LASTEXITCODE -ne 0) { Souci "Le modele $voulu n'a pas pu etre telecharge : dans LM Studio, cherche-le et telecharge-le, puis relance Archi." }
                $la = ModelesLa $lms
                $cle = CleDuModele $la $voulu
            }
            $quoi = if ($role -eq "cerveau") { "Modele du cerveau" } else { "Modele de vision" }
            if ($cle) { Noter "$quoi : $cle" } else { Souci "$quoi absent ($voulu)." ; $cle = $voulu }
            if ($role -eq "cerveau") { $modeleFinal = $cle } else { $visionFinale = $cle }
        }
    } catch { Souci "LM Studio : $($_.Exception.Message)" }
}
ReglerEnv "ARCHI_MODELE" $modeleFinal -Forcer
ReglerEnv "ARCHI_MODELE_VISION" $visionFinale -Forcer
ReglerEnv "CUSTOM_MODEL" $modeleFinal -Forcer

# ---------------------------------------------------------------- 10. la voix : Whisper (l'oreille) et Pocket TTS (la parole)
Titre "10. La voix (tout en local)"
$pVoix = if ((-not $nouveauEnv) -and $PortVoix -eq 0 -and (ValeurEnv "ARCHI_VOIX_PORT") -match '^\d+$') { [int](ValeurEnv "ARCHI_VOIX_PORT") } else { ChoisirPort $PortVoix 5683 }
if ($SansVoix) {
    Noter "Voix non installee (option -SansVoix) : Archi repond par ecrit."
} else {
    # l'oreille : whisper.cpp (processeur) et son modele ; rien ne sort du PC
    try {
        $wh = Trouver (Join-Path $PROG "whisper\programme") "whisper-cli.exe"
        if (-not $wh) {
            $zip = Telecharger "whisper.zip"
            Decompresser $zip (Join-Path $PROG "whisper\programme")
            $wh = Trouver (Join-Path $PROG "whisper\programme") "whisper-cli.exe"
        }
        if (-not $wh) { throw "whisper-cli.exe introuvable dans le ZIP" }
        # on le LANCE pour de bon : un fichier present ne prouve pas qu'il marche (extraction coupee, composant manquant)
        $r = Lancer $wh @("-h") 60
        if ($r.code -ne 0) {
            Remove-Item (Join-Path $PROG "whisper\programme") -Recurse -Force -ErrorAction SilentlyContinue
            throw "whisper-cli.exe ne se lance pas sur ce PC (code $($r.code)) ; relance installation.bat"
        }
        $modeles = Join-Path $PROG "whisper\modeles"
        $mo = Join-Path $modeles "ggml-small.bin"
        if (-not ((Test-Path $mo) -and (EmpreinteBonne $mo "ggml-small.bin"))) {
            Dire "  modele de l'oreille (environ 490 Mo)..."
            $f = Telecharger "ggml-small.bin"
            New-Item -ItemType Directory -Force $modeles | Out-Null
            Move-Item $f $mo -Force
        }
        ReglerEnv "ARCHI_WHISPER_EXE" $wh -Forcer
        ReglerEnv "ARCHI_WHISPER_MODELE" $mo -Forcer
        Noter "Oreille prete : whisper.cpp et son modele (tes messages vocaux sont transcrits sur ce PC)."
    } catch { Souci "Oreille (Whisper) : $($_.Exception.Message) (Archi lira tes messages ecrits, pas les vocaux)" }
    # la parole : Pocket TTS, un petit serveur local lance avec Archi
    try {
        $pk = Trouver (Join-Path $PROG "voix\programme") "pocket-tts.exe"
        if (-not $pk) {
            $zip = Telecharger "pocket-tts.zip"
            Decompresser $zip (Join-Path $PROG "voix\programme")
            $pk = Trouver (Join-Path $PROG "voix\programme") "pocket-tts.exe"
        }
        if (-not $pk) { throw "pocket-tts.exe introuvable dans le ZIP" }
        $r = Lancer $pk @("--version") 60
        if ($r.code -ne 0) {
            Remove-Item (Join-Path $PROG "voix\programme") -Recurse -Force -ErrorAction SilentlyContinue
            throw "pocket-tts.exe ne se lance pas sur ce PC (code $($r.code)) ; relance installation.bat"
        }
        # une premiere phrase : Pocket telecharge son modele (Hugging Face) et le range dans le dossier d'Archi
        $cacheVoix = Join-Path $PROG "voix\cache"
        New-Item -ItemType Directory -Force $cacheVoix, $TELE | Out-Null
        $essai = Join-Path $TELE "essai_voix.wav"
        Remove-Item $essai -Force -ErrorAction SilentlyContinue
        if ($SansReseau -and -not (Test-Path (Join-Path $cacheVoix "hub"))) { throw "pas de reseau (mode essai) pour le modele de la voix" }
        $hfAvant = $env:HF_HOME
        $env:HF_HOME = $cacheVoix
        try {
            if (-not (Test-Path (Join-Path $cacheVoix "hub"))) { Dire "  modele de la voix (environ 430 Mo, une seule fois)..." }
            $r = Lancer $pk @("generate", "--language", "french", "--voice", "charles", "--quiet", "--text", "Bonjour, je suis Archi.", "--output-path", $essai) 1800 -Points
        } finally { $env:HF_HOME = $hfAvant }
        if ($r.code -ne 0 -or -not (Test-Path $essai) -or (Get-Item $essai).Length -lt 10000) { throw "la premiere phrase n'a pas pu etre dite (code $($r.code))" }
        Remove-Item $essai -Force -ErrorAction SilentlyContinue
        Noter "Parole prete : Pocket TTS (Archi lit ses reponses a voix haute, sur le telephone et sur la page d'accueil)."
    } catch { Souci "Parole (Pocket TTS) : $($_.Exception.Message) (Archi repondra par ecrit)" }
}
# le port de la voix ne doit etre celui d'aucune autre brique d'Archi
while (@($pN8n, $pPortail, $pPorte, $pServeur) -contains $pVoix) { $pVoix++ }
ReglerEnv "ARCHI_VOIX" $(if ($SansVoix) { "non" } else { "oui" }) -Forcer:$SansVoix
if (-not $SansVoix -and (ValeurEnv "ARCHI_VOIX") -eq "non") { Noter "La voix est installee mais COUPEE : ARCHI_VOIX=non dans le fichier .env (mets oui pour entendre Archi)." }
ReglerEnv "ARCHI_VOIX_PORT" "$pVoix" -Forcer
ReglerEnv "ARCHI_VOIX_NOM" "charles"
ReglerEnv "ARCHI_LANGUE" "fr"

# ---------------------------------------------------------------- 11. n8n : identifiants et workflows
Titre "11. n8n : identifiants et workflows"
try {
    if (-not (Test-Path $PY)) { throw "Python n'est pas pret (voir plus haut)" }
    if (-not (Test-Path $n8nBin)) { throw "n8n n'est pas pret (voir plus haut)" }
    if (-not (PortLibre $pN8n)) { throw "le port $pN8n repond deja : ferme la fenetre 'Archi' (n8n doit etre arrete pendant l'import), puis relance installation.bat" }
    ChargerEnv | Out-Null
    Dire "  creation des identifiants et import des workflows (2 a 4 minutes)"
    $r = Lancer $PY @("-I", (Join-Path $Destination "n8n\creer_identifiants.py")) 600 -Points
    ($r.sortie -split "`r?`n") | Where-Object { $_.Trim() } | ForEach-Object { Noter $_ }
    if ($r.code -ne 0) { Souci "Identifiants n8n : la creation automatique a echoue." }
    $r = Lancer $PY @("-I", (Join-Path $Destination "n8n\importer_workflows.py")) 1800 -Points
    ($r.sortie -split "`r?`n") | Where-Object { $_.Trim() } | ForEach-Object { if ($_ -match "Echec|PAS active") { Souci $_ } else { Noter $_ } }
} catch { Souci "n8n : $($_.Exception.Message)" }

# ---------------------------------------------------------------- 12. le raccourci et le bilan
Titre "Bilan"
if (-not $SansRaccourci) { try {
    $bureau = [Environment]::GetFolderPath("Desktop")
    $lien = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $bureau "Archi.lnk"))
    $lien.TargetPath = Join-Path $Destination "lancer_archi.bat"
    $lien.WorkingDirectory = $Destination
    $lien.Description = "Lancer Archi (agent IA local)"
    $lien.Save()
    Noter "Raccourci 'Archi' pose sur le Bureau."
} catch { Souci "Raccourci : $($_.Exception.Message) (lance $Destination\lancer_archi.bat)" } }
$RAPPORT.Insert(0, "Installation d'Archi $VERSION_ARCHI du $(Get-Date -Format 'dd/MM/yyyy HH:mm') dans $Destination")
[System.IO.File]::WriteAllLines((Join-Path $Destination "installation.txt"), $RAPPORT, $utf8)
$soucis = @($RAPPORT | Where-Object { $_ -like "SOUCI*" })
Dire ""
if ($soucis.Count) {
    Dire "Installe, avec $($soucis.Count) souci(s) :" "Yellow"
    $soucis | ForEach-Object { Dire "  - $_" "Yellow" }
} else { Dire "Tout est installe, sans aucun souci." "Green" }
Dire "Le bilan complet est dans $Destination\installation.txt"
Dire ""
if ($SansLancer) { Dire "Pour lancer Archi : double-clique sur lancer_archi.bat (ou sur le raccourci 'Archi' du Bureau)."; exit ($(if ($soucis.Count) { 2 } else { 0 })) }
Dire "MAINTENANT : Archi demarre dans une nouvelle fenetre, puis sa page d'accueil s'ouvre dans ton navigateur." "Green"
Dire "  - ecris-lui 'Quels outils as-tu ?', ou clique sur le micro et parle-lui ;"
Dire "  - pour le telephone : scanne le QR code de la page d'accueil."
Dire "Les fois suivantes : le raccourci 'Archi' du Bureau."
Start-Process -FilePath (Join-Path $Destination "lancer_archi.bat") -WorkingDirectory $Destination
