#!/usr/bin/env python3
"""
Compatibility shim — DO NOT add logic here.

A stale Render start command (cached Blueprint sync / an old manual dashboard
setting) invokes `python cloud_gateway_stripe_crypto.py`. That filename never
existed in the repo, which is what crash-loops the deploy.

Rather than duplicate the gateway (a copy would drift the moment cloud_gateway.py
changes and silently reintroduce the crash), this runs the EXACT same server.
Equivalent to `python cloud_gateway.py`. Also resolves `uvicorn cloud_gateway_stripe_crypto:app`.
"""
# Importing cloud_gateway runs its module-level setup (load_env, init_db, routes).
from cloud_gateway import app, HOST, PORT  # noqa: F401  (app re-exported for uvicorn)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
