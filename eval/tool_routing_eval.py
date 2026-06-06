# TASK 6 EXTENSION (§C): offline eval for the pgvector tool router.
"""
Measures how well the pgvector tool router surfaces the correct tool, using a
labelled test set (eval/routing_testset.json).

Reported metrics (deterministic — depend only on the embedding + DB, not on the
LLM's sampling):
  - top-1 accuracy : the single most-similar tool is the expected one
  - recall@k       : the expected tool appears in the top-k candidates

This is the "testing evidence" for the router: it shows the candidate set handed
to the LLM almost always contains the right tool, which is what fixes small-model
mis-routing (e.g. policy/RAG questions that the 1B model otherwise ignores).

Usage (after docker compose up -d + python skeleton/seed_tool_router.py):
    python eval/tool_routing_eval.py
"""

import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_DIR)

from skeleton.llm_provider import llm
from databases.relational.queries import query_tool_candidates

TOP_K = 4


def load_testset():
    with open(os.path.join(SCRIPT_DIR, "routing_testset.json"), encoding="utf-8") as f:
        return json.load(f)


def main():
    cases = load_testset()
    top1_hits = 0
    recall_hits = 0

    print(f"Tool router eval — {len(cases)} cases, top_k={TOP_K}\n")
    print(f"{'expected':<32} {'top-1':<32} hit  in@k")
    print("-" * 78)

    for c in cases:
        emb = llm.embed(c["query"])
        cands = query_tool_candidates(emb, TOP_K)
        names = [x["name"] for x in cands]
        top1 = names[0] if names else "(none)"
        is_top1 = top1 == c["expected"]
        in_k = c["expected"] in names
        top1_hits += int(is_top1)
        recall_hits += int(in_k)
        print(f"{c['expected']:<32} {top1:<32} {'✓' if is_top1 else '✗'}    {'✓' if in_k else '✗'}")

    n = len(cases)
    print("-" * 78)
    print(f"top-1 accuracy : {top1_hits}/{n} = {top1_hits / n:.0%}")
    print(f"recall@{TOP_K}      : {recall_hits}/{n} = {recall_hits / n:.0%}")


if __name__ == "__main__":
    main()
