# station-v0.38

Single-fix cut for a Studio render bug Dave caught while recording a
demo video.

## What was broken

Studio's Receipts tab detail pane rendered:

    signature = [object Object]

for real signed receipts. The Sends card on the same execution
correctly showed `signature = present`, so the data was there — only
the render was wrong.

## Root cause

Receipts are signed with the modern object shape:

    "signature": {
      "alg": "ed25519",
      "sig": "<hex>",
      "key_id": "<fingerprint>"
    }

The Receipts view code did:

    const sig = body.signature || body.sig || '';
    ...
    ${escape(String(sig).slice(0, 88))}

Since `body.signature` was the truthy object, `sig` became that
object, `String({...})` → `"[object Object]"`, sliced to 88 chars,
rendered.

## Fix

Type-check the raw field. If object, extract `.sig` (the actual hex)
as the primary signature string, surface `.alg` + `.key_id` on
separate lines. If string (legacy receipts from before receipt_signer
took the object shape), use as-is. Same code path handles both.

## Files changed

- `workbench/studio/scripts/views/receipts.js` — 12 lines (engine
  commit `c6985d536`)

## Verify

```bash
curl -sSL https://railcall.ai/install.sh | bash
# STATION_SHA=c7058c21ad1e48ba8d1152b14c5eddc6ba6e993224fd48962ff0458d19fdfbe2
```

Open Studio → Receipts → any signed run. Detail pane now shows:

    sha256    = <64-hex>
    signature = <128-hex> (truncated to 88 chars + …)
    alg       = ed25519
    key_id    = <fingerprint>
    timestamp = <iso>

## Credit

**Dave** — reported it mid-demo-recording with the exact contrast
(Sends card correct, Receipts card wrong) that let us localize the
bug to a single line in `receipts.js`. Same reporter as the earlier
Track B `spend_ceiling` cond-node observation.
