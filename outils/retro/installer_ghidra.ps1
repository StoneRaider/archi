# installer_ghidra.ps1 - moteur natif pour REA : Ghidra 12.1.x + un JDK 21 DEDIE.
# Le JDK 21 va dans outils\retro\moteurs\jdk : il ne remplace PAS ton JDK 17 systeme
# (rea.cmd ne l'utilise que pour REA). Rapport : .local\install_ghidra.txt
$ErrorActionPreference = "Continue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$UA = @{ "User-Agent" = "archi-retro-installer" }

$ici = Split-Path -Parent $MyInvocation.MyCommand.Path
$moteurs = Join-Path $ici "moteurs"
$localdir = Join-Path $ici ".local"
New-Item -ItemType Directory -Force -Path $moteurs, $localdir | Out-Null
Start-Transcript -Path (Join-Path $localdir "install_ghidra.txt") -Force | Out-Null

function Etape($t){ Write-Host ""; Write-Host ("===== " + $t + " =====") }
function OK($t){ Write-Host ("[OK] " + $t) }
function KO($t){ Write-Host ("[ECHEC] " + $t) }
function Dossier($parent, $motif){
  Get-ChildItem $parent -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like $motif } | Select-Object -First 1
}

Write-Host ("Installateur Ghidra - " + (Get-Date))

# --- 1. JDK 21 portable (dedie a Ghidra, via Adoptium) ---
Etape "1. JDK 21 portable (dedie)"
$jdkRoot = Join-Path $moteurs "jdk"
New-Item -ItemType Directory -Force -Path $jdkRoot | Out-Null
$d = Dossier $jdkRoot "jdk-21*"
if ($d) { OK ("Deja present : " + $d.FullName) }
else {
  try {
    $u = "https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jdk/hotspot/normal/eclipse"
    $zip = Join-Path $env:TEMP "jdk21.zip"
    Write-Host ("Telechargement JDK 21 : " + $u)
    Invoke-WebRequest -UseBasicParsing -Headers $UA -Uri $u -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $jdkRoot -Force
    Remove-Item $zip -Force
    $d = Dossier $jdkRoot "jdk-21*"
    if ($d) { OK ("Installe : " + $d.FullName) } else { KO "JDK 21 : dossier introuvable apres extraction" }
  } catch { KO ("JDK 21 : " + $_.Exception.Message) }
}

# --- 2. Ghidra 12.1.x (release PUBLIC, NSA) ---
Etape "2. Ghidra 12.1.x"
$ghRoot = Join-Path $moteurs "ghidra"
New-Item -ItemType Directory -Force -Path $ghRoot | Out-Null
$d = Dossier $ghRoot "ghidra_12.1*"
if ($d) { OK ("Deja present : " + $d.FullName) }
else {
  try {
    $rel = Invoke-RestMethod -UseBasicParsing -Headers $UA -Uri "https://api.github.com/repos/NationalSecurityAgency/ghidra/releases?per_page=30"
    $cible = $rel | Where-Object { $_.tag_name -match "Ghidra_12\.1\." } | Select-Object -First 1
    if (-not $cible) { KO "Aucune release Ghidra 12.1.x trouvee" }
    else {
      $asset = $cible.assets | Where-Object { $_.name -like "ghidra_*PUBLIC*.zip" } | Select-Object -First 1
      $zip = Join-Path $env:TEMP $asset.name
      Write-Host ("Telechargement " + $asset.browser_download_url + " (environ 500 Mo)")
      Invoke-WebRequest -UseBasicParsing -Headers $UA -Uri $asset.browser_download_url -OutFile $zip
      Expand-Archive -Path $zip -DestinationPath $ghRoot -Force
      Remove-Item $zip -Force
      $d = Dossier $ghRoot "ghidra_12.1*"
      if ($d) { OK ("Installe : " + $d.FullName) } else { KO "Ghidra : dossier introuvable apres extraction" }
    }
  } catch { KO ("Ghidra : " + $_.Exception.Message) }
}

Etape "FIN"
Write-Host "rea.cmd detecte automatiquement Ghidra et le JDK 21 (sans toucher a ton JDK 17 systeme)."
Write-Host "Verifie avec : moteurs\rea.cmd doctor"
Write-Host "Puis connecte l'expert : moteurs\rea-setup.cmd (ferme Claude Desktop avant)."
Stop-Transcript | Out-Null
