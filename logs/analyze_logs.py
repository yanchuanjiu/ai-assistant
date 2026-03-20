import json
from collections import Counter

records = []
with open('/root/ai-assistant/logs/interactions.jsonl') as f:
    for line in f:
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except Exception as e:
                print("parse error:", e)

total = len(records)
corrections = [r for r in records if r.get('has_correction') == True]
high_latency = [r for r in records if r.get('latency_ms', 0) > 8000]

tool_counts = Counter()
for r in records:
    for t in (r.get('tools_used') or []):
        tool_counts[t] += 1

print(f"Total: {total}")
print(f"Corrections: {len(corrections)} ({len(corrections)/total*100:.1f}%)")
print(f"High latency >8s: {len(high_latency)}")
print(f"Top tools:")
for t, c in tool_counts.most_common(10):
    print(f"  {t}: {c}")

print(f"Correction contexts:")
for r in corrections:
    print(f"  [{r.get('ts','')}] {r.get('user_message','')[:150]}")

latencies = [r.get('latency_ms', 0) for r in records if r.get('latency_ms')]
if latencies:
    avg_lat = sum(latencies) / len(latencies)
    print(f"Avg latency: {avg_lat:.0f}ms, max: {max(latencies)}ms")

print("\nRecent 5 records:")
for r in records[-5:]:
    print(f"  [{r.get('ts','')}] correction={r.get('has_correction')} latency={r.get('latency_ms',0)}ms")
    print(f"    msg: {r.get('user_message','')[:100]}")
