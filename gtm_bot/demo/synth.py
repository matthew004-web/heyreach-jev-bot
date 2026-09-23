"""Synthetic HeyReach workspaces for testing GTM Bot without real campaigns.

Two workspaces, in HeyReach API shapes:
  campaigns  - 2 senders, 4 finished campaigns with an inbox of past conversations
               (some replied), and a draft campaign: 60 fresh leads x 3 A/B variants
  coldstart  - 1 sender whose LinkedIn network is available, 1 imported lead list,
               no campaigns and no conversations

Every lead and message is built from known attributes (role fit, seniority,
company type and size, signal type/age, what the message does). A hidden reply
model turns those into a true reply probability, so the test can check how
well Jev reads the text, and how well GTM Bot predicts replies, against a
known answer. The reply model encodes common outbound wisdom; it is an
assumption about the world, not measured LinkedIn data.
"""

import math
import random
from datetime import date, datetime, timedelta, timezone

FIRST = ["Priya", "Marcus", "Elena", "Tom", "Aisha", "Jordan", "Daniel", "Hannah", "Sam", "Grace", "Victor", "Nina",
         "Luis", "Mei", "Omar", "Sofia", "Ben", "Chloe", "Raj", "Anna", "Kwame", "Julia", "Mateo", "Ines", "Noah",
         "Fatima", "Ethan", "Leah", "Hugo", "Zara", "Ivan", "Maya", "Felix", "Nadia", "Oscar", "Amara", "Theo", "Lena",
         "Kenji", "Rosa", "Adam", "Selin", "Diego", "Emma", "Yusuf", "Clara", "Arjun", "Mila", "Kofi", "Isla"]
LAST = ["Raman", "Dale", "Voss", "Becker", "Mensah", "Kim", "Ortiz", "Lee", "Whitaker", "Okafor", "Hale", "Petrova",
        "Moreno", "Chen", "Haddad", "Rossi", "Carter", "Dubois", "Iyer", "Nowak", "Boateng", "Fischer", "Silva",
        "Costa", "Walsh", "Rahman", "Brooks", "Klein", "Laurent", "Ahmed", "Novak", "Singh", "Weber", "Karimi",
        "Lindqvist", "Adeyemi", "Murphy", "Holm", "Tanaka", "Vega", "Grant", "Aydin", "Ramos", "Hughes", "Yilmaz",
        "Berg", "Mehta", "Horvat", "Asante", "Reid"]

# (title, fit class 0-3, seniority 0-4)
ROLES = {
    3: [("VP of Sales", 3), ("VP Sales", 3), ("Head of Sales", 3), ("Director of Sales", 3),
        ("Head of Sales Development", 3), ("SDR Manager", 2), ("BDR Team Lead", 2),
        ("Senior Manager, Sales Development", 2), ("Director of Revenue Operations", 3), ("RevOps Manager", 2),
        ("Chief Revenue Officer", 4)],
    2: [("Account Executive", 1), ("Senior Account Executive", 1), ("Enterprise Account Executive", 1),
        ("Sales Enablement Manager", 2), ("Director of Customer Success", 3), ("Sales Development Representative", 1)],
    1: [("Head of Marketing", 3), ("Demand Generation Manager", 2), ("Growth Marketing Lead", 2),
        ("Content Marketing Manager", 2), ("Partnerships Manager", 2), ("Marketing Coordinator", 1), ("VP Marketing", 3)],
    0: [("Senior Software Engineer", 1), ("Product Designer", 1), ("HR Business Partner", 2), ("Finance Manager", 2),
        ("Data Scientist", 1), ("Head of Engineering", 3), ("Office Manager", 1), ("Chief Financial Officer", 4),
        ("Product Manager", 1)],
}
BIGCO = ["Salesforce", "HubSpot", "Gong", "Outreach", "Zendesk", "Oracle", "Stripe"]
PREFIX = ["Ledger", "Crate", "Bright", "Stack", "Tally", "Fern", "North", "Quill", "Harbor", "Mint", "Vector", "Cedar",
          "Orbit", "Relay", "Beacon", "Summit", "Lumen", "Atlas", "Kite", "Arbor", "Copper", "Delta", "Echo", "Flint",
          "Granite", "Juniper", "Maple", "Nimbus", "Onyx", "Pioneer"]
SUFFIX = ["line", "flow", "desk", "point", "beam", "works", "ly", "base", "hub", "loop", "grid", "path", "wise", "field"]
SAAS_WHAT = ["accounting automation", "inventory management", "customer support", "spend management", "HR and payroll",
             "logistics tracking", "security compliance", "contract management", "field service scheduling",
             "sales analytics", "procurement", "data pipeline"]
SAAS_WHOM = ["mid-market finance teams", "B2B wholesalers", "SaaS companies", "startups", "mid-size companies",
             "freight brokers", "IT teams", "legal teams", "construction firms", "manufacturers"]
NONFIT = [("regional hospital network", "Hospitals and Health Care"), ("family-owned restaurant group", "Restaurants"),
          ("public university", "Higher Education"), ("national retail bank", "Banking"),
          ("commercial construction contractor", "Construction"), ("nonprofit food bank", "Non-profit Organizations"),
          ("chain of dental clinics", "Medical Practices"), ("industrial fastener manufacturer", "Manufacturing"),
          ("boutique hotel group", "Hospitality"), ("K-12 school district", "Primary and Secondary Education")]
FIT_SIZES = [22, 35, 48, 60, 85, 120, 150, 210, 260, 340, 450]
OFF_SIZES = [4, 7, 1800, 4500, 12000]

PROBLEM_POSTS = [
    ("Our SDRs booked {n}% fewer meetings this quarter on the same activity. Cold lists are dead. How are you deciding which accounts to work?",
     "your post about meetings dropping {n}%"),
    ("Spent 3 hours today building a prospect list and half of them had already left their company. There has to be a better way.",
     "your post about the 3-hour prospect list"),
    ("Reply rates on our LinkedIn outreach went from 18% to 7% this year. What changed for everyone else?",
     "your post about reply rates falling to 7%"),
    ("Doing founder-led sales and spending 2 hours a day prospecting on LinkedIn. How do you know who's actually ready to talk?",
     "your post about 2 hours a day of prospecting"),
    ("Hot take: most outbound fails because reps work accounts that aren't in-market. Has anyone actually solved prioritization?",
     "your hot take on reps working accounts that aren't in-market"),
]
OFF_POSTS = [("Excited to share that we just launched our new mobile app!", "your launch post"),
             ("Grateful for this amazing team offsite in Lisbon.", "your offsite post")]
COMPETITOR = [
    ("{first} commented on a post by Scoutrill (a competing buying-signal tool) about intent data: '{c}'",
     "your comment on Scoutrill's intent data post"),
    ("{first} followed the company page of IntentPilot (a competing buying-signal tool).", "you following IntentPilot"),
    ("{first} liked a case study posted by Prospectly (a competing buying-signal tool).", "the Prospectly case study you liked"),
]
COMMENTS = ["Curious how this compares to just watching job changes.", "We tried intent data last year, mostly noise.",
            "Does this work for mid-market teams?"]
AUTHORS = ["Jamie Cole", "Ana Ruiz", "Dev Patel", "Marta Kowalski"]
ON_TOPICS = ["cold outreach reply rates", "how to structure an SDR team", "prioritizing accounts with buying signals",
             "LinkedIn prospecting tips", "why outbound pipeline is drying up"]
OFF_TOPICS = ["remote work culture", "product-led growth pricing", "raising a seed round", "engineering career ladders"]
ON_WEBINARS = ["Rebuilding outbound around buying signals", "The death of the cold list", "SDR metrics that matter in 2026"]
OFF_WEBINARS = ["Scaling Kubernetes on a budget", "Modern payroll compliance", "Brand storytelling for startups"]
CITIES = ["Austin", "Denver", "Toronto", "Lisbon", "Berlin"]

# message archetypes: truth attributes + templates
ARCH = {
    "signal_question": dict(refs=True, ask="answer_question", pitch=False, templated=False, creepy=False, broken=False, long=False, t=[
        "{first}, {hook} stuck with me. Are your reps prioritizing accounts by any signals yet, or is it still territory-based?",
        "{first}, saw {hook}. Curious how {company} decides which accounts get worked first right now?",
        "Hey {first}, {hook} got me thinking. What's the first thing your team looks at when picking accounts each week?"]),
    "signal_resource": dict(refs=True, ask="accept_resource", pitch=False, templated=False, creepy=False, broken=False, long=False, t=[
        "{first}, saw {hook}. We pulled together how 6 SaaS sales teams re-cut their account lists around hiring and competitor signals. Happy to send it if useful.",
        "{first}, {hook} is why I'm writing. I have a one-page breakdown of the signals that predicted meetings for teams like {company}. Want it?"]),
    "signal_pitch_meeting": dict(refs=True, ask="book_meeting", pitch=True, templated=False, creepy=False, broken=False, long=False, t=[
        "Hi {first}, saw {hook}. Pipewell flags in-market accounts from buying signals so reps stop wasting time on cold lists. Teams see 2x more meetings. Do you have 20 minutes Thursday for a demo?",
        "{first}, noticed {hook}. That's exactly what Pipewell solves: we surface accounts showing buying signals and route them to reps. Could we find 15 minutes next week?"]),
    "generic_pitch_meeting": dict(refs=False, ask="book_meeting", pitch=True, templated=True, creepy=False, broken=False, long=False, t=[
        "Hi {first}, I hope this message finds you well! I'm reaching out because Pipewell is the #1 AI-powered buying signal platform, helping sales teams 3x their pipeline. Do you have 15 minutes next Tuesday or Wednesday for a quick demo?",
        "Hi {first}, I came across your profile and wanted to introduce Pipewell. We help companies like {company} find in-market accounts with AI. Would you be open to a 30-minute call this week? https://cal.com/pipewell/demo"]),
    "merge_interest": dict(refs=False, ask="interest_check", pitch=True, templated=True, creepy=False, broken=False, long=False, t=[
        "Hi {first}, hope you're having a great week! We help companies like {company} grow pipeline with buying signals. Let me know if you'd be interested in learning more.",
        "Hey {first}, as {title} at {company} I'm sure pipeline is top of mind. Pipewell helps sales teams find in-market accounts. Open to hearing more?"]),
    "flattery_brain": dict(refs=False, ask="interest_check", pitch=False, templated=True, creepy=False, broken=False, long=False, t=[
        "Hi {first}, I came across your profile and was really impressed by your background. I'd love to connect and pick your brain about how you run sales at {company}!",
        "Hi {first}, your experience is so impressive! Would love to connect and learn from you."]),
    "role_question": dict(refs=False, ask="answer_question", pitch=False, templated=False, creepy=False, broken=False, long=False, t=[
        "{first}, quick question for a {title}: how does your team decide which accounts to prospect each week?",
        "{first}, how are you finding outbound at {company} this year? Most teams I talk to say lists are going stale faster."]),
    "long_ramble": dict(refs=True, ask="answer_question", pitch=True, templated=False, creepy=False, broken=False, long=True, t=[
        "{first}, {hook} really resonated with me. Most sales leaders I talk to are dealing with exactly this: reps spend the majority of their week prospecting accounts that were never going to buy this quarter, and the ones that are in-market get the same generic sequence as everyone else. It's brutal because every hour spent on the wrong account is an hour not spent on deals that are actually moving. We've been working on this with a handful of teams at your stage, using signals like competitor engagement, hiring, and funding to figure out who is actually in-market before anyone picks up the phone or sends a message. Out of curiosity, how is {company} deciding who to go after today?"]),
    "creepy_visit": dict(refs=False, ask="accept_resource", pitch=False, templated=False, creepy=True, broken=False, long=False, t=[
        "Hi {first}, I saw you visited our pricing page three times this week, so I figured you're evaluating tools. Want me to send over a proposal?",
        "{first}, noticed you opened our last two emails and clicked through to the demo page. Should I send you a quick walkthrough?"]),
    "broken_merge": dict(refs=False, ask="interest_check", pitch=True, templated=True, creepy=False, broken=True, long=False, t=[
        "Hi {first}, I noticed {{COMPANY_NAME}} is growing fast! Pipewell helps teams like yours find in-market accounts. Open to a quick chat?",
        "Hi {{FIRST_NAME}}, we help sales teams at companies like {company} book more meetings. Interested?"]),
}
HISTORY_MIX = {"signal_question": 14, "signal_resource": 9, "signal_pitch_meeting": 12, "generic_pitch_meeting": 18,
               "merge_interest": 14, "flattery_brain": 9, "role_question": 9, "long_ramble": 6, "creepy_visit": 4,
               "broken_merge": 5}

# the draft campaign's A/B/C first-message variants (HeyReach merge tags)
CAMPAIGN_VARIANTS = {
    "A": ("signal_question", "{FIRST_NAME}, {SIGNAL_HOOK} caught my eye. Curious how {COMPANY} decides which accounts your reps work first right now?"),
    "B": ("generic_pitch_meeting", "Hi {FIRST_NAME}, hope you're well! Pipewell helps teams like {COMPANY} 3x pipeline with AI buying signals. Open to a 15-minute demo this week?"),
    "C": ("signal_resource", "{FIRST_NAME}, saw {SIGNAL_HOOK}. We mapped how 6 SaaS sales teams re-cut their account lists around hiring and competitor signals. Want me to send it over?"),
}
# cold-start drafts the user wants checked before a first campaign (1st-degree connections, so no signal hook)
DRAFTS = {
    "A": ("role_question", "{FIRST_NAME}, it's been a while since we connected. Curious how {COMPANY} is deciding which accounts to prospect these days?"),
    "B": ("generic_pitch_meeting", "Hi {FIRST_NAME}, hope all is well! I just launched Pipewell, an AI buying-signal platform that helps sales teams 3x pipeline. Would you be open to a 15-minute demo?"),
}
REPLIES = ["Thanks for reaching out, not a priority right now.", "Interesting. How does this work with HubSpot?",
           "Sure, send it over.", "We're actually looking at this. What does pricing look like?",
           "Appreciate it, but we're set.", "Good question, honestly it's mostly territory-based today.",
           "Happy to chat next week."]

SIGNAL_TYPE_WEIGHT = {"wrote_about_problem": 1.0, "engaged_with_competitor": 0.8, "engaged_with_topic": 0.55,
                      "company_event": 0.6, "role_change": 0.55, "event_attendance": 0.45, "other": 0.1}


def _sig(x):
    return 1 / (1 + math.exp(-x))


class World:
    def __init__(self, seed, today):
        self.r = random.Random(seed)
        self.today = today
        self.used_names, self.used_cos, self.n = set(), set(), 0

    # ---- people and companies ----
    def name(self):
        while True:
            f, l = self.r.choice(FIRST), self.r.choice(LAST)
            if (f, l) not in self.used_names:
                self.used_names.add((f, l))
                return f, l

    def company_name(self):
        while True:
            c = self.r.choice(PREFIX) + self.r.choice(SUFFIX)
            if len(self.used_cos) > 300:  # 420 two-part names; add a third word once they thin out
                c += " " + self.r.choice(["Labs", "Systems", "Cloud", "Group", "HQ", "Technologies", "AI", "Software"])
            if c not in self.used_cos:
                self.used_cos.add(c)
                return c

    def company(self, p_fit=0.7):
        name = self.company_name()
        roll = self.r.random()
        if roll < p_fit:
            desc = f"{self.r.choice(SAAS_WHAT)} software for {self.r.choice(SAAS_WHOM)}"
            return dict(name=name, desc=desc, industry="Software Development", size=self.r.choice(FIT_SIZES),
                        type_fit=True, size_fit=True)
        if roll < p_fit + 0.1:  # right kind of company, wrong size: size is checked in code, not by Jev
            desc = f"{self.r.choice(SAAS_WHAT)} software for {self.r.choice(SAAS_WHOM)}"
            return dict(name=name, desc=desc, industry="Software Development", size=self.r.choice(OFF_SIZES),
                        type_fit=True, size_fit=False)
        desc, industry = self.r.choice(NONFIT)
        return dict(name=name, desc=desc, industry=industry, size=self.r.choice([15, 90, 900, 2500, 30000]),
                    type_fit=False, size_fit=True)

    def person(self, fit_weights=(20, 20, 20, 40), disq_rate=0.08, p_fit_company=0.7):
        first, last = self.name()
        self.n += 1
        url = f"https://www.linkedin.com/in/gtmbot-test-{first.lower()}-{last.lower()}-{self.n:04d}"  # never a real person
        roll = self.r.random()
        if roll < disq_rate:
            kind = self.r.choice(["agency", "recruiter", "open_to_work"])
            co = self.company_name()
            if kind == "agency":
                return dict(first=first, last=last, url=url, fit=2, seniority=4, disq="agency", title="Founder & CEO",
                            headline=f"Founder @ {co} Growth | We book 30+ meetings a month for B2B SaaS with LinkedIn outbound",
                            company=dict(name=f"{co} Growth", desc="outbound lead generation agency", industry="Marketing Services",
                                         size=12, type_fit=False, size_fit=False))
            if kind == "recruiter":
                return dict(first=first, last=last, url=url, fit=0, seniority=1, disq="recruiter", title="Senior Technical Recruiter",
                            headline=f"Senior Technical Recruiter at {co} Talent | Placing engineers at startups",
                            company=dict(name=f"{co} Talent", desc="recruiting and staffing firm", industry="Staffing and Recruiting",
                                         size=40, type_fit=False, size_fit=True))
            return dict(first=first, last=last, url=url, fit=3, seniority=0, disq="open_to_work", title="",
                        headline=f"Open to work | Former SDR Manager at {co} | Seeking sales leadership roles",
                        company=dict(name="", desc=None, industry=None, size=None, type_fit=False, size_fit=False))
        fit = self.r.choices([3, 2, 1, 0], weights=fit_weights)[0]
        company = self.company(p_fit_company)
        if fit == 3 and company["type_fit"] and company["size"] <= 85 and self.r.random() < 0.3:
            title, sen, flair = "Co-founder & CEO", 4, self.r.choice(["Founder-led sales, for now", "Building in public", "2x founder"])
        else:
            title, sen = self.r.choice(ROLES[fit])
            flair = self.r.choice(["", "", f"ex-{self.r.choice(BIGCO)}",
                                   f"Building a {self.r.choice([8, 12, 20, 25])}-person outbound team" if fit == 3 else "Opinions my own"])
        fmt = self.r.choice(["{t} at {c}", "{t} @ {c}", "{t} | {c}"])
        headline = fmt.format(t=title, c=company["name"]) + (f" | {flair}" if flair else "")
        return dict(first=first, last=last, url=url, fit=fit, seniority=sen, disq=None, title=title,
                    headline=headline, company=company)

    # ---- signals ----
    def signal(self, p, as_of):
        first, co = p["first"], p["company"]["name"] or "their company"
        kind = self.r.choices(["post", "off_post", "competitor", "topic", "off_topic", "hiring", "funding", "office",
                               "role", "webinar", "off_webinar"],
                              weights=[14, 4, 15, 16, 7, 10, 6, 4, 12, 8, 4])[0]
        n = self.r.choice([20, 30, 40, 45])
        if kind == "post":
            post, hook = self.r.choice(PROBLEM_POSTS)
            text, hook, typ, rel = f"{first} wrote a LinkedIn post: '{post.format(n=n)}'", hook.format(n=n), "wrote_about_problem", 1.0
        elif kind == "off_post":
            post, hook = self.r.choice(OFF_POSTS)
            text, typ, rel = f"{first} wrote a LinkedIn post: '{post}'", "other", 0.2
        elif kind == "competitor":
            tpl, hook = self.r.choice(COMPETITOR)
            text, typ, rel = tpl.format(first=first, c=self.r.choice(COMMENTS)), "engaged_with_competitor", 1.0
        elif kind in ("topic", "off_topic"):
            a, t = self.r.choice(AUTHORS), self.r.choice(ON_TOPICS if kind == "topic" else OFF_TOPICS)
            text, hook, typ, rel = f"{first} liked a post by {a} about {t}.", f"{a}'s post on {t}", "engaged_with_topic", 1.0 if kind == "topic" else 0.2
        elif kind == "hiring":
            k = self.r.choice([3, 4, 5, 6, 8])
            text, hook, typ, rel = f"{co} posted {k} open SDR roles on LinkedIn this month.", f"{co} hiring {k} SDRs", "company_event", 1.0
        elif kind == "funding":
            m, s = self.r.choice([8, 12, 20, 35]), self.r.choice(["A", "B"])
            text, hook, typ, rel = f"{co} announced a ${m}M Series {s} round.", f"the Series {s} news", "company_event", 0.7
        elif kind == "office":
            c = self.r.choice(CITIES)
            text, hook, typ, rel = f"{co} opened a new office in {c}.", f"the new {c} office", "company_event", 0.35
        elif kind == "role":
            text, hook, typ, rel = f"{first} started a new role as {p['title'] or 'a sales leader'} at {co}.", f"the new role at {co}", "role_change", 1.0
        else:
            w = self.r.choice(ON_WEBINARS if kind == "webinar" else OFF_WEBINARS)
            text, hook, typ, rel = f"{first} registered for the webinar '{w}'.", f"the '{w}' webinar", "event_attendance", 1.0 if kind == "webinar" else 0.2
        age = self.r.choices([self.r.randint(0, 7), self.r.randint(8, 30), self.r.randint(31, 90)], weights=[40, 35, 25])[0]
        return dict(text=text, hook=hook, type=typ, relevance=rel, date=(as_of - timedelta(days=age)).isoformat(), age=age,
                    strength=SIGNAL_TYPE_WEIGHT[typ] * rel)

    # ---- messages ----
    def message(self, p, arch, signal):
        a = ARCH[arch]
        tpl = self.r.choice(a["t"])
        text = tpl.format(first=p["first"], company=p["company"]["name"] or "your company", title=p["title"] or "sales leader",
                          hook=(signal or {}).get("hook", ""))
        return text, {k: a[k] for k in ("refs", "ask", "pitch", "templated", "creepy", "broken", "long")}

    # ---- truth ----
    def true_logit(self, p, signal, msg, noise):
        z = {3: 0.9, 2: 0.35, 1: -0.1, 0: -0.9}[p["fit"]] + 0.15 * (min(p["seniority"], 3) - 2)
        z += 0.35 if (p["company"]["type_fit"] and p["company"]["size_fit"]) else -0.35
        s = 0.0
        if signal:
            s = signal["strength"] * 0.5 ** (signal["age"] / 30)
            z += 0.8 * s
        if msg:
            if msg["refs"] and signal:
                z += 0.4 + 0.3 * s
            z += {"answer_question": 0.35, "accept_resource": 0.25, "interest_check": -0.05, "book_meeting": -0.45}[msg["ask"]]
            z += -0.3 * msg["pitch"] - 0.45 * msg["templated"] - 0.9 * msg["creepy"] - 2.0 * msg["broken"] - 0.35 * msg["long"]
        z += {"agency": -1.2, "recruiter": -0.9, "open_to_work": -0.4, None: 0.0}[p["disq"]]
        return z + noise


def profile(p, signal=None, custom=True, sparse=False, r=None):
    """HeyReach profile shape. custom=True adds Clay-style custom fields (company info, signal)."""
    co = p["company"]
    prof = {"linkedin_id": p["url"].rsplit("-", 1)[-1], "profileUrl": p["url"], "firstName": p["first"],
            "lastName": p["last"], "headline": p["headline"], "imageUrl": None, "location": None,
            "companyName": co["name"] or None, "companyUrl": None, "position": p["title"] or None, "about": None,
            "connections": 500, "followers": 800, "emailAddress": None, "tags": []}
    if sparse and r is not None:  # network profiles are often thin
        if r.random() < 0.3:
            prof["headline"] = None
        if r.random() < 0.15:
            prof["position"] = None
    if custom:
        cf = []
        if co.get("desc"):
            cf.append({"name": "company_description", "value": co["desc"]})
        if co.get("size"):
            cf.append({"name": "employee_count", "value": str(co["size"])})
        if signal:
            cf += [{"name": "signal", "value": signal["text"]}, {"name": "signal_date", "value": signal["date"]},
                   {"name": "signal_hook", "value": signal["hook"]}]
        prof["customFields"] = cf
    return prof


def truth_for(p, signal):
    return {"fit": p["fit"], "seniority": p["seniority"], "disq": p["disq"],
            "company_fit": bool(p["company"]["type_fit"] and p["company"]["size_fit"]),
            "company_type_fit": bool(p["company"]["type_fit"]), "size": p["company"].get("size"),
            "signal_type": signal["type"] if signal else None, "signal_relevance": signal["relevance"] if signal else None,
            "signal_age": signal["age"] if signal else None, "name": f"{p['first']} {p['last']}"}


def build(seed=7, n_history=400, n_fresh=60, n_network=150, n_list=40, today=date(2026, 9, 22), target_reply=0.12):
    w = World(seed, today)
    truth = {"leads": {}, "history": {}, "fresh": {}}

    # ---------- campaigns workspace: history ----------
    senders = [{"id": 101, "firstName": "Alex", "lastName": "Rowe"}, {"id": 102, "firstName": "Jess", "lastName": "Park"}]
    past = [{"id": 9001 + i, "name": n, "status": "FINISHED"} for i, n in
            enumerate(["Q2 SaaS sales leaders", "Q2 competitor engagers", "Q3 hiring signal", "Q3 founders"])]
    rows = []
    for i in range(n_history):
        sent = datetime(2026, 5, 1, 9, tzinfo=timezone.utc) + timedelta(days=w.r.randint(0, 130), minutes=w.r.randint(0, 600))
        p = w.person(fit_weights=(40, 20, 20, 20))
        sig = w.signal(p, sent.date()) if w.r.random() < 0.7 else None
        mix = {k: v for k, v in HISTORY_MIX.items() if sig or not ARCH[k]["refs"]}
        arch = w.r.choices(list(mix), weights=list(mix.values()))[0]
        text, mattr = w.message(p, arch, sig)
        rows.append((i, sent, p, sig, arch, text, mattr, w.r.gauss(0, 0.4), w.r.random(), w.r.choice(past)["id"]))

    # pick the intercept so the account-wide reply rate lands near target_reply
    lo, hi = -8.0, 4.0
    for _ in range(50):
        mid = (lo + hi) / 2
        mean = sum(_sig(mid + w.true_logit(p, sig, m, nz)) for _, _, p, sig, _, _, m, nz, _, _ in rows) / len(rows)
        lo, hi = (mid, hi) if mean < target_reply else (lo, mid)
    intercept = (lo + hi) / 2

    convos = []
    for i, sent, p, sig, arch, text, mattr, noise, u, camp in rows:
        pt = _sig(intercept + w.true_logit(p, sig, mattr, noise))
        replied = u < pt
        msgs = [{"createdAt": sent.isoformat().replace("+00:00", "Z"), "body": text, "subject": None, "postLink": None,
                 "isInMail": False, "sender": "ME"}]
        if replied:
            msgs.append({"createdAt": (sent + timedelta(hours=w.r.randint(2, 96))).isoformat().replace("+00:00", "Z"),
                         "body": w.r.choice(REPLIES), "subject": None, "postLink": None, "isInMail": False, "sender": "CORRESPONDENT"})
        sender = w.r.choice(senders)
        cid = f"conv-{i:04d}"
        convos.append({"id": cid, "read": True, "groupChat": False, "blockedByMe": False, "blockedByParticipant": False,
                       "lastMessageAt": msgs[-1]["createdAt"], "lastMessageText": msgs[-1]["body"],
                       "lastMessageType": "TEXT", "lastMessageSender": msgs[-1]["sender"], "totalMessages": len(msgs),
                       "linkedInAccountId": sender["id"], "campaignId": camp,
                       "correspondentProfile": profile(p, sig), "linkedInAccount": sender, "messages": msgs})
        truth["leads"][p["url"]] = truth_for(p, sig)
        truth["history"][cid] = {"url": p["url"], "arch": arch, "msg": mattr, "p": pt, "replied": replied}

    # inbox noise the pipeline must ignore: inbound threads and group chats
    for j in range(15):
        p = w.person()
        t = (datetime(2026, 6, 1, tzinfo=timezone.utc) + timedelta(days=j * 5)).isoformat().replace("+00:00", "Z")
        convos.append({"id": f"inbound-{j}", "read": True, "groupChat": False, "totalMessages": 2, "linkedInAccountId": 101,
                       "campaignId": None, "correspondentProfile": profile(p), "linkedInAccount": senders[0],
                       "messages": [{"createdAt": t, "body": "Hi! Saw your post, would love to chat about a partnership.", "sender": "CORRESPONDENT"},
                                    {"createdAt": t, "body": "Sure, happy to.", "sender": "ME"}]})
    for j in range(3):
        convos.append({"id": f"group-{j}", "groupChat": True, "totalMessages": 1, "linkedInAccountId": 101, "campaignId": None,
                       "correspondentProfile": {}, "linkedInAccount": senders[0],
                       "messages": [{"createdAt": "2026-07-01T10:00:00Z", "body": "Welcome everyone!", "sender": "ME"}]})
    w.r.shuffle(convos)

    stats = []
    for c in past:
        mine = [h for cid, h in truth["history"].items() if next(x for x in convos if x["id"] == cid)["campaignId"] == c["id"]]
        replies = sum(h["replied"] for h in mine)
        stats.append({"campaignId": c["id"], "campaignName": c["name"], "isCampaignDeleted": False,
                      "messagesSent": len(mine), "totalMessageStarted": len(mine), "totalMessageReplies": replies,
                      "messageReplyRate": replies / len(mine) if mine else 0.0, "connectionsSent": 0,
                      "connectionsAccepted": 0, "connectionAcceptanceRate": 0.0})

    # ---------- campaigns workspace: draft campaign with fresh leads ----------
    fresh_profiles = []
    for _ in range(n_fresh):
        p = w.person(fit_weights=(45, 20, 20, 15))
        sig = w.signal(p, today) if w.r.random() < 0.75 else None
        fresh_profiles.append(profile(p, sig))
        truth["leads"][p["url"]] = truth_for(p, sig)
        variants = {}
        for label, (arch, _) in CAMPAIGN_VARIANTS.items():
            m = {k: ARCH[arch][k] for k in ("refs", "ask", "pitch", "templated", "creepy", "broken", "long")}
            if m["refs"] and not sig:  # {SIGNAL_HOOK} has nothing to fill: the message goes out broken
                m.update(refs=False, broken=True)
            variants[label] = {"arch": arch, "msg": m, "p": _sig(intercept + w.true_logit(p, sig, m, 0.0))}
        truth["fresh"][p["url"]] = variants
    draft_list = {"id": 7001, "name": "Q4 signal list", "totalItemsCount": n_fresh, "listType": "USER_LIST",
                  "creationTime": "2026-09-20T10:00:00Z", "campaignIds": [9100]}
    draft = {"id": 9100, "name": "Q4 signal test", "status": "DRAFT", "creationTime": "2026-09-20T10:05:00Z",
             "linkedInUserListName": draft_list["name"], "linkedInUserListId": draft_list["id"], "campaignAccountIds": [101, 102],
             "progressStats": {"totalUsers": n_fresh, "totalUsersInProgress": 0, "totalUsersPending": n_fresh,
                               "totalUsersFinished": 0, "totalUsersFailed": 0}}
    sequence = {"nodeType": "CONNECTION_REQUEST", "actionDelay": 0, "actionDelayUnit": "DAY",
                "payload": {"messages": [], "fallbackMessage": None, "toBeWithdrawnAfterDays": 21},
                "conditionalNode": {"nodeType": "MESSAGE", "actionDelay": 1, "actionDelayUnit": "DAY",
                                    "payload": {"messages": [t for _, t in CAMPAIGN_VARIANTS.values()], "fallbackMessage": None},
                                    "unconditionalNode": {"nodeType": "END", "actionDelay": 0, "actionDelayUnit": "HOUR"}},
                "unconditionalNode": {"nodeType": "END", "actionDelay": 0, "actionDelayUnit": "HOUR"}}

    campaigns_ws = {
        "accounts": [{**s, "isActive": True, "activeCampaigns": 0, "authIsValid": True,
                      "profileUrl": f"https://www.linkedin.com/in/{s['firstName'].lower()}-{s['lastName'].lower()}"} for s in senders],
        "campaigns": [{**c, "creationTime": "2026-05-01T09:00:00Z", "linkedInUserListId": None, "campaignAccountIds": [101, 102]}
                      for c in past] + [draft],
        "lists": [draft_list],
        "list_leads": {str(draft_list["id"]): fresh_profiles},
        "campaign_leads": {},
        "sequences": {str(draft["id"]): sequence},
        "conversations": convos,
        "stats": stats,
        "network": {},
        "lead_details": {},
    }

    # ---------- cold-start workspace ----------
    sender = {"id": 201, "firstName": "Sam", "lastName": "Rivera"}
    net, details = [], {}
    for _ in range(n_network):
        p = w.person(fit_weights=(15, 15, 20, 50), disq_rate=0.06, p_fit_company=0.55)
        prof = profile(p, custom=False, sparse=True, r=w.r)
        net.append(prof)
        full = profile(p, custom=False)
        full.update({"industry": p["company"]["industry"], "summary": None, "fullName": f"{p['first']} {p['last']}"})
        details[p["url"]] = full
        truth["leads"][p["url"]] = {**truth_for(p, None), "source": "network"}
    imported = []
    for _ in range(n_list):
        p = w.person(fit_weights=(50, 20, 15, 15), p_fit_company=0.75)
        sig = w.signal(p, today) if w.r.random() < 0.8 else None
        imported.append(profile(p, sig))
        truth["leads"][p["url"]] = {**truth_for(p, sig), "source": "list"}
    clay_list = {"id": 7101, "name": "Clay import: SaaS sales leaders", "totalItemsCount": n_list, "listType": "USER_LIST",
                 "creationTime": "2026-09-18T12:00:00Z", "campaignIds": []}
    coldstart_ws = {
        "accounts": [{**sender, "isActive": True, "activeCampaigns": 0, "authIsValid": True,
                      "profileUrl": "https://www.linkedin.com/in/sam-rivera"}],
        "campaigns": [], "lists": [clay_list], "list_leads": {str(clay_list["id"]): imported}, "campaign_leads": {},
        "sequences": {}, "conversations": [], "stats": [], "network": {str(sender["id"]): net}, "lead_details": details,
    }

    truth["intercept"] = intercept
    return {"fake-campaigns": campaigns_ws, "fake-coldstart": coldstart_ws}, truth
