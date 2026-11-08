# Matériel : ce qu'on a et ce qu'on viserait

## Aujourd'hui
Archi tourne sur un PC de bureau avec une **AMD Radeon RX 9070 (16 Go)**, LM Studio (Vulkan) et gpt-oss-20b.
Le modèle de vision (Gemma ; dans ma version, un 26B quantifié, dans la démo un 12B) et la reconnaissance
vocale (Whisper) doivent **se partager les 16 Go**. Résultat : on charge et décharge les modèles à tour de rôle,
l'analyse d'une photo sur le terrain attend que le bon modèle soit chargé, et le contexte reste court.

## Avec plus de mémoire vidéo (32 Go)
- gpt-oss-20b et le modèle de vision **chargés en même temps** : plus d'attente de chargement entre la photo et la réponse ;
- un contexte de 64k jetons : plus de château relu à chaque message, moins d'oublis ;
- de quoi essayer un modèle plus gros pour le raisonnement, ou un affinage léger (LoRA) sur mes propres conversations validées.

