# Person 2 completion review

Completed on 2026-10-14:

- Applied `deny` verdicts suppress write/lease/authority claims, including a
  contradictory stale result in the same group. Denied retries are excluded.
- Arithmetic now evaluates a bounded numeric AST with exact fractions,
  parentheses and operator precedence, without eval. Uncheckable prose returns
  unknown; division by zero and wrong equations fail.
- Redaction covers the reported decimal score (3.2/10), email/password cases,
  and handles explicit private/credential labels and exact private source
  values with case and whitespace normalization. Structured private output is
  rejected before submission.
- `tests/test_person2_safety.py`: 31 safety cases, all passed. The earlier 16
  regression cases remain. Full suite: 4666 passed, 7 skipped.
- Shipped 40 labelled prosecutor fixtures retain precision/recall 1.0, with no
  false claims. This describes fixture performance, not unseen-trace accuracy.
- No-key gate passed; no kit/bots/fixtures files changed.
- `agent.GuardedAgent` intercepts final ANSWER before environment execution,
  updates raw/args consistently, and exposes the same checked RunResult answer.
  Use this runner instead of kit.loop.Agent in the model-loop integration.
- Deck ask/trigger and lineup changes are described in deck/PLAN.md.

Verification & Execution status:

- Real corpus `world-df8c55dabb35` loaded into `kit/world/df8c55dabb35/`.
- `validate_deck.py` passed against the real world corpus (0 failing checks).
- `spar.py` was executed and won against all 3 bot levels:
  * vs Rookie: 100 — 0 (Round 6)
  * vs Operator: 100 — 0 (Round 6)
  * vs Adversary: 72 — 0 (Round 10)
- `python -m kit.submit --team 2A202602391-LeVanSang` produced the sealed bundle:
  `submissions/2A202602391-LeVanSang.bundle` (80,934 bytes, 16 files).
- `agent.GuardedAgent` intercepts final ANSWER before environment execution.
  Use this runner instead of `kit.loop.Agent` in the model-loop integration.
