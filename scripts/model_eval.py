"""D.2: LLM model evaluation for the Reforger-LLM-Squad bridge.

Measures the metrics that matter for AI soldier thoughts on the LAN proxy:
  - valid-JSON rate   (extract_json_block returns a dict — rules 37/40/59)
  - thought rate      (dict has a non-empty "thought" string)
  - tool-call rate    (dict has a "tool" block — F8.3 agent actions)
  - mood-valid rate   (mood in the known set)
  - parrot rate       (exact-duplicate thoughts across samples)
  - latency           (avg seconds; first call = cold model load)

Uses the SAME prompt template (AI_THOUGHT_SYSTEM_PROMPT_SOLO) and the SAME
JSON parser (extract_json_block) as the bridge, so the numbers reflect what
the bridge would actually produce. No game client needed.

Usage:
  python_bridge\venv\Scripts\python.exe scripts\model_eval.py
  python_bridge\venv\Scripts\python.exe scripts\model_eval.py --models llama3.2-3b,phi4 --samples 8
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python_bridge"))
import main as bridge  # noqa: E402  (reuses extract_json_block + prompt template)

MODEL_ALIASES = {
    "llama3.2-3b": "llama3.2-3b",                    # baseline (current)
    "ministral": "Ministral-3-14B-Reasoning-2512",   # 14B candidate
    "phi4": "phi4",                                  # Phi-4-reasoning-plus, 14B candidate
    "gemma4-12b": "gemma4-12b",                      # 12B candidate
    "gemma4-12b-gpu1": "gemma4-12b-gpu1",            # 12B qat q4_0 GPU1 candidate
    "llama3": "llama3",                              # 8B candidate
}

DEFAULT_MODELS = ["llama3.2-3b", "ministral", "phi4", "gemma4-12b-gpu1"]

VALID_MOODS = {"alert", "bored", "nervous", "confident", "annoyed", "scared", "calm", "excited"}

# Realistic situations, rotated across samples (same situations for every
# model so results are comparable). Mirror the bridge's per-soldier turns.
SITUATIONS = [
    # contact
    ("SITUATION: 3 hostiles spotted 200m east, advancing toward our position. "
     "Squadmate chatter: Alpha_2: \"Contact! 3 hostiles east, 200 meters!\"",
     "event: contact"),
    # idle patrol
    ("SITUATION: Quiet patrol along the treeline. No contacts. Squadmate chatter: "
     "Alpha_3: \"Radio check, all quiet out here.\"",
     "event: idle"),
    # order change
    ("SITUATION: CO ordered the squad to move to grid 045-122, formation Wedge. "
     "Squadmate chatter: Alpha_1: \"Moving out, Wedge formation.\"",
     "event: order_change"),
    # casualty
    ("SITUATION: Alpha_3 is DOWN, medic called. Squadmate chatter: Alpha_4: "
     "\"Alpha_3 is hit! Medic!\". Your last action's result: MEDIC order queued.",
     "event: casualty"),
    # leader down
    ("SITUATION: The CO (squad leader) is DOWN! Squadmate chatter: Alpha_2: "
     "\"CO is down! We need to cover him!\"",
     "event: leader_downed"),
]

IDENTITY_SAMPLE = {
    "identity": "SPC Alpha_1",
    "backstory": "Three deployments, survived two ambushes. From Texas.",
    "personality": "VETERAN",
    "personality_desc": "calm, experienced, tactical observations",
}


def build_prompt(situation: str):
    system = bridge.AI_THOUGHT_SYSTEM_PROMPT_SOLO.format(**IDENTITY_SAMPLE)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": situation},
    ]


def evaluate_model(client, model: str, samples: int, max_tokens: int) -> dict:
    valid = 0
    with_thought = 0
    with_tool = 0
    mood_valid = 0
    seen_thoughts = set()
    parrots = 0
    latencies = []
    completion_tokens = []
    errors = 0
    sample_thoughts = []

    for i in range(samples):
        situation, _tag = SITUATIONS[i % len(SITUATIONS)]
        messages = build_prompt(situation)
        t0 = time.time()
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.7,
                response_format={"type": "json_object"},
            )
        except Exception as e:  # noqa: BLE001 - report any proxy failure
            errors += 1
            latencies.append(time.time() - t0)
            print(f"    [ERROR] {model} sample {i}: {type(e).__name__}: {e}")
            continue
        dt = time.time() - t0
        latencies.append(dt)
        content = (resp.choices[0].message.content or "") if resp.choices else ""
        usage = resp.usage
        if usage and getattr(usage, "completion_tokens", None):
            completion_tokens.append(usage.completion_tokens)

        data = bridge.extract_json_block(content)
        if data is not None:
            valid += 1
        thought = (data or {}).get("thought") if isinstance(data, dict) else None
        if isinstance(thought, str) and thought.strip():
            with_thought += 1
            key = thought.strip().lower()
            if key in seen_thoughts:
                parrots += 1
            seen_thoughts.add(key)
            sample_thoughts.append(thought.strip())
        tool = (data or {}).get("tool") if isinstance(data, dict) else None
        if isinstance(tool, dict) and tool.get("name"):
            with_tool += 1
        mood = (data or {}).get("mood") if isinstance(data, dict) else None
        if mood in VALID_MOODS:
            mood_valid += 1

    n = max(1, samples - errors)
    return {
        "model": model,
        "samples": samples,
        "errors": errors,
        "valid_json_rate": round(valid / n, 3),
        "thought_rate": round(with_thought / n, 3),
        "tool_rate": round(with_tool / n, 3),
        "mood_valid_rate": round(mood_valid / n, 3),
        "parrot_rate": round(parrots / n, 3),
        "avg_latency_s": round(sum(latencies) / max(1, len(latencies)), 2),
        "cold_start_s": round(latencies[0], 2) if latencies else None,
        "avg_completion_tokens": round(sum(completion_tokens) / max(1, len(completion_tokens)), 1) if completion_tokens else None,
        "samples_with_tools": [t for t in sample_thoughts if t],
    }


def main():
    ap = argparse.ArgumentParser(description="D.2: evaluate LLM models for soldier thoughts")
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS),
                    help="comma-separated model names or aliases")
    ap.add_argument("--samples", type=int, default=6, help="samples per model")
    ap.add_argument("--max-tokens", type=int, default=600, help="max_tokens (rule 39: keep high)")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "model_eval_results.json"))
    args = ap.parse_args()

    models = []
    for m in args.models.split(","):
        m = m.strip()
        models.append(MODEL_ALIASES.get(m, m))
    if not models:
        print("no models given")
        sys.exit(1)

    client = bridge.OpenAI(
        base_url=bridge.CONFIG["llm"]["base_url"],
        api_key=bridge.CONFIG["llm"]["api_key"],
        timeout=120.0,  # cold model load can be slow
    )

    # Rule 41: ASCII only in console output (cp1252 crashes on unicode)
    print(f"D.2 model evaluation - {len(models)} model(s), {args.samples} samples each, "
          f"proxy {bridge.CONFIG['llm']['base_url']}\n")
    results = []
    for model in models:
        print(f"== {model} ==")
        r = evaluate_model(client, model, args.samples, args.max_tokens)
        results.append(r)
        print(f"   valid_json={r['valid_json_rate']}  thought={r['thought_rate']}  "
              f"tool={r['tool_rate']}  mood={r['mood_valid_rate']}  "
              f"parrot={r['parrot_rate']}  avg={r['avg_latency_s']}s  "
              f"cold={r['cold_start_s']}s  tokens={r['avg_completion_tokens']}\n")

    print("-- Summary --")
    header = f"{'model':<32}{'valid':>7}{'thought':>9}{'tool':>7}{'mood':>7}{'parrot':>8}{'avg_s':>8}{'cold_s':>8}"
    print(header)
    for r in results:
        print(f"{r['model']:<32}{r['valid_json_rate']:>7}{r['thought_rate']:>9}"
              f"{r['tool_rate']:>7}{r['mood_valid_rate']:>7}{r['parrot_rate']:>8}"
              f"{r['avg_latency_s']:>8}{str(r['cold_start_s']):>8}")

    out_path = Path(args.out)
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nresults saved to {out_path}")


if __name__ == "__main__":
    main()
