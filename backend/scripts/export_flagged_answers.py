"""List the replies people marked as bad, so wrong or unsafe answers can be reviewed and fixed.

    .\\.venv\\Scripts\\python.exe scripts\\export_flagged_answers.py            # the latest 50, as readable text
    .\\.venv\\Scripts\\python.exe scripts\\export_flagged_answers.py --json     # one JSON object per line
    .\\.venv\\Scripts\\python.exe scripts\\export_flagged_answers.py --reason unsafe --limit 200

For each one it shows what the person asked, what the assistant answered, the reason they chose, their note, the intent the
assistant saw and what the response check did. Names and contact details are not included.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.database.connection import get_session_factory, init_engine  # noqa: E402
from app.database.models import Conversation, Message, MessageFeedback  # noqa: E402


async def main(limit: int, reason: str | None, as_json: bool) -> None:
    init_engine(get_settings().database_url)
    async with get_session_factory()() as session:
        q = select(MessageFeedback, Message, Conversation).join(Message, MessageFeedback.message_id == Message.id).join(Conversation, Message.conversation_id == Conversation.id).where(MessageFeedback.rating == "down")
        if reason:
            q = q.where(MessageFeedback.reason == reason)
        rows = (await session.execute(q.order_by(MessageFeedback.created_at.desc()).limit(limit))).all()
        for fb, reply, conv in rows:
            asked = await session.scalar(
                select(Message.content).where(Message.conversation_id == reply.conversation_id, Message.role == "user", Message.seq < reply.seq).order_by(Message.seq.desc()).limit(1)
            )
            meta = reply.meta or {}
            item = {
                "when": fb.created_at.isoformat(), "reason": fb.reason, "note": fb.note, "language": conv.language, "asked": asked, "answered": reply.content,
                "intent": meta.get("intent"), "tools": meta.get("tools_used"), "validation": meta.get("validation"),
            }
            if as_json:
                print(json.dumps(item, ensure_ascii=False))
            else:
                print(f"--- {item['when'][:16]}  [{item['reason'] or 'no reason'}]  lang={item['language']}  intent={item['intent']}  tools={item['tools']}")
                print(f"ASKED:    {item['asked']}")
                print(f"ANSWERED: {item['answered']}")
                if item["note"]:
                    print(f"NOTE:     {item['note']}")
                if item["validation"]:
                    print(f"CHECK:    {item['validation']}")
        if not rows:
            print("No bad replies flagged yet.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--reason", choices=["wrong_info", "unsafe", "misunderstood", "not_helpful", "other"])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # Indian-language text on a Windows console
    asyncio.run(main(a.limit, a.reason, a.json))
