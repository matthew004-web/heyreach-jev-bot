"""Learn reply probability from past HeyReach conversations.

Each past conversation that started with our message becomes one labeled
example: Jev scores the lead and the first message exactly as it would a new
one, and `replied` is whether the lead ever answered. A logistic regression
over Jev's features turns them into a reply probability for this account.
"""

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict

COMPOSITE = ["lead_score", "message_score"]
FULL = ["lead_score", "message_score", "function_fit", "seniority", "company_fit", "has_signal",
        "signal_relevance", "personalization", "recipient_focus", "pitches", "ask_question",
        "ask_meeting", "ask_interest", "templated", "easy_reply", "clear_why", "uses_signal",
        "words_100", "has_link"]

# Readable splits for the "what actually gets replies" table.
SPLITS = [
    ("Message mentions the signal", "uses_signal", lambda x: x >= 0.5),
    ("Asks for a meeting on first touch", "ask_meeting", lambda x: x >= 0.5),
    ("Asks a question about them", "ask_question", lambda x: x >= 0.5),
    ("Pitches the product", "pitches", lambda x: x >= 0.6),
    ("Stock outreach phrasing", "templated", lambda x: x >= 0.5),
    ("Personalized beyond merge fields", "personalization", lambda x: x >= 2 / 3),
    ("Under 60 words", "words_100", lambda x: x < 0.6),
    ("Exact-fit role", "function_fit", lambda x: x >= 0.8),
    ("Lead score 70+", "lead_score", lambda x: x >= 0.7),
    ("Message score 70+", "message_score", lambda x: x >= 0.7),
]


def _fit(X, y, C):
    mean, std = X.mean(0), X.std(0)
    std[std == 0] = 1
    Z = (X - mean) / std
    folds = min(5, int(y.sum()), int((1 - y).sum()))
    auc = None
    if folds >= 2:
        pred = cross_val_predict(LogisticRegression(C=C, max_iter=2000), Z, y,
                                 cv=StratifiedKFold(folds, shuffle=True, random_state=0), method="predict_proba")[:, 1]
        auc = float(roc_auc_score(y, pred))
    clf = LogisticRegression(C=C, max_iter=2000).fit(Z, y)
    return clf, mean, std, auc


def fit_model(rows):
    """rows: list of (features dict, replied bool). Returns (model dict, insights list)."""
    y = np.array([1 if r else 0 for _, r in rows])
    if y.sum() < 5 or (1 - y).sum() < 5:
        raise ValueError(f"need at least 5 replied and 5 unreplied conversations, got {int(y.sum())}/{int((1 - y).sum())}")

    candidates = [("composite", COMPOSITE, 1.0)]
    if len(rows) >= 150:
        candidates.append(("full", FULL, 0.3))
    best = None
    for kind, feats, C in candidates:
        X = np.array([[f[k] for k in feats] for f, _ in rows], dtype=float)
        clf, mean, std, auc = _fit(X, y, C)
        if best is None or (auc or 0) > (best["auc_cv"] or 0):
            best = {"kind": kind, "features": feats, "coef": clf.coef_[0].tolist(),
                    "intercept": float(clf.intercept_[0]), "mean": mean.tolist(), "std": std.tolist(),
                    "auc_cv": auc, "n": len(rows), "reply_rate": float(y.mean())}
    return best, insights(rows)


def insights(rows):
    out = []
    for label, key, test in SPLITS:
        yes = [r for f, r in rows if test(f[key])]
        no = [r for f, r in rows if not test(f[key])]
        if len(yes) >= 5 and len(no) >= 5:
            out.append({"split": label, "n_yes": len(yes), "reply_yes": sum(yes) / len(yes),
                        "n_no": len(no), "reply_no": sum(no) / len(no)})
    return out
