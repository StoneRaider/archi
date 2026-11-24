# Demarre la boite a outils Docker (Presenton, SearXNG, globe de l'oeil) EN ARRIERE-PLAN, lance par lancer_archi.ps1 :
# Archi ne doit jamais attendre ni tomber parce que Docker Desktop n'est pas encore pret.
# Le compte rendu est ecrit dans boite_outils\demarrage.txt.
param(
    [Parameter(Mandatory = $true)][string]$Docker,
    [Parameter(Mandatory = $true)][string]$EnvFichier,
    [string]$Profils = ""   # ex. "--profile,oeil,--profile,tunnel" (une seule chaine : -File ne passe pas de tableau)
)
$ErrorActionPreference = "Continue"
$ici = Split-Path -Parent $MyInvocation.MyCommand.Path
$journal = Join-Path $ici "demarrage.txt"
$sortie = Join-Path $ici "demarrage_sortie.txt"
$erreurs = Join-Path $ici "demarrage_erreurs.txt"
function Noter([string]$t) { Add-Content -Path $journal -Value ((Get-Date -Format "dd/MM/yyyy HH:mm:ss") + " " + $t) -Encoding ASCII }
function Entre([string]$a) { if ($a -match '[\s"]') { return '"' + ($a -replace '"', '\"') + '"' } else { return $a } }
# Start-Process et des fichiers : la sortie d'erreur de docker ne devient jamais une exception de PowerShell 5.1
function Docker([string[]]$arguments) {
    $p = Start-Process -FilePath $Docker -ArgumentList (($arguments | ForEach-Object { Entre $_ }) -join " ") -WindowStyle Hidden `
        -RedirectStandardOutput $sortie -RedirectStandardError $erreurs -Wait -PassThru
    return $p.ExitCode
}
function Pret { return ((Docker @("info")) -eq 0) }

Set-Content -Path $journal -Value "" -Encoding ASCII
if (-not (Pret)) {
    $appli = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (Test-Path $appli) { Start-Process -FilePath $appli }
    Noter "Docker Desktop ne repondait pas : demarrage (5 minutes au plus)."
    $ok = $false
    for ($i = 0; $i -lt 60 -and -not $ok; $i++) { Start-Sleep -Seconds 5; $ok = Pret }
    if (-not $ok) {
        Noter "SOUCI : Docker Desktop ne repond pas. Ouvre-le une fois (accepte ses conditions, redemarre si Windows le demande), puis relance Archi."
        exit 1
    }
}
$liste = @("compose", "--project-directory", $ici, "-f", (Join-Path $ici "docker-compose.yml"), "--env-file", $EnvFichier) +
    @($Profils -split "," | Where-Object { $_ }) + @("up", "-d", "--build")
$code = Docker $liste
foreach ($f in @($sortie, $erreurs)) { if (Test-Path $f) { Get-Content $f | Select-Object -Last 10 | ForEach-Object { Noter "  $_" } } }
if ($code -eq 0) { Noter "Boite a outils prete." } else { Noter "SOUCI : les conteneurs n'ont pas demarre (code $code)." }
exit $code
