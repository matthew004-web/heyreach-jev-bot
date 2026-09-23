"""HTML page for the fake-workspace test results."""

import html


def _e(s):
    return html.escape(str(s))


def _pct(v):
    return "n/a" if v is None else f"{v:.0%}"


def _table(head, rows, cls=""):
    th = "".join(f"<th>{_e(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table class='{cls}'><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def _bar(v, vmax):
    w = 0 if not vmax else max(0, min(1, v / vmax)) * 100
    return f"<span class='bar'><i style='width:{w:.0f}%'></i></span>"


LABELS = {
    "function_fit": "Role fit (4 levels, exact)", "function_fit_within1": "Role fit (within one level)",
    "seniority": "Seniority (5 levels, exact)", "seniority_within1": "Seniority (within one level)",
    "company_type_with_description": "Company type, with description", "company_type_network_profiles": "Company type, thin network profiles",
    "skip_precision": "Auto-skip precision", "skip_recall": "Auto-skip recall (agencies, recruiters, job seekers)",
    "signal_type": "Signal type (7 options)", "signal_on_vs_off_topic": "Signal on-topic vs off-topic",
    "ask_type": "What the message asks for (5 options)", "mentions_signal": "Message mentions the signal",
    "pitches": "Message pitches the product", "stock_phrasing": "Stock outreach phrasing", "tracking_reveal": "Reveals private tracking",
    "unfilled_merge_tag (code)": "Unfilled merge tag (checked in code)",
}


def render(r):
    j = r["jev"]
    judg = [(LABELS.get(k, k), f"<b>{_pct(v[0])}</b>", _bar(v[0] or 0, 1), v[1])
            for k, v in r["judgments"].items() if isinstance(v, (list, tuple))]
    rp = r["reply_prediction"]
    pred = [(_e(k), f"<b>{a:.2f}</b>", _bar(max(0, a - 0.5), 0.5), f"{c:.0%}") for k, (a, c) in rp.items()]
    cal = [(f"{p:.1%}", f"{o:.1%}", f"{t:.1%}", n) for p, o, t, n in r["calibration_quintiles"]]
    vmax = max(r["variant_choice_per_100"].values())
    var = [(_e(k), f"<b>{v:.1f}</b>", _bar(v, vmax)) for k, v in r["variant_choice_per_100"].items()]
    pmax = max(r["prioritization_expected_replies"].values())
    pri = [(_e(k), f"<b>{v:.1f}</b>", _bar(v, pmax)) for k, v in r["prioritization_expected_replies"].items()]
    cs = r["coldstart"]
    cold = [(_e(k), _e(f"{v[0]} of {v[1]} ({v[0] / max(1, v[1]):.0%})" if isinstance(v, (list, tuple)) else
                      f"{v:.0%}" if isinstance(v, float) else v)) for k, v in cs.items()]
    ins = [(_e(i["split"]), f"{i['reply_yes']:.0%} <small>n={i['n_yes']}</small>", f"{i['reply_no']:.0%} <small>n={i['n_no']}</small>")
           for i in r.get("insights") or []]
    s = r["safety"]
    eps = [(_e(k), v) for k, v in sorted(s["endpoints"].items(), key=lambda kv: -kv[1])]
    b = r["broken_sends"]

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GTM Bot Test</title>
<style>
:root{{--bg:#f7f7f5;--card:#fff;--ink:#16181d;--mute:#5d6470;--line:#e3e4e8;--accent:#2f5bea;--chip:#eef0f4;--good:#1f8a4c}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#0f1115;--card:#171a20;--ink:#e8eaee;--mute:#9aa1ad;--line:#2a2e37;--accent:#7c9cff;--chip:#232731;--good:#4ade80}}}}
:root[data-theme="dark"]{{--bg:#0f1115;--card:#171a20;--ink:#e8eaee;--mute:#9aa1ad;--line:#2a2e37;--accent:#7c9cff;--chip:#232731;--good:#4ade80}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Inter","Segoe UI",sans-serif}}
main{{max-width:980px;margin:0 auto;padding:32px 16px 64px}}h1{{font-size:26px;margin:0 0 6px}}h2{{font-size:18px;margin:34px 0 6px}}
p{{margin:0 0 12px;color:var(--mute)}}.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}}
.stat{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}}.stat b{{display:block;font-size:22px}}.stat span{{color:var(--mute);font-size:13px}}
.wrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:14px}}
th{{text-align:left;font-weight:600;color:var(--mute);font-size:12px;padding:8px 12px;border-bottom:1px solid var(--line)}}td{{padding:7px 12px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}}
tr:last-child td{{border-bottom:0}}.bar{{display:inline-block;width:120px;height:8px;background:var(--chip);border-radius:99px;overflow:hidden;vertical-align:middle}}
.bar i{{display:block;height:100%;background:var(--accent)}}small{{color:var(--mute)}}.ok{{color:var(--good);font-weight:600}}
</style></head><body><main>
<h1>GTM Bot · fake workspace test</h1>
<p>Two synthetic HeyReach workspaces (a team with campaign history, and a cold start with only a network and a list) served by a local fake HeyReach. The real CLI ran against them; every number below is graded against the truth the fake world was built from. The reply model in that world encodes common outbound wisdom, so section 2 and 3 show how well the pipeline recovers a known pattern, not what real LinkedIn replies do.</p>
<div class="stats">
<div class="stat"><b>{j['requests']:,}</b><span>Jev requests</span></div>
<div class="stat"><b>{j['judgments']:,}</b><span>Jev judgments</span></div>
<div class="stat"><b>{j['wall_seconds']:.0f}s</b><span>Jev wall time</span></div>
<div class="stat"><b>${j['cost_usd']:.3f}</b><span>Jev cost</span></div>
<div class="stat"><b class="ok">{len(s['outside_allowlist']) + len(s['blocked'])}</b><span>write attempts</span></div>
</div>

<h2>1. How accurately Jev reads leads and messages</h2>
<p>Each judgment compared with the attribute the fake lead or message was built from. Across {r['judgments']['n_messages']} messages and every lead scored.</p>
<div class="wrap">{_table(["Judgment", "Accuracy", "", "n"], judg)}</div>

<h2>2. Predicting replies on past conversations</h2>
<p>{r['model']['n']} past first touches, {r['model']['reply_rate']:.1%} replied. AUC: 0.5 is a coin flip, 1.0 is perfect ranking. The calibrated row is scored out-of-fold, on conversations it did not train on.</p>
<div class="wrap">{_table(["Ranking by", "AUC", "", "Top 20% catches"], pred)}</div>
<p style="margin-top:12px">Calibration of the trained model, by fifths of predicted probability:</p>
<div class="wrap">{_table(["Predicted", "Observed", "True", "n"], cal)}</div>
<p style="margin-top:12px">What the calibrated model reports about this account:</p>
<div class="wrap">{_table(["Message trait", "Replied when yes", "Replied when no"], ins)}</div>

<h2>3. The draft campaign: 60 leads, 3 A/B variants</h2>
<p>Expected replies per 100 leads under each sending strategy, using each lead's true reply probability. Leads without a signal would get an unfilled {{SIGNAL_HOOK}} from variants A and C: a random split sends {b['random']:.0f} broken messages; Jev's picks send {b['jev']}.</p>
<div class="wrap">{_table(["Strategy", "Replies / 100", ""], var)}</div>
<p style="margin-top:12px">If you only contact a third of the list:</p>
<div class="wrap">{_table(["Who gets contacted", "Expected replies", ""], pri)}</div>

<h2>4. Cold start: network + one imported list, no history</h2>
<p>Everyone ranked against the ICP. True ICP = exact-fit role at a target company of the right size, not an agency, recruiter or job seeker.</p>
<div class="wrap">{_table(["", ""], cold)}</div>

<h2>5. Safety</h2>
<p>Every request the CLI sent to the fake HeyReach. Anything outside the read-only allowlist would appear as a write attempt; there were {len(s['outside_allowlist']) + len(s['blocked'])}.</p>
<div class="wrap">{_table(["Endpoint", "Requests"], eps)}</div>
</main></body></html>"""
