"""Local stand-in for the HeyReach public API, serving synthetic workspaces.

Each API key maps to one workspace. By default only read endpoints are served;
any other request is answered 403 and recorded in `blocked`, so a test can
assert that nothing tried to send, add, tag or start anything. With
writable=True it also serves the setup writes (create list, add leads to a
list, create a DRAFT campaign) and records them in `writes`; sending endpoints
stay blocked either way.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PREFIX = "/api/public"


def _page(items, body):
    off, lim = int(body.get("offset") or 0), int(body.get("limit") or 100)
    return {"totalCount": len(items), "items": items[off:off + lim]}


def _strip(convo):
    return {k: v for k, v in convo.items() if k != "campaignId"}


ROUTES = {
    ("GET", "/auth/CheckApiKey"): lambda ws, b, q: None,
    ("POST", "/campaign/GetAll"): lambda ws, b, q: _page(ws["campaigns"], b),
    ("POST", "/list/GetAll"): lambda ws, b, q: _page(ws["lists"], b),
    ("POST", "/li_account/GetAll"): lambda ws, b, q: _page(ws["accounts"], b),
    ("POST", "/list/GetLeadsFromList"): lambda ws, b, q: _page(ws["list_leads"].get(str(b.get("listId")), []), b),
    ("POST", "/campaign/GetLeadsFromCampaign"): lambda ws, b, q: _page(ws["campaign_leads"].get(str(b.get("campaignId")), []), b),
    ("GET", "/campaign/GetCampaignSequence"): lambda ws, b, q: ws["sequences"].get((q.get("campaignId") or [""])[0]),
    ("POST", "/inbox/GetConversationsV2"): lambda ws, b, q: _page(
        [_strip(c) for c in ws["conversations"]
         if not ((b.get("filters") or {}).get("campaignIds")) or c.get("campaignId") in b["filters"]["campaignIds"]], b),
    ("POST", "/stats/GetOverallStatsByCampaign"): lambda ws, b, q: {
        "byDayStats": {}, "overallStats": [s for s in ws["stats"]
                                           if not b.get("campaignIds") or s["campaignId"] in b["campaignIds"]]},
    ("POST", "/MyNetwork/GetMyNetworkForSender"): lambda ws, b, q: (lambda net, n, size: {
        "totalCount": len(net), "items": net[n * size:(n + 1) * size]})(
        ws["network"].get(str(b.get("senderId")), []), int(b.get("pageNumber") or 0), int(b.get("pageSize") or 100)),
    ("POST", "/lead/GetLead"): lambda ws, b, q: ws["lead_details"].get(b.get("profileUrl")),
    ("GET", "/campaign/GetById"): lambda ws, b, q: next(
        (c for c in ws["campaigns"] if str(c["id"]) == (q.get("campaignId") or [""])[0]), None),
}


def _create_list(ws, b, q):
    lid = 800000 + len(ws["lists"]) + 1
    ws["lists"].append({"id": lid, "name": b.get("name"), "totalItemsCount": 0, "listType": b.get("type") or "USER_LIST",
                        "creationTime": "2026-09-22T12:00:00Z", "campaignIds": []})
    ws["list_leads"][str(lid)] = []
    return {"id": lid, "name": b.get("name"), "count": 0, "listType": "USER_LIST"}


def _add_leads(ws, b, q):
    rows = ws["list_leads"].setdefault(str(b.get("listId")), [])
    for lead in b.get("leads") or []:
        rows.append({**lead, "headline": lead.get("summary"), "customFields": lead.get("customUserFields") or []})
    for li in ws["lists"]:
        if li["id"] == b.get("listId"):
            li["totalItemsCount"] = len(rows)
    return {"addedLeadsCount": len(b.get("leads") or []), "updatedLeadsCount": 0, "failedLeadsCount": 0}


def _create_campaign(ws, b, q):
    if not b.get("linkedInAccountIds"):
        return None  # the real API rejects this; handled as 400 below
    cid = 990000 + len(ws["campaigns"]) + 1
    ws["campaigns"].append({"id": cid, "name": b["name"], "status": "DRAFT", "linkedInUserListId": b["linkedInUserListId"],
                            "campaignAccountIds": b["linkedInAccountIds"], "creationTime": "2026-09-22T12:00:00Z"})
    ws["sequences"][str(cid)] = b.get("sequence")
    return {"campaignId": cid}


WRITE_ROUTES = {
    ("POST", "/list/CreateEmptyList"): _create_list,
    ("POST", "/list/AddLeadsToListV2"): _add_leads,
    ("POST", "/campaign/Create"): _create_campaign,
}


class FakeHeyReach:
    def __init__(self, workspaces, writable=False):
        self.workspaces = workspaces
        self.writable = writable
        self.requests, self.blocked, self.writes = [], [], []
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _handle(self, method):
                url = urlparse(self.path)
                path = url.path[len(PREFIX):] if url.path.startswith(PREFIX) else url.path
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                key = self.headers.get("X-API-KEY")
                with outer._lock:
                    outer.requests.append((method, path))
                ws = outer.workspaces.get(key)
                if ws is None:
                    return self._send(401, {"error": "invalid api key"})
                route = ROUTES.get((method, path))
                if route is None and outer.writable and (method, path) in WRITE_ROUTES:
                    with outer._lock:
                        outer.writes.append((method, path))
                    res = WRITE_ROUTES[(method, path)](ws, body, parse_qs(url.query))
                    return self._send(200, res) if res is not None else self._send(400, {"error": "linkedInAccountIds required"})
                if route is None:
                    with outer._lock:
                        outer.blocked.append((method, path))
                    return self._send(403, {"error": "fake HeyReach serves read endpoints only"})
                return self._send(200, route(ws, body, parse_qs(url.query)))

            def _send(self, status, payload):
                data = b"" if payload is None else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

            def do_PUT(self):
                self._handle("PUT")

            def do_PATCH(self):
                self._handle("PATCH")

            def do_DELETE(self):
                self._handle("DELETE")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}{PREFIX}"

    def start(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.server.shutdown()


if __name__ == "__main__":
    # Serve a fixture for manual CLI runs:  python -m gtm_bot.demo.fake_heyreach [fixture.json]
    import sys
    import time

    from .synth import build

    wss = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else build()[0]
    fake = FakeHeyReach(wss).start()
    print(f"HEYREACH_BASE_URL={fake.base_url}")
    print("keys: " + ", ".join(wss))
    sys.stdout.flush()
    while True:
        time.sleep(3600)
