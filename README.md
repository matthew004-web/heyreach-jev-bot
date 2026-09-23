# HeyReach-jev-bot

Signal-based LinkedIn outbound scoring for [HeyReach](https://heyreach.io), running on Jev (TypeSafe System One).

It scores every lead in your HeyReach lists and campaigns, every first-message variant you wrote, and the chance each lead replies. It picks the best message for each person and writes the result back into HeyReach as lead lists and DRAFT campaigns. Once you have reply history, it learns what actually earns replies in your account and ranks the next list with that.

**Nothing here starts a campaign or sends a message.** See [Guardrails](#guardrails).

---

## Run it in Claude Code

If you already use HeyReach, this is the whole setup. About 10 minutes, most of it waiting for `pip install`.

### 1. Get two API keys

| Key | Where | What it's for |
|---|---|---|
| `TYPESAFE_API_KEY` | [console.typesafe.ai](https://console.typesafe.ai) | Jev, the model that reads leads and messages |
| `HEYREACH_API_KEY` | HeyReach → Settings → Integrations → API | reading your lists, campaigns, network and inbox, and writing the drafts back |

The HeyReach key is a normal public-API key. You can delete it when you're done.

### 2. Open the folder in Claude Code

Unzip it wherever you keep projects, then start Claude Code in it:

```bash
unzip gtm-bot.zip
cd gtm-bot
claude
```

Want it in your own GitHub? It's a plain folder, so make it a repo in two commands:

```bash
git init && git add . && git commit -m "Initial commit"
gh repo create gtm-bot --private --source=. --push
```

`.env` and `data/` are git-ignored from the start, so your keys, your leads and your run output never leave your machine.

### 3. Ask Claude to set it up

Paste this:

```text
Set this repo up: create a venv, install requirements.txt, and copy .env.example to .env. Then stop and tell me to paste my keys.
```

Open `.env` in your editor and paste your two keys in yourself, next to the names that are already there. **Don't paste a key into the chat, into a commit, or into any file other than `.env`** (which is git-ignored).

Then:

```text
Run python -m gtm_bot demo and walk me through the report.
```

The demo scores 12 example leads and 14 first messages against a made-up offer. It takes a few seconds, costs about a tenth of a cent, and touches nothing in your HeyReach account. Read the report it opens: that's exactly what you'll get on your own data.

### 4. Tell it what you sell

```bash
cp config.example.json my.json
```

Two sentences about your offer, your target roles, the company type you sell to, your employee range and who to exclude. That's everything Jev knows about your business, so be specific. Claude can fill it for you:

```text
Read my.json, then fill it from our website at example.com and the positioning in this doc. Ask me about anything you're not sure of.
```

### 5. Point it at your HeyReach account

```text
Run python -m gtm_bot hr check, then show me my lists and campaigns.
```

`hr check` confirms the key works and prints what's in the workspace. Then write 2 or 3 first messages in `variants.txt`, separated by a line of three dashes (see [Message variants](#message-variants)), and run the whole flow:

```bash
python -m gtm_bot hr start --config my.json --messages variants.txt
```

`hr start` looks at the account and picks a mode by itself:

- **Campaign mode**, with 30+ past conversations: scores every first message you've already sent, learns what earned replies in this account, then ranks the leads waiting in your live and draft campaigns and picks a variant per lead.
- **Cold start**, with no history: pulls the sender's 1st-degree network (`--enrich` fills thin profiles) and every lead list, ranks them against your ICP, and checks your draft messages.

### 6. Push the result back into HeyReach

```bash
python -m gtm_bot hr setup --from data/gtm_bot/RUN/raw.json --messages variants.txt --dry-run
python -m gtm_bot hr setup --from data/gtm_bot/RUN/raw.json --messages variants.txt
```

Run the `--dry-run` first: it prints every list and campaign it would create, and writes nothing. Then drop the flag.

You get, per tier and per variant Jev picked, one lead list and one single-message DRAFT campaign. Every lead carries its verdict as HeyReach custom fields, so you can read it in the UI:

```text
gtm_tier           A
gtm_lead_score     95
gtm_reply_p        0.499
gtm_best_variant   Variant A
gtm_why            Exact-fit role · Head / Director / VP · wrote about problem, 2d ago
```

Open the campaigns in HeyReach, add a follow-up step if you want one, and start them yourself.

---

## What to ask Claude for

| Ask | What runs |
|---|---|
| "What's in my HeyReach workspace?" | `hr check`, `hr lists`, `hr campaigns`, `hr accounts` |
| "Score list 12345 against my ICP with these messages" | `hr score --list-id 12345` |
| "Score the leads in campaign 6789" | `hr score --campaign-id 6789` |
| "Rank my 1st-degree network" | `hr network --enrich` |
| "Learn what gets replies in my account" | `hr calibrate` |
| "Do the whole thing and push the drafts" | `hr start`, then `hr setup` |
| "Score this CSV before I import it" | `score leads.csv` |

## Requirements

- Python 3.9+
- A HeyReach account with at least one lead list, campaign, or a connected sender whose network you want ranked
- A TypeSafe API key for Jev
- `requests`, `numpy`, `scikit-learn` (from `requirements.txt`)

Outputs go to `data/gtm_bot/<run>/` as `report.html`, `scores.json` and `raw.json`. The whole `data/` directory is git-ignored, and so is `.env`.

## What it costs

Jev is cheap enough that you can score everything instead of sampling. The demo's 12 leads and 14 messages are 26 requests: about 2.6 seconds and $0.0013 in total. Learning from 400 past conversations is about 800 requests: under a minute and $0.0381.

## What Jev judges

Each lead gets one request, and each message variant gets another. The questions inside a request run in parallel. Everything numeric (signal age, word counts, weights, thresholds) stays in code, in `scoring.py`, for you to read and change.

| Lead (state: offer, ICP, profile, signal) | Message (state: offer, recipient, signal, text) |
|---|---|
| function fit vs target roles (score) | personalization depth (score) |
| seniority (score) | about them vs about us (score) |
| company fit vs ICP (score) | pitches the product (noul) |
| signal relevance to the problem (score) | what it asks for: question / resource / chat / meeting (choice) |
| signal type: wrote about problem, competitor engagement, hiring... (choice) | stock outreach phrasing (noul) |
| sells something similar / open to work / matches exclusion (nouls) | reveals private tracking (noul) |
| | answerable in one line / clear why-you / mentions the signal (nouls) |

`scoring.py` turns those into:

- **Lead score (0-100)** = fit (function, seniority, company) + intent (signal relevance × signal-type weight × freshness decay). Disqualifiers force tier Skip.
- **Message score (0-100)** = weighted message judgments, with penalties for stock phrasing, tracking reveals, unfilled `{MERGE_TAGS}` and length.
- **Reply probability**: a logistic prior around your base reply rate until you calibrate, then a model learned from your own HeyReach inbox.
- **Best variant per lead**: each lead gets the variant with the highest predicted reply.

## Signals

The signal is what the person actually did, and it's where most of the intent score comes from. It goes in a HeyReach lead custom field named `signal`, plus `signal_date`. One sentence:

> Priya wrote a LinkedIn post: our SDRs booked 40% fewer meetings this quarter on the same activity volume.

Jev reads it and decides how close it is to the problem you solve and what kind of signal it is; code applies the weight for that type and halves it every 21 days. `company_description` and `employee_count` custom fields get used when they're there.

## Message variants

`--messages variants.txt` takes your first messages separated by a line containing `---`. HeyReach merge tags (`{FIRST_NAME}`, `{COMPANY}`, custom fields like `{SIGNAL_HOOK}`) are filled per lead, and a variant with an unfilled tag is never picked while a clean one exists.

## Learning from your inbox

```bash
python -m gtm_bot hr calibrate --config my.json
```

Every conversation you started becomes one example: Jev scores the lead and your first message the same way it scores a new one, and the label is whether they ever wrote back. A logistic regression over those judgments becomes a reply probability for your account, saved to `data/gtm_bot/model.json`.

- **Under 150 conversations** it learns from the lead score and the message score.
- **From 150 up** it also tries 19 features (both scores, Jev's individual judgments, word count, links) and keeps whichever predicts better on conversations it didn't train on.
- It needs **at least 5 conversations that got a reply and 5 that didn't**. With fewer it says so and exits.

It also prints what earns replies in your account, habit by habit: mentioning the signal, asking for a meeting on the first touch, pitching, stock phrasing, staying under 60 words, exact-fit roles. Every split shows the reply rate on both sides and how many conversations are behind it.

`hr start` re-learns from the inbox first whenever you have 30+ conversations, so it gets sharper every week.

## Guardrails

- Scoring reads HeyReach through a client that refuses any endpoint outside a read-only allowlist (`heyreach.READ_ONLY`).
- `hr_setup.py` is the only code that writes, through its own allowlist: create a lead list, add leads to a list, create a campaign. Anything else is blocked.
- HeyReach creates campaigns in DRAFT and needs a connected LinkedIn sender. **Nothing in this codebase can start a campaign or send a message. A person does that.**
- `--dry-run` on `hr setup` prints the full plan and writes nothing.
- Your keys live in `.env`, which is git-ignored. Run outputs land in `data/`, also git-ignored.

## Troubleshooting

| What you see | What it means |
|---|---|
| `blocked: POST ... is not an allowed setup write` | Working as intended: the endpoint isn't on the write allowlist |
| HeyReach rejects campaign creation | No connected LinkedIn sender. The lists still get created; run `hr setup --campaigns-from data/gtm_bot/RUN/setup.json` once a sender is connected |
| `hr calibrate` exits early | Fewer than 5 replied and 5 unreplied conversations. Keep sending, try next week |
| Every lead comes back tier C or Skip | `my.json` is too vague or too narrow. Check `target_roles` and `employee_range` first |
| A variant is never picked | It probably has an unfilled merge tag; the run output says which |

## Test it without touching a real account

```bash
python -m gtm_bot.demo.fake_eval
```

Builds two synthetic HeyReach workspaces (a team with 400 past conversations and a 60-lead draft campaign with 3 variants, plus a cold start with a 150-person network and an imported list), serves them from a local fake HeyReach, runs the real CLI against both, and grades every judgment against the hidden truth the fake world was built from. Writes `data/gtm_bot/fake/test_report.html`.

## Running it on a client's HeyReach

If you run outbound for other people, `giveaway.py` does the whole flow against another workspace without their key ever touching disk.

```bash
python -m gtm_bot.giveaway new HANDLE             # intake.json, filled from their answers
python -m gtm_bot.giveaway run HANDLE --dry-run   # score only, nothing written
python -m gtm_bot.giveaway run HANDLE             # score + push [GTM] lists and drafts
python -m gtm_bot.giveaway status
```

Ask them for what they sell and the problem it solves, target roles, company type and size, who to exclude, their draft messages if they have them, and a HeyReach API key made just for this that they delete afterwards. `run` asks for the key at a hidden prompt and keeps it in memory for that run only. It is never written to disk.

`run` learns from their inbox when they have 30+ past conversations, scores the leads nobody is contacting yet, and pushes one `[GTM]` list and one single-message DRAFT campaign per tier and picked variant. Nothing is started. It writes `report.html` and `deliver.md` to `data/gtm_bot/giveaway/HANDLE/`.

## Command reference

```bash
python -m gtm_bot demo                                     # the example run, no HeyReach needed
python -m gtm_bot score leads.csv --config my.json --messages variants.txt
python -m gtm_bot hr check | campaigns | lists | accounts  # read the workspace
python -m gtm_bot hr score --config my.json --list-id N --messages variants.txt
python -m gtm_bot hr score --config my.json --campaign-id N --messages variants.txt
python -m gtm_bot hr network --config my.json --enrich     # rank the sender's 1st-degree network
python -m gtm_bot hr calibrate --config my.json            # learn from the inbox
python -m gtm_bot hr start --config my.json --messages variants.txt   # the whole flow
python -m gtm_bot hr setup --from data/gtm_bot/RUN/raw.json --messages variants.txt [--dry-run]
```

`hr score` takes `--model data/gtm_bot/model.json` to score with what it learned from your inbox. `hr setup` takes `--tiers` (default A and B) and `--prefix` (default `[GTM]`), and `hr start` takes `--max-campaigns` (default 3).
