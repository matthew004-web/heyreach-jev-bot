"""Self-contained HTML report for a scoring run."""

import html
import json

TIER_CLASS = {"A": "a", "B": "b", "C": "c", "Skip": "skip"}


def _e(s):
    return html.escape(str(s if s is not None else ""))


def _pct(p):
    return f"{p * 100:.0f}%"


def _judgment_rows(ans):
    rows = []
    for k, a in ans.items():
        if a["type"] == "noul":
            val, bar = f"{a['noul']:.2f}", a["noul"]
        elif a["type"] == "score":
            n = len(a["legend"]) - 1
            val = f"{a['score']:.2f} / {n} · {a['legend'][str(round(a['score']))]}"
            bar = a["score"] / n
        else:
            val = f"{a['choice'].replace('_', ' ')} ({a['confidence']:.2f})"
            bar = a["probabilities"][a["choice"]]
        rows.append(f"<tr><td class='k'>{_e(k.replace('_', ' '))}</td>"
                    f"<td><span class='mini'><i style='width:{bar * 100:.0f}%'></i></span></td>"
                    f"<td class='v'>{_e(val)}</td></tr>")
    return "<table class='j'>" + "".join(rows) + "</table>"


def _variant(v, best):
    fixes = "".join(f"<li>{_e(f)}</li>" for f in v["fixes"]) or "<li class='ok'>Nothing to fix</li>"
    tag = "<span class='best'>Best</span>" if v["label"] == best else ""
    return f"""
    <div class='variant{' is-best' if v['label'] == best else ''}'>
      <div class='vhead'><strong>{_e(v['label'])}</strong>{tag}
        <span class='vnums'>message {v['score']:.0f} · reply {_pct(v['reply_p'])} · {v['code']['words']} words</span></div>
      <blockquote>{_e(v['text'])}</blockquote>
      <ul class='fixes'>{fixes}</ul>
      <details><summary>Jev judgments on this message</summary>{_judgment_rows(v['answers'])}</details>
    </div>"""


def render(results, meta, cfg, title="GTM Bot", note=None):
    rows = []
    for rank, r in enumerate(results, 1):
        lead, ls = r["lead"], r["lead_score"]
        best = next((v for v in r["variants"] if v["label"] == r["best"]), None)
        signal = (lead.get("signal") or {}).get("text") or "No signal on file"
        flags = "".join(f"<span class='flag'>{_e(f)}</span>" for f in ls["flags"])
        why = "".join(f"<span class='chip'>{_e(w)}</span>" for w in ls["why"])
        rp = r["reply_p"]
        msg_cell = f"{best['score']:.0f}" if best else "&ndash;"
        reply_cell = (f"<span class='bar'><i style='width:{min(rp / 0.6, 1) * 100:.0f}%'></i></span><b>{_pct(rp)}</b>"
                      if rp is not None else "<span class='bar'></span><b>&ndash;</b>")
        rows.append(f"""
  <details class='row'>
    <summary>
      <span class='rank'>{rank}</span>
      <span class='who'><strong>{_e(lead.get('name'))}</strong><small>{_e(lead.get('headline'))}</small></span>
      <span class='tier {TIER_CLASS[ls['tier']]}'>{_e(ls['tier'])}</span>
      <span class='num'>{ls['score']:.0f}<small>lead</small></span>
      <span class='num'>{msg_cell}<small>message</small></span>
      <span class='reply'>{reply_cell}</span>
    </summary>
    <div class='body'>
      <div class='why'>{why}{flags}</div>
      <p class='signal'><span>Signal</span>{_e(signal)}</p>
      {''.join(_variant(v, r['best']) for v in r['variants'])}
      <details><summary>Jev judgments on this lead</summary>{_judgment_rows(r['lead_answers'])}</details>
    </div>
  </details>""")

    if not any(r["variants"] for r in results):
        mode = "Lead scores only: no message to score yet"
    else:
        mode = ("Reply probability calibrated on " + f"{meta['model_info']['n']} past conversations"
                if meta["mode"] == "calibrated" else
                f"Reply probability from prior weights (base rate {cfg.get('weights', {}).get('reply', {}).get('base_rate', 0.12):.0%})")
    stats = [
        (str(len(results)), "leads"),
        (str(sum(len(r["variants"]) for r in results)), "messages"),
        (str(meta["judgments"]), "Jev judgments"),
        (f"{meta['wall_seconds']:.1f}s", "wall time"),
        (f"${meta['cost_usd']:.4f}", "Jev cost"),
    ]
    stat_html = "".join(f"<div class='stat'><b>{_e(a)}</b><span>{_e(b)}</span></div>" for a, b in stats)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title>
<style>
:root{{--bg:#f7f7f5;--card:#fff;--ink:#16181d;--mute:#5d6470;--line:#e3e4e8;--accent:#2f5bea;--good:#1f8a4c;--warn:#b7791f;--bad:#c2410c;--chip:#eef0f4}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#0f1115;--card:#171a20;--ink:#e8eaee;--mute:#9aa1ad;--line:#2a2e37;--accent:#7c9cff;--good:#4ade80;--warn:#fbbf24;--bad:#fb923c;--chip:#232731}}}}
:root[data-theme="dark"]{{--bg:#0f1115;--card:#171a20;--ink:#e8eaee;--mute:#9aa1ad;--line:#2a2e37;--accent:#7c9cff;--good:#4ade80;--warn:#fbbf24;--bad:#fb923c;--chip:#232731}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Inter","Segoe UI",sans-serif}}
main{{max-width:1040px;margin:0 auto;padding:32px 16px 64px}}
h1{{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}}.sub{{color:var(--mute);margin:0 0 20px}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:10px}}
.stat{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}}.stat b{{display:block;font-size:22px;font-variant-numeric:tabular-nums}}.stat span{{color:var(--mute);font-size:13px}}
.mode{{color:var(--mute);font-size:13px;margin:0 0 22px}}
.row{{background:var(--card);border:1px solid var(--line);border-radius:10px;margin-bottom:8px}}
.row>summary{{list-style:none;display:grid;grid-template-columns:28px minmax(0,1fr) 52px 64px 64px 150px;gap:12px;align-items:center;padding:12px 16px;cursor:pointer}}
.row>summary::-webkit-details-marker{{display:none}}
.rank{{color:var(--mute);font-variant-numeric:tabular-nums}}
.who{{min-width:0}}.who strong{{display:block}}.who small{{display:block;color:var(--mute);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.tier{{justify-self:start;font-weight:700;font-size:12px;padding:3px 9px;border-radius:99px;border:1px solid currentColor}}
.tier.a{{color:var(--good)}}.tier.b{{color:var(--accent)}}.tier.c{{color:var(--warn)}}.tier.skip{{color:var(--bad)}}
.num{{font-size:20px;font-weight:650;font-variant-numeric:tabular-nums;line-height:1.1}}.num small{{display:block;font-size:11px;font-weight:400;color:var(--mute)}}
.reply{{display:flex;align-items:center;gap:8px}}.reply b{{font-variant-numeric:tabular-nums;min-width:38px;text-align:right}}
.bar{{flex:1;height:8px;background:var(--chip);border-radius:99px;overflow:hidden}}.bar i{{display:block;height:100%;background:var(--accent)}}
.body{{padding:0 16px 16px 56px}}
.why{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}}.chip,.flag{{font-size:12px;padding:2px 8px;border-radius:6px;background:var(--chip)}}.flag{{color:var(--bad)}}
.signal{{margin:0 0 12px;font-size:14px}}.signal span{{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);margin-right:8px}}
.variant{{border:1px solid var(--line);border-radius:8px;padding:12px;margin-bottom:10px}}.variant.is-best{{border-color:var(--accent)}}
.vhead{{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline}}.vnums{{margin-left:auto;color:var(--mute);font-size:13px;font-variant-numeric:tabular-nums}}
.best{{font-size:11px;font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:.06em}}
blockquote{{margin:8px 0;padding:8px 12px;border-left:3px solid var(--line);color:var(--ink);font-size:14px}}
.fixes{{margin:6px 0;padding-left:18px;font-size:14px}}.fixes .ok{{color:var(--good);list-style:none;margin-left:-18px}}
details details>summary{{cursor:pointer;color:var(--mute);font-size:13px;margin-top:6px}}
table.j{{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}}table.j td{{padding:3px 6px;border-bottom:1px solid var(--line)}}
.k{{color:var(--mute);white-space:nowrap}}.v{{width:60%}}.mini{{display:inline-block;width:70px;height:6px;background:var(--chip);border-radius:99px;overflow:hidden;vertical-align:middle}}.mini i{{display:block;height:100%;background:var(--accent)}}
.head{{display:grid;grid-template-columns:28px minmax(0,1fr) 52px 64px 64px 150px;gap:12px;padding:0 16px 6px;font-size:12px;color:var(--mute)}}
@media (max-width:720px){{.row>summary{{grid-template-columns:22px minmax(0,1fr) 44px 64px}}.row>summary .num,.head{{display:none}}.reply{{grid-column:2/-1}}.body{{padding:0 12px 12px}}}}
</style></head><body><main>
<h1>{_e(title)}</h1>
<p class="sub">{_e(note or cfg['offer']['what_we_sell'])}</p>
<div class="stats">{stat_html}</div>
<p class="mode">{_e(mode)} · {_e(meta['model'])} · p50 {meta['p50_latency_s'] * 1000:.0f} ms per request · read-only, nothing sent</p>
<div class="head"><span>#</span><span>Lead</span><span>Tier</span><span>Lead</span><span>Message</span><span>Reply probability</span></div>
{''.join(rows)}
</main></body></html>"""


def write(results, meta, cfg, out_dir, title="GTM Bot", note=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.html").write_text(render(results, meta, cfg, title, note), encoding="utf-8")
    slim = [{"name": r["lead"].get("name"), "profile_url": r["lead"].get("profile_url"),
             "tier": r["lead_score"]["tier"], "lead_score": r["lead_score"]["score"],
             "best_variant": r["best"], "reply_p": r["reply_p"],
             "variants": [{k: v[k] for k in ("label", "text", "score", "reply_p", "fixes")} for v in r["variants"]],
             "why": r["lead_score"]["why"], "flags": r["lead_score"]["flags"]} for r in results]
    (out_dir / "scores.json").write_text(json.dumps({"meta": meta, "leads": slim}, indent=2, default=str), encoding="utf-8")
    (out_dir / "raw.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    return out_dir / "report.html"
