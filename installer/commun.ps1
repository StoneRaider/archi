# commun.ps1 - les fonctions partagees par installer.ps1, telegram.ps1 et lancer_archi.ps1 (chargees avec un point).
# Le script appelant definit $ENVF (le chemin du fichier .env) avant de s'en servir. ASCII seulement.

function Dire([string]$t, [string]$couleur = "Gray") { Write-Host $t -ForegroundColor $couleur }
function Titre([string]$t) { Write-Host ""; Write-Host "=== $t ===" -ForegroundColor Green }

$script:utf8SansBom = New-Object System.Text.UTF8Encoding($false)

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
function ValeurEnv([string]$nom) {
    if (-not (Test-Path $ENVF)) { return "" }
    foreach ($l in [System.IO.File]::ReadAllLines($ENVF, $script:utf8SansBom)) {
        if ($l -match ('^\s*' + [regex]::Escape($nom) + '\s*=\s*(.*?)\s*$')) { return $Matches[1] }
    }
    return ""
}

# Regle NOM=valeur. Sans -Forcer, une valeur deja remplie n'est jamais changee (tes reglages restent).
function ReglerEnv([string]$nom, [string]$valeur, [switch]$Forcer) {
    $lignes = New-Object System.Collections.Generic.List[string]
    if (Test-Path $ENVF) { $lignes.AddRange([System.IO.File]::ReadAllLines($ENVF, $script:utf8SansBom)) }
    $motif = '^\s*' + [regex]::Escape($nom) + '\s*=\s*(.*?)\s*$'
    $vu = $false
    for ($i = 0; $i -lt $lignes.Count; $i++) {
        if ($lignes[$i] -match $motif) {
            $vu = $true
            if ($Forcer -or $Matches[1] -eq "") { $lignes[$i] = "$nom=$valeur" }
            break
        }
    }
    if (-not $vu) { $lignes.Add("$nom=$valeur") }
    [System.IO.File]::WriteAllLines($ENVF, $lignes, $script:utf8SansBom)
}

# Met le .env dans l'environnement de CETTE fenetre. Le .env gagne toujours : un autre n8n installe sur le PC
# (ou une variable N8N_... de Windows) ne doit pas se meler de celui d'Archi. Rend le nombre de valeurs chargees.
# Memes regles de lecture que archi_env.py : "valeur" ou 'valeur', sinon on coupe a " #".
function ChargerEnv {
    $n = 0
    foreach ($l in [System.IO.File]::ReadAllLines($ENVF, $script:utf8SansBom)) {
        if ($l -match '^\s*#' -or $l -notmatch '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') { continue }
        $nom = $Matches[1]; $v = $Matches[2]
        if ($v.Length -ge 2 -and ('"', "'" -contains [string]$v[0]) -and $v.IndexOf($v[0], 1) -gt 0) { $v = $v.Substring(1, $v.IndexOf($v[0], 1) - 1) }
        elseif ($v.Contains(' #')) { $v = $v.Substring(0, $v.IndexOf(' #')).TrimEnd() }
        if ($v -ne "") { [Environment]::SetEnvironmentVariable($nom, $v, "Process"); $n++ }
    }
    return $n
}

# Lance un programme sans fenetre et rend {code, sortie, erreur}. -Points : un point toutes les 5 s (longues etapes).
function Lancer([string]$exe, [string[]]$arguments, [int]$secondes = 600, [switch]$Points) {
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $exe
    $info.Arguments = ($arguments | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join " "
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
