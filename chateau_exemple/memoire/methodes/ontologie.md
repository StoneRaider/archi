---
type: methode
piece: methodes
statut: reference
maj: 2026-11-12
alias: []
resume: "La liste fermée des sortes de fiches et des liens permis dans le château."
---

# 🧭 Ontologie du château

Pièce [[Méthodes]] du [[Château]]. À lire avant toute écriture, avec [[memoire]].

## À quoi ça sert
La liste FERMÉE des sortes de fiches et des sortes de liens. Sans elle, chaque écriture invente ses propres fiches et ses
propres liens, le château se remplit de doublons et Archi finit par s'y perdre. Elle est décidée par l'utilisateur.

## Les sortes de fiches (une pièce chacune)
| Sorte | Pièce |
|---|---|
| moi | moi |
| personne, animal, groupe | personnes |
| lieu | lieux |
| projet | projets |
| passion | passions |
| travail, client | travail |
| préférence | preferences |
| leçon | lecons |
| méthode | methodes |
| sujet (savoir) | bibliotheque |

## Les liens permis
On écrit un lien dans la rubrique **Liens :** sous la forme `- relation :: [[fiche]] (précision libre)`.
Le double deux-points permet à Obsidian de lire le lien comme une étiquette.

| Relation | De → vers |
|---|---|
| famille | personne → personne |
| ami | personne → personne |
| couple | personne → personne |
| animal | personne → animal |
| membre_de | personne → groupe ou projet |
| habite | personne → lieu |
| situe_a | projet, chose → lieu |
| participe | personne → projet |
| client | projet → personne ou entreprise |
| fait_partie_de | fiche → fiche plus grande (chaque fiche → l'index de sa pièce) |
| utilise | projet → méthode ou outil |
| voir_aussi | fiche → fiche, en dernier recours |

Une relation qui manque : on met `voir_aussi`, et l'utilisateur tranche.

## Liens
- fait_partie_de :: [[Méthodes]]
- utilise :: [[memoire]]
