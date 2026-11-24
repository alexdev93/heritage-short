"""Summarise runs.jsonl and stage timings into tables for COSTS.md.

Usage: python -m pipeline.costs
"""
from __future__ import annotations

import json
from collections import defaultdict

from pipeline import common as C
from pipeline import config


def _read(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def list_price(model: str, usage: dict, gpu_s: float) -> float | None:
    price = config.LIST_PRICES_USD.get(model)
    if not price or price["usd"] is None:
        return None
    unit = price["unit"]
    if unit == "image":
        return price["usd"] * usage.get("images", 0)
    if unit == "1M_tokens":
        tokens = (usage.get("tokens_in") or 0) + (usage.get("tokens_out") or 0)
        return price["usd"] * tokens / 1e6
    if unit == "gpu_hour":
        return price["usd"] * gpu_s / 3600
    return None


def main(argv=None) -> None:
    runs = _read(C.RUNS)
    groups = defaultdict(lambda: {"calls": 0, "ok": 0, "latency": [], "gpu_s": 0.0, "list": 0.0, "priced": True})
    for r in runs:
        g = groups[(r.get("stage"), r.get("model"))]
        g["calls"] += 1
        g["ok"] += r.get("status") == "ok"
        g["latency"].append(r.get("latency_s") or 0)
        gpu = r.get("gpu_s") or 0
        g["gpu_s"] += gpu
        lp = list_price(r.get("model"), r.get("usage") or {}, gpu)
        if lp is None:
            g["priced"] = False
        else:
            g["list"] += lp

    print(f"## Model calls ({C.rel(C.RUNS)}, {len(runs)} lines)\n")
    print("| Stage | Model | Calls | OK | Mean latency (s) | Max latency (s) | GPU min | List-price equivalent (USD) |")
    print("|---|---|---|---|---|---|---|---|")
    for (stage, model), g in sorted(groups.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or "")):
        lat = g["latency"]
        mean = sum(lat) / len(lat) if lat else 0
        price = f"{g['list']:.4f}" if g["priced"] else "set price in config.py"
        print(f"| {stage} | {model} | {g['calls']} | {g['ok']} | {mean:.2f} | {max(lat):.2f} | "
              f"{g['gpu_s'] / 60:.1f} | {price} |")

    times = _read(C.STAGE_TIMES)
    if times:
        agg = defaultdict(list)
        for t in times:
            agg[t["stage"]].append(t["seconds"])
        print(f"\n## Stage wall-clock time ({C.rel(C.STAGE_TIMES)})\n")
        print("| Stage | Runs | Mean (s) | Last (s) |")
        print("|---|---|---|---|")
        for stage, secs in sorted(agg.items()):
            print(f"| {stage} | {len(secs)} | {sum(secs) / len(secs):.1f} | {secs[-1]:.1f} |")


if __name__ == "__main__":
    main()
