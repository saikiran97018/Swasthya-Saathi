"""Create the Saathi Plus plans at Razorpay and print their ids.

Run once, from the backend folder, after RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are in .env (use TEST keys first):

    .\\.venv\\Scripts\\python.exe scripts\\create_razorpay_plans.py

It prints plan ids (not secrets). Put them in .env (and in Render's environment) as RAZORPAY_PLAN_MONTHLY and RAZORPAY_PLAN_YEARLY.
The amounts come from PLAN_MONTHLY_INR and PLAN_YEARLY_INR. You can also create plans by hand in the Razorpay dashboard
(Subscriptions -> Plans) and just paste their ids.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.core.config import get_settings  # noqa: E402


def main() -> int:
    s = get_settings()
    if not (s.razorpay_key_id and s.razorpay_key_secret):
        print("Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in backend/.env first.")
        return 1
    mode = "TEST" if s.razorpay_key_id.startswith("rzp_test_") else "LIVE"
    print(f"Creating plans with {mode} keys...")
    for env_name, period, amount in (("RAZORPAY_PLAN_MONTHLY", "monthly", s.plan_monthly_inr), ("RAZORPAY_PLAN_YEARLY", "yearly", s.plan_yearly_inr)):
        body = {"period": period, "interval": 1, "item": {"name": f"Saathi Plus ({period})", "amount": amount * 100, "currency": "INR", "description": "Unlimited chat and live calls"}}
        r = httpx.post("https://api.razorpay.com/v1/plans", json=body, auth=(s.razorpay_key_id, s.razorpay_key_secret), timeout=30)
        if r.status_code >= 400:
            print(f"  {period}: Razorpay said HTTP {r.status_code}: {r.json().get('error', {}).get('description', '')}")
            return 1
        print(f"  {env_name}={r.json()['id']}   (Rs {amount} per {period[:-2] if period == 'monthly' else 'year'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
