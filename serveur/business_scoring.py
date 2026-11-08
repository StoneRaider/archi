def compute_business_score(priority, sender_memory):

    score = priority * 10

    if sender_memory:
        score += sender_memory.get("avg_priority", 0) * 5

    return score