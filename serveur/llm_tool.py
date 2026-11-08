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
        "max_tokens": 500,
        "top_p": 0.9,
    }

    response = requests.post(LM_STUDIO_URL, json=payload, timeout=300)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]