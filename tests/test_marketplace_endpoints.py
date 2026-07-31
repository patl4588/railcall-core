#!/usr/bin/env python3
"""
test_marketplace_endpoints.py — proof for /v1/market/list · get · stats.

Shape 1 of the marketplace launch: RailCall-published discovery only, no
publish flow, no payments. This suite pins what the browse + install
skeleton must guarantee before we point a storefront at it:

  1. /v1/market/stats reports the 7,240-listing catalogue and 50 curated
     exemplars — the exact counts customers see quoted in marketing.
  2. /v1/market/list defaults to a bounded page (never dumps the 3.4MB
     index) and honors limit + offset for pagination.
  3. Filters compose: category × pattern × trigger × provider × free-text q
     all AND together server-side, so the storefront's chips can stack.
  4. featured=1 restricts to the ~50 curated set (what the storefront shows
     by default so users see intent, not a wall of combinatorics).
  5. Free-text search is case-insensitive and hits title + id + archetype
     substrings.
  6. /v1/market/get returns the full spec for a curated listing (installable);
     metadata-only for the rest (honestly labeled).
  7. Unknown id → 404 without leaking anything.
  8. limit is bounded — a caller asking for limit=99999 gets pinned to the
     max so a single request can't scrape the whole index in one shot.

Run: python3 test_marketplace_endpoints.py
"""
import os
import sys
import tempfile

FAILED = []


def ok(label, cond, detail=None):
    print(("✓ " if cond else "✗ ") + label)
    if not cond:
        FAILED.append(label)
        if detail is not None:
            print("    got: %r" % (detail,))


def main():
    tmp = tempfile.mkdtemp(prefix="rc-mk-")
    os.environ["RAILCALL_DB_PATH"] = os.path.join(tmp, "test.db")
    os.environ["DATABASE_URL"] = ""
    os.environ["RAILCALL_LOCAL_ADMIN"] = "1"

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from fastapi.testclient import TestClient
    except Exception as e:
        print("• SKIP — fastapi TestClient unavailable: %r" % (e,))
        return 0

    import cloud_gateway as G   # noqa: E402
    G.DB_PATH = os.path.join(tmp, "test.db")
    G.init_db()
    client = TestClient(G.app)

    # ─── 1. stats ────────────────────────────────────────────────────────────
    r = client.get("/v1/market/stats")
    ok("1a. /v1/market/stats → 200", r.status_code == 200, r.text[:200])
    j = r.json() if r.status_code == 200 else {}
    ok("1b. total_listings = 7240 (the full library size)",
       j.get("total_listings") == 7240, j.get("total_listings"))
    ok("1c. featured_count = 50 (curated exemplars)",
       j.get("featured_count") == 50, j.get("featured_count"))
    ok("1d. categories includes Revenue + Eng + Ops (the storefront chips)",
       all(c in (j.get("categories") or [])
           for c in ("Revenue", "Eng", "Ops", "HR/IT", "Finance")), j.get("categories"))
    ok("1e. index_root is a sha256:… (tamper-evidence over the whole catalogue)",
       str(j.get("index_root", "")).startswith("sha256:"), j.get("index_root"))

    # ─── 2. list default page size + pagination ─────────────────────────────
    r = client.get("/v1/market/list")
    j = r.json()
    ok("2a. default list caps at 50 items (never dumps the whole index)",
       len(j.get("items", [])) == 50, len(j.get("items", [])))
    ok("2b. default is featured-only (curated intent, not combinatorial wall)",
       j.get("total") == 50, j.get("total"))
    r = client.get("/v1/market/list?limit=10&offset=5&featured=0")
    j = r.json()
    ok("2c. offset+limit pagination works",
       len(j.get("items", [])) == 10 and j.get("offset") == 5,
       (len(j.get("items", [])), j.get("offset")))
    r = client.get("/v1/market/list?featured=0")
    j = r.json()
    ok("2d. featured=0 unlocks the full 7240 catalogue for filtered browse",
       j.get("total") == 7240, j.get("total"))

    # ─── 3. filters compose ─────────────────────────────────────────────────
    r = client.get("/v1/market/list?category=Revenue&featured=0")
    ok("3a. category=Revenue narrows to Revenue-only",
       all(x["category"] == "Revenue" for x in r.json().get("items", [])),
       r.json().get("items")[0] if r.json().get("items") else None)
    r = client.get("/v1/market/list?pattern=durable_wait&featured=0&limit=200")
    items = r.json().get("items", [])
    ok("3b. pattern=durable_wait returns only durable-wait listings",
       all(x["pattern"] == "durable_wait" for x in items), len(items))
    r = client.get("/v1/market/list?provider=stripe&featured=0&limit=200")
    items = r.json().get("items", [])
    ok("3c. provider=stripe returns only stripe-touching listings",
       all("stripe" in x["providers"] for x in items), len(items))
    r = client.get("/v1/market/list?category=Revenue&pattern=linear&provider=stripe&featured=0&limit=200")
    items = r.json().get("items", [])
    ok("3d. all three filters compose (Revenue AND linear AND stripe)",
       all(x["category"] == "Revenue" and x["pattern"] == "linear"
           and "stripe" in x["providers"] for x in items), len(items))

    # ─── 4. featured flag ───────────────────────────────────────────────────
    r = client.get("/v1/market/list?featured=1&limit=200")
    items = r.json().get("items", [])
    ok("4a. featured=1 → all items marked featured",
       all(x["featured"] for x in items), len(items))
    ok("4b. featured set = 50 curated exemplars",
       r.json().get("total") == 50, r.json().get("total"))

    # ─── 5. free-text search ────────────────────────────────────────────────
    r = client.get("/v1/market/list?q=fraud&featured=0&limit=5")
    items = r.json().get("items", [])
    ok("5a. q=fraud returns fraud-review listings",
       all("fraud" in x["id"].lower() or "fraud" in (x["title"] or "").lower()
           for x in items), len(items))
    r = client.get("/v1/market/list?q=FRAUD&featured=0&limit=5")
    ok("5b. free-text is case-insensitive",
       len(r.json().get("items", [])) > 0, r.json().get("total"))
    r = client.get("/v1/market/list?q=nonexistent_zqx_string&featured=0")
    ok("5c. no match → empty page, not 404",
       r.status_code == 200 and r.json().get("total") == 0, r.status_code)

    # ─── 6. get: curated has full spec, unlisted metadata-only ─────────────
    # Any curated exemplar id works — pull one from the samples we know is there.
    sample_id = list(G._MARKET_SAMPLES.keys())[0]
    r = client.get(f"/v1/market/get?id={sample_id}")
    ok("6a. curated listing → 200 with has_full_spec=True",
       r.status_code == 200 and r.json().get("has_full_spec") is True,
       (r.status_code, r.json().get("has_full_spec")))
    j = r.json()
    ok("6b. curated returns the full DAG (spec.nodes present)",
       isinstance((j.get("spec") or {}).get("nodes"), list)
       and len(j["spec"]["nodes"]) > 0, j.get("spec"))
    # A non-curated id — pick one from the index that isn't in samples
    non_curated = next(e["id"] for e in G._MARKET_INDEX if e["id"] not in G._MARKET_SAMPLES)
    r = client.get(f"/v1/market/get?id={non_curated}")
    ok("6c. non-curated listing → 200 with has_full_spec=False (honest)",
       r.status_code == 200 and r.json().get("has_full_spec") is False,
       (r.status_code, r.json().get("has_full_spec")))

    # ─── 7. unknown id → 404 ────────────────────────────────────────────────
    r = client.get("/v1/market/get?id=totally_made_up_id_1234")
    ok("7. unknown id → 404 unknown listing", r.status_code == 404,
       r.status_code)

    # ─── 8. limit bound — no scrape-in-one-request ─────────────────────────
    r = client.get("/v1/market/list?limit=99999&featured=0")
    j = r.json()
    ok("8. limit=99999 gets pinned to 50 (default), preventing full-index scrape",
       j.get("limit") == 50 and len(j.get("items", [])) == 50,
       (j.get("limit"), len(j.get("items", []))))

    if FAILED:
        print("\n%d check(s) FAILED:" % len(FAILED))
        for f in FAILED:
            print("  - " + f)
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
