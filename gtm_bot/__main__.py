"""GTM Bot: score LinkedIn leads and messages with Jev, sort them back into HeyReach. Never sends.

  python -m gtm_bot demo
  python -m gtm_bot score LEADS.json|LEADS.csv --config CONFIG.json [--model MODEL.json]

  python -m gtm_bot hr start --config CONFIG.json [--messages FILE]
      Looks at the workspace and picks a mode:
        campaign mode   past conversations exist: learn reply patterns from the inbox,
                        then rank the leads waiting in live/draft campaigns and pick a variant per lead
        cold start      no history, but a LinkedIn sender is connected: score its network
                        (plus any lead lists) against the ICP and check draft messages

  python -m gtm_bot hr check | campaigns | lists | accounts
  python -m gtm_bot hr calibrate --config CONFIG.json [--campaign-ids 1,2] [--max 500]
  python -m gtm_bot hr score --config CONFIG.json --campaign-id N | --list-id N [--messages FILE] [--model M]
  python -m gtm_bot hr network --config CONFIG.json [--account-id N] [--messages FILE] [--enrich]

  python -m gtm_bot hr setup --from RUN/raw.json --messages TEMPLATES.txt [--prefix NAME] [--tiers A,B] [--dry-run]
  python -m gtm_bot hr setup --campaigns-from RUN/setup.json
      The only command that writes: one lead list per tier (with the GTM Bot verdict as custom
      fields) and one DRAFT campaign per tier. Campaigns are never started; nothing is sent.
"""

import argparse
import csv
import json
import os
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

warnings.filterwarnings("ignore")

from . import heyreach as HR  # noqa: E402
from .calibrate import fit_model  # noqa: E402
from .jev import Jev  # noqa: E402
from .report import write  # noqa: E402
from .scoring import evaluate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
OUT = ROOT / "data" / "gtm_bot"
LIVE_STATUSES = {"DRAFT", "IN_PROGRESS", "PAUSED", "SCHEDULED", "STARTING"}
MIN_HISTORY = 30  # outbound conversations needed before campaign mode is worth calibrating


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _out_dir(args, name):
    return Path(args.out) if getattr(args, "out", None) else OUT / f"{name}-{datetime.now():%Y%m%d-%H%M%S}"


def _jev(cfg):
    return Jev(model=cfg.get("jev_model", "jev-latest"))


def _run(cfg, leads, model, out_dir, title="GTM Bot", note=None, top=None):
    results, meta = evaluate(cfg, leads, _jev(cfg), model=model)
    path = write(results, meta, cfg, out_dir, title, note)
    print(f"\n{'#':>3}  {'lead':<24} tier  lead  msg  reply")
    for i, r in enumerate(results[:top] if top else results, 1):
        best = next((v for v in r["variants"] if v["label"] == r["best"]), None)
        msg = f"{best['score']:>4.0f}" if best else "   -"
        reply = f"{r['reply_p']:>5.1%}" if r["reply_p"] is not None else "    -"
        print(f"{i:>3}  {(r['lead'].get('name') or '?')[:24]:<24} {r['lead_score']['tier']:<4} "
              f"{r['lead_score']['score']:>4.0f} {msg}  {reply}")
    if top and len(results) > top:
        print(f"  ... {len(results) - top} more in the report")
    tiers = {t: sum(r["lead_score"]["tier"] == t for r in results) for t in ("A", "B", "C", "Skip")}
    print(f"\ntiers: {tiers}")
    print(f"{meta['requests']} Jev requests · {meta['judgments']} judgments · {meta['wall_seconds']}s · "
          f"${meta['cost_usd']:.4f} · {meta['model']} · mode={meta['mode']}")
    print(f"report: {path}")
    return results, meta


def _split_messages(text):
    return [m.strip() for m in text.split("\n---\n") if m.strip()]


def _attach(leads, templates):
    for lead in leads:
        lead["messages"] = [{"label": f"Variant {chr(65 + i)}" if len(templates) > 1 else "Message",
                             "text": HR.render_template(t, lead)} for i, t in enumerate(templates)]
    return leads


# ---- CSV leads ---------------------------------------------------------------

def load_csv(path):
    """Leads from a CSV export (Sales Navigator, Clay, ...). Column names are matched loosely."""
    def pick(row, *names):
        for n in names:
            v = row.get(n)
            if v not in (None, ""):
                return v.strip()
        return ""

    leads = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row = {(k or "").strip().lower().replace(" ", "_"): v for k, v in row.items()}
            first, last = pick(row, "first_name", "firstname"), pick(row, "last_name", "lastname")
            lead = {
                "id": pick(row, "profile_url", "linkedin_url", "linkedin") or None,
                "name": pick(row, "name", "full_name") or f"{first} {last}".strip(),
                "first_name": first,
                "headline": pick(row, "headline"),
                "position": pick(row, "position", "title", "job_title"),
                "company": pick(row, "company", "company_name", "companyname"),
                "company_description": pick(row, "company_description", "company_summary") or None,
                "industry": pick(row, "industry") or None,
                "employee_count": HR._employees(pick(row, "employee_count", "employees", "company_size", "headcount")),
                "about": pick(row, "about", "summary")[:1200],
                "profile_url": pick(row, "profile_url", "linkedin_url", "linkedin") or None,
                "custom_fields": row,
            }
            if pick(row, "signal"):
                lead["signal"] = {"text": pick(row, "signal"), "date": pick(row, "signal_date") or None}
            msgs = [row[k] for k in sorted(row) if k.startswith("message") and row[k]]
            if msgs:
                lead["messages"] = msgs
            leads.append(lead)
    return leads


# ---- local commands ----------------------------------------------------------

def cmd_demo(args):
    cfg, leads = _json(HERE / "demo" / "config.json"), _json(HERE / "demo" / "leads.json")
    for lead in leads:  # score the example signals as of the day they were written for, so the output never drifts
        lead.setdefault("as_of", cfg.get("as_of"))
    _run(cfg, leads, None, _out_dir(args, "demo"), "GTM Bot · demo")


def cmd_score(args):
    cfg = _json(args.config)
    leads = load_csv(args.leads) if args.leads.endswith(".csv") else _json(args.leads)
    if args.messages:
        _attach(leads, _split_messages(Path(args.messages).read_text(encoding="utf-8")))
    model = _json(args.model) if args.model else None
    _run(cfg, leads, model, _out_dir(args, Path(args.leads).stem))


# ---- HeyReach building blocks -------------------------------------------------

def calibrate_from_inbox(hr, cfg, campaign_ids=None, max_items=500, signal_field="signal", out_dir=None):
    convos = hr.conversations(campaign_ids, max_items=max_items)
    examples = [e for e in (HR.conversation_example(c, signal_field) for c in convos) if e]
    replied = sum(e["replied"] for e in examples)
    print(f"inbox: {len(convos)} conversations -> {len(examples)} started by you ({replied} replied)")
    # as_of = send date, so a signal is aged as it was when the message went out
    leads = [{**e["lead"], "messages": [e["message"]], "as_of": e["sent_at"]} for e in examples]
    results, meta = evaluate(cfg, leads, _jev(cfg))
    label = {id(lead): e["replied"] for lead, e in zip(leads, examples)}
    rows = [(r["variants"][0]["features"], label[id(r["lead"])]) for r in results]
    if out_dir:  # every past conversation as scored, for inspection
        convo = {id(lead): e["conversation_id"] for lead, e in zip(leads, examples)}
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "history.json").write_text(json.dumps({"meta": meta, "rows": [
            {"conversation_id": convo[id(r["lead"])], "lead_id": r["lead"]["id"], "replied": label[id(r["lead"])],
             "prior_reply_p": r["reply_p"], "lead_score": r["lead_score"], "lead_answers": r["lead_answers"],
             "message": r["variants"][0]["text"], "message_score": r["variants"][0]["score"],
             "message_answers": r["variants"][0]["answers"], "code": r["variants"][0]["code"],
             "features": r["variants"][0]["features"]} for r in results]}, indent=1, default=str), encoding="utf-8")
    model, insights = fit_model(rows)
    print(f"Jev: {meta['requests']} requests · {meta['wall_seconds']}s · ${meta['cost_usd']:.4f}")
    return model, insights


def print_model(model, insights):
    auc = f"{model['auc_cv']:.3f}" if model["auc_cv"] is not None else "n/a"
    print(f"model: {model['kind']} · n={model['n']} · reply rate {model['reply_rate']:.1%} · cross-validated AUC {auc}")
    print("\nwhat gets replies in this account:")
    for i in insights:
        print(f"  {i['split']:<36} yes {i['reply_yes']:>5.1%} (n={i['n_yes']:<4}) vs no {i['reply_no']:>5.1%} (n={i['n_no']})")


def save_model(model, insights, path, campaign_ids=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**model, "insights": insights, "campaign_ids": campaign_ids or [],
                                "trained_at": datetime.now(timezone.utc).isoformat()}, indent=2), encoding="utf-8")
    print(f"saved {path}")


def campaign_leads(hr, campaign, max_items, signal_field):
    raw = hr.leads_from_campaign(campaign["id"], max_items=max_items)
    if not raw and campaign.get("linkedInUserListId"):  # drafts have no campaign leads yet: read the attached list
        raw = hr.leads_from_list(campaign["linkedInUserListId"], max_items=max_items)
    return [HR.to_lead(p, signal_field=signal_field) for p in raw]


def campaign_templates(hr, campaign_id):
    t = HR.first_touch_templates(hr.campaign_sequence(campaign_id))
    return t["first_message"] or t["connection_note"]


def base_rate(hr, campaign_ids=None):
    end = datetime.now(timezone.utc)
    s = hr.stats_by_campaign((end - timedelta(days=90)).isoformat(), end.isoformat(), campaign_ids) or {}
    rows = [x for x in s.get("overallStats") or [] if x.get("messagesSent")]
    sent = sum(x.get("totalMessageStarted") or x["messagesSent"] for x in rows)
    replies = sum(x.get("totalMessageReplies") or 0 for x in rows)
    return replies / sent if sent else None


def network_leads(hr, account_ids, max_items, enrich):
    leads, seen = [], set()
    for acc in account_ids:
        for p in hr.network(acc, max_items=max_items):
            lead = HR.to_lead(p)
            if not lead["id"] or lead["id"] in seen:
                continue
            seen.add(lead["id"])
            lead["source"] = "network"
            thin = not (lead["headline"] and lead["position"] and (lead["industry"] or lead["company_description"]))
            if enrich and thin and lead["profile_url"]:
                full = hr.get_lead(lead["profile_url"]) or {}
                lead.update({k: v for k, v in HR.to_lead(full).items() if v and not lead.get(k)})
            leads.append(lead)
    return leads


# ---- HeyReach commands ----------------------------------------------------------

def cmd_hr(args):
    if args.hr_cmd == "setup":
        return hr_setup(args)
    hr = HR.HeyReach()
    fn = {"check": hr_check, "campaigns": hr_campaigns, "lists": hr_lists, "accounts": hr_accounts,
          "score": hr_score, "calibrate": hr_calibrate, "network": hr_network, "start": hr_start}[args.hr_cmd]
    fn(hr, args)


def hr_check(hr, args):
    hr.check()
    print("HeyReach API key OK (read-only client)")
    print("workspace:", hr.workspace_summary())


def hr_campaigns(hr, args):
    end = datetime.now(timezone.utc)
    stats = hr.stats_by_campaign((end - timedelta(days=90)).isoformat(), end.isoformat()) or {}
    by_id = {s["campaignId"]: s for s in stats.get("overallStats") or []}
    for c in hr.campaigns():
        s = by_id.get(c["id"], {})
        print(f"{c['id']:>8}  {(c.get('status') or ''):<12} list={c.get('linkedInUserListId')!s:<8} "
              f"sent={s.get('messagesSent', 0):>5} reply={s.get('messageReplyRate', 0):>5.1%}  {c['name']}")


def hr_lists(hr, args):
    for li in hr.lists():
        print(f"{li['id']:>8}  {li.get('totalItemsCount', 0):>6} leads  {li.get('listType') or '':<12} {li['name']}")


def hr_accounts(hr, args):
    for a in hr.accounts():
        print(f"{a['id']:>8}  {'active' if a.get('isActive') else 'inactive':<8} "
              f"campaigns={a.get('activeCampaigns', 0)}  {a.get('firstName', '')} {a.get('lastName', '')}  {a.get('profileUrl', '')}")


def hr_calibrate(hr, args):
    cfg = _json(args.config)
    ids = [c for c in (args.campaign_ids or "").split(",") if c]
    path = Path(args.out) if args.out else OUT / "model.json"
    try:
        model, insights = calibrate_from_inbox(hr, cfg, ids, args.max, args.signal_field, out_dir=path.parent)
    except ValueError as e:
        sys.exit(f"not enough reply history to learn from yet ({e}). Keep sending and run it again.")
    print_model(model, insights)
    save_model(model, insights, path, ids)


def hr_score(hr, args):
    cfg = _json(args.config)
    if args.campaign_id:
        campaign = {"id": args.campaign_id}
        campaign.update(next((c for c in hr.campaigns() if c["id"] == args.campaign_id), {}))
        leads = campaign_leads(hr, campaign, args.max, args.signal_field)
    elif args.list_id:
        leads = [HR.to_lead(p, signal_field=args.signal_field) for p in hr.leads_from_list(args.list_id, max_items=args.max)]
    else:
        sys.exit("pass --campaign-id or --list-id")

    templates = (_split_messages(Path(args.messages).read_text(encoding="utf-8")) if args.messages
                 else campaign_templates(hr, args.campaign_id) if args.campaign_id else [])
    if templates:
        _attach(leads, templates)

    if args.campaign_id and "base_rate" not in cfg.get("weights", {}).get("reply", {}):
        rate = base_rate(hr, [args.campaign_id])
        if rate:
            cfg.setdefault("weights", {}).setdefault("reply", {})["base_rate"] = rate
            print(f"base reply rate from HeyReach (90d): {rate:.1%}")

    model = _json(args.model) if args.model else None
    print(f"scoring {len(leads)} leads x {len(templates) or 'no'} message variant(s) with Jev (nothing is sent)")
    _run(cfg, leads, model, _out_dir(args, f"hr-{args.campaign_id or args.list_id}"))


def hr_network(hr, args):
    cfg = _json(args.config)
    accounts = [args.account_id] if args.account_id else [a["id"] for a in hr.accounts()]
    if not accounts:
        sys.exit("no LinkedIn sender connected in this HeyReach workspace")
    leads = network_leads(hr, accounts, args.max, args.enrich)
    if args.messages:
        _attach(leads, _split_messages(Path(args.messages).read_text(encoding="utf-8")))
    print(f"scoring {len(leads)} 1st-degree connections against your ICP (nothing is sent)")
    _run(cfg, leads, None, _out_dir(args, "network"), note="Your LinkedIn network, ranked against your ICP", top=25)


def hr_start(hr, args):
    cfg = _json(args.config)
    ws = hr.workspace_summary()
    print("workspace:", ws)
    out = _out_dir(args, "start")

    if ws["conversations"] >= MIN_HISTORY:
        print("\n== campaign mode: you have outreach history, so learn from it first ==")
        model = None
        try:
            model, insights = calibrate_from_inbox(hr, cfg, None, args.max_history, args.signal_field, out_dir=out)
            print_model(model, insights)
            save_model(model, insights, out / "model.json")
        except ValueError as e:
            print(f"not enough reply history to calibrate ({e}); using prior weights")
            rate = base_rate(hr)
            if rate:
                cfg.setdefault("weights", {}).setdefault("reply", {})["base_rate"] = rate

        live = [c for c in hr.campaigns() if (c.get("status") or "").upper() in LIVE_STATUSES]
        if not live:
            print("\nno live or draft campaigns to score. Create one in HeyReach and re-run.")
        for c in live[:args.max_campaigns]:
            leads = campaign_leads(hr, c, args.max, args.signal_field)
            templates = (_split_messages(Path(args.messages).read_text(encoding="utf-8")) if args.messages
                         else campaign_templates(hr, c["id"]))
            if not leads:
                continue
            if templates:
                _attach(leads, templates)
            print(f"\n== campaign {c['id']} '{c['name']}' ({c.get('status')}): "
                  f"{len(leads)} leads x {len(templates)} variant(s) ==")
            _run(cfg, leads, model, out / f"campaign-{c['id']}", note=f"Campaign: {c['name']}", top=15)

    elif ws["linkedin_accounts"] or ws["lists"]:
        print("\n== cold start: no outreach history yet, so rank who to target first ==")
        leads = network_leads(hr, [a["id"] for a in hr.accounts()], args.max, args.enrich) if ws["linkedin_accounts"] else []
        print(f"network: {len(leads)} 1st-degree connections" if ws["linkedin_accounts"]
              else "no LinkedIn sender connected, so scoring lead lists only")
        seen = {lead["id"] for lead in leads}
        for li in hr.lists():
            extra = [HR.to_lead(p, signal_field=args.signal_field) for p in hr.leads_from_list(li["id"], max_items=args.max)]
            extra = [lead for lead in extra if lead["id"] not in seen]
            for lead in extra:
                lead["source"] = f"list: {li['name']}"
                seen.add(lead["id"])
            print(f"list '{li['name']}': {len(extra)} leads")
            leads += extra
        if args.messages:
            _attach(leads, _split_messages(Path(args.messages).read_text(encoding="utf-8")))
        _run(cfg, leads, None, out / "targets", note="Cold start: your network and lists, ranked against your ICP", top=25)

    else:
        print("\nNothing to work with yet. Connect a LinkedIn sender or import a lead list in HeyReach, then re-run,\n"
              "or score a lead export directly: python -m gtm_bot score leads.csv --config CONFIG.json")


def hr_setup(args):
    from .hr_setup import HeyReachSetup, create_pending, run_setup
    hr = HeyReachSetup()
    if args.campaigns_from:
        return create_pending(hr, Path(args.campaigns_from))
    if not (args.from_run and args.messages):
        sys.exit("hr setup needs --from RUN/raw.json and --messages TEMPLATES.txt (or --campaigns-from setup.json)")
    results = _json(args.from_run)
    templates = _split_messages(Path(args.messages).read_text(encoding="utf-8"))
    tiers = tuple(t.strip() for t in args.tiers.split(","))
    out = Path(args.out) if args.out else Path(args.from_run).parent
    run_setup(hr, results, templates, args.prefix, out, tiers, dry_run=args.dry_run)


def main():
    load_env()
    ap = argparse.ArgumentParser(prog="gtm_bot", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("demo")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_demo)

    p = sub.add_parser("score")
    p.add_argument("leads")
    p.add_argument("--config", required=True)
    p.add_argument("--messages")
    p.add_argument("--model")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_score)

    p = sub.add_parser("hr")
    p.add_argument("hr_cmd", choices=["check", "campaigns", "lists", "accounts", "score", "calibrate", "network", "start", "setup"])
    p.add_argument("--config")
    p.add_argument("--list-id", type=int)
    p.add_argument("--campaign-id", type=int)
    p.add_argument("--campaign-ids")
    p.add_argument("--account-id", type=int)
    p.add_argument("--messages")
    p.add_argument("--model")
    p.add_argument("--max", type=int, default=500)
    p.add_argument("--max-history", type=int, default=500)
    p.add_argument("--max-campaigns", type=int, default=3)
    p.add_argument("--enrich", action="store_true", help="fill network profiles missing headline, position or industry with GetLead (read-only)")
    p.add_argument("--signal-field", default="signal")
    p.add_argument("--from", dest="from_run", help="setup: raw.json of a scoring run")
    p.add_argument("--campaigns-from", help="setup: create the saved draft campaigns once a sender is connected")
    p.add_argument("--prefix", default="[TEST] GTM Bot")
    p.add_argument("--tiers", default="A,B")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_hr)

    args = ap.parse_args()
    if args.cmd == "hr" and args.hr_cmd in ("score", "calibrate", "network", "start") and not args.config:
        ap.error(f"hr {args.hr_cmd} needs --config")
    args.fn(args)


if __name__ == "__main__":
    main()
