#!/usr/bin/env python3
"""gen_connector_catalog.py — regenerate dashboard.html's CONNECTORS block from the engine registry.

The engine's integrations registry (served by the Studio's /api/integrations/list) is the ONLY
source of truth for WHICH connectors exist and their categories. The dashboard catalog is a
PRESENTATION of it — env-key hints, SENSITIVE flags, and aggregator notes are display metadata
merged in here. Hand-editing the CONNECTORS array in dashboard.html is how the 138-vs-137 drift
happened; from now on, edit THIS script (or the registry) and re-run:

    python3 tools/gen_connector_catalog.py [path/to/integrations.json]

Default registry path: assets/integrations_registry.json (a committed snapshot of the engine
registry — refresh it from ~/.railcall/station/.railcall_workspace/integrations.json when the
engine registry changes; it holds no secrets, it is the same data the Integrate tab shows).
"""
import json, re, sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "assets", "integrations_registry.json")
DASH = os.path.join(ROOT, "dashboard.html")

def norm(name):
    """Collapsed form: lowercase, parenthetical stripped, '·' treated as a space."""
    s = re.sub(r"\s*\(.*\)$", "", (name or "")).lower().replace("·", " ")
    return re.sub(r"\s+", " ", s).strip()

def aliases(name):
    """Match keys for a display name: collapsed form + its first word-segment."""
    n = norm(name)
    return {n, n.split(" ")[0]}

# ---- 1 · load the registry (engine truth) with the engine's own dedup rule ----
reg = json.load(open(REG))
seen, cats = set(), []          # cats: [(category, [entry, ...])] in registry order
for cat, items in reg.items():
    rows = []
    for it in (items if isinstance(items, list) else []):
        iid = it.get("id")
        if iid in seen:
            continue
        seen.add(iid)
        rows.append(it)
    if rows:
        cats.append((cat, rows))
total = sum(len(r) for _, r in cats)

# ---- 2 · harvest presentation metadata from the CURRENT dashboard catalog (env, flags, notes) ----
html = open(DASH).read()
m = re.search(r"var CONNECTORS=(\[.*?\n  \]);", html, re.S)
if not m:
    sys.exit("CONNECTORS block not found in dashboard.html")
old = json.loads(m.group(1))
meta = {}                        # alias -> [display, env, flag, note?] (collapsed key wins over bare first-word)
for _cat, items in old:
    for c in items:
        for a in sorted(aliases(c[0]), key=len):   # short alias first, precise alias overwrites
            meta[a] = c

# ---- 3 · build the new catalog: registry decides existence+category, meta decorates ----
out, missing_meta = [], []
for cat, rows in cats:
    entries = []
    for it in rows:
        name = it.get("name") or it.get("id")
        k = norm(name)
        if k in meta:
            c = list(meta[k])
            c[0] = meta[k][0]    # keep the curated display name (short form)
        else:
            missing_meta.append(name)
            c = [re.sub(r"\s*\(.*\)$", "", name), "set in Studio · Integrate"]
        entries.append(c)
    out.append([cat, entries])

# ---- 4 · splice back into dashboard.html ----
new_js = "var CONNECTORS=" + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";"
html = html[: m.start()] + new_js + html[m.end():]
open(DASH, "w").write(html)

reg_keys = set()
for _, rows in cats:
    for it in rows:
        reg_keys |= aliases(it.get("name") or it.get("id"))
dropped = sorted({c[0] for _c, items in old for c in items if not (aliases(c[0]) & reg_keys)})
print(f"regenerated: {total} connectors in {len(cats)} categories (registry: {os.path.basename(REG)})")
if dropped:
    print("dropped (in old catalog, NOT in registry):", ", ".join(dropped))
if missing_meta:
    print("no display metadata yet (rendered with Studio hint):", ", ".join(missing_meta))
