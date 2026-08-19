"""Model fallback + error laundering for the hosted /v1/compose endpoint.

Split out of cloud_gateway.py so it can be unit-tested without importing the
FastAPI app (which pulls in stripe, pydantic, middleware and a live DB config —
none of which a laptop or CI box has). The 2026-08-19 outage below went
undetected partly because nothing in this path was reachable by a test.

## The incident

`POST /v1/compose` returned 502 "hosted engine call failed — flow refunded, try
again" for a key with 465 flows remaining. That is the Studio Builder down for
EVERY user on the hosted tier — anyone without their own Groq/OpenAI key.

Two defects turned one upstream problem into a day-long outage:

  1. NO FALLBACK — the route asked for _COMPOSE_MODELS[0] and gave up, even
     though the allowlist holds a second model that was never tried.
  2. NO DIAGNOSABILITY — the 502 detail was a fixed string, so a decommissioned
     model, a revoked key and a transient 5xx all looked identical from the
     client. Root-causing needed Render log access.

## Why `status_code` and not `HTTPException`

This module deliberately does NOT import fastapi. An exception carrying a
`status_code` attribute is treated as a deliberate signal from our own code
(e.g. 503 when the platform key is unset) and is re-raised immediately rather
than retried — trying a second model cannot fix an unset key, it would only
delay an honest error. Duck-typing the contract keeps this module importable
anywhere.
"""

import re

# Scrubber for upstream error text before it is echoed to a client. HTTP libs
# and vendor SDKs happily interpolate the whole request — including an
# Authorization header or a `?key=` query param — into their exception message.
# We now surface those messages for diagnosability, so laundering them is a
# security control, not a nicety: a leaked platform key compromises the hosted
# tier for every user.
KEY_LIKE = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._\-]+"
    r"|(?:gsk|sk|xai|api)[-_][A-Za-z0-9._\-]{8,}"
    r"|key=[^\s&\"']+)")


def scrub(text, limit=200):
    """Launder credentials out of upstream error text and bound its length."""
    return KEY_LIKE.sub("***", str(text))[:limit]


def describe_failure(exc, tried, limit=200):
    """Build the diagnosable (and safe) 502 detail.

    NEVER includes the user's prompt — only the exception class, its laundered
    message, and which models were attempted.
    """
    return ("hosted engine call failed — flow refunded, try again "
            "[upstream: %s; models tried: %s]"
            % (scrub("%s: %s" % (type(exc).__name__, exc), limit),
               ", ".join(tried)))


def models_to_try(model, allowlist):
    """Requested model first, then the rest of the allowlist, no duplicates."""
    return [model] + [m for m in allowlist if m != model]


def compose_with_fallback(complete, clean, model, allowlist):
    """Call `complete(clean, model)`, falling through `allowlist` on failure.

    Returns (reply, model_that_answered, models_tried).
    Raises the last upstream error if every model fails, or immediately
    re-raises any exception carrying a `status_code` (see module docstring).
    """
    tried = models_to_try(model, allowlist)
    last_err = None
    for m in tried:
        try:
            return complete(clean, m), m, tried
        except Exception as e:
            if hasattr(e, "status_code"):
                raise            # our own deliberate signal — do not retry
            last_err = e
    raise last_err or RuntimeError("no compose model succeeded")
