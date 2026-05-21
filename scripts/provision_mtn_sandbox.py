"""
Create MTN MoMo sandbox API User + API Key and print .env lines.

Requires a valid Collection subscription key from https://momodeveloper.mtn.com

  venv\\Scripts\\python scripts/provision_mtn_sandbox.py
  venv\\Scripts\\python scripts/provision_mtn_sandbox.py --callback-host abc123.ngrok-free.app
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE = (os.getenv("MTN_MOMO_BASE_URL") or "https://sandbox.momodeveloper.mtn.com").rstrip("/")
SUB = (os.getenv("MTN_MOMO_SUBSCRIPTION_KEY") or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision MTN MoMo sandbox API user/key")
    parser.add_argument(
        "--callback-host",
        default="localhost",
        help="Hostname only (no https://), registered with MTN as providerCallbackHost",
    )
    args = parser.parse_args()

    if not SUB:
        print("Set MTN_MOMO_SUBSCRIPTION_KEY in .env first (Primary Key from Collection product).", file=sys.stderr)
        return 1

    ref = str(uuid.uuid4())
    headers = {
        "X-Reference-Id": ref,
        "Ocp-Apim-Subscription-Key": SUB,
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=45.0) as client:
        r1 = client.post(
            f"{BASE}/v1_0/apiuser",
            headers=headers,
            json={"providerCallbackHost": args.callback_host},
        )
        if r1.status_code not in (200, 201):
            print(f"Create API user failed ({r1.status_code}): {r1.text}", file=sys.stderr)
            if r1.status_code == 401:
                print(
                    "\nSubscription key is invalid or not subscribed to Collection.\n"
                    "Fix at https://momodeveloper.mtn.com → your app → subscribe to Collection → copy Primary Key.",
                    file=sys.stderr,
                )
            return 1

        r2 = client.post(
            f"{BASE}/v1_0/apiuser/{ref}/apikey",
            headers={"Ocp-Apim-Subscription-Key": SUB},
        )
        if r2.status_code not in (200, 201):
            print(f"Create API key failed ({r2.status_code}): {r2.text}", file=sys.stderr)
            return 1

        api_key = (r2.json() or {}).get("apiKey", "")
        if not api_key:
            print("API key missing in response.", file=sys.stderr)
            return 1

        cred = base64.b64encode(f"{ref}:{api_key}".encode()).decode()
        r3 = client.post(
            f"{BASE}/collection/token/",
            headers={
                "Authorization": f"Basic {cred}",
                "Ocp-Apim-Subscription-Key": SUB,
            },
        )
        if r3.status_code != 200:
            print(f"Token test failed ({r3.status_code}): {r3.text}", file=sys.stderr)
            return 1

    print("MTN sandbox credentials OK. Add to .env:\n")
    print(f"MTN_MOMO_API_USER={ref}")
    print(f"MTN_MOMO_API_KEY={api_key}")
    print("MTN_MOMO_TARGET_ENVIRONMENT=sandbox")
    print(f"MTN_MOMO_BASE_URL={BASE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
