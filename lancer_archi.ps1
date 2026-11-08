# lancer_archi.ps1 - lance Archi avec les reglages du fichier .env (lance par lancer_archi.bat).
#   1. lit .env (sans jamais afficher les valeurs) et le met dans l'environnement de cette fenetre ;
#   2. cree ou met a jour les identifiants n8n (bot Telegram, LM Studio) a partir du .env ;
#   3. demarre la boite Docker (si Docker est installe), le serveur mails/agenda, puis n8n.
param([switch]$SansDocker, [switch]$SansServeur)
$ErrorActionPreference = "Stop"
$racine = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFichier = Join-Path $racine ".env"
if (-not (Test-Path $envFichier)) { Write-Host "Pas de .env : copie .env.example en .env, remplis-le, puis relance."; exit 1 }

$n = 0
foreach ($l in Get-Content -LiteralPath $envFichier -Encoding UTF8) {
    if ($l -match '^\s*#' -or $l -notmatch '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') { continue }
    $nom = $Matches[1]; $v = $Matches[2]
    # meme regle que archi_env.py : "valeur" ou 'valeur' (un commentaire peut suivre), sinon on coupe a " #"
    if ($v.Length -ge 2 -and ('"', "'" -contains [string]$v[0]) -and $v.IndexOf($v[0], 1) -gt 0) { $v = $v.Substring(1, $v.IndexOf($v[0], 1) - 1) }
    elseif ($v.Contains(' #')) { $v = $v.Substring(0, $v.IndexOf(' #')).TrimEnd() }
    if ($v -ne "" -and -not [Environment]::GetEnvironmentVariable($nom, "Process")) {
        [Environment]::SetEnvironmentVariable($nom, $v, "Process"); $n++
    }
}
if (-not $env:ARCHI_DEPOT) { $env:ARCHI_DEPOT = $racine }
# le chateau : les workflows et les outils en ont besoin (vide dans le .env = ~/.n8n-files)
if (-not $env:ARCHI_BASE) { $env:ARCHI_BASE = Join-Path $env:USERPROFILE ".n8n-files" }
Write-Host "Reglages charges depuis .env : $n valeurs (non affichees)."

$py = if ($env:ARCHI_PY) { $env:ARCHI_PY } else { "python" }
& $py -I (Join-Path $racine "archi_env.py")

# identifiants n8n a partir du .env (le jeton ne passe que par un fichier temporaire, efface aussitot)
& $py -I (Join-Path $racine "n8n\creer_identifiants.py")
# workflows (principal + optionnels) avec leurs ID fixes : au premier lancement seulement (n8n est encore arrete ici)
& $py -I (Join-Path $racine "n8n\importer_workflows.py")

if (-not $SansDocker -and (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Boite Docker (oeil, SearXNG, Presenton)..."
    Push-Location (Join-Path $racine "boite_outils")
    # services facultatifs : le globe seulement si son code est la, le tunnel seulement s'il a un jeton
    $profils = @()
    if (Test-Path (Join-Path $racine "boite_outils\gods-eye-view\package.json")) { $profils += "--profile", "oeil" }
    if ($env:TUNNEL_TOKEN -and $profils.Count -gt 0) { $profils += "--profile", "tunnel" }   # le tunnel a besoin de la porte (profil oeil)
    try { docker compose --env-file $envFichier @profils up -d --build } catch { Write-Host "Docker : $($_.Exception.Message)" }
    Pop-Location
}
if (-not $SansServeur) {
    Write-Host "Serveur mails et agenda (127.0.0.1:$(if ($env:ARCHI_SERVEUR_PORT) { $env:ARCHI_SERVEUR_PORT } else { 8765 }))..."
    # le serveur a son propre venv (serveur\venv, voir serveur\LISEZMOI.md), sinon le Python de ARCHI_PY ;
    # lance DEPUIS son dossier (ses modules sont a cote) et dans une fenetre visible : une erreur se voit
    $dosServeur = Join-Path $racine "serveur"
    $pyServeur = Join-Path $dosServeur "venv\Scripts\python.exe"
    if (-not (Test-Path $pyServeur)) { $pyServeur = $py }
    Start-Process -FilePath $pyServeur -ArgumentList "archi_server.py" -WorkingDirectory $dosServeur
}
Write-Host "n8n (http://127.0.0.1:$(if ($env:N8N_PORT) { $env:N8N_PORT } else { 5678 }))..."
$version = if ($env:ARCHI_N8N_VERSION) { $env:ARCHI_N8N_VERSION } else { "1" }
npx --yes "n8n@$version"
