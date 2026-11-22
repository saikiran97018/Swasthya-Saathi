"""Phone / browser notifications (Web Push): sign-up, delivery with a reminder, cleanup of dead devices."""
import base64
from datetime import timedelta
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import WebPushException

from app.services import push as push_mod
from app.services.push import vapid_keys
from tests.test_booking_api import book
from tests.test_healthcare import appointments, first_slot, new_user, when

P = "/api/v1"


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def device(n: int = 1) -> dict:
    """A realistic browser subscription: a real P-256 public key and a 16-byte auth secret."""
    key = ec.generate_private_key(ec.SECP256R1())
    point = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"endpoint": f"https://push.example.test/send/device-{n}-" + "x" * 30, "keys": {"p256dh": b64(point), "auth": b64(bytes(range(16)))}}


class Pushes:
    """Replaces the network call; remembers (endpoint, payload) for each push."""

    def __init__(self, fail: dict[str, int] | None = None):
        self.sent: list[tuple[str, dict]] = []
        self.fail = fail or {}

    def install(self, monkeypatch):
        import json

        def fake(subscription_info, data=None, **kw):
            code = self.fail.get(subscription_info["endpoint"])
            if code:
                raise WebPushException("rejected", response=SimpleNamespace(status_code=code))
            self.sent.append((subscription_info["endpoint"], json.loads(data)))

        monkeypatch.setattr(push_mod, "webpush", fake)
        return self


def config(client, auth):
    return client.get(f"{P}/push/config", headers=auth).json()


def sign_up(client, auth, dev):
    return client.post(f"{P}/push/subscriptions", json=dev, headers=auth)


def run_reminders(client, auth):
    start = max(when(a) for a in appointments(client, auth))
    return client.portal.call(client.app.state.reminder_service.deliver_due, start - timedelta(minutes=1))


def test_keys_are_stable_valid_and_depend_on_the_secret(make_client):
    a, b = make_client(jwt_secret="x" * 40), make_client(jwt_secret="y" * 40)
    ka, kb = vapid_keys(a.app.state.settings), vapid_keys(a.app.state.settings)
    assert ka == kb  # same secret, same key: devices stay registered across restarts and redeploys
    assert vapid_keys(b.app.state.settings) != ka
    assert len(base64.urlsafe_b64decode(ka[1] + "==")) == 65  # an uncompressed P-256 point, as browsers expect
    explicit = make_client(vapid_private_key=ka[0])
    assert vapid_keys(explicit.app.state.settings) == ka


def test_a_real_push_is_encrypted_and_signed_with_the_published_key(make_client, monkeypatch):
    """Runs pywebpush for real (only the HTTP post is faked) to prove the key we publish is the key that signs."""
    import pywebpush

    c = make_client()
    seen = {}

    def fake_post(url, data=None, headers=None, **kw):
        seen.update(url=url, headers=headers, body=data)
        return SimpleNamespace(status_code=201, ok=True, text="", headers={})

    monkeypatch.setattr(pywebpush.requests, "post", fake_post)
    auth, _ = new_user(c)
    dev = device()
    assert sign_up(c, auth, dev).status_code == 201
    assert c.post(f"{P}/push/test", headers=auth).json() == {"sent": 1}
    assert seen["url"] == dev["endpoint"]
    assert seen["headers"]["authorization"].startswith("vapid t=") and f"k={config(c, auth)['public_key']}" in seen["headers"]["authorization"]
    assert seen["headers"]["content-encoding"] == "aes128gcm" and b"Notifications are on" not in seen["body"]  # encrypted


def test_requires_login(client):
    assert client.get(f"{P}/push/config").status_code == 401
    assert client.post(f"{P}/push/subscriptions", json=device()).status_code == 401
    assert client.post(f"{P}/push/test").status_code == 401


def test_config_gives_the_public_key_and_device_count(client):
    auth, _ = new_user(client)
    cfg = config(client, auth)
    assert cfg["available"] is True and cfg["devices"] == 0 and len(cfg["public_key"]) > 80
    assert "private" not in str(cfg).lower()
    assert sign_up(client, auth, device(1)).json()["devices"] == 1
    assert config(client, auth)["devices"] == 1


def test_signing_up_twice_is_one_device_and_unsubscribing_removes_it(client):
    auth, _ = new_user(client)
    dev = device()
    sign_up(client, auth, dev)
    assert sign_up(client, auth, dev).json()["devices"] == 1
    assert client.request("DELETE", f"{P}/push/subscriptions", json={"endpoint": dev["endpoint"]}, headers=auth).status_code == 204
    assert config(client, auth)["devices"] == 0


def test_devices_belong_to_their_owner(client):
    a, _ = new_user(client)
    b, _ = new_user(client)
    dev = device()
    sign_up(client, a, dev)
    client.request("DELETE", f"{P}/push/subscriptions", json={"endpoint": dev["endpoint"]}, headers=b)  # someone else cannot remove it
    assert config(client, a)["devices"] == 1


def test_bad_sign_ups_are_refused(client):
    auth, _ = new_user(client)
    assert client.post(f"{P}/push/subscriptions", json={"endpoint": "x", "keys": {"p256dh": "a", "auth": "b"}}, headers=auth).status_code == 422
    for n in range(10):
        assert sign_up(client, auth, device(n)).status_code == 201
    over = sign_up(client, auth, device(99))
    assert over.status_code == 409 and over.json()["error"]["code"] == "too_many_devices"


def test_disabled_on_the_server(make_client):
    c = make_client(push_enabled=False)
    auth, _ = new_user(c)
    assert config(c, auth)["available"] is False
    assert sign_up(c, auth, device()).json()["error"]["code"] == "push_unavailable"


def test_a_due_reminder_pops_up_on_every_device(make_client, monkeypatch):
    c = make_client()
    pushes = Pushes().install(monkeypatch)
    auth, _ = new_user(c)
    assert book(c, auth, first_slot(c, auth, days_ahead=3)).status_code == 201
    d1, d2 = device(1), device(2)
    sign_up(c, auth, d1), sign_up(c, auth, d2)
    assert run_reminders(c, auth) == 2
    assert len(pushes.sent) == 4  # two reminders x two devices
    endpoints = {e for e, _ in pushes.sent}
    assert endpoints == {d1["endpoint"], d2["endpoint"]}
    payload = pushes.sent[0][1]
    assert payload["title"] and payload["body"] and payload["url"] == "/activity"


def test_no_device_no_push_and_other_people_are_not_pushed(make_client, monkeypatch):
    c = make_client()
    pushes = Pushes().install(monkeypatch)
    auth, _ = new_user(c)
    other, _ = new_user(c)
    sign_up(c, other, device())
    assert book(c, auth, first_slot(c, auth, days_ahead=3)).status_code == 201
    assert run_reminders(c, auth) == 2
    assert pushes.sent == []


def test_dead_devices_are_forgotten_but_others_still_get_it(make_client, monkeypatch):
    c = make_client()
    gone, alive = device(1), device(2)
    pushes = Pushes(fail={gone["endpoint"]: 410}).install(monkeypatch)
    auth, _ = new_user(c)
    sign_up(c, auth, gone), sign_up(c, auth, alive)
    assert book(c, auth, first_slot(c, auth, days_ahead=3)).status_code == 201
    run_reminders(c, auth)
    assert config(c, auth)["devices"] == 1  # the 410 device was removed
    assert {e for e, _ in pushes.sent} == {alive["endpoint"]}


def test_a_failing_push_service_never_blocks_the_in_app_reminder(make_client, monkeypatch):
    c = make_client()
    dev = device()
    Pushes(fail={dev["endpoint"]: 500}).install(monkeypatch)
    auth, _ = new_user(c)
    sign_up(c, auth, dev)
    assert book(c, auth, first_slot(c, auth, days_ahead=3)).status_code == 201
    assert run_reminders(c, auth) == 2
    assert c.get(f"{P}/notifications?limit=100", headers=auth).json()["total"] == 2
    assert config(c, auth)["devices"] == 1  # a server error is not a reason to forget the device
