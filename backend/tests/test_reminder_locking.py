"""Two workers running the reminder loop at the same moment must not deliver the same reminder twice.

Needs a database with row locks, so it runs only on PostgreSQL (set TEST_DATABASE_URL, see conftest.py).
"""
import asyncio
import os
from datetime import datetime, timedelta

import pytest

from tests.conftest import login_guest
from tests.test_healthcare import appointments, book, first_slot, new_user, when

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="row locking needs PostgreSQL (set TEST_DATABASE_URL)")


def test_concurrent_workers_deliver_each_reminder_once(client, llm):
    auth, _ = new_user(client)
    for n in range(4):  # several appointments -> several due reminders
        book(client, auth, llm, first_slot(client, auth, days_ahead=2 + n, nth=n), name=f"Patient {n}")
    last = max(when(a) for a in appointments(client, auth))
    later = last + timedelta(days=1)
    svc = client.app.state.reminder_service

    async def two_workers() -> list[int]:
        return list(await asyncio.gather(svc.deliver_due(later), svc.deliver_due(later)))

    delivered = client.portal.call(two_workers)
    pending_after = client.portal.call(svc.deliver_due, later)
    notes = client.get("/api/v1/notifications?limit=100", headers=auth).json()
    assert pending_after == 0
    assert sum(delivered) == notes["total"], (delivered, notes["total"])  # no reminder counted twice
    ids = [n["id"] for n in notes["items"]]
    assert len(ids) == len(set(ids))
