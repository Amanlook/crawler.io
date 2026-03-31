"""Check fetch log status."""
with open("/tmp/fetch_virat_all.log") as f:
    lines = f.readlines()
done = any("Done" in l for l in lines)
inserted = [l.strip() for l in lines if "Inserted" in l]
collected = [l.strip() for l in lines if "Collected" in l]
no_more = [l.strip() for l in lines if "No more" in l or "stopping" in l]
last_page = [l.strip() for l in lines if l.strip().startswith("Page")]
print(f"Lines: {len(lines)}, Done: {done}")
if inserted: print(f"DB: {inserted[0]}")
if collected: print(f"  {collected[0]}")
if no_more: print(f"  {no_more[0]}")
if last_page: print(f"  {last_page[-1]}")
