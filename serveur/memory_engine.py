import json
import os
from reglages import chemin

MEMORY_FILE = chemin("memoire_expediteurs.json")


def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}


def save_memory(memory):
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=4, ensure_ascii=False)


def update_contact(sender, priority):
    memory = load_memory()

    if sender not in memory:
        memory[sender] = {
            "interactions": 0,
            "avg_priority": 0
        }

    n = memory[sender]["interactions"]
    old_avg = memory[sender]["avg_priority"]

    memory[sender]["interactions"] = n + 1
    memory[sender]["avg_priority"] = (old_avg * n + priority) / (n + 1)

    save_memory(memory)