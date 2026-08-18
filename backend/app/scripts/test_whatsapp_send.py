"""Standalone connectivity test for the real Meta WhatsApp Cloud API adapter.

Sends ONE message using Meta's `hello_world` sample template - the only
template every WhatsApp Business Account has pre-approved from creation, and
the same one Meta's own "Send message" button on the WhatsApp > API Setup
dashboard page uses. This script exists purely to prove
WHATSAPP_ACCESS_TOKEN + WHATSAPP_PHONE_NUMBER_ID actually work end-to-end
against the real Graph API - decoupled from `MessageDispatchService`/the
outbox pipeline (see `app.services.message_dispatch`) and from any custom
message template, both of which come later.

Usage (inside the backend container, matching how every other script in
this repo runs - see tools/start-local.ps1):

    docker compose exec backend python -m app.scripts.test_whatsapp_send --to +919000000001

Requires WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID in the repo
root .env (wired into the backend container via docker-compose.yml). The
recipient number must be one you've added under "To" on Meta's WhatsApp API
Setup page - a test/unverified app can only message allow-listed numbers.
"""

from __future__ import annotations

import argparse
import sys

from app.config import settings
from app.services.whatsapp_provider import MetaCloudApiAdapter


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--to", required=True, help="Recipient phone number in E.164 format, e.g. +919000000001")
    parser.add_argument("--template", default="hello_world", help="Pre-approved template name (default: hello_world)")
    parser.add_argument("--language", default="en_US", help="Template language code (default: en_US)")
    args = parser.parse_args()

    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        print(
            "ERROR: WHATSAPP_ACCESS_TOKEN and/or WHATSAPP_PHONE_NUMBER_ID are not set "
            "(check the repo root .env and docker-compose.yml).",
            file=sys.stderr,
        )
        return 1

    adapter = MetaCloudApiAdapter()
    result = adapter.send(
        recipient_phone=args.to,
        template=args.template,
        payload={"language_code": args.language},
    )

    if result.ok:
        print(f"OK - message sent. provider_message_id={result.provider_message_id}")
        return 0

    print(f"FAILED - code={result.failure_code} reason={result.failure_reason}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
