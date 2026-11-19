# Matériel : ce qu'on a et ce qu'on viserait

## Aujourd'hui
Archi tourne sur un PC de bureau avec une **AMD Radeon RX 9070 (16 Go)**, LM Studio (Vulkan) et Qwythos 9B (6,5 Go).
Ce modèle raisonne, écrit et décrit les photos : il reste seul chargé, donc une photo n'attend aucun chargement.
La reconnaissance vocale (Whisper) tourne sur le processeur. Ce qui reste limité : le contexte (16k jetons)
et la taille du modèle, choisi petit pour répondre vite.

## Avec plus de mémoire vidéo (32 Go)
- un modèle plus gros pour le raisonnement, **sans perdre la réactivité** d'aujourd'hui ;
- un contexte de 64k jetons : plus de château relu à chaque message, moins d'oublis ;
- de quoi essayer un modèle plus gros pour le raisonnement, ou un affinage léger (LoRA) sur mes propres conversations validées.

