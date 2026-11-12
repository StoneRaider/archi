# Signature de l'appli Android

Android n'accepte une mise a jour d'appli que si elle est signee par **la meme cle** que la version deja installee.
L'appli publiee (page Releases) est donc toujours signee par une seule cle, stable, qui n'est **jamais** dans ce depot.

## Comment c'est fait

- `appli/app/build.gradle` lit la cle dans 4 variables d'environnement :
  `ARCHI_CLE_FICHIER` (chemin du fichier .jks), `ARCHI_CLE_MDP` (mot de passe),
  `ARCHI_CLE_ALIAS` (facultatif, `archi` par defaut), `ARCHI_CLE_MDP_ALIAS` (facultatif, le meme mot de passe par defaut).
- Sur GitHub, le workflow `publication.yml` les remplit a partir de deux **secrets du depot** :
  `ARCHI_CLE_B64` (le fichier .jks encode en base64) et `ARCHI_CLE_MDP`. Le fichier est efface a la fin de l'etape.
- Sans ces variables (une copie du depot chez quelqu'un d'autre), `assembleRelease` signe avec la cle debug
  de la machine : l'appli s'installe et marche, mais ce n'est pas la meme signature que l'appli publiee.

## Empreinte de la cle officielle d'Archi 1.0

Certificat `CN=Archi 1.0, O=Archi`, SHA-256 :
`1e1d8c41733184361ee79269ba4587515bc02dc2c28a5ed5b5eebbff44938542`

Pour verifier un APK telecharge : `apksigner verify --print-certs Archi.apk`.

## Fabriquer soi-meme

```
cd appli
./gradlew assembleRelease
```
L'APK sort dans `appli/app/build/outputs/apk/release/app-release.apk`.
