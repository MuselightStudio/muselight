"""Muselight Credits: one prepaid balance for every model, paid to Muselight instead of to each provider.

Runs go through the Muselight Credits server (muselight_cloud/server.py), which holds the provider keys, charges the quoted price and
refunds runs that fail. The models are fal's, so the price comparison sees them as the same models as fal's and still picks the
cheapest connected provider: someone with their own fal key pays fal's price, someone without one can still run everything.
"""
import mimetypes, os, urllib.request

from . import _core as core

ID, LABEL, GROUP = "muselight", "Muselight Credits", "muselight"
KEYS = ["MUSELIGHT_TOKEN"]
LINK, BILLING = "", "Credits in Muselight"
HELP = ("One balance for every model, no provider accounts needed. Create an account and top up under Credits; "
        "this is your sign-in code, so keep a copy to use Muselight Credits on another PC.")
FILES = "upload"
SERVER = "https://api.muselight.studio"  # the Muselight Credits server (MUSELIGHT_CLOUD_URL overrides it, e.g. for testing)
call = core.caller(__name__)
schemas = {}
prefer = lambda mid: None  # the supplier the user chose for an open model (the app sets this from its settings)


def url():
    return (os.environ.get("MUSELIGHT_CLOUD_URL") or SERVER).rstrip("/")


def headers():
    return {"Authorization": "Bearer " + core.key("MUSELIGHT_TOKEN")}


def ready():
    return bool(url() and core.key("MUSELIGHT_TOKEN"))


def models():
    if not url():
        return []  # no Muselight Credits server yet
    out = []
    for m in call(f"{url()}/v1/prices", auth=False)["models"]:
        per = m["cost"]["per"]
        out.append({"id": m["id"], "name": m["name"], "cat": m["cat"], "desc": m["desc"], "thumb": m["thumb"], "cost": m["cost"],
                    "price": core.price(m["cost"]["usd"]) + ("" if per == "run" else f" per {'video' if per == 'clip' else per}")})
    return out


def schema(mid):
    if mid not in schemas:
        schemas[mid] = core.fal_schema(mid)
    return schemas[mid]


def quote(mid, body):
    return options(mid, body)["price"]


def options(mid, body, chosen=True):
    """The price, who runs it, and for open models every supplier's price: {price, provider, provider_name, hosted, choices?}.
    chosen=False prices it at best price, ignoring the supplier the user picked."""
    return call(f"{url()}/v1/quote", {"model": mid, "input": body, "provider": prefer(mid) if chosen else None}, timeout=60)


def run(mid, body, job):
    r = call(f"{url()}/v1/runs", {"model": mid, "input": body, "provider": prefer(mid)})

    def check():
        s = call(f"{url()}/v1/runs/{r['id']}")
        job["queue_position"] = s.get("queue_position")
        if s["status"] in ("failed", "cancelled"):
            raise RuntimeError((s.get("error") or "The run failed.") + " Your credits for it were refunded.")
        return s if s["status"] == "done" else None
    got = core.wait(job, check, LABEL, cancel=lambda: call(f"{url()}/v1/runs/{r['id']}/cancel", {}))
    if got is None:
        return None
    result = got["result"] if isinstance(got["result"], dict) else {"output": got["result"]}
    return dict(result, muselight_charge=got["charged"]), got.get("outputs") or core.media_urls(result)


def charged(result):
    return result.get("muselight_charge")


def upload(path):
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    up = call(f"{url()}/v1/uploads", {"file_name": path.name, "content_type": mime})
    req = urllib.request.Request(up["upload_url"], data=path.read_bytes(), method="PUT", headers={"Content-Type": mime})
    urllib.request.urlopen(req, timeout=600).close()
    return up["file_url"]


def balance():
    return call(f"{url()}/v1/me")


def join(accept_terms):
    """A new Muselight account: returns its sign-in code."""
    return call(f"{url()}/v1/accounts", {"accept_terms": bool(accept_terms)}, auth=False)["token"]


def topup(amount):
    """A Paddle checkout link for this many dollars of credit."""
    return call(f"{url()}/v1/topups", {"amount": amount})["checkout_url"]


def test():
    return f"Signed in to Muselight Credits. Balance ${balance()['balance']:.2f}"
