"""GTM Bot giveaway: Jev lead scoring run on someone's HeyReach, sorted back into it.

  python -m gtm_bot.giveaway new HANDLE       intake template, filled from their DM
  python -m gtm_bot.giveaway run HANDLE [--dry-run]
  python -m gtm_bot.giveaway status

What `run` does in their workspace:
  1. Reads it. With 30+ past conversations it first learns what earns replies there.
  2. Scores the leads not yet being contacted: the lists behind draft campaigns, lists not
     attached to any campaign, and the sender's network when there are no lists.
  3. Pushes back one list per (tier, the variant Jev picked), with the verdict as custom
     fields, and a single-message DRAFT campaign for each. Nothing is started or sent.
  4. Writes report.html, scores.json and deliver.md (the DM to send them) to their folder.

Their HeyReach API key is never stored: `run` asks for it at a hidden prompt (or reads it
from stdin with --key-stdin), holds it in memory for that run only, and never writes it
to disk, logs or output.
"""

import argparse
import getpass
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

from . import heyreach as HR
from .__main__ import (MIN_HISTORY, _attach, calibrate_from_inbox, campaign_leads, campaign_templates,
                       load_env, network_leads, save_model)
from .hr_setup import HeyReachSetup, run_setup
from .jev import Jev
from .report import write
from .scoring import evaluate

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "data" / "gtm_bot" / "giveaway"
OURS = ("[GTM]", "[TEST] GTM Bot")  # lists we created: never re-scored
PUSH_TIERS = ("A", "B")


def _handle(h):
    return re.sub(r"[^a-z0-9_.-]", "", h.lower().lstrip("@"))


def _dir(h):
    return FOLDER / _handle(h)


def _ask_key(handle, from_stdin):
    if from_stdin:
        key = sys.stdin.readline().strip()
    elif sys.stdin.isatty():
        key = getpass.getpass(f"HeyReach API key for @{handle} (hidden, used for this run only): ").strip()
    else:
        sys.exit("run this in a terminal (the key is typed at a hidden prompt), or pipe it with --key-stdin")
    if not key:
        sys.exit("no key given")
    return key


# ---- commands --------------------------------------------------------------------

def cmd_new(a):
    d = _dir(a.handle)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "intake.json"
    if path.exists():
        sys.exit(f"{path} already exists")
    path.write_text(json.dumps({
        "handle": _handle(a.handle),
        "requested_at": date.today().isoformat(),
        "offer": {"what_we_sell": "", "problem_it_solves": ""},
        "icp": {"target_roles": [], "target_companies": "", "employee_range": [20, 500],
                "exclude": ["Agencies that sell the same thing we sell", "Recruiters"]},
        "messages": [],
        "include_network": False,
        "max_leads": 500,
        "status": "intake",
    }, indent=2), encoding="utf-8")
    print(f"fill {path} from their DM, then: python -m gtm_bot.giveaway run {_handle(a.handle)} --dry-run")


def cmd_status(a):
    for d in sorted(FOLDER.glob("*/intake.json")):
        i = json.loads(d.read_text())
        print(f"@{i['handle']:<24} {i.get('status', ''):<10} requested {i.get('requested_at', ''):<11} "
              f"ran {i.get('ran_at', '-'):<17} {i.get('summary', '')}")


def sources(hr, intake, max_leads):
    """(label, leads, templates) groups: draft campaigns, then unattached lists, then the network."""
    campaigns = hr.campaigns()
    lists = hr.lists()
    attached = {c.get("linkedInUserListId") for c in campaigns}
    groups, seen = [], set()

    def keep(leads):
        out = []
        for lead in leads:
            if lead["id"] and lead["id"] not in seen:
                seen.add(lead["id"])
                out.append(lead)
        return out

    for c in campaigns:
        if (c.get("status") or "").upper() == "DRAFT" and not c["name"].startswith(OURS):
            leads = keep(campaign_leads(hr, c, max_leads, "signal"))
            if leads:
                groups.append((c["name"], leads, campaign_templates(hr, c["id"])))
    for li in lists:
        if li["id"] in attached or li["name"].startswith(OURS) or (li.get("listType") or "USER_LIST") != "USER_LIST":
            continue
        leads = keep([HR.to_lead(p) for p in hr.leads_from_list(li["id"], max_items=max_leads)])
        if leads:
            groups.append((li["name"], leads, intake.get("messages") or []))
    if intake.get("include_network") or not groups:
        accounts = [x["id"] for x in hr.accounts()]
        if accounts:
            leads = keep(network_leads(hr, accounts, max_leads, enrich=True))
            if leads:
                groups.append(("LinkedIn network", leads, intake.get("messages") or []))
    return groups


def cmd_run(a):
    d = _dir(a.handle)
    intake = json.loads((d / "intake.json").read_text())
    if not (intake["offer"]["what_we_sell"] and intake["icp"]["target_roles"]):
        sys.exit("intake is missing the offer or target roles")
    hr = HeyReachSetup(api_key=_ask_key(intake["handle"], a.key_stdin))
    hr.check()
    cfg = {"offer": intake["offer"], "icp": intake["icp"], "weights": intake.get("weights", {})}
    ws = hr.workspace_summary()
    print(f"@{intake['handle']} workspace: {ws}")

    model, insights = None, []
    if ws["conversations"] >= MIN_HISTORY:
        try:
            model, insights = calibrate_from_inbox(hr, cfg, max_items=500, out_dir=d)
            save_model(model, insights, d / "model.json")
        except ValueError as e:
            print(f"not enough replies to learn from ({e}); using prior weights")

    groups = sources(hr, intake, intake.get("max_leads", 500))
    drafts = {c["name"] for c in hr.campaigns() if (c.get("status") or "").upper() == "DRAFT"}
    if not groups:
        sys.exit("nothing to score: no draft campaigns, no unused lists, no connected sender")
    jev = Jev()
    scored_at = date.today().isoformat()
    t0 = time.time()
    all_results, created = [], []
    for label, leads, templates in groups:
        if templates:
            _attach(leads, templates)
        results, _ = evaluate(cfg, leads, jev, model=model)
        all_results += results
        tiers = {t: sum(r["lead_score"]["tier"] == t for r in results) for t in ("A", "B", "C", "Skip")}
        print(f"\n{label}: {len(leads)} leads x {len(templates) or 'no'} variant(s) -> {tiers}")
        rec = run_setup(hr, results, templates, f"[GTM] {label[:22]}",
                        d / (re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "source"),
                        PUSH_TIERS, dry_run=a.dry_run, scored_at=scored_at)
        if rec:
            created.append({"source": label, "from_draft": label in drafts, **rec})

    meta = {**jev.summary(), "wall_seconds": round(time.time() - t0, 1),
            "judgments": sum(len(r["lead_answers"]) + sum(len(v["answers"]) for v in r["variants"]) for r in all_results),
            "mode": "calibrated" if model else "prior",
            "model_info": model and {k: model[k] for k in ("n", "reply_rate", "auc_cv", "kind")}}
    all_results.sort(key=lambda r: (r["lead_score"]["tier"] != "Skip",
                                    r["reply_p"] if r["reply_p"] is not None else r["lead_score"]["score"] / 100),
                     reverse=True)
    report = write(all_results, meta, cfg, d, f"GTM Bot · @{intake['handle']}")
    (d / "deliver.md").write_text(deliver_text(all_results, created, insights), encoding="utf-8")

    tiers = {t: sum(r["lead_score"]["tier"] == t for r in all_results) for t in ("A", "B", "C", "Skip")}
    intake.update(status="dry-run" if a.dry_run else "pushed", ran_at=datetime.now().isoformat(timespec="minutes"),
                  summary=f"{len(all_results)} leads {tiers}")
    (d / "intake.json").write_text(json.dumps(intake, indent=2), encoding="utf-8")
    print(f"\n{meta['requests']} Jev requests · {meta['judgments']} judgments · {meta['wall_seconds']}s · "
          f"${meta['cost_usd']:.4f}\nreport: {report}\nDM to send: {d / 'deliver.md'}")


def deliver_text(results, created, insights):
    tiers = {t: sum(r["lead_score"]["tier"] == t for r in results) for t in ("A", "B", "C", "Skip")}
    lists = sum(len(c["lists"]) for c in created)
    drafts = sum(len(c["campaigns"]) for c in created)
    pending = sum(len(c["pending_campaigns"]) for c in created)
    top = [r for r in results if r["lead_score"]["tier"] == "A"][:5]
    lines = [
        "Your GTM Bot is in your HeyReach.",
        "",
        f"Jev scored {len(results)} leads against your ICP: {tiers['A']} tier A, {tiers['B']} tier B, "
        f"{tiers['C']} tier C, {tiers['Skip']} skipped (agencies, recruiters, job seekers, excluded).",
        "",
    ]
    if drafts:
        lines.append(f"I added {lists} lists and {drafts} draft campaigns, each named [GTM]. Every lead is routed to the "
                     f"message variant Jev picked for them. Nothing is started: open the tier A drafts and start them.")
        replaced = [c["source"] for c in created if c.get("from_draft") and c["campaigns"]]
        if replaced:
            lines.append(f"Your draft {', '.join(repr(r) for r in replaced)} is untouched. Start the [GTM] drafts "
                         f"instead of it so nobody gets two messages.")
    elif lists:
        lines.append(f"I added {lists} lists named [GTM], one per tier and message. "
                     + (f"Connect a LinkedIn sender and I can turn them into {pending} draft campaigns."
                        if pending else "Attach them to a campaign when you're ready."))
    if top:
        lines += ["", "Start with:"] + [f"- {r['lead'].get('name')}: {' · '.join(r['lead_score']['why'])}" for r in top]
    if insights:
        habits = [i for i in insights if not i["split"].endswith("score 70+")]  # message habits, not our own scores
        best = sorted(habits, key=lambda i: abs(i["reply_yes"] - i["reply_no"]), reverse=True)[:3]
        lines += ["", "What earns replies in your account:"] + [
            f"- {i['split']}: {i['reply_yes']:.0%} replied vs {i['reply_no']:.0%}" for i in best]
    return "\n".join(lines) + "\n"


def main():
    load_env()
    ap = argparse.ArgumentParser(prog="giveaway", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new")
    p.add_argument("handle")
    p.set_defaults(fn=cmd_new)
    p = sub.add_parser("run")
    p.add_argument("handle")
    p.add_argument("--dry-run", action="store_true", help="score everything, write nothing to their HeyReach")
    p.add_argument("--key-stdin", action="store_true", help="read their key from stdin instead of a prompt")
    p.set_defaults(fn=cmd_run)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
