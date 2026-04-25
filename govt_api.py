from __future__ import annotations

import os


def get_gstn_integration_status():
    client_id = os.getenv("GSTN_CLIENT_ID", "").strip()
    client_secret = os.getenv("GSTN_CLIENT_SECRET", "").strip()
    gstin = os.getenv("GSTN_AUTH_GSTIN", "").strip()

    configured = bool(client_id and client_secret and gstin)
    return {
        "configured": configured,
        "provider_mode": "Authorized GSP / ASP integration required",
        "client_id_present": bool(client_id),
        "client_secret_present": bool(client_secret),
        "gstin_present": bool(gstin),
        "status_text": (
            "Integration secrets detected. Real filing still requires onboarding with an authorized GSTN/GSP setup."
            if configured
            else "No official GSTN credentials configured. Local filing mode is active."
        ),
    }
