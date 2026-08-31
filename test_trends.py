"""Quick test script to verify worldwide trend collection."""
from autoshorts.services.trend_sources import collect_worldwide_trends

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

trends = collect_worldwide_trends()
print(f"\nTotal unique trends collected: {len(trends)}")
print("\nTop 15 by popularity (what Gemini will see first):")
for i, t in enumerate(trends[:15]):
    title = t["title"][:70]
    pop = t["popularity"]
    src = t["source"]
    print(f"  [{i+1:2d}] {title} | pop={pop:.0f} | src={src}")
