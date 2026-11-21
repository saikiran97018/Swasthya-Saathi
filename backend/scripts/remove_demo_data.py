"""Delete the invented sample clinics ("Demo ...") and everything that points at them.

    .\\.venv\\Scripts\\python.exe scripts\\remove_demo_data.py          # dry run: only counts what would go
    .\\.venv\\Scripts\\python.exe scripts\\remove_demo_data.py --yes    # really delete

Removes: sample providers (is_demo), the appointments booked with them, those appointments' reminders/notifications.
Keeps: users, conversations, family members, emergency contacts, the knowledge base, and planned visits at real places.
Run `alembic upgrade head` first.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func, select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.database import connection  # noqa: E402
from app.database.models import Appointment, Provider, Reminder  # noqa: E402


async def main(really: bool) -> None:
    settings = get_settings()
    connection.init_engine(settings.database_url)
    async with connection.get_session_factory()() as session:
        demo_ids = list((await session.scalars(select(Provider.id).where(Provider.is_demo.is_(True)))).all())
        appt_ids = list((await session.scalars(select(Appointment.id).where(Appointment.provider_id.in_(demo_ids)))).all()) if demo_ids else []
        reminders = (await session.scalar(select(func.count()).select_from(Reminder).where(Reminder.appointment_id.in_(appt_ids)))) if appt_ids else 0
        print(f"sample providers: {len(demo_ids)} | appointments with them: {len(appt_ids)} | their reminders: {reminders}")
        if not demo_ids:
            print("nothing to remove")
            return
        if not really:
            print("dry run: nothing deleted. Re-run with --yes to delete.")
            return
        if appt_ids:
            await session.execute(delete(Reminder).where(Reminder.appointment_id.in_(appt_ids)))
            await session.execute(delete(Appointment).where(Appointment.id.in_(appt_ids)))
        await session.execute(delete(Provider).where(Provider.id.in_(demo_ids)))
        await session.commit()
        print("deleted.")
    await connection.dispose_engine()


if __name__ == "__main__":
    asyncio.run(main("--yes" in sys.argv))
