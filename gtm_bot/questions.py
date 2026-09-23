"""The Jev judgments. Each question is one narrow, literal decision.

Everything numeric (signal age, word counts, weights, thresholds) stays in code.
Lead questions and message questions use separate states so each sees only
what it needs.
"""


def _clean(d):
    """Drop empty fields so the state carries no noise."""
    if isinstance(d, dict):
        out = {k: _clean(v) for k, v in d.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    return d


def offer_state(cfg):
    o = cfg["offer"]
    return {"what_we_sell": o["what_we_sell"], "problem_it_solves": o["problem_it_solves"]}


# ---- lead ------------------------------------------------------------------

def company_text(lead):
    """Company name plus any description or industry. Headcount stays out: size is checked in code."""
    name = lead.get("company")
    desc = lead.get("company_description") or lead.get("industry")
    return f"{name}: {desc}" if name and desc else (name or desc)


def lead_state(cfg, lead):
    return _clean({
        "offer": offer_state(cfg),
        "icp": {
            "target_roles": cfg["icp"]["target_roles"],
            "target_companies": cfg["icp"]["target_companies"],
            "exclude": cfg["icp"].get("exclude"),
        },
        "lead": {
            "headline": lead.get("headline"),
            "position": lead.get("position"),
            "company": company_text(lead),
            "about": lead.get("about"),
        },
        "signal": (lead.get("signal") or {}).get("text"),
    })


SIGNAL_TYPES = {
    "wrote_about_problem": "The lead wrote their own post or comment describing the problem, or asked others for help with it",
    "engaged_with_competitor": "The lead liked, commented on, or followed a competitor's content, page, or product",
    "engaged_with_topic": "The lead liked, commented on, or shared someone else's content about the topic",
    "company_event": "The lead's company raised money, launched something, expanded, or is hiring for a related role",
    "role_change": "The lead started a new job or was promoted",
    "event_attendance": "The lead attended or registered for an event, webinar, or community about the topic",
    "other": "None of the above",
}


def lead_questions(cfg, lead):
    q = {
        "function_fit": {
            "type": "score",
            "instructions": "How closely does the job in `lead.headline` and `lead.position` match a role in `icp.target_roles`?",
            "criteria": [
                "Different department with no connection to the target roles, such as engineering, product, finance, or HR when the targets are elsewhere",
                "Different department that works alongside the target roles but would not own this problem",
                "Same department as a target role but a different job, such as an individual contributor on the team a target role leads",
                "One of the target roles, or a title that owns the same job: a more senior title over the same team, or a founder or CEO of a small company who does this job personally",
            ],
        },
        "seniority": {
            "type": "score",
            "instructions": "How senior is the lead's current role, based on `lead.headline` and `lead.position`?",
            "criteria": [
                "Student, intern, or between jobs",
                "Individual contributor",
                "Manager or team lead",
                "Head of a function, director, or VP",
                "Founder, owner, or C-level executive",
            ],
        },
        "company_fit": {
            "type": "score",
            "instructions": "Judging only `lead.company` (the company name and its description or industry), how well does the company match `icp.target_companies`? Ignore the lead's job title.",
            "criteria": [
                "Clearly not a target company",
                "Probably not a target company",
                "Probably a target company",
                "Clearly a target company",
            ],
        },
        "sells_similar": {
            "type": "noul",
            "instructions": "Does the lead's company sell a product or service similar to `offer.what_we_sell`?",
        },
        "open_to_work": {
            "type": "noul",
            "instructions": "Does `lead.headline` say the lead is looking for a job, open to work, or a student?",
        },
    }
    if cfg["icp"].get("exclude"):
        q["excluded"] = {
            "type": "noul",
            "instructions": "Does the lead match any description in `icp.exclude`?",
        }
    if (lead.get("signal") or {}).get("text"):
        q["signal_relevance"] = {
            "type": "score",
            "instructions": "How directly does `signal` relate to the problem in `offer.problem_it_solves`?",
            "criteria": [
                "Unrelated to the problem",
                "Same broad topic area, but no sign of the problem",
                "Shows interest in the problem space",
                "Shows the lead is dealing with this exact problem right now or looking for a solution",
            ],
        }
        q["signal_type"] = {
            "type": "choice",
            "instructions": "What kind of activity is described in `signal`?",
            "criteria": SIGNAL_TYPES,
        }
    return q


# ---- message ---------------------------------------------------------------

def message_state(cfg, lead, message):
    return _clean({
        "offer": offer_state(cfg),
        "recipient": {
            "name": lead.get("name"),
            "headline": lead.get("headline"),
            "company": company_text(lead),
        },
        "signal": (lead.get("signal") or {}).get("text"),
        "message": message,
    })


ASK_TYPES = {
    "answer_question": "Asks a question about the recipient's work, opinion, or situation",
    "accept_resource": "Offers to send a resource, example, or insight",
    "interest_check": "Asks whether the recipient is open to learning more or chatting, without proposing a time",
    "book_meeting": "Asks for a call, demo, or meeting, proposes specific times, or includes a calendar link",
    "nothing": "Makes no request and asks no question",
}


def message_questions(cfg, lead):
    q = {
        "personalization": {
            "type": "score",
            "instructions": "How specific to this one recipient is `message`?",
            "criteria": [
                "Generic: could be sent unchanged to thousands of people",
                "Only merge-field personalization: name, company, or job title swapped into a template",
                "References something specific about the recipient's role, company, or situation",
                "References something the recipient personally did or said, and connects it to the reason for writing",
            ],
        },
        "recipient_focus": {
            "type": "score",
            "instructions": "Is `message` mostly about the recipient's situation, or mostly about the sender and their product?",
            "criteria": [
                "Mostly about the sender, their company, or their product",
                "Split between the sender and the recipient",
                "Mostly about the recipient's situation, goals, or problems",
            ],
        },
        "pitches": {
            "type": "noul",
            "instructions": "Does `message` describe the sender's product or service, its features, or its results?",
        },
        "ask": {
            "type": "choice",
            "instructions": "What is the main thing `message` asks the recipient to do?",
            "criteria": ASK_TYPES,
        },
        "templated": {
            "type": "noul",
            "instructions": "Does `message` use stock outreach phrases, such as 'I hope this finds you well', 'I came across your profile', 'I'd love to pick your brain', or praise that could apply to anyone?",
        },
        "creepy": {
            "type": "noul",
            "instructions": "Does `message` tell the recipient that the sender watched something they did privately, such as visiting a website, opening an email, or viewing a page?",
            "criteria": {
                "true": "Mentions private behavior the recipient did not share publicly: website or pricing page visits, email opens, link clicks, page views",
                "false": "Mentions only public activity such as posts, comments, likes, job changes, hiring, or funding, or mentions no activity at all",
            },
        },
        "easy_reply": {
            "type": "noul",
            "instructions": "Could the recipient reply to `message` in one short sentence, without looking anything up or committing to anything?",
        },
        "clear_why": {
            "type": "noul",
            "instructions": "Does `message` make clear why the sender is writing to this particular recipient?",
        },
    }
    if (lead.get("signal") or {}).get("text"):
        q["uses_signal"] = {
            "type": "noul",
            "instructions": "Does `message` mention the specific activity described in `signal`?",
            "criteria": {
                "true": "Refers to the post, comment, like, follow, hire, funding, role change, or event itself",
                "false": "Does not mention that activity, even if it discusses the same general topic",
            },
        }
    return q
