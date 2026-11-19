import re

import requests
from reglages import LM_URL as LM_STUDIO_URL, MODELE, UTILISATEUR


def ask_llm(prompt: str) -> str:
    payload = {
        "model": MODELE,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Tu es Archi, assistant exécutif personnel de " + UTILISATEUR + ". "
                    "Tu es stratégique, structuré, synthétique et orienté action. "
                    "Tu classes les priorités clairement. "
                    "Tu proposes des réponses professionnelles. "
                    "Tu demandes validation explicite avant toute action automatique."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 2000,   # le modele reflechit avant d'ecrire : avec 500, Qwythos 9B rendait des reponses vides (banc du 19/11 : 5/5 avec 2000)
        "top_p": 0.9,
    }

    response = requests.post(LM_STUDIO_URL, json=payload, timeout=300)
    response.raise_for_status()
    texte = response.json()["choices"][0]["message"].get("content") or ""
    return re.sub(r"(?s)<think>.*?</think>", "", texte).strip()   # une reflexion laissee dans le texte n'est pas la reponse