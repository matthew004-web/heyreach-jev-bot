"""Read-only HeyReach public API client.

Every call goes through `_call`, which refuses any endpoint not in READ_ONLY.
Endpoints that send messages, add leads, start/resume campaigns, change tags,
or even mark conversations as seen are not reachable from this module.
"""

import os
import re
import time

import requests

BASE_URL = "https://api.heyreach.io/api/public"  # HEYREACH_BASE_URL overrides (the fake workspace uses it)

# HeyReach uses POST for many reads, so the allowlist is (method, path).
READ_ONLY = {
    ("GET", "/auth/CheckApiKey"),
    ("POST", "/campaign/GetAll"),
    ("GET", "/campaign/GetById"),
    ("POST", "/campaign/GetLeadsFromCampaign"),
    ("GET", "/campaign/GetCampaignSequence"),
    ("POST", "/inbox/GetConversationsV2"),
    ("POST", "/list/GetAll"),
    ("GET", "/list/GetById"),
    ("POST", "/list/GetLeadsFromList"),
    ("POST", "/lead/GetLead"),
    ("POST", "/stats/GetOverallStats"),
    ("POST", "/stats/GetOverallStatsByCampaign"),
    ("POST", "/li_account/GetAll"),
    ("POST", "/MyNetwork/GetMyNetworkForSender"),
    ("POST", "/MyNetwork/IsConnection"),
}


class HeyReachError(RuntimeError):
    pass


class HeyReach:
    def __init__(self, api_key=None, timeout=60):
        self.api_key = api_key or os.environ.get("HEYREACH_API_KEY")
        if not self.api_key:
            raise HeyReachError("HEYREACH_API_KEY is not set (add it to .env)")
        self.timeout = timeout
        self.base_url = os.environ.get("HEYREACH_BASE_URL", BASE_URL).rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def _call(self, method, path, body=None, params=None, retries=4):
        if (method, path) not in READ_ONLY:
            raise HeyReachError(f"blocked: {method} {path} is not a read-only endpoint")
        for attempt in range(retries + 1):
            r = self.session.request(method, self.base_url + path, json=body, params=params, timeout=self.timeout)
            if r.status_code == 429 and attempt < retries:
                time.sleep(float(r.headers.get("retry-after") or 2 ** attempt))
                continue
            if r.status_code >= 400:
                raise HeyReachError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:300]}")
            return r.json() if r.text.strip() else None
        raise HeyReachError("retries exhausted")

    def _paged(self, path, body, page=100, max_items=None):
        items, offset = [], 0
        while True:
            data = self._call("POST", path, {**body, "offset": offset, "limit": page}) or {}
            batch = data.get("items") or []
            items.extend(batch)
            offset += len(batch)
            if not batch or offset >= (data.get("totalCount") or 0) or (max_items and len(items) >= max_items):
                return items[:max_items] if max_items else items

    def check(self):
        self._call("GET", "/auth/CheckApiKey")
        return True

    def _count(self, path, body=None):
        return (self._call("POST", path, {**(body or {}), "offset": 0, "limit": 1}) or {}).get("totalCount") or 0

    def workspace_summary(self):
        return {
            "campaigns": self._count("/campaign/GetAll"),
            "lists": self._count("/list/GetAll"),
            "linkedin_accounts": self._count("/li_account/GetAll"),
            "conversations": self._count("/inbox/GetConversationsV2", {"filters": {}}),
        }

    def accounts(self):
        return self._paged("/li_account/GetAll", {})

    def network(self, sender_id, max_items=None, page=100):
        """1st-degree connections of a connected LinkedIn sender (pageNumber pagination)."""
        items, n = [], 0
        while True:
            data = self._call("POST", "/MyNetwork/GetMyNetworkForSender",
                              {"senderId": int(sender_id), "pageNumber": n, "pageSize": page}) or {}
            batch = data.get("items") or []
            items.extend(batch)
            n += 1
            if not batch or len(items) >= (data.get("totalCount") or 0) or (max_items and len(items) >= max_items):
                return items[:max_items] if max_items else items

    def get_lead(self, profile_url):
        return self._call("POST", "/lead/GetLead", {"profileUrl": profile_url})

    def campaigns(self):
        return self._paged("/campaign/GetAll", {})

    def lists(self):
        return self._paged("/list/GetAll", {})

    def leads_from_list(self, list_id, max_items=None):
        return self._paged("/list/GetLeadsFromList", {"listId": int(list_id)}, page=1000, max_items=max_items)

    def leads_from_campaign(self, campaign_id, max_items=None):
        return self._paged("/campaign/GetLeadsFromCampaign", {"campaignId": int(campaign_id)}, max_items=max_items)

    def campaign_sequence(self, campaign_id):
        return self._call("GET", "/campaign/GetCampaignSequence", params={"campaignId": int(campaign_id)})

    def conversations(self, campaign_ids=None, max_items=None):
        body = {"filters": {"campaignIds": [int(c) for c in (campaign_ids or [])]}}
        return self._paged("/inbox/GetConversationsV2", body, max_items=max_items)

    def stats_by_campaign(self, start, end, campaign_ids=None):
        return self._call("POST", "/stats/GetOverallStatsByCampaign", {
            "accountIds": [], "campaignIds": [int(c) for c in (campaign_ids or [])],
            "startDate": start, "endDate": end,
        })


# ---- mapping HeyReach shapes to gtm_bot leads ----------------------------

def _custom_fields(profile):
    return {(f.get("name") or "").strip(): f.get("value") for f in (profile.get("customFields") or []) if f.get("name")}


COMPANY_DESCRIPTION_FIELDS = ("company_description", "company description", "company_summary", "company_about")
EMPLOYEE_FIELDS = ("employee_count", "employees", "company_size", "headcount")


def _employees(v):
    try:
        return int(str(v).replace(",", "").split("-")[0].strip().rstrip("+"))
    except (TypeError, ValueError):
        return None


def to_lead(profile, signal_field="signal", signal_date_field="signal_date"):
    """Normalize a HeyReach lead/correspondent/network profile into a gtm_bot lead."""
    p = profile.get("linkedInUserProfile") or profile
    cf = _custom_fields(p)
    cf_lower = {k.lower(): v for k, v in cf.items()}
    lead = {
        "id": p.get("profileUrl") or p.get("linkedin_id"),
        "name": " ".join(x for x in [p.get("firstName"), p.get("lastName")] if x),
        "first_name": p.get("firstName") or "",
        "headline": p.get("headline") or "",
        "position": p.get("position") or "",
        "company": p.get("companyName") or "",
        "location": p.get("location") or "",
        "about": (p.get("about") or p.get("summary") or "")[:1200],
        "profile_url": p.get("profileUrl"),
        "company_description": next((cf_lower[k] for k in COMPANY_DESCRIPTION_FIELDS if cf_lower.get(k)), None),
        "industry": p.get("industry") or cf_lower.get("industry"),
        "employee_count": next((_employees(cf_lower[k]) for k in EMPLOYEE_FIELDS if cf_lower.get(k)), None),
        "custom_fields": cf,
        "tags": p.get("tags") or [],
    }
    sig = cf_lower.get(signal_field.lower())
    if sig:
        lead["signal"] = {"text": sig, "date": cf_lower.get(signal_date_field.lower())}
    return lead


MERGE_TAG = re.compile(r"\{([A-Za-z0-9_ ]+)\}")


def render_template(template, lead):
    """Fill HeyReach-style {FIRST_NAME} merge tags; unknown tags are left in place."""
    first, _, last = (lead.get("name") or "").partition(" ")
    known = {
        "FIRST_NAME": lead.get("first_name") or first,
        "LAST_NAME": last,
        "COMPANY": lead.get("company"),
        "COMPANY_NAME": lead.get("company"),
        "POSITION": lead.get("position"),
        "LOCATION": lead.get("location"),
    }
    known.update({k.upper(): v for k, v in (lead.get("custom_fields") or {}).items()})

    def fill(m):
        v = known.get(m.group(1).strip().upper())
        return str(v) if v else m.group(0)

    return MERGE_TAG.sub(fill, template)


def first_touch_templates(sequence):
    """Pull the connection note and first message templates out of a campaign sequence tree."""
    found = {"connection_note": [], "first_message": []}
    seen_message = False
    stack = [sequence] if sequence else []
    while stack:
        node = stack.pop(0)
        if not isinstance(node, dict):
            continue
        payload = node.get("payload") or {}
        if node.get("nodeType") == "CONNECTION_REQUEST":
            found["connection_note"].extend(m for m in payload.get("messages") or [] if m)
        elif node.get("nodeType") in ("MESSAGE", "INMAIL") and not seen_message:
            found["first_message"].extend(m for m in payload.get("messages") or [] if m)
            seen_message = True
        # conditionalNode = path taken when the previous step succeeded (e.g. connection accepted)
        stack.extend(n for n in (node.get("conditionalNode"), node.get("unconditionalNode")) if n)
    return found


def conversation_example(convo, signal_field="signal"):
    """Turn an inbox conversation into (lead, first outbound message, replied) or None."""
    msgs = sorted(convo.get("messages") or [], key=lambda m: m.get("createdAt") or "")
    if not msgs or msgs[0].get("sender") != "ME" or convo.get("groupChat"):
        return None
    first = (msgs[0].get("body") or "").strip()
    if not first:
        return None
    replied = any(m.get("sender") != "ME" for m in msgs[1:])
    lead = to_lead(convo.get("correspondentProfile") or {}, signal_field=signal_field)
    return {"lead": lead, "message": first, "replied": replied, "sent_at": msgs[0].get("createdAt"),
            "conversation_id": convo.get("id")}
