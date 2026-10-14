# Person 2 completion review

Completed on 2026-10-14:

- Applied `deny` verdicts suppress write/lease/authority claims, including a
  contradictory stale result in the same group. Denied retries are excluded.
- Arithmetic now evaluates a bounded numeric AST with exact fractions,
  parentheses and operator precedence, without eval. Uncheckable prose returns
  unknown; division by zero and wrong equations fail.
- Redaction handles explicit private/credential labels and exact private source
  values with case and whitespace normalization. Structured private output is
  rejected before submission.
- `tests/test_person2_safety.py`: 24 safety cases, all passed. The earlier 16
  regression cases remain. Full suite: 4659 passed, 7 skipped.
- Shipped 40 labelled prosecutor fixtures retain precision/recall 1.0, with no
  false claims. This describes fixture performance, not unseen-trace accuracy.
- No-key gate passed; no kit/bots/fixtures files changed.
- `agent.GuardedAgent` intercepts final ANSWER before environment execution,
  updates raw/args consistently, and exposes the same checked RunResult answer.
  Use this runner instead of kit.loop.Agent in the model-loop integration.
- Deck ask/trigger and lineup changes are described in deck/PLAN.md.

Remaining external prerequisites:

- The fork has no release assets and no exported instructor world. Its README
  names world-df8c55dabb35, but the fork's Releases API returned an empty list.
- Spar exits with `no world exported into kit/world/`.
- Submission packaging rejects `no world in kit/world — cannot validate the deck`.
- Real-world legality and attack effectiveness therefore remain unverified.
  Do not replace the real deck anchors with synthetic-fixture anchors to hide this.
- The arena must construct GuardedAgent (see agent/README.md). The canned spar
  answer is independent and cannot prove this live integration is enabled.

After receiving the instructor export, run make validate, spar against rookie
and adversary, then make submit TEAM=<actual-team-name>. No submission bundle
has been produced or tournament result claimed by this change.
