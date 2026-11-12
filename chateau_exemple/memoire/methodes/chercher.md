---
type: methode
piece: methodes
statut: actif
maj: 2026-11-12
alias: ["recherche", "trouver une fiche", "chercher dans le chateau"]
resume: "Le COMMENT de la recherche : trouver la bonne fiche en lisant le moins possible."
---

# 🔎 Méthode : chercher dans le château

Pièce [[Méthodes]] du [[Château]]. Où est quoi : [[carte_du_chateau]]. Pour écrire : [[memoire]].

## Pourquoi
Plus on remplit le contexte d'un modèle, plus il oublie ce qu'il a lu. On cherche donc PEU, mais JUSTE.

## L'entonnoir (on s'arrête dès qu'on a la réponse)
1. **Les autres noms** : le tableau « alias » de [[carte_du_chateau]] et la ligne `alias` des en-têtes.
2. **Le catalogue** : `catalogue.md`, une ligne par fiche avec son résumé. Il dit QUELLE fiche lire.
3. **L'en-tête et la Synthèse** : le haut de la fiche. Dans la plupart des cas, la réponse est là.
4. **La fiche entière** : seulement si la Synthèse ne répond pas.
5. **L'historique** (`# Historique`) : pour « quand a-t-on décidé… ».

## Pour Archi
- À chaque message, une ligne « CHÂTEAU » arrive dans son profil : la SYNTHÈSE de la fiche la plus probable, puis le nom
  des autres fiches possibles. Il répond d'abord depuis cette Synthèse, sans rien y ajouter.
- Pour plus de détail : outil `memoire`, action `lire`, avec la pièce et le nom de la fiche.
- Rien trouvé : « je ne trouve pas ça dans le château ». On n'invente pas.

## Liens
- fait_partie_de :: [[Méthodes]]
- utilise :: [[carte_du_chateau]]
- voir_aussi :: [[memoire]]
