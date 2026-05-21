from collections import Counter
from typing import Any


def rank_pr(pr: dict[str, Any], keywords: list[str]) -> dict[str, Any]:
    text_parts = [
        pr.get("title", ""),
        pr.get("body", ""),
        " ".join(pr.get("labels", [])),
        " ".join(pr.get("changed_files", [])),
    ]
    text = "\n".join(text_parts).lower()
    matches = Counter()
    for keyword in keywords:
        key = keyword.lower()
        if key and key in text:
            matches[key] += text.count(key)

    file_bonus = 0
    for filename in pr.get("changed_files", []):
        lowered = filename.lower()
        if any(part in lowered for part in ("memory", "mem", "context", "retrieval", "embedding")):
            file_bonus += 2

    score = sum(matches.values()) + file_bonus
    if score >= 4:
        relevance = "high"
    elif score >= 2:
        relevance = "medium"
    elif score >= 1:
        relevance = "low"
    else:
        relevance = "none"

    ranked = dict(pr)
    ranked["score"] = score
    ranked["relevance"] = relevance
    ranked["matched_keywords"] = sorted(matches)
    return ranked


def rank_all(prs: list[dict[str, Any]], keywords: list[str]) -> list[dict[str, Any]]:
    ranked = [rank_pr(pr, keywords) for pr in prs]
    return sorted(ranked, key=lambda item: (item["score"], item.get("merged_at", "")), reverse=True)
