# commun.ps1 - les fonctions partagees par installer.ps1, telegram.ps1, verifier.ps1 et lancer_archi.ps1 (chargees avec un point).
# Le script appelant definit $ENVF (le chemin du fichier .env) avant de s'en servir. ASCII seulement.

function Dire([string]$t, [string]$couleur = "Gray") { Write-Host $t -ForegroundColor $couleur }
function Titre([string]$t) { Write-Host ""; Write-Host "=== $t ===" -ForegroundColor Green }

$script:utf8SansBom = New-Object System.Text.UTF8Encoding($false)
$script:nomsEnv = @()

# Vrai si personne ne repond sur ce port et qu'on peut s'y installer.
function PortLibre([int]$port) {
    try {
        $c = New-Object Net.Sockets.TcpClient
        $a = $c.BeginConnect("127.0.0.1", $port, $null, $null)
        $pris = $a.AsyncWaitHandle.WaitOne(300) -and $c.Connected
        $c.Close()
        if ($pris) { return $false }
    } catch {}
    try { $l = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, $port); $l.Start(); $l.Stop(); return $true } catch { return $false }
}

# ---------------------------------------------------------------- le fichier .env (ses valeurs ne sont jamais affichees)
# Memes regles de lecture que archi_env.py et core/env.js : "valeur" ou 'valeur' (un commentaire peut suivre),
# sinon on coupe a " #".
$script:motifEnv = '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$'
function ValeurLue([string]$v) {
    if ($v.Length -ge 2 -and ('"', "'" -contains [string]$v[0]) -and $v.IndexOf($v[0], 1) -gt 0) { return $v.Substring(1, $v.IndexOf($v[0], 1) - 1) }
    if ($v.Contains(' #')) { return $v.Substring(0, $v.IndexOf(' #')).TrimEnd() }
    return $v
}
# Une valeur qui contient " #" (un dossier 'Jean #1'), ou qui commence par un guillemet, est ecrite entre guillemets.
function ValeurEcrite([string]$v) {
    if (($v.Contains(' #') -or $v.StartsWith("'")) -and -not $v.Contains('"')) { return '"' + $v + '"' }
    if ($v.StartsWith('"') -and -not $v.Contains("'")) { return "'" + $v + "'" }
    return $v
}

function ValeurEnv([string]$nom) {
    if (-not (Test-Path $ENVF)) { return "" }
    foreach ($l in [System.IO.File]::ReadAllLines($ENVF, $script:utf8SansBom)) {
        if ($l -notmatch '^\s*#' -and $l -match $script:motifEnv -and $Matches[1] -eq $nom) { return (ValeurLue $Matches[2]) }
    }
    return ""
}

# Regle NOM=valeur. Sans -Forcer, une valeur deja remplie n'est jamais changee (tes reglages restent).
function ReglerEnv([string]$nom, [string]$valeur, [switch]$Forcer) {
    $lignes = New-Object System.Collections.Generic.List[string]
    if (Test-Path $ENVF) { $lignes.AddRange([System.IO.File]::ReadAllLines($ENVF, $script:utf8SansBom)) }
    $vu = $false
    for ($i = 0; $i -lt $lignes.Count; $i++) {
        if ($lignes[$i] -notmatch '^\s*#' -and $lignes[$i] -match $script:motifEnv -and $Matches[1] -eq $nom) {
            $vu = $true
            if ($Forcer -or (ValeurLue $Matches[2]) -eq "") { $lignes[$i] = "$nom=" + (ValeurEcrite $valeur) }
            break
        }
    }
    if (-not $vu) { $lignes.Add("$nom=" + (ValeurEcrite $valeur)) }
    [System.IO.File]::WriteAllLines($ENVF, $lignes, $script:utf8SansBom)
}

# Met le .env dans l'environnement de CETTE fenetre. Le .env gagne toujours : un autre n8n installe sur le PC
# (ou une variable N8N_... de Windows) ne doit pas se meler de celui d'Archi. Rend le nombre de valeurs chargees.
function ChargerEnv {
    $noms = New-Object System.Collections.Generic.List[string]
    foreach ($l in [System.IO.File]::ReadAllLines($ENVF, $script:utf8SansBom)) {
        if ($l -match '^\s*#' -or $l -notmatch $script:motifEnv) { continue }
        $nom = $Matches[1]; $v = ValeurLue $Matches[2]
        if ($v -ne "") { [Environment]::SetEnvironmentVariable($nom, $v, "Process"); $noms.Add($nom) }
    }
    $script:nomsEnv = $noms.ToArray()
    return $noms.Count
}

# Apres ChargerEnv : retire de CETTE fenetre les reglages de n8n et de tunnel herites de Windows mais absents du .env
# (le WEBHOOK_URL ou le N8N_... d'un autre n8n du PC changerait le comportement de celui d'Archi sans rien dire).
function NettoyerEnvHerite {
    $retires = 0
    foreach ($nom in @([Environment]::GetEnvironmentVariables("Process").Keys)) {
        if ($nom -match '^(N8N_|WEBHOOK_URL$|NODE_FUNCTION_|NODES_|EXECUTIONS_|DB_|QUEUE_|TUNNEL_)' -and $script:nomsEnv -notcontains $nom) {
            [Environment]::SetEnvironmentVariable($nom, $null, "Process"); $retires++
        }
    }
    return $retires
}

# Un argument tel que Windows le relira : entre guillemets s'il le faut, avec les \ doubles devant un guillemet.
function Citer([string]$a) {
    if ($a -ne "" -and $a -notmatch '[\s"]') { return $a }
    $a = $a -replace '(\\*)"', '$1$1\"'
    $a = $a -replace '(\\+)$', '$1$1'
    return '"' + $a + '"'
}

# Lance un programme sans fenetre et rend {code, sortie, erreur}. -Points : un point toutes les 5 s (longues etapes).
function Lancer([string]$exe, [string[]]$arguments, [int]$secondes = 600, [switch]$Points) {
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $exe
    $info.Arguments = ($arguments | ForEach-Object { Citer $_ }) -join " "
    $info.UseShellExecute = $false
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.CreateNoWindow = $true
    $dossier = Split-Path -Parent $ENVF
    if ($dossier -and (Test-Path $dossier)) { $info.WorkingDirectory = $dossier }
    $p = [System.Diagnostics.Process]::Start($info)
    $sortie = $p.StandardOutput.ReadToEndAsync()
    $erreur = $p.StandardError.ReadToEndAsync()
    $fin = (Get-Date).AddSeconds($secondes)
    while (-not $p.WaitForExit(5000)) {
        if ($Points) { Write-Host "." -NoNewline }
        if ((Get-Date) -gt $fin) { try { $p.Kill() } catch {}; if ($Points) { Write-Host "" }; return @{ code = -1; sortie = ""; erreur = "trop long" } }
    }
    $p.WaitForExit()
    if ($Points) { Write-Host "" }
    return @{ code = $p.ExitCode; sortie = $sortie.Result; erreur = $erreur.Result }
}

# L'outil en ligne de commande de LM Studio, ou $null.
function TrouverLms {
    foreach ($c in @((Join-Path $env:USERPROFILE ".lmstudio\bin\lms.exe"), (Join-Path $env:USERPROFILE ".cache\lm-studio\bin\lms.exe"))) {
        if (Test-Path $c) { return $c }
    }
    $cmd = Get-Command lms -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}
