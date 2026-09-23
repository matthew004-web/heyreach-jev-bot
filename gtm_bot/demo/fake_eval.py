"""End-to-end test of GTM Bot against synthetic HeyReach workspaces.

  python -m gtm_bot.demo.fake_eval [--history 400] [--fresh 60] [--network 150] [--list 40]

Builds two fake workspaces, serves them from a local fake HeyReach, runs the
real CLI (`hr start`) against each, then grades the output against the hidden
truth the fake world was built from. Nothing touches the real HeyReach API.
"""

import argparse
import json
import os
import random
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from ..calibrate import COMPOSITE
from ..heyreach import READ_ONLY
from .fake_heyreach import FakeHeyReach
from .synth import ARCH, CAMPAIGN_VARIANTS, DRAFTS, build

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def run_cli(args, key, base_url, log):
    env = {**os.environ, "HEYREACH_API_KEY": key, "HEYREACH_BASE_URL": base_url, "PYTHONWARNINGS": "ignore"}
    cmd = [sys.executable, "-m", "gtm_bot", *args]
    print("$ " + " ".join(["python", "-m", "gtm_bot", *args]), flush=True)
    p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    log.write_text(p.stdout + p.stderr, encoding="utf-8")
    if p.returncode:
        print(p.stdout[-3000:], p.stderr[-3000:])
        raise SystemExit(f"CLI failed: {' '.join(args)}")
    return p.stdout


def acc(pairs):
    pairs = list(pairs)
    return (sum(a == b for a, b in pairs) / len(pairs), len(pairs)) if pairs else (None, 0)


def auc(y, s):
    return float(roc_auc_score(y, s)) if 0 < sum(y) < len(y) else None


def capture(y, s, frac=0.2):
    """Share of all replies that sit in the top `frac` of leads ranked by s."""
    k = max(1, int(len(y) * frac))
    top = np.argsort(-np.asarray(s))[:k]
    return float(np.asarray(y)[top].sum() / max(1, sum(y)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", type=int, default=400)
    ap.add_argument("--fresh", type=int, default=60)
    ap.add_argument("--network", type=int, default=150)
    ap.add_argument("--list", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(ROOT / "data" / "gtm_bot" / "fake"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    wss, truth = build(seed=a.seed, n_history=a.history, n_fresh=a.fresh, n_network=a.network, n_list=a.list)
    (out / "fixture.json").write_text(json.dumps(wss), encoding="utf-8")
    (out / "truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    cfg = json.loads((HERE / "config.json").read_text())
    cfg["icp"]["employee_range"] = [20, 500]
    (out / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    (out / "drafts.txt").write_text("\n---\n".join(t for _, t in DRAFTS.values()), encoding="utf-8")

    fake = FakeHeyReach(wss).start()
    print(f"fake HeyReach at {fake.base_url}\n", flush=True)
    run_cli(["hr", "start", "--config", str(out / "config.json"), "--out", str(out / "campaigns")],
            "fake-campaigns", fake.base_url, out / "campaigns.log")
    run_cli(["hr", "start", "--config", str(out / "config.json"), "--messages", str(out / "drafts.txt"), "--enrich",
             "--out", str(out / "coldstart")], "fake-coldstart", fake.base_url, out / "coldstart.log")
    fake.stop()

    L = truth["leads"]
    hist = json.loads((out / "campaigns" / "history.json").read_text())
    camp = json.loads((out / "campaigns" / "campaign-9100" / "raw.json").read_text())
    cold = json.loads((out / "coldstart" / "targets" / "raw.json").read_text())
    model = json.loads((out / "campaigns" / "model.json").read_text())
    M = {}

    # ---------------- 1. judgment accuracy vs truth ----------------
    leads = [(row["lead_id"], row["lead_answers"], row["lead_score"]) for row in hist["rows"]]
    leads += [(r["lead"]["id"], r["lead_answers"], r["lead_score"]) for r in camp + cold]
    t = lambda lid: L[lid]  # noqa: E731
    real = [x for x in leads if t(x[0])["disq"] is None]
    M["function_fit"] = acc((round(ans["function_fit"]["score"]), t(i)["fit"]) for i, ans, _ in real)
    M["function_fit_within1"] = acc((abs(round(ans["function_fit"]["score"]) - t(i)["fit"]) <= 1, True) for i, ans, _ in real)
    M["seniority"] = acc((round(ans["seniority"]["score"]), t(i)["seniority"]) for i, ans, _ in real)
    M["seniority_within1"] = acc((abs(round(ans["seniority"]["score"]) - t(i)["seniority"]) <= 1, True) for i, ans, _ in real)
    with_desc = [x for x in real if t(x[0]).get("source") != "network"]
    thin = [x for x in real if t(x[0]).get("source") == "network"]
    M["company_type_with_description"] = acc((ans["company_fit"]["score"] >= 1.5, t(i)["company_type_fit"]) for i, ans, _ in with_desc)
    M["company_type_network_profiles"] = acc((ans["company_fit"]["score"] >= 1.5, t(i)["company_type_fit"]) for i, ans, _ in thin)
    disq_pred = [(ls["tier"] == "Skip", t(i)["disq"] is not None) for i, _, ls in leads]
    tp = sum(p and y for p, y in disq_pred)
    M["skip_precision"] = (tp / max(1, sum(p for p, _ in disq_pred)), sum(p for p, _ in disq_pred))
    M["skip_recall"] = (tp / max(1, sum(y for _, y in disq_pred)), sum(y for _, y in disq_pred))
    sig = [x for x in leads if t(x[0])["signal_type"]]
    M["signal_type"] = acc((ans["signal_type"]["choice"], t(i)["signal_type"]) for i, ans, _ in sig)
    M["signal_on_vs_off_topic"] = acc((ans["signal_relevance"]["score"] >= 1.5, t(i)["signal_relevance"] >= 0.5)
                                      for i, ans, _ in sig if t(i)["signal_type"] in ("engaged_with_topic", "event_attendance", "wrote_about_problem", "other"))

    # messages: history + draft campaign variants + cold-start drafts
    msgs = []
    for row in hist["rows"]:
        h = truth["history"][row["conversation_id"]]
        msgs.append((row["message_answers"], row["code"], h["msg"], t(row["lead_id"])["signal_type"] is not None))
    for r in camp:
        for v, label in zip(r["variants"], CAMPAIGN_VARIANTS):
            msgs.append((v["answers"], v["code"], truth["fresh"][r["lead"]["id"]][label]["msg"], "signal" in r["lead"]))
    for r in cold:
        for v, label in zip(r["variants"], DRAFTS):
            m = {k: ARCH[DRAFTS[label][0]][k] for k in ("refs", "ask", "pitch", "templated", "creepy", "broken", "long")}
            # draft A merges {COMPANY}; open-to-work profiles have no company, so it goes out broken
            m["broken"] = label == "A" and t(r["lead"]["id"])["disq"] == "open_to_work"
            msgs.append((v["answers"], v["code"], m, "signal" in r["lead"]))
    ok = [x for x in msgs if not x[2]["broken"]]
    M["ask_type"] = acc((ans["ask"]["choice"], m["ask"]) for ans, _, m, _ in ok)
    M["mentions_signal"] = acc((ans["uses_signal"]["noul"] >= 0.5, m["refs"]) for ans, _, m, s in ok if s)
    M["pitches"] = acc((ans["pitches"]["noul"] >= 0.6, m["pitch"]) for ans, _, m, _ in ok)
    M["stock_phrasing"] = acc((ans["templated"]["noul"] >= 0.5, m["templated"]) for ans, _, m, _ in ok)
    M["tracking_reveal"] = acc((ans["creepy"]["noul"] >= 0.5, m["creepy"]) for ans, _, m, _ in ok)
    M["unfilled_merge_tag (code)"] = acc((bool(c["unfilled_tags"]), m["broken"]) for _, c, m, _ in msgs)
    M["n_messages"] = len(msgs)

    # ---------------- 2. reply prediction on history ----------------
    rows = hist["rows"]
    y = [int(r["replied"]) for r in rows]
    tp_ = [truth["history"][r["conversation_id"]]["p"] for r in rows]
    prior = [r["prior_reply_p"] for r in rows]
    Xf = np.array([[r["features"][k] for k in model["features"]] for r in rows])
    Z = (Xf - Xf.mean(0)) / np.where(Xf.std(0) == 0, 1, Xf.std(0))
    C = 1.0 if model["features"] == COMPOSITE else 0.3
    cv = cross_val_predict(LogisticRegression(C=C, max_iter=2000), Z, y,
                           cv=StratifiedKFold(5, shuffle=True, random_state=0), method="predict_proba")[:, 1]
    rnd = random.Random(0)
    shuffled = [rnd.random() for _ in y]
    R = {
        "random order": (auc(y, shuffled), capture(y, shuffled)),
        "lead score only": (auc(y, [r["lead_score"]["score"] for r in rows]), capture(y, [r["lead_score"]["score"] for r in rows])),
        "message score only": (auc(y, [r["message_score"] for r in rows]), capture(y, [r["message_score"] for r in rows])),
        "prior (lead + message, no training)": (auc(y, prior), capture(y, prior)),
        f"calibrated ({model['kind']}, out-of-fold)": (auc(y, list(cv)), capture(y, list(cv))),
        "ceiling: true probability": (auc(y, tp_), capture(y, tp_)),
    }
    order = np.argsort(cv)
    buckets = []
    for chunk in np.array_split(order, 5):
        buckets.append((float(np.mean(cv[chunk])), float(np.mean(np.asarray(y)[chunk])), float(np.mean(np.asarray(tp_)[chunk])), len(chunk)))

    # ---------------- 3. draft campaign: variant choice + prioritization ----------------
    F = truth["fresh"]
    labels = list(CAMPAIGN_VARIANTS)
    per_lead = []
    for r in camp:
        tv = F[r["lead"]["id"]]
        pick = labels[[v["label"] for v in r["variants"]].index(r["best"])]
        per_lead.append({"id": r["lead"]["id"], "jev_p": r["reply_p"], "pick": pick, "true": {lab: tv[lab]["p"] for lab in labels},
                         "broken": {lab: tv[lab]["msg"]["broken"] for lab in labels}})
    n = len(per_lead)
    V = {f"always {lab}": 100 * statistics.mean(x["true"][lab] for x in per_lead) for lab in labels}
    V["random variant (A/B/C split)"] = 100 * statistics.mean(statistics.mean(x["true"].values()) for x in per_lead)
    V["Jev picks per lead"] = 100 * statistics.mean(x["true"][x["pick"]] for x in per_lead)
    V["ceiling: best variant per lead"] = 100 * statistics.mean(max(x["true"].values()) for x in per_lead)
    broken_random = sum(sum(x["broken"].values()) / len(labels) for x in per_lead)
    broken_jev = sum(x["broken"][x["pick"]] for x in per_lead)
    k = max(1, n // 3)
    ranked = sorted(per_lead, key=lambda x: -x["jev_p"])
    P = {
        f"random {k} leads, random variant": statistics.mean(statistics.mean(x["true"].values()) for x in per_lead) * k,
        f"Jev's top {k} leads, Jev's variant": sum(x["true"][x["pick"]] for x in ranked[:k]),
        f"ceiling: best {k} leads, best variant": sum(sorted((max(x["true"].values()) for x in per_lead), reverse=True)[:k]),
    }

    # ---------------- 4. cold start: does the real ICP rise to the top? ----------------
    icp = lambda i: L[i]["fit"] == 3 and L[i]["company_fit"] and L[i]["disq"] is None  # noqa: E731
    tiers = {tt: [r["lead"]["id"] for r in cold if r["lead_score"]["tier"] == tt] for tt in ("A", "B", "C", "Skip")}
    n_icp = sum(icp(r["lead"]["id"]) for r in cold)
    CS = {
        "leads scored": len(cold),
        "true ICP leads (exact role, right company)": n_icp,
        "tier sizes": {tt: len(v) for tt, v in tiers.items()},
        "tier A that are true ICP": (sum(icp(i) for i in tiers["A"]), len(tiers["A"])),
        "tier A+B that are true ICP": (sum(icp(i) for i in tiers["A"] + tiers["B"]), len(tiers["A"] + tiers["B"])),
        "true ICP found in A+B": (sum(icp(i) for i in tiers["A"] + tiers["B"]), n_icp),
        "true ICP in top 20 by lead score": (sum(icp(r["lead"]["id"]) for r in sorted(cold, key=lambda r: -r["lead_score"]["score"])[:20]), 20),
        "base rate of ICP in the pool": n_icp / len(cold),
    }
    draft_picks = {}
    for r in cold:
        if r["best"]:
            draft_picks[r["best"]] = draft_picks.get(r["best"], 0) + 1

    # ---------------- 5. safety + cost ----------------
    endpoints = {}
    for m_, p_ in fake.requests:
        endpoints[f"{m_} {p_}"] = endpoints.get(f"{m_} {p_}", 0) + 1
    outside = [e for e in endpoints if tuple(e.split(" ", 1)) not in READ_ONLY]
    metas = [hist["meta"], *(json.loads(p.read_text())["meta"] for p in out.rglob("scores.json"))]
    cost = sum(x["cost_usd"] for x in metas)
    reqs = sum(x["requests"] for x in metas)
    judg = sum(x["judgments"] for x in metas)
    wall = sum(x["wall_seconds"] for x in metas)

    result = {"generated": datetime.now().isoformat(), "judgments": M, "reply_prediction": R, "calibration_quintiles": buckets,
              "model": {k2: model[k2] for k2 in ("kind", "n", "reply_rate", "auc_cv")}, "insights": model.get("insights"),
              "variant_choice_per_100": V, "broken_sends": {"random": broken_random, "jev": broken_jev, "leads": n},
              "prioritization_expected_replies": P, "coldstart": CS, "draft_picks": draft_picks,
              "safety": {"endpoints": endpoints, "blocked": fake.blocked, "outside_allowlist": outside},
              "jev": {"requests": reqs, "judgments": judg, "cost_usd": cost, "wall_seconds": wall}}
    (out / "results.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    from .fake_report import render
    (out / "test_report.html").write_text(render(result), encoding="utf-8")
    print_summary(result)
    print(f"\nreports:\n  {out / 'test_report.html'}\n  {out / 'campaigns' / 'campaign-9100' / 'report.html'}\n"
          f"  {out / 'coldstart' / 'targets' / 'report.html'}")


def print_summary(r):
    f = lambda v: "n/a" if v is None else f"{v:.0%}"  # noqa: E731
    print("\n=== 1. Jev judgment accuracy vs truth ===")
    for k, v in r["judgments"].items():
        if isinstance(v, tuple) or isinstance(v, list):
            print(f"  {k:<36} {f(v[0]):>5}  (n={v[1]})")
    print("\n=== 2. Reply prediction on past conversations ===")
    for k, (a_, c_) in r["reply_prediction"].items():
        print(f"  {k:<42} AUC {a_:.3f}   top-20% catches {c_:.0%} of replies")
    print("  calibration (predicted vs observed vs true), quintiles:")
    for p_, o_, t_, n_ in r["calibration_quintiles"]:
        print(f"    predicted {p_:5.1%}  observed {o_:5.1%}  true {t_:5.1%}  (n={n_})")
    print("\n=== 3. Draft campaign: expected replies per 100 leads ===")
    for k, v in r["variant_choice_per_100"].items():
        print(f"  {k:<36} {v:5.1f}")
    b = r["broken_sends"]
    print(f"  broken merge tags sent: random split {b['random']:.0f} of {b['leads']}, Jev picks {b['jev']}")
    for k, v in r["prioritization_expected_replies"].items():
        print(f"  {k:<40} {v:5.1f} expected replies")
    print("\n=== 4. Cold start ===")
    for k, v in r["coldstart"].items():
        print(f"  {k:<44} {v}")
    print(f"  draft picked per lead: {r['draft_picks']}")
    s = r["safety"]
    print(f"\n=== 5. Safety === endpoints hit: {len(s['endpoints'])}, outside read-only allowlist: {s['outside_allowlist']}, "
          f"blocked writes: {s['blocked']}")
    j = r["jev"]
    print(f"Jev total: {j['requests']} requests · {j['judgments']} judgments · {j['wall_seconds']:.0f}s · ${j['cost_usd']:.3f}")


if __name__ == "__main__":
    main()
