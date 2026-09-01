"""Go-live utility: retire the WhatsApp outbox backlog before flipping on
real sending.

`app.services.outbox_scheduler._build_adapter` switches from the sandbox
sender to `MetaCloudApiAdapter` the moment real credentials
(`WHATSAPP_ACCESS_TOKEN` / `WHATSAPP_PHONE_NUMBER_ID`) are configured -
automatically, on the very next dispatch pass. `MessageDispatchService.
_select_events` re-selects every `OutboxEvent` that is still `'pending'`,
plus every `'dispatched'` event that still has a `'failed'` `MessageDelivery`
against it, oldest-first, with no date cutoff (see that module's docstring).
Weeks of testing against the sandbox adapter have accumulated exactly that
backlog - task prompts, gate reminders, etc. that were only ever pretend-sent.
Flipping the switch without running this first delivers all of it, for real,
to real phones, starting with the oldest.

This does NOT delete rows - it marks each backlog `OutboxEvent` `'failed'`
(a value the status CHECK constraint already allows - see
`app.execution_models.OutboxEvent`'s own docstring: 'failed' is the terminal
"a later unit decided not to deliver this" state). That is enough:
`_select_events` never re-selects a bare `'failed'` OutboxEvent (only
`'pending'`, or `'dispatched'` with a failed delivery), so it permanently
drops out of the dispatch loop while the row itself - and every
`MessageDelivery` already recorded against it - stays queryable for later
audit. Nothing about *what was emitted* or *who would have received it*
changes; this only stops it from ever actually being attempted.

Selects the exact same rows `MessageDispatchService._select_events` would
have picked up next, by construction (imports and reuses its predicate)
rather than re-deriving it - so this script can never drift out of sync with
what dispatch would otherwise do.

Usage (inside the backend container, matching this repo's other scripts):

    docker compose exec backend python -m app.scripts.clear_whatsapp_backlog

Requires typing CLEAR-WHATSAPP-BACKLOG to confirm. Run this once, immediately
before WHATSAPP_ACCESS_TOKEN/WHATSAPP_PHONE_NUMBER_ID are set for the first
time - not on a schedule, and not after real sending is already live (by
then the backlog is real, current work, not stale test noise).
"""

from __future__ import annotations

from app.database import SessionLocal
from app.services.message_dispatch import MessageDispatchService

CONFIRMATION = "CLEAR-WHATSAPP-BACKLOG"


def run() -> None:
    with SessionLocal() as db:
        # `limit` far above any realistic backlog size - this is a one-off
        # sweep, not a paced dispatch pass, so there is no reason to cap it
        # the way `process_pending`'s default does.
        events = MessageDispatchService(db)._select_events(limit=1_000_000)

        if not events:
            print("No backlog found - nothing to clear.")
            return

        print(f"\nWARNING: this will retire {len(events)} backlog outbox event(s) - they will")
        print("NEVER be dispatched, even after real WhatsApp sending goes live.")
        print("Run this only once, immediately before setting real WhatsApp credentials.")

        value = input(f"\nType {CONFIRMATION} to continue: ").strip()
        if value != CONFIRMATION:
            print("Cancelled - no rows changed.")
            return

        for event in events:
            event.status = "failed"
            db.add(event)
        db.commit()

        print(f"\nDone. {len(events)} backlog event(s) retired; none will be dispatched.")


if __name__ == "__main__":
    run()
