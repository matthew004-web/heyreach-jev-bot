"""Turn a GTM Bot run into HeyReach lead lists and DRAFT campaigns. Never starts or sends.

Kept apart from heyreach.py on purpose: the scoring client stays read-only.
This client adds exactly three writes: create a lead list, add leads to a list,
and create a campaign, which HeyReach always creates in DRAFT status. Starting
or resuming a campaign, adding leads to a campaign, and sending messages are
not in its allowlist, so a campaign made here does nothing until a person
starts it in HeyReach.
"""

import json
import re
import time
from collections import Counter

from .heyreach import MERGE_TAG as MERGE
from .heyreach import HeyReach, HeyReachError

WRITE_ALLOWED = {
    ("POST", "/list/CreateEmptyList"),
    ("POST", "/list/AddLeadsToListV2"),
    ("POST", "/campaign/Create"),
}
FIELD_NAME = re.compile(r"[^A-Za-z0-9_]")


class HeyReachSetup(HeyReach):
    def _write(self, path, body, retries=3):
        if ("POST", path) not in WRITE_ALLOWED:
            raise HeyReachError(f"blocked: POST {path} is not an allowed setup write")
        for attempt in range(retries + 1):
            r = self.session.post(self.base_url + path, json=body, timeout=self.timeout)
            if r.status_code == 429 and attempt < retries:  # rate limited before anything was created
                time.sleep(float(r.headers.get("retry-after") or 2 ** attempt))
                continue
            if r.status_code >= 400:
                raise HeyReachError(f"POST {path} -> HTTP {r.status_code}: {r.text[:400]}")
            return r.json() if r.text.strip() else None
        raise HeyReachError("retries exhausted")

    def create_list(self, name):
        return self._write("/list/CreateEmptyList", {"name": name, "type": "USER_LIST"})

    def add_leads(self, list_id, leads):
        totals = Counter()
        for i in range(0, len(leads), 100):
            res = self._write("/list/AddLeadsToListV2", {"listId": int(list_id), "leads": leads[i:i + 100]}) or {}
            totals.update({k: res.get(k, 0) for k in ("addedLeadsCount", "updatedLeadsCount", "failedLeadsCount")})
        return dict(totals)

    def create_draft_campaign(self, name, list_id, account_ids, sequence):
        body = {"name": name[:50], "linkedInUserListId": int(list_id), "linkedInAccountIds": [int(a) for a in account_ids],
                "excludeContactedFromOtherCampaigns": True, "excludeHasOtherAccConversations": True,
                "excludeContactedFromSenderInOtherCampaign": True, "sequence": sequence}
        return self._write("/campaign/Create", body)


# ---- building payloads from a scored run -----------------------------------------

def lead_payload(result, scored_at=None):
    """HeyReach lead payload with the GTM Bot verdict carried as custom fields."""
    lead, ls = result["lead"], result["lead_score"]
    first, _, last = (lead.get("name") or "").partition(" ")
    fields = {
        "gtm_tier": ls["tier"],
        "gtm_lead_score": f"{ls['score']:.0f}",
        "gtm_reply_p": f"{result['reply_p']:.3f}" if result.get("reply_p") is not None else "",
        "gtm_best_variant": result.get("best") or "",
        "gtm_why": " · ".join(ls["why"] + ls["flags"]),
        "gtm_scored_at": scored_at,
        "signal": (lead.get("signal") or {}).get("text"),
        "signal_date": (lead.get("signal") or {}).get("date"),
        "company_description": lead.get("company_description"),
        "employee_count": lead.get("employee_count"),
    }
    for k, v in (lead.get("custom_fields") or {}).items():  # keep the lead's own fields (signal_hook, ...)
        fields.setdefault(FIELD_NAME.sub("_", k), v)
    return {
        "firstName": lead.get("first_name") or first, "lastName": last,
        "position": lead.get("position") or "", "companyName": lead.get("company") or "",
        "summary": lead.get("headline") or "", "about": lead.get("about") or "", "location": lead.get("location") or "",
        "profileUrl": lead.get("profile_url") or lead.get("id"),
        "customUserFields": [{"name": k, "value": str(v)} for k, v in fields.items() if v not in (None, "")],
    }


def draft_sequence(templates, fallback):
    """Connection request without a note, then the first message 3 hours after the accept, then stop."""
    return {
        "nodeType": "CONNECTION_REQUEST", "actionDelay": 0, "actionDelayUnit": "DAY",
        "payload": {"messages": [], "fallbackMessage": None, "toBeWithdrawnAfterDays": 21},
        "conditionalNode": {
            "nodeType": "MESSAGE", "actionDelay": 3, "actionDelayUnit": "HOUR",
            "payload": {"messages": templates, "fallbackMessage": fallback},
            "unconditionalNode": {"nodeType": "END", "actionDelay": 3, "actionDelayUnit": "HOUR"},
        },
        "unconditionalNode": {"nodeType": "END", "actionDelay": 3, "actionDelayUnit": "HOUR"},
    }


def message_sequence(templates, fallback):
    """For 1st-degree connections: no connection request, the message goes out first, then stop."""
    return {
        "nodeType": "MESSAGE", "actionDelay": 0, "actionDelayUnit": "HOUR",
        "payload": {"messages": templates, "fallbackMessage": fallback},
        "unconditionalNode": {"nodeType": "END", "actionDelay": 3, "actionDelayUnit": "HOUR"},
    }


def is_connection(result):
    """Leads pulled from a sender's 1st-degree network are already connected: never send them a request."""
    return (result["lead"].get("source") or "") == "network"


def routing_plan(results, templates, tiers=("A", "B")):
    """Group leads by (tier, the variant Jev picked for them, already connected or not).

    A HeyReach campaign splits its A/B variants across all its leads, so to send
    each lead the variant Jev chose, every (tier, variant) pair gets its own list
    and a single-message campaign. 1st-degree connections get their own group, so
    their campaign starts with the message instead of a connection request.
    """
    labels = [f"Variant {chr(65 + i)}" if len(templates) > 1 else "Message" for i in range(len(templates))]
    groups = {}
    for r in results:
        tier = r["lead_score"]["tier"]
        if tier in tiers:
            groups.setdefault((tier, r.get("best"), is_connection(r)), []).append(r)
    plan = []
    for (tier, label, connected), rows in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or "", kv[0][2])):
        template = templates[labels.index(label)] if label in labels else None
        plan.append({"tier": tier, "variant": label, "connected": connected, "template": template, "results": rows})
    return plan


def _group_name(prefix, g):
    return f"{prefix} · {g['tier']} · {g['variant'] or 'no message'}" + (" · 1st-degree" if g["connected"] else "")


def _fallback(templates):
    """HeyReach sends the fallback when merge data is missing, so it must carry no merge tags."""
    return next((t for t in templates if not MERGE.search(t)), "Thanks for connecting!")


def run_setup(hr, results, templates, prefix, out_dir, tiers=("A", "B"), dry_run=False, scored_at=None):
    plan = routing_plan(results, templates, tiers)
    if dry_run:
        for g in plan:
            first = "message first" if g["connected"] else "connection request, then the message 3 hours after the accept"
            print(f"[dry run] {_group_name(prefix, g)}: {len(g['results'])} leads ({first})")
        print("[dry run] first lead payload:", json.dumps(lead_payload(plan[0]["results"][0], scored_at), indent=1)[:1500])
        return None
    accounts = [a["id"] for a in hr.accounts() if a.get("isActive", True) and a.get("authIsValid", True)]
    record = {"prefix": prefix, "lists": [], "campaigns": [], "pending_campaigns": []}
    fallback = _fallback(templates)
    for g in plan:
        name = _group_name(prefix, g)
        list_id = (hr.create_list(name) or {}).get("id")
        counts = hr.add_leads(list_id, [lead_payload(r, scored_at) for r in g["results"]])
        record["lists"].append({"tier": g["tier"], "variant": g["variant"], "connected": g["connected"], "id": list_id,
                                "name": name, "leads": len(g["results"]), **counts})
        print(f"list '{name}' (id {list_id}): {counts}")
        if not g["template"]:
            continue
        sequence = (message_sequence if g["connected"] else draft_sequence)([g["template"]], fallback)
        campaign = {"tier": g["tier"], "variant": g["variant"], "connected": g["connected"], "name": name[:50],
                    "list_id": list_id, "sequence": sequence}
        if accounts:
            campaign["id"] = (hr.create_draft_campaign(campaign["name"], list_id, accounts, campaign["sequence"]) or {}).get("campaignId")
            record["campaigns"].append(campaign)
            print(f"campaign '{campaign['name']}' created as DRAFT (id {campaign['id']}), not started")
        else:
            record["pending_campaigns"].append(campaign)
    if record["pending_campaigns"]:
        print(f"\n{len(record['pending_campaigns'])} campaign(s) not created: HeyReach needs at least one connected "
              f"LinkedIn sender to create a campaign. The payloads are saved; connect a sender and run "
              f"`hr setup --campaigns-from {out_dir / 'setup.json'}`.")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "setup.json").write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return record


def create_pending(hr, setup_path):
    """Second step once a LinkedIn sender is connected: create the saved campaigns, as DRAFTs."""
    rec = json.loads(setup_path.read_text(encoding="utf-8"))
    accounts = [a["id"] for a in hr.accounts() if a.get("isActive", True) and a.get("authIsValid", True)]
    if not accounts:
        raise HeyReachError("still no connected LinkedIn sender with valid auth in this workspace")
    for c in rec.get("pending_campaigns") or []:
        res = hr.create_draft_campaign(c["name"], c["list_id"], accounts, c["sequence"]) or {}
        c["id"] = res.get("campaignId")
        rec.setdefault("campaigns", []).append(c)
        print(f"campaign '{c['name']}' created as DRAFT (id {c['id']}), not started")
    rec["pending_campaigns"] = []
    setup_path.write_text(json.dumps(rec, indent=2, default=str), encoding="utf-8")
