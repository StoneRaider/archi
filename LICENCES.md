# Licences

## Le code d'Archi : PolyForm Noncommercial 1.0.0

Le code de ce dépôt (scripts, workflows n8n, appli Android, portail, installateur, documentation) est publié sous
la licence **PolyForm Noncommercial 1.0.0** : texte complet dans [LICENSE](LICENSE).

En clair (le texte de la licence fait foi) :

- **Permis** : l'utiliser, l'étudier, le modifier et le partager pour un usage personnel, pour un loisir, pour la
  recherche, l'enseignement, ou au sein d'une association, d'une école ou d'un service public.
- **Pas permis** : tout usage commercial (le vendre, l'intégrer à un produit ou un service payant, s'en servir dans une
  entreprise pour gagner de l'argent) sans autorisation écrite.
- **En le partageant** : garder ce texte de licence (ou son adresse) et la ligne `Required Notice:` du fichier LICENSE.

**Usage commercial : me contacter** (StoneRaider), par l'onglet « Issues » de la page GitHub du projet.
Une licence commerciale peut être discutée au cas par cas.

## Les briques des autres

Archi s'appuie sur des logiciels écrits par d'autres. Ils gardent **leur propre licence**, que PolyForm ne remplace pas.
La plupart ne sont pas dans ce dépôt : l'installateur les télécharge depuis leur source officielle.

| Brique | Rôle dans Archi | Licence | Où |
|---|---|---|---|
| n8n 1.x | les workflows (cerveau du circuit) | Sustainable Use License (n8n GmbH) : usage interne et personnel permis, revente comme service interdite | téléchargé par l'installateur (npm) |
| Node.js | fait tourner n8n et le portail | MIT | téléchargé par l'installateur |
| uv (Astral) | installe Python et ses bibliothèques | MIT ou Apache 2.0 | téléchargé par l'installateur |
| Python | les outils maison | PSF License | installé par uv |
| FFmpeg (version « essentials » de GyanD) | lire et convertir le son et la vidéo | GPL v3 | téléchargé par l'installateur, jamais modifié |
| LM Studio | sert le modèle de langage sur le PC | conditions d'utilisation de LM Studio (lmstudio.ai) | installé par winget ou par l'utilisateur |
| gpt-oss-20b | le modèle de langage local | Apache 2.0 (OpenAI) | téléchargé par LM Studio |
| whisper.cpp et modèle Whisper | l'oreille (voix vers texte) | MIT | téléchargés par l'installateur |
| Pocket TTS (Kyutai) | la voix (texte vers voix) | licence dans son dossier ; licence de chaque voix sur la page `kyutai/tts-voices` de Hugging Face | téléchargé par l'installateur |
| cloudflared | le tunnel pour le téléphone | Apache 2.0 | téléchargé par l'installateur |
| Polices Fraunces, Nunito, Cinzel, Cormorant, Michroma, Orbitron | l'affichage du portail | SIL Open Font License 1.1 | dans `portail/polices/`, avec leur texte de licence (`OFL-*.txt`) |
| Bibliothèques Python (FastAPI, Uvicorn, Pydantic, Requests, ReportLab, Pillow, pypdfium2, yt-dlp, Google API) | serveur et outils | leurs licences respectives (MIT, BSD, Apache 2.0, Unlicense…) | téléchargées par pip (`requirements.txt`) |
| Bibliothèques Android (AndroidX, Gradle) | l'appli téléphone | Apache 2.0 | téléchargées par Gradle à la fabrication de l'APK |

Si tu redistribues Archi avec l'une de ces briques incluse, respecte aussi sa licence.
