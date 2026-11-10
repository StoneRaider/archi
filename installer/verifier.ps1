# verifier.ps1 - controle qu'Archi marche vraiment sur ce PC, de bout en bout. Lance par verifier_archi.bat,
# pendant qu'Archi tourne. Ecrit un rapport dans donnees\etat\verification.txt. Aucune cle n'est affichee ni ecrite.
# ASCII seulement.
param([string]$Depot = (Split-Path -Parent $PSScriptRoot), [switch]$SansQuestion)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
$ENVF = Join-Path $Depot ".env"
. (Join-Path $PSScriptRoot "commun.ps1")
if (-not (Test-Path $ENVF)) { Dire "Pas de fichier .env dans $Depot : lance d'abord installation.bat." "Red"; exit 1 }
ChargerEnv | Out-Null
$pN8n = if ($env:N8N_PORT) { [int]$env:N8N_PORT } else { 5678 }
$pPortail = if ($env:ARCHI_PORTAIL_PORT) { [int]$env:ARCHI_PORTAIL_PORT } else { 5680 }
$pPorte = if ($env:ARCHI_PORTE_PORT) { [int]$env:ARCHI_PORTE_PORT } else { $pPortail + 1 }
$portail = "http://127.0.0.1:$pPortail"
$porte = "http://127.0.0.1:$pPorte"
$maison = @{ "X-Archi-Portail" = "1" }
$rapport = New-Object System.Collections.Generic.List[string]
$script:rates = 0

function Controle([string]$nom, [bool]$ok, [string]$detail = "") {
    $ligne = $(if ($ok) { "OK    " } else { "ECHEC " }) + $nom + $(if ($detail) { " : $detail" } else { "" })
    $rapport.Add($ligne) | Out-Null
    Dire ("  " + $ligne) $(if ($ok) { "Green" } else { "Red" })
    if (-not $ok) { $script:rates++ }
}
# code HTTP d'une demande (0 si le serveur ne repond pas)
function Code([string]$url, [string]$methode = "GET", [hashtable]$entetes = @{}, [string]$corps = $null) {
    try {
        $p = @{ Uri = $url; Method = $methode; Headers = $entetes; UseBasicParsing = $true; TimeoutSec = 20 }
        if ($corps) { $p.Body = $corps; $p.ContentType = "application/json" }
        return [int](Invoke-WebRequest @p).StatusCode
    } catch { try { return [int]$_.Exception.Response.StatusCode } catch { return 0 } }
}

Titre "1. Ce qui est installe"
$prog = Join-Path $Depot "programmes"
foreach ($x in @(@("Python prive", "python\venv\Scripts\python.exe"), @("n8n prive", "n8n\node_modules\n8n\bin\n8n"), @("tunnel", "cloudflared\cloudflared.exe"))) {
    Controle $x[0] (Test-Path (Join-Path $prog $x[1]))
}
Controle "Node.js prive" ([bool](Get-ChildItem (Join-Path $prog "node") -Recurse -Filter node.exe -File -ErrorAction SilentlyContinue | Select-Object -First 1))
Controle "cle de l'appli (16 caracteres ou plus, jamais affichee)" ("$env:ARCHI_CLE_TELEPHONE".Length -ge 16)
Controle "chateau (memoire)" (Test-Path (Join-Path $env:ARCHI_BASE "memoire"))
$voixVoulue = ($env:ARCHI_VOIX -ne "non")
if ($voixVoulue) {
    Controle "oreille : whisper.cpp et son modele" (("$env:ARCHI_WHISPER_EXE" -ne "") -and (Test-Path "$env:ARCHI_WHISPER_EXE") -and ("$env:ARCHI_WHISPER_MODELE" -ne "") -and (Test-Path "$env:ARCHI_WHISPER_MODELE"))
    Controle "parole : Pocket TTS" ([bool](Get-ChildItem (Join-Path $prog "voix") -Recurse -Filter pocket-tts.exe -File -ErrorAction SilentlyContinue | Select-Object -First 1))
} else { $rapport.Add("      Voix : coupee (ARCHI_VOIX=non dans .env)") | Out-Null }

Titre "2. Ce qui tourne"
$modeles = @()
try { $modeles = @((Invoke-RestMethod -Uri "$($env:ARCHI_LM_URL.TrimEnd('/'))/models" -TimeoutSec 5).data | ForEach-Object { $_.id }) } catch {}
Controle "LM Studio repond" ($modeles.Count -gt 0) "$($modeles.Count) modeles"
Controle "modele du cerveau present" ($modeles -contains $env:ARCHI_MODELE) $env:ARCHI_MODELE
Controle "modele de vision present" ($modeles -contains $env:ARCHI_MODELE_VISION) $env:ARCHI_MODELE_VISION
Controle "n8n repond" ((Code "http://127.0.0.1:$pN8n/healthz") -eq 200) "port $pN8n"
$etat = $null
try { $etat = Invoke-RestMethod -Uri "$portail/api/etat" -Headers $maison -TimeoutSec 10 } catch {}
Controle "page d'accueil (portail)" ([bool]$etat) $portail
if ($voixVoulue) {
    $pVoix = if ($env:ARCHI_VOIX_PORT -match '^\d+$') { [int]$env:ARCHI_VOIX_PORT } else { 5683 }
    Controle "la voix repond (Pocket TTS)" ((Code "http://127.0.0.1:$pVoix/") -eq 200) "127.0.0.1:$pVoix"
    # la boucle complete, sans micro : la voix dit une phrase temoin, l'oreille la reecoute
    $b = $null
    try {
        $nodeExe = Get-ChildItem (Join-Path $prog "node") -Recurse -Filter node.exe -File -ErrorAction SilentlyContinue | Select-Object -First 1
        $nodeExe = if ($nodeExe) { $nodeExe.FullName } else { "node" }
        try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
        $sortie = '{"action":"boucle"}' | & $nodeExe (Join-Path $Depot "core\voix.js")
        $b = @($sortie | Where-Object { "$_".Trim().StartsWith("{") }) | Select-Object -Last 1 | ConvertFrom-Json
    } catch {}
    $detail = if ($b -and $b.entendu) { "entendu : $($b.entendu) (parole $($b.ms_parole) ms, oreille $($b.ms_oreille) ms)" } elseif ($b) { "$($b.etape) : $($b.raison) $($b.detail)" } else { "pas de reponse" }
    Controle "voix puis oreille : Archi comprend ce qu'il dit" ([bool]($b -and $b.ok)) $detail
}
if ($etat) {
    Controle "outils maison au registre" ($etat.outils.Count -gt 0) "$($etat.outils.Count) outils"
    Controle "adresse HTTPS du telephone" ([bool]$etat.adresse_publique) $(if ($etat.adresse_publique) { $etat.adresse_publique } else { "pas de tunnel (le PC marche seul)" })
    Controle "appli Android prete a telecharger" ([bool]$etat.apk)
    $rapport.Add("      Telegram : " + $(if ($etat.telegram) { "branche" } else { "pas branche (en option : brancher_telegram.bat)" })) | Out-Null
    # ou en est le telephone : la porte note l'heure de chaque etape (information, pas un controle)
    $tl = $etat.telephone
    if ($tl) {
        $age = { param($t) "il y a " + [int](($tl.maintenant - $t) / 1000) + " s" }
        $ou = if ($tl.appli) { "appli branchee, dernier signe " + (& $age $tl.appli) }
              elseif ($tl.apk) { "appli telechargee " + (& $age $tl.apk) + ", pas encore branchee (touche 'Brancher l'appli' sur la page du telephone)" }
              elseif ($tl.page) { "page ouverte " + (& $age $tl.page) + ", appli pas encore telechargee" }
              else { "pas encore vu (scanne le QR code de la page d'accueil)" }
        $rapport.Add("      Telephone : $ou") | Out-Null
    }
}

Titre "3. Ce qui sort du PC (liste blanche du portail)"
Controle "la page d'accueil refuse un appel sans l'en-tete maison" ((Code "$portail/api/etat") -eq 403)
Controle "une autre page web ne peut pas parler a Archi" ((Code "$portail/api/message" "POST" @{ "X-Archi-Portail" = "1"; "Origin" = "https://exemple.invalid" } '{"texte":"x"}') -eq 403)
Controle "la page d'accueil n'existe pas pour un relais" ((Code "$portail/" "GET" @{ "X-Forwarded-For" = "203.0.113.9" }) -eq 404)
# la porte du telephone (la cible du tunnel), essayee ici directement : seule la liste blanche repond
Controle "porte du telephone : ni page d'accueil, ni etat, ni n8n" (((Code "$porte/") -eq 404) -and ((Code "$porte/api/etat" "GET" $maison) -eq 404) -and ((Code "$porte/rest/login") -eq 404) -and ((Code "$porte/healthz") -eq 404))
Controle "porte du telephone : un message sans la cle est refuse" ((Code "$porte/webhook/telephone-archi" "POST" @{} '{"texte":"x"}') -eq 403)
Controle "porte du telephone : un faux message Telegram est refuse" ((Code "$porte/webhook/ArchiDemo0000001/telegram/webhook" "POST" @{ "X-Telegram-Bot-Api-Secret-Token" = "x" } '{}') -eq 404)
Controle "porte du telephone : avec la cle, la boite repond" ((Code "$porte/webhook/telephone-boite" "POST" @{ "x-archi-cle" = $env:ARCHI_CLE_TELEPHONE } '{}') -eq 200)
Controle "porte du telephone : la page d'installation s'ouvre" ((Code "$porte/telephone") -eq 200)
if ($etat -and $etat.adresse_publique) {
    $pub = $etat.adresse_publique
    # l'adresse vient d'etre creee : on laisse a Internet le temps de la connaitre
    $vu = 0
    for ($i = 0; $i -lt 12 -and $vu -ne 200; $i++) { $vu = Code "$pub/telephone"; if ($vu -ne 200) { Start-Sleep -Seconds 5 } }
    Controle "Internet : la page du telephone s'ouvre" ($vu -eq 200)
    Controle "Internet : la page d'accueil est invisible" ((Code "$pub/") -eq 404)
    Controle "Internet : l'editeur et l'API de n8n sont invisibles" (((Code "$pub/rest/login") -eq 404) -and ((Code "$pub/healthz") -eq 404) -and ((Code "$pub/api/etat" "GET" $maison) -eq 404))
    Controle "Internet : un message sans la cle est refuse" ((Code "$pub/webhook/telephone-archi" "POST" @{} '{"texte":"x"}') -eq 403)
    Controle "Internet : un message avec la cle passe" ((Code "$pub/webhook/telephone-boite" "POST" @{ "x-archi-cle" = $env:ARCHI_CLE_TELEPHONE } '{}') -eq 200)
} else { $rapport.Add("      (pas d'adresse publique : controles Internet sautes)") | Out-Null }

if (-not $SansQuestion) {
    Titre "4. Une vraie question a Archi (le modele repond sur ta carte graphique)"
    $debut = Get-Date
    $texte = ""
    try {
        $r = Invoke-RestMethod -Uri "$portail/api/message" -Method Post -Headers $maison -ContentType "application/json" `
            -Body ([System.Text.Encoding]::UTF8.GetBytes('{"texte":"Quels outils as-tu ? Cite-en trois, en une phrase."}')) -TimeoutSec 600
        $texte = "$($r.texte)"
    } catch {}
    $duree = [int]((Get-Date) - $debut).TotalSeconds
    Controle "Archi repond" ($texte.Length -gt 10) "$duree s"
    if ($texte) {
        $court = ($texte -replace "\s+", " ")
        if ($court.Length -gt 300) { $court = $court.Substring(0, 300) + "..." }
        $rapport.Add("      Reponse : $court") | Out-Null
        Dire "      $court"
    }
}

$rapport.Insert(0, "Verification d'Archi du $(Get-Date -Format 'dd/MM/yyyy HH:mm') : " + $(if ($script:rates) { "$($script:rates) echec(s)" } else { "tout est bon" }))
$sortie = Join-Path $Depot "donnees\etat"
New-Item -ItemType Directory -Force $sortie | Out-Null
[System.IO.File]::WriteAllLines((Join-Path $sortie "verification.txt"), $rapport, (New-Object System.Text.UTF8Encoding($false)))
Dire ""
if ($script:rates) { Dire "$($script:rates) controle(s) en echec. Le rapport est dans donnees\etat\verification.txt" "Yellow"; exit 2 }
Dire "Tout est bon. Le rapport est dans donnees\etat\verification.txt" "Green"
