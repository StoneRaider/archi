# telegram.ps1 - branche un bot Telegram PERSONNEL sur Archi, pas a pas. Lance par brancher_telegram.bat
# (ou par l'installateur). Le jeton est saisi sans s'afficher, ecrit seulement dans le .env, et jamais montre.
# ASCII seulement.
param(
    [string]$Depot = (Split-Path -Parent $PSScriptRoot),
    [switch]$DansInstallation      # l'installateur importera lui-meme les identifiants et les workflows ensuite
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
$ENVF = Join-Path $Depot ".env"
. (Join-Path $PSScriptRoot "commun.ps1")
if (-not (Test-Path $ENVF)) { Dire "Pas de fichier .env dans $Depot : lance d'abord installation.bat." "Red"; exit 1 }

# Appel a l'API Telegram. Une erreur ne montre JAMAIS l'adresse appelee : elle contient le jeton.
function Telegram([string]$jeton, [string]$methode, [int]$delai = 30) {
    try { return Invoke-RestMethod -Uri "https://api.telegram.org/bot$jeton/$methode" -UseBasicParsing -TimeoutSec $delai }
    catch {
        $code = 0
        try { $code = [int]$_.Exception.Response.StatusCode } catch {}
        return [pscustomobject]@{ ok = $false; code = $code }
    }
}

Dire ""
Dire "Un bot Telegram rien qu'a toi : seul TON compte pourra parler a Archi." "Green"
Dire "  1. Dans Telegram, cherche  @BotFather  (avec la coche bleue) et ecris-lui :  /newbot"
Dire "  2. Donne un nom (ex. Archi), puis un identifiant qui finit par  bot  (ex. archi_de_camille_bot)"
Dire "  3. BotFather repond avec un jeton : une longue ligne du genre  123456789:AAH...  Copie-la."
Dire ""

$jeton = ""; $bot = $null
for ($essai = 1; $essai -le 3 -and -not $bot; $essai++) {
    $sec = Read-Host "Colle le jeton ici (il ne s'affiche pas), puis Entree ; ou Entree seule pour abandonner" -AsSecureString
    $jeton = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)).Trim()
    if (-not $jeton) { Dire "Abandon : Telegram n'est pas branche. Tu pourras relancer brancher_telegram.bat."; exit 2 }
    if ($jeton -notmatch '^\d{6,12}:[A-Za-z0-9_\-]{30,}$') { Dire "  Ca ne ressemble pas a un jeton de BotFather (chiffres, deux-points, lettres). Recommence." "Yellow"; continue }
    $r = Telegram $jeton "getMe"
    if ($r.ok) { $bot = $r.result } else { Dire "  Telegram refuse ce jeton. Verifie que tu l'as copie en entier." "Yellow" }
}
if (-not $bot) { Dire "Telegram n'est pas branche. Tu pourras relancer brancher_telegram.bat." "Yellow"; exit 2 }
Dire "  Bot reconnu : @$($bot.username)" "Green"

Dire ""
Dire "MAINTENANT : dans Telegram, ouvre  @$($bot.username)  et ecris-lui  salut" "Green"
Dire "  (j'attends ton message pendant 3 minutes pour reconnaitre ton compte)"
$chat = $null
$fin = (Get-Date).AddMinutes(3)
$nettoye = $false
while (-not $chat -and (Get-Date) -lt $fin) {
    $r = Telegram $jeton "getUpdates?timeout=20&allowed_updates=%5B%22message%22%5D" 40
    if (-not $r.ok) {
        if ($r.code -eq 409 -and -not $nettoye) {
            # un ancien branchement tient encore le bot : on le libere (n8n le reprendra au prochain lancement d'Archi)
            Telegram $jeton "deleteWebhook" | Out-Null
            $nettoye = $true
        } else { Start-Sleep -Seconds 3 }
        continue
    }
    $m = @($r.result | Where-Object { $_.message -and $_.message.chat.type -eq "private" }) | Select-Object -Last 1
    if ($m) { $chat = $m.message.chat }
}
if (-not $chat) { Dire "Je n'ai pas vu ton message. Relance brancher_telegram.bat quand tu veux." "Yellow"; exit 2 }
$nom = ("$($chat.first_name) $($chat.last_name)").Trim() -replace '[^\p{L}\p{N} \-]', ''
$r = Read-Host "  Message recu de : $nom. C'est bien toi ? [O/n]"
if ($r -and -not $r.Trim().ToLower().StartsWith("o")) { Dire "D'accord, rien n'est change." "Yellow"; exit 2 }

ReglerEnv "TELEGRAM_BOT_TOKEN" $jeton -Forcer
ReglerEnv "ARCHI_TELEGRAM_CHAT_ID" "$($chat.id)" -Forcer
$jeton = ""
Dire "  Telegram est note dans le .env : seul ton compte sera ecoute." "Green"
if ($DansInstallation) { exit 0 }

# hors installation : on met n8n a jour tout de suite (il doit etre arrete pendant l'import)
ChargerEnv | Out-Null
$port = if ($env:N8N_PORT) { [int]$env:N8N_PORT } else { 5678 }
while (-not (PortLibre $port)) {
    Read-Host "Archi tourne encore : ferme sa fenetre (celle de n8n), puis appuie sur Entree" | Out-Null
}
$py = if ($env:ARCHI_PY -and (Test-Path $env:ARCHI_PY)) { $env:ARCHI_PY } else { "python" }
Dire "Mise a jour de n8n (1 a 2 minutes)..."
foreach ($script in @("creer_identifiants.py", "importer_workflows.py")) {
    $r = Lancer $py @("-I", (Join-Path $Depot "n8n\$script")) 900 -Points
    ($r.sortie -split "`r?`n") | Where-Object { $_.Trim() } | ForEach-Object { Dire "  $_" }
}
Dire ""
Dire "C'est branche. Relance Archi (raccourci du Bureau), puis ecris a @$($bot.username)." "Green"
