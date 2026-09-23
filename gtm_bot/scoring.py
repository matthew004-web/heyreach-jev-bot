"""Compose Jev judgments into lead score, message score and reply probability.

Jev answers narrow questions; this module owns every weight, threshold and
formula, so changing a weight never needs another model call.
"""

import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from . import questions as Q
from .heyreach import MERGE_TAG

DEFAULT_WEIGHTS = {
    "lead": {"fit": 0.55, "intent": 0.45,
             "function_fit": 0.45, "seniority": 0.25, "company_fit": 0.30},
    "signal_type": {
        "wrote_about_problem": 1.0, "engaged_with_competitor": 0.85, "company_event": 0.7,
        "role_change": 0.65, "engaged_with_topic": 0.6, "event_attendance": 0.6, "other": 0.35,
    },
    "signal_half_life_days": 21,
    "target_seniority": 3,  # 0 student .. 4 founder/C-level; at or above this counts as full fit
    "message": {"personalization": 0.25, "uses_signal": 0.15, "recipient_focus": 0.15,
                "no_pitch": 0.10, "ask": 0.15, "easy_reply": 0.10, "clear_why": 0.10},
    "ask_value": {"answer_question": 1.0, "accept_resource": 0.85, "interest_check": 0.6,
                  "nothing": 0.4, "book_meeting": 0.15},
    "max_words": 80,
    "reply": {"base_rate": 0.12, "lead_beta": 2.8, "message_beta": 1.8, "disqualified_shift": -1.5, "broken_shift": -2.5},
    "disqualify_at": 0.6,
    "outside_size_factor": 0.25,  # company_fit multiplier when headcount is outside icp.employee_range
}

URL = re.compile(r"https?://|www\.", re.I)
FUNCTION_LABELS = ["Unrelated role", "Adjacent role", "Same function", "Exact-fit role"]
SENIORITY_LABELS = ["Student / between jobs", "Individual contributor", "Manager", "Head / Director / VP", "Founder / C-level"]


def _norm(ans):
    return ans["score"] / (len(ans["legend"]) - 1)


def _expected(ans, values):
    return sum(p * values.get(k, 0.0) for k, p in ans["probabilities"].items())


def _sigmoid(x):
    return 1 / (1 + math.exp(-x))


def _logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def weights_for(cfg):
    return _merge(DEFAULT_WEIGHTS, cfg.get("weights"))


def _messages(lead):
    out = []
    for i, m in enumerate(lead.get("messages") or []):
        if isinstance(m, str):
            m = {"text": m}
        out.append({"label": m.get("label") or ("Message" if len(lead["messages"]) == 1 else f"Variant {chr(65 + i)}"),
                    "text": m["text"]})
    return out


# ---- lead ------------------------------------------------------------------

def lead_tier(fn, co, fit, intent, flags):
    """Tier by fit so leads without signals (a cold-start network) still sort; a strong signal lifts a near-fit.

    fn = role fit, co = company fit after the size check, fit = blended fit, intent = signal strength (all 0-1).
    Tier A needs the company to fit too.
    """
    if flags:
        return "Skip"
    if co >= 0.5 and ((fn >= 0.75 and fit >= 0.75) or (fn >= 0.6 and intent >= 0.5)):
        return "A"
    if (fn >= 0.5 and fit >= 0.55) or (fn >= 0.3 and intent >= 0.5):
        return "B"
    return "C"


def compose_lead(ans, lead, W, today, icp=None):
    sig = lead.get("signal") or {}
    as_of = _parse_date(lead.get("as_of")) or today  # history is scored as of the send date
    fn, sen, co = _norm(ans["function_fit"]), ans["seniority"]["score"], _norm(ans["company_fit"])
    size, rng, size_fit = lead.get("employee_count"), (icp or {}).get("employee_range"), None
    if size is not None and rng:
        size_fit = 1.0 if rng[0] <= size <= rng[1] else W["outside_size_factor"]
        co *= size_fit
    sen_fit = min(1.0, sen / W["target_seniority"])
    lw = W["lead"]
    fit = (lw["function_fit"] * fn + lw["seniority"] * sen_fit + lw["company_fit"] * co) / (
        lw["function_fit"] + lw["seniority"] + lw["company_fit"])

    intent, freshness, age = 0.0, None, None
    if "signal_relevance" in ans:
        d = _parse_date(sig.get("date"))
        age = (as_of - d).days if d else None
        freshness = 0.5 ** (max(age, 0) / W["signal_half_life_days"]) if age is not None else 0.75
        type_w = _expected(ans["signal_type"], W["signal_type"])
        intent = _norm(ans["signal_relevance"]) * type_w * freshness

    score = 100 * (lw["fit"] * fit + lw["intent"] * intent)
    flags = [name for name, key in (("sells something similar", "sells_similar"),
                                    ("open to work / student", "open_to_work"),
                                    ("matches an exclusion", "excluded"))
             if key in ans and ans[key]["noul"] >= W["disqualify_at"]]
    tier = lead_tier(fn, co, fit, intent, flags)

    why = [FUNCTION_LABELS[round(ans["function_fit"]["score"])], SENIORITY_LABELS[round(sen)]]
    if size_fit is not None and size_fit < 1:
        why.append(f"{size:,} employees, outside target size")
    if "signal_type" in ans:
        st = ans["signal_type"]["choice"].replace("_", " ")
        why.append(f"{st}, {age}d ago" if age is not None else st)
    else:
        why.append("no signal")

    return {"score": round(score, 1), "tier": tier, "fit": round(fit, 3), "intent": round(intent, 3),
            "freshness": freshness, "signal_age_days": age, "size_fit": size_fit, "flags": flags, "why": why}


# ---- message ---------------------------------------------------------------

def code_features(text, is_connection_note=False):
    words = len(text.split())
    return {
        "words": words,
        "chars": len(text),
        "questions": text.count("?"),
        "has_link": bool(URL.search(text)),
        "unfilled_tags": MERGE_TAG.findall(text),
        "over_note_limit": is_connection_note and len(text) > 300,
    }


def compose_message(ans, text, W, has_signal):
    mw = W["message"]
    parts = {
        "personalization": _norm(ans["personalization"]),
        "recipient_focus": _norm(ans["recipient_focus"]),
        "no_pitch": 1 - ans["pitches"]["noul"],
        "ask": _expected(ans["ask"], W["ask_value"]),
        "easy_reply": ans["easy_reply"]["noul"],
        "clear_why": ans["clear_why"]["noul"],
    }
    if has_signal:
        parts["uses_signal"] = ans["uses_signal"]["noul"]
    base = sum(mw[k] * v for k, v in parts.items()) / sum(mw[k] for k in parts)

    cf = code_features(text)
    penalty = (1 - 0.3 * ans["templated"]["noul"]) * (1 - 0.5 * ans["creepy"]["noul"])
    if cf["unfilled_tags"]:
        penalty *= 0.4
    if cf["words"] > W["max_words"]:
        penalty *= max(0.6, 1 - (cf["words"] - W["max_words"]) / 150)
    score = 100 * base * penalty
    return {"score": round(score, 1), "parts": {k: round(v, 3) for k, v in parts.items()},
            "code": cf, "fixes": message_fixes(ans, cf, W, has_signal)}


def message_fixes(ans, cf, W, has_signal):
    fixes = []
    if cf["unfilled_tags"]:
        fixes.append(f"Unfilled merge field {{{cf['unfilled_tags'][0]}}}. This would go out broken.")
    if ans["creepy"]["noul"] >= 0.5:
        fixes.append("Mentions tracking (site visits, opens). Refer to public activity only.")
    if has_signal and ans["uses_signal"]["noul"] < 0.5:
        fixes.append("Doesn't use the signal. Open with the thing they did.")
    if ans["ask"]["choice"] == "book_meeting":
        fixes.append("Asks for a meeting on first touch. Ask about their situation instead.")
    if ans["pitches"]["noul"] >= 0.6:
        fixes.append("Pitches the product. Save it for when they reply.")
    if ans["templated"]["noul"] >= 0.5:
        fixes.append("Stock outreach phrasing. Cut the opener.")
    if ans["recipient_focus"]["score"] < 1:
        fixes.append("About you, not them.")
    if ans["personalization"]["score"] < 1.5 and not (has_signal and ans["uses_signal"]["noul"] >= 0.5):
        fixes.append("Only name/company personalization.")
    if ans["easy_reply"]["noul"] < 0.4:
        fixes.append("Hard to answer in one line.")
    if cf["words"] > W["max_words"]:
        fixes.append(f"{cf['words']} words. First touch works best under {W['max_words']}.")
    if cf["has_link"]:
        fixes.append("Contains a link. Links in first touches get skipped.")
    return fixes


# ---- reply probability -----------------------------------------------------

def feature_vector(lead_ans, msg_ans, lead_out, msg_out):
    """Named numeric features shared by the prior and the calibrated model."""
    def noul(a, k):
        return a[k]["noul"] if k in a else 0.0

    ask = msg_ans["ask"]["probabilities"]
    return {
        "lead_score": lead_out["score"] / 100,
        "message_score": msg_out["score"] / 100,
        "function_fit": _norm(lead_ans["function_fit"]),
        "seniority": _norm(lead_ans["seniority"]),
        "company_fit": _norm(lead_ans["company_fit"]),
        "sells_similar": noul(lead_ans, "sells_similar"),
        "open_to_work": noul(lead_ans, "open_to_work"),
        "has_signal": 1.0 if "signal_relevance" in lead_ans else 0.0,
        "signal_relevance": _norm(lead_ans["signal_relevance"]) if "signal_relevance" in lead_ans else 0.0,
        "personalization": _norm(msg_ans["personalization"]),
        "recipient_focus": _norm(msg_ans["recipient_focus"]),
        "pitches": noul(msg_ans, "pitches"),
        "ask_question": ask.get("answer_question", 0.0),
        "ask_meeting": ask.get("book_meeting", 0.0),
        "ask_interest": ask.get("interest_check", 0.0),
        "templated": noul(msg_ans, "templated"),
        "creepy": noul(msg_ans, "creepy"),
        "easy_reply": noul(msg_ans, "easy_reply"),
        "clear_why": noul(msg_ans, "clear_why"),
        "uses_signal": noul(msg_ans, "uses_signal"),
        "words_100": msg_out["code"]["words"] / 100,
        "has_link": 1.0 if msg_out["code"]["has_link"] else 0.0,
    }


def reply_probability(features, lead_out, W, model=None):
    if model:
        z = model["intercept"] + sum(
            c * (features[f] - m) / s for f, c, m, s in zip(model["features"], model["coef"], model["mean"], model["std"]))
        return _sigmoid(z)
    R = W["reply"]
    z = (_logit(R["base_rate"]) + R["lead_beta"] * (features["lead_score"] - 0.5)
         + R["message_beta"] * (features["message_score"] - 0.5))
    if lead_out["flags"]:
        z += R["disqualified_shift"]
    return _sigmoid(z)


# ---- run -------------------------------------------------------------------

def evaluate(cfg, leads, jev, model=None, today=None, workers=8):
    """Score every lead and every message variant. Returns (results, meta)."""
    W = weights_for(cfg)
    today = today or date.today()
    jobs = []
    for i, lead in enumerate(leads):
        jobs.append(("lead", i, None, Q.lead_state(cfg, lead), Q.lead_questions(cfg, lead)))
        for j, m in enumerate(_messages(lead)):
            jobs.append(("msg", i, j, Q.message_state(cfg, lead, m["text"]), Q.message_questions(cfg, lead)))

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        answers = list(pool.map(lambda job: jev.ask(job[3], job[4]), jobs))
    wall = time.time() - t0

    lead_ans, msg_ans = {}, {}
    for job, ans in zip(jobs, answers):
        if job[0] == "lead":
            lead_ans[job[1]] = ans
        else:
            msg_ans[(job[1], job[2])] = ans

    results = []
    for i, lead in enumerate(leads):
        la = lead_ans[i]
        lo = compose_lead(la, lead, W, today, cfg.get("icp"))
        has_signal = "signal_relevance" in la
        variants = []
        for j, m in enumerate(_messages(lead)):
            ma = msg_ans[(i, j)]
            mo = compose_message(ma, m["text"], W, has_signal)
            fv = feature_vector(la, ma, lo, mo)
            rp = reply_probability(fv, lo, W, model)
            if mo["code"]["unfilled_tags"]:
                rp = _sigmoid(_logit(rp) + W["reply"]["broken_shift"])
            variants.append({**m, **mo, "reply_p": round(rp, 4),
                             "features": fv, "answers": ma})
        # an unfilled merge tag is a hard stop: such a variant is only picked if every variant has one
        sendable = [v for v in variants if not v["code"]["unfilled_tags"]] or variants
        best = max(sendable, key=lambda v: v["reply_p"]) if variants else None
        results.append({"lead": lead, "lead_score": lo, "lead_answers": la,
                        "variants": variants, "best": best["label"] if best else None,
                        "reply_p": best["reply_p"] if best else None})

    # leads with no message yet (cold start) rank by lead score
    results.sort(key=lambda r: (r["lead_score"]["tier"] != "Skip",
                                r["reply_p"] if r["reply_p"] is not None else r["lead_score"]["score"] / 100),
                 reverse=True)
    meta = {"wall_seconds": round(wall, 2), "judgments": sum(len(j[4]) for j in jobs),
            "mode": "calibrated" if model else "prior", "model_info": model and {
                k: model[k] for k in ("n", "reply_rate", "auc_cv", "kind") if k in model},
            **jev.summary()}
    return results, meta
