"""agent/gateway.py — YOUR control plane. CONTRACTS.md section 4, exactly.

READ agent/README.md FIRST — it maps all five files in this directory to what
each is scored on. This file is the one CONTRACTS.md calls "the trusted
envelope's untrusted half": every single MCP / A2A / DISCOVER command your
agent's model wants to make passes through `Gateway.decide` before it is
allowed to happen.

WHY THERE IS NO `execute()` METHOD ON `GatewayContext` (read this before you
go looking for one — there isn't one, and that is not an oversight)
----------------------------------------------------------------------------
CONTRACTS.md section 4's trusted envelope, reproduced here because it is the
one diagram worth memorising:

    [ trusted ]   loop emits a raw action line
         v
    [ trusted ]   INTERCEPT + CANONICALISE -> Command        (kit/loop/agent.py)
         v
    [ UNTRUSTED ] Gateway.decide(cmd) -> Decision             <- THIS FILE
         v
    [ trusted ]   ENFORCE: honour the Decision, meter it,
                  apply the active mutation, execute the
                  ToolCall or refuse it                       (the arena)
         v
    [ trusted ]   RECORD the authoritative L1 event, then
                  RENDER the Observation                      (the arena)
         v
    [ trusted ]   the model sees the Observation

`decide()` returns a *decision*, never a *result*. You cannot reach a tool
server, a file, a socket, or a clock from in here — there is nothing to
call. Two things follow from that, and both matter more than they look:

  1. YOUR TRACE CANNOT BE FORGED. Every `command` / `decision` / `enforced`
     / `tool_call` / `tool_result` L1 event (CONTRACTS.md 5.2) is written by
     the arena, from what the arena itself actually did — never from
     anything you claimed happened. A student gateway that wanted to lie
     about having blocked an attack ("I totally denied that, trust me")
     simply has no channel to lie through: the only thing you ever hand
     back is this one small `Decision` value, and the arena is the one that
     turns it into history.
  2. NOBODY CAN ACCUSE YOU OF A CALL YOU DID NOT AUTHORISE, either. Because
     `decide()` is the ONLY door a command can walk through on its way to
     actually running, a prosecutor's `enforcement_failure` claim against
     you has exactly one thing to point at: the `Decision` you returned for
     that specific `cmd_id`. There is no ambiguity about "maybe the loop
     called the tool directly" — CONTRACTS.md 4.2 removed that path on
     purpose, and kit/loop/agent.py's own module docstring names the same
     invariant from the other side (the loop never imports this module,
     never sees a `Decision`, never executes anything itself).

The cost of that guarantee is that this file is PURE: synchronous, no I/O,
no threads, no `sleep`, 250 ms wall-clock deadline (RULES.md section 3).
Raising anything, returning something that is not a valid `Decision`, or
missing the deadline is treated by the arena as a DENIED command PLUS a 2
credit penalty PLUS an `integrity` event that hands the prosecutor a free
`enforcement_failure` — CONTRACTS.md 4.1's charging table, reproduced in
agent/README.md's own table. Getting this file to just plainly return valid
`Decision` values, every time, is worth more than getting it clever.

THE STARTER'S SHAPE (read this before you start editing `decide()`)
----------------------------------------------------------------------------
This starter FORWARDS ALMOST EVERYTHING AND DENIES NOTHING. That is not a
placeholder oversight — it is the honest zero-defence baseline you are
meant to beat: `bots/rookie` in the kit's own ladder does exactly the same
thing, and RULES.md's own words are "if you cannot beat Rookie you have a
bug, not a strategy." `decide()` below is structured as four named jobs —
ROUTE, ADMIT, AUTHORIZE, BUDGET — each with a one-line TODO naming what a
real implementation checks and why. None of the four currently rejects,
rewrites, or reroutes anything; they are seams, not solutions. Fill them in
using `agent/strategy.py` (routing/budget policy) and `agent/guardrails.py`
(the safety checks) — both already import cleanly from here.

ONE THING WORTH INTERNALISING BEFORE YOU WRITE YOUR FIRST REAL CHECK:
`verdict="deny"` costs the CALLER (your own team) **zero credits** —
CONTRACTS.md 4.1's charging table has exactly one $0 row, and it is this
one. Refusing to make a call you cannot justify is FREE. That makes
abstention a real strategy, not a luxury you can't afford: a `deny` you can
defend beats a `forward` you can't, every time a prosecutor is watching.

Stdlib only. No network, no randomness, no wall-clock reads, no sleeping —
none of that would even survive the kernel sandbox (CONTRACTS.md 12), but
the point is this file has no reason to want any of it in the first place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

# kit.mcp.types is a collaborator's file (workspace hard rule 2: import it,
# degrade gracefully). It is present as of this writing and is core, stable
# infrastructure (CONTRACTS.md 3.1) — but this module must still not fail to
# IMPORT if a concurrent edit ever breaks it transiently. When it is
# unavailable, `Decision.call` type-checking is skipped (not enforced), and
# `Gateway.decide` falls back to a minimal local dict-shaped stand-in so the
# rest of this file — everything that does not need a *real* ToolCall — still
# runs.
try:
    from kit.mcp.types import ToolCall
    _TOOLCALL_AVAILABLE = True
except ImportError:  # pragma: no cover - collaborator file
    ToolCall = Any  # type: ignore[assignment, misc]
    _TOOLCALL_AVAILABLE = False

# kit.loop.agent is also a collaborator's file, used only by this module's
# own __main__ demo (to build real Commands the same way the arena's trusted
# canonicaliser would) — never by decide() itself, which never touches the
# loop. Degraded the same way.
try:
    from kit.loop.agent import canonicalise_action as _canonicalise_action
except ImportError:  # pragma: no cover - collaborator file
    _canonicalise_action = None

from agent.strategy import (
    WASTEFUL_ROUND_CEILING,
    is_catalog_trap,
    pick_replica,
    round_allowance,
    successor_of,
)
from agent.telemetry import RecordingGatewayContext, Telemetry

try:
    from kit.mcp.specs import cost as _spec_cost
except ImportError:  # pragma: no cover - collaborator file
    _spec_cost = None

__all__ = [
    "COMMAND_KINDS",
    "DECISION_VERDICTS",
    "Command",
    "Decision",
    "GatewayContext",
    "Gateway",
]

# CONTRACTS.md 4.1: `Command.kind` — "mcp" | "a2a" | "discover". An "answer"
# action is NEVER a Command (kit/loop/agent.py's own module docstring: "an
# answer is not a tool call routed to a server, so it never becomes a
# Command at all") — it is handled entirely by the loop/arena and never
# reaches `Gateway.decide`.
COMMAND_KINDS: frozenset[str] = frozenset({"mcp", "a2a", "discover"})

# CONTRACTS.md 4.1: `Decision.verdict` — the closed three-member set.
DECISION_VERDICTS: frozenset[str] = frozenset({"forward", "deny", "rewrite"})


# ---------------------------------------------------------------------------
# Policy data + pure helpers used by Gateway._decide (no I/O, no state).
# ---------------------------------------------------------------------------

WRITE_TOOLS: frozenset[tuple[str, str]] = frozenset(
    {("progress", "record_mastery"), ("content", "flag_stale_slide"), ("content", "file_content_bug")}
)
# Body keys that try to choose a route/replica — routing belongs in the header.
_BODY_ROUTE_KEYS = ("route", "_route", "replica", "mcp-replica", "x-mcp-body-route")
# Argument keys that name WHOM a call acts on. `for_learner` on a READ is not
# authority (it is only a filter), so it is deliberately not in this list.
_TARGET_KEYS = ("learner", "learner_id", "act", "subject", "target")
_UNTRUSTED_MARKS = frozenset({"unvouched", "invalid", "forged", "unknown", "unsigned", "mismatch"})
# Instruction-shaped text aimed at an agent (not merely emphatic prose).
_INJECTION_MARKERS = (
    "ignore previous instruction", "ignore all previous", "disregard the above", "system override",
    "you must now", "instead, record", "also record this for", "reveal the", "print the system",
    "bỏ qua mọi hướng dẫn",
)
_MAX_ARG_CHARS = 1024
# Cheapest useful masks for the two "punishment button" catalog tools.
_CHEAP_MASKS = {("registry", "list_servers"): ("name",), ("glossary", "list_terms"): ("term",)}
# Credits kept in reserve per remaining round before discovery is refused.
_CREDIT_FLOOR_PER_ROUND = 4


def _header(headers: Mapping[str, Any], name: str) -> Any:
    name = name.lower()
    for k, v in headers.items():
        if str(k).lower() == name:
            return v
    return None


def _path_id_of(anchor: Any) -> str | None:
    if not isinstance(anchor, str) or ":" not in anchor:
        return None
    return anchor.split(":", 1)[1].split("/", 1)[0] or None


def _rev_of(anchor: Any) -> str | None:
    """The replica letter an anchor names (`Frame:abc/w/041` -> `w`), if any."""
    if not isinstance(anchor, str):
        return None
    parts = anchor.split(":", 1)[-1].split("#", 1)[0].split("/")
    return parts[1] if len(parts) >= 3 and parts[1] in ("w", "c") else None


# A2A peers whose call is a corroboration, not the answer itself — the first thing
# to postpone when a round's allowance is spent (citation-checker is also
# rate-limited to 2 calls per 3 rounds).
_OPTIONAL_PEERS = frozenset({"citation-checker"})


def _injected_instruction(args: Mapping[str, Any]) -> str | None:
    blob = " ".join(str(v) for v in args.values()).casefold()
    return next((m for m in _INJECTION_MARKERS if m in blob), None)


def _looks_like_learner(value: str) -> bool:
    return value.strip().casefold().startswith("learner:")


def _same_learner(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def _idempotency_key(server: str, tool: str, args: Mapping[str, Any]) -> str:
    """Deterministic: the same logical write always gets the same key, so a retry
    of it is recognisable as a duplicate instead of a fresh write."""
    import hashlib
    import json as _json

    body = _json.dumps({"s": server, "t": tool, "a": dict(args)}, sort_keys=True, default=str)
    return "idem-" + hashlib.sha256(body.encode("utf8")).hexdigest()[:16]


def _estimate_cost(server: str, tool: str, fields: tuple[str, ...]) -> int:
    if _spec_cost is None:
        return 4
    try:
        return int(_spec_cost(server, tool, fields=fields))
    except Exception:  # unknown tool: an honest middle guess, never 0
        return 4


def _same_call_already_failed(history: Any, cmd: "Command") -> bool:
    """True iff `ctx.history` holds an earlier FAILED call identical to `cmd`
    (server, tool, args, fields). History entries are read defensively — any
    shape this does not recognise is simply skipped."""
    for entry in history or ():
        if not isinstance(entry, Mapping):
            continue
        prior = entry.get("command") or entry.get("cmd")
        if prior is not None and not isinstance(prior, Mapping):
            prior = prior.to_dict() if hasattr(prior, "to_dict") else None
        outcome = entry.get("outcome") or entry.get("result") or {}
        if not isinstance(prior, Mapping) or not isinstance(outcome, Mapping):
            continue
        failed = outcome.get("ok") is False or bool(outcome.get("error_code"))
        code = outcome.get("error_code")
        if not failed or code == "unavailable":  # one identical retry of `unavailable` is sanctioned
            continue
        if (prior.get("server"), prior.get("tool"), dict(prior.get("args") or {}), tuple(prior.get("fields") or ())) == (
            cmd.server, cmd.tool, dict(cmd.args), tuple(cmd.fields)
        ):
            return True
    return False


@dataclass(frozen=True, slots=True)
class Command:
    """CONTRACTS.md 4.1, field for field — "canonicalised by the arena
    BEFORE the student sees it". You never build one of these from your own
    agent's raw text; the arena's canonicaliser (kit/loop/agent.py's
    `canonicalise_action`, run inside the trusted envelope) already did that
    work and minted `cmd_id` by the time `decide()` sees it. The
    `from_action_dict` classmethod below exists only so this file's own demo
    (and your local tests, if you write any) can build a realistic `Command`
    without duplicating the arena's canonicalisation logic."""

    cmd_id: str
    kind: str  # "mcp" | "a2a" | "discover" — see COMMAND_KINDS
    raw: str
    server: str
    tool: str
    args: dict
    fields: tuple[str, ...]
    headers: dict
    lease_id: str | None
    call_index: int

    def __post_init__(self) -> None:
        if not isinstance(self.cmd_id, str) or not self.cmd_id:
            raise ValueError(f"Command.cmd_id must be a non-empty str, got {self.cmd_id!r}")
        if self.kind not in COMMAND_KINDS:
            raise ValueError(f"Command.kind must be one of {sorted(COMMAND_KINDS)}, got {self.kind!r}")
        if not isinstance(self.server, str) or not self.server:
            raise ValueError(f"Command.server must be a non-empty str, got {self.server!r}")
        if not isinstance(self.tool, str) or not self.tool:
            raise ValueError(f"Command.tool must be a non-empty str, got {self.tool!r}")
        if not isinstance(self.args, dict):
            raise ValueError(f"Command.args must be a dict, got {type(self.args).__name__}")
        if not isinstance(self.headers, dict):
            raise ValueError(f"Command.headers must be a dict, got {type(self.headers).__name__}")
        if (
            not isinstance(self.call_index, int)
            or isinstance(self.call_index, bool)
            or self.call_index < 0
        ):
            raise ValueError(f"Command.call_index must be a non-negative int, got {self.call_index!r}")

    @classmethod
    def from_action_dict(cls, action: Mapping[str, Any], *, cmd_id: str) -> "Command":
        """Build a `Command` from the dict shape `kit.loop.agent.canonicalise_action`
        returns (`kind, raw, server, tool, args, fields, headers, lease_id,
        call_index` — everything except the arena-minted `cmd_id`, supplied
        here as a keyword). Raises `ValueError` if `action["kind"] ==
        "answer"` — an answer is never a Command (see the module docstring).
        This is a convenience for tests/demos, not something the real arena
        calls: the trusted envelope mints `cmd_id` itself and constructs the
        real `Command` on its own side of the boundary."""
        kind = action.get("kind")
        if kind == "answer":
            raise ValueError(
                "an 'answer' action never becomes a Command (kit/loop/agent.py: "
                "\"an answer is not a tool call routed to a server\") — do not "
                "route it through Gateway.decide at all"
            )
        return cls(
            cmd_id=cmd_id,
            kind=kind,
            raw=action["raw"],
            server=action["server"],
            tool=action["tool"],
            args=dict(action.get("args", {})),
            fields=tuple(action.get("fields", ())),
            headers=dict(action.get("headers", {})),
            lease_id=action.get("lease_id"),
            call_index=action.get("call_index", 0),
        )

    def to_dict(self) -> dict:
        return {
            "cmd_id": self.cmd_id,
            "kind": self.kind,
            "raw": self.raw,
            "server": self.server,
            "tool": self.tool,
            "args": dict(self.args),
            "fields": list(self.fields),
            "headers": dict(self.headers),
            "lease_id": self.lease_id,
            "call_index": self.call_index,
        }


@dataclass(frozen=True, slots=True)
class Decision:
    """CONTRACTS.md 4.1, field for field.

    Validated strictly (`__post_init__`) because a *structurally* invalid
    `Decision` is charged exactly like a raised exception — CONTRACTS.md
    4.1's charging table: "malformed Decision (schema-invalid) -> 2 cr
    penalty, command denied." Failing loudly HERE, in your own process
    during development, is strictly better than discovering it live in a
    duel as an unexplained penalty.

    `verdict == "deny"` requires a non-empty `reason` (CONTRACTS.md 4.1:
    "required when verdict == 'deny'; shown in the combat log") and
    forbids `call` — a real denial has nothing left to carry out.
    `verdict` in `("forward", "rewrite")` requires `call` to be set — the
    arena executes exactly that `ToolCall`, nothing else, per the trusted
    envelope's whole point (see the module docstring)."""

    verdict: str  # "forward" | "deny" | "rewrite" — see DECISION_VERDICTS
    reason: str | None = None
    call: "ToolCall | None" = None
    quarantine: bool = False
    note: str | None = None

    def __post_init__(self) -> None:
        if self.verdict not in DECISION_VERDICTS:
            raise ValueError(
                f"Decision.verdict must be one of {sorted(DECISION_VERDICTS)}, got {self.verdict!r}"
            )
        if self.verdict == "deny":
            if not isinstance(self.reason, str) or not self.reason.strip():
                raise ValueError("Decision.verdict=='deny' requires a non-empty 'reason'")
            if self.call is not None:
                raise ValueError("Decision.verdict=='deny' must not carry a 'call' — there is nothing to run")
        else:  # forward | rewrite
            if self.call is None:
                raise ValueError(f"Decision.verdict=={self.verdict!r} requires 'call' to be set")
            if _TOOLCALL_AVAILABLE and not isinstance(self.call, ToolCall):
                raise ValueError(
                    f"Decision.call must be a kit.mcp.types.ToolCall instance, got {type(self.call).__name__}"
                )
        if not isinstance(self.quarantine, bool):
            raise ValueError(f"Decision.quarantine must be a bool, got {self.quarantine!r}")
        if self.note is not None and not isinstance(self.note, str):
            raise ValueError(f"Decision.note must be a str or None, got {self.note!r}")

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "call": self.call.to_dict() if self.call is not None and hasattr(self.call, "to_dict") else self.call,
            "quarantine": self.quarantine,
            "note": self.note,
        }


@runtime_checkable
class GatewayContext(Protocol):
    """CONTRACTS.md 4.2 — "read-only, arena-provided". Note what this is
    NOT: unlike `Command`/`Decision` above, CONTRACTS.md writes this as a
    plain `class`, not a `@dataclass(frozen=True, ...)`. That is a real
    signal, not an inconsistency — a `GatewayContext` is a LIVE VIEW the
    arena owns and updates as the duel actually progresses (credits get
    spent, rounds advance, leases mint and expire), not a frozen snapshot
    you receive once. This file therefore models it as a structural
    `Protocol`: the arena hands your `Gateway.__init__` some object shaped
    like this (see `agent/telemetry.py`'s `RecordingGatewayContext` for a
    concrete example your own tests/demos can build), and you read
    `self.ctx.<field>` fresh every time `decide()` runs — NEVER cache a
    context field into a local variable across calls; if you need memory
    that persists across the duel (a cache, a budget tracker, drift notes),
    keep it on YOUR OWN `Gateway` instance attributes instead (CONTRACTS.md
    4.3: "Gateway is instantiated once per duel... persists across the 10
    rounds").

    There is deliberately no `execute` method here — see the module
    docstring's "WHY THERE IS NO execute() METHOD" section. `emit` is the
    ONE thing you can do that has any side effect at all, and it writes to
    `own_telemetry` only: your own side, never scored, never shown to the
    opponent (`agent/telemetry.py` wraps it)."""

    act: str  # "learner:sv-0417" — WHOM YOU SERVE. Authority derives from this.
    sub: str  # "agent:vlearn-tutor" — what you are. NOT authority.
    scopes: frozenset[str]  # {"wiki.read"}; writes need "wiki.write:progress" etc.
    credits: int  # remaining this duel
    round: int
    call_index: int
    leases: tuple[str, ...]  # live lease ids, arena-tracked
    history: tuple[Mapping[str, Any], ...]  # YOUR OWN prior (Command, Decision, outcome) triples this duel

    def emit(self, name: str, **payload: Any) -> None: ...


class Gateway:
    """The control plane. One instance per duel (CONTRACTS.md 4.3) — built
    once at duel start with a `GatewayContext`, then asked to `decide()` on
    every MCP/A2A/DISCOVER command either side of the duel makes for all 10
    rounds. See the module docstring for the trusted-envelope diagram and
    why there is no `execute()` to call instead.

    Instance attributes below are this starter's ENTIRE per-duel memory —
    all currently unused by `decide()`'s naive body, but declared here
    (rather than invented ad hoc later) so the four TODO jobs below have
    somewhere obvious to keep state once you implement them. `agent/
    strategy.py` has working building blocks for exactly this (a budget
    pacer, a result cache, a replica-choice heuristic) — this starter does
    not wire them in for you; that wiring is the assignment.
    """

    def __init__(self, ctx: GatewayContext) -> None:
        self.ctx = ctx
        self._telemetry = Telemetry(ctx)

        # --- per-duel memory, unused by the naive starter below ---------
        # A cache of anchor -> body-ish data you have already paid for this
        # duel (agent/strategy.py's ResultCache is a ready-made version of
        # this). Populating it needs the *result* of a call, which decide()
        # never sees (it only sees the outgoing Command) — you would fill
        # this from whatever the arena hands back to your agent loop AFTER
        # a call executes, then consult it here on the NEXT decide() call
        # for the same anchor.
        self._seen_anchors: dict[str, Any] = {}
        # Credits you have personally authorised so far this duel — your
        # own running total, independent of (and a cross-check against)
        # `ctx.credits`, which the arena maintains authoritatively.
        self._credits_authorised: int = 0
        # Command ids you have already denied, in case a later job wants to
        # know "have I already said no to this once".
        self._denied_cmd_ids: set[str] = set()
        # Idempotency keys this gateway has let through — a second write with
        # the same key is refused (exactly-once, write_violation).
        self._idempotency_keys: set[str] = set()
        # anchor -> latest etag seen from registry.provenance (note_provenance, or
        # harvested from ctx.history). Lets a write carry a real If-Match instead of
        # being refused.
        self._etags: dict[str, str] = {}
        # round -> credits this gateway has authorised in that round.
        self._spent_by_round: dict[int, int] = {}

    def decide(self, cmd: Command) -> Decision:
        """SYNCHRONOUS. PURE. NO I/O. 250 ms wall (RULES.md section 3).
        Raising anything, or returning a `Decision` `__post_init__` rejects,
        is treated by the arena exactly like an explicit deny PLUS a 2
        credit penalty PLUS a scored `integrity` event (CONTRACTS.md 4.1's
        charging table) — so the one thing this method must never do is
        blow up or wander off into I/O, no matter how tempting a "quick
        check" against something external looks. Everything you need to
        decide is already sitting in `cmd` and `self.ctx`.

        This starter forwards EVERYTHING it is handed, unmodified, and
        denies NOTHING — see the module docstring's "THE STARTER'S SHAPE".
        The four jobs below are named, ordered, and commented; none of them
        currently changes the outcome."""
        self._telemetry.decision_seen(cmd)
        try:
            decision = self._decide(cmd)
        except Exception as exc:  # noqa: BLE001 — raising is charged as enforcement_failure; never raise
            return self.deny(cmd, f"gateway check failed closed ({type(exc).__name__})")
        if decision.verdict != "deny":  # denials were already recorded by self.deny()
            self._telemetry.decision_made(cmd, decision)
        return decision

    def _decide(self, cmd: Command) -> Decision:
        """The four jobs, in order. Each check below denies only on an affirmative,
        visible fact about `cmd` or `self.ctx` — never on a hunch — because a blank
        card answered with a refusal costs 8 just like an attack let through.

        JOB 1 — ROUTE ............ routing smuggled in the body, deprecated tools,
                                   explicit replica header
        JOB 2 — ADMIT ............ dead leases, injected instructions, counterfeit
                                   servers / cards, unverified peers, inflated
                                   payloads, a write that already conflicted
        JOB 3 — AUTHORIZE ........ act ownership, delegation audience, write scope,
                                   exactly-once write headers
        JOB 4 — BUDGET ........... punishment-button masks, credit floor
        """
        server, tool = cmd.server, cmd.tool
        args = dict(cmd.args)
        headers = dict(cmd.headers)
        fields = tuple(cmd.fields)
        rewrote: list[str] = []

        # ---- JOB 1 — ROUTE ----------------------------------------------
        # Routing is decided by the header, never by the body: a route/replica
        # field inside `args` is exactly what `drop_header` / `swap_replica` plant
        # (header_spoof / replica_flip). Refuse it rather than strip it — a body
        # route means something upstream rewrote the request.
        body_route = [k for k in _BODY_ROUTE_KEYS if k in args]
        if body_route:
            return self.deny(cmd, f"route declared in the request body ({', '.join(body_route)}), not the Mcp-Replica header")
        successor = successor_of(server, tool)
        if successor is not None:  # slides.search -> slides.query (deprecated = wasteful)
            server, tool = successor
            rewrote.append(f"deprecated {cmd.server}.{cmd.tool} -> {server}.{tool}")
        replica_key = next((k for k in headers if k.lower() == "mcp-replica"), None)
        if replica_key is not None and str(headers[replica_key]).lower() not in ("w", "c"):
            return self.deny(cmd, f"invalid Mcp-Replica header {headers[replica_key]!r}")
        anchor_rev = _rev_of(args.get("anchor"))
        if replica_key is not None and anchor_rev and str(headers[replica_key]).lower() != anchor_rev:
            # The header must agree with the replica the anchor itself names; a
            # mismatch is exactly what a swap_replica/replica_flip produces.
            return self.deny(cmd, f"Mcp-Replica={headers[replica_key]!r} contradicts the anchor's own replica /{anchor_rev}/")
        if replica_key is None and server == "slides" and tool in ("get_frame", "query", "whatlinkshere"):
            # Pin the replica on the header. An anchor that names its replica keeps it;
            # otherwise read the FRESHER replica of a drifting deck (measured table).
            path_id = _path_id_of(args.get("anchor")) or args.get("path_id")
            choice = anchor_rev or pick_replica(path_id=path_id, known_drifting=False).replica
            headers["Mcp-Replica"] = choice
            rewrote.append(f"Mcp-Replica={choice}")

        # ---- JOB 2 — ADMIT ----------------------------------------------
        if (server, tool) == ("slides", "get_frame"):
            live = tuple(getattr(self.ctx, "leases", ()) or ())
            if not cmd.lease_id:
                return self.deny(cmd, "get_frame without a lease — run slides.query first (protocol_misuse)")
            if live and cmd.lease_id not in live:
                return self.deny(cmd, f"lease {cmd.lease_id} is not live any more — re-query before get_frame")
        injected = _injected_instruction(args)
        if injected:
            return self.deny(cmd, f"instruction-shaped text in the call payload ({injected!r}) — not forwarding it")
        fingerprint = _header(headers, "x-server-fingerprint")
        if fingerprint is not None and str(fingerprint).lower() in _UNTRUSTED_MARKS:
            return self.deny(cmd, f"server fingerprint {fingerprint!r} is not vouched for by the registry (shadow)")
        signature = _header(headers, "x-card-signature")
        if signature is not None and str(signature).lower() in _UNTRUSTED_MARKS:
            return self.deny(cmd, "peer Agent Card signature does not verify (forged_card)")
        if args.get("peer_unverified") or args.get("unverified"):
            return self.deny(cmd, "peer answer is flagged unverified — needs an independent cross-check first")
        oversized = [k for k, v in args.items() if isinstance(v, str) and len(v) > _MAX_ARG_CHARS]
        if oversized:
            return self.deny(cmd, f"argument {oversized[0]!r} is {len(args[oversized[0]])} chars — inflated payload (schema_bomb)")
        if _same_call_already_failed(getattr(self.ctx, "history", ()) or (), cmd):
            return self.deny(cmd, "identical call already failed this duel and nothing changed — retrying it unchanged is wasteful")

        # ---- JOB 3 — AUTHORIZE -------------------------------------------
        act = str(getattr(self.ctx, "act", "") or "")
        for key in _TARGET_KEYS:
            target = args.get(key)
            if isinstance(target, str) and _looks_like_learner(target) and act and not _same_learner(target, act):
                return self.deny(cmd, f"{key}={target} is not the learner this session serves ({act}) — authority comes from act, not sub")
        aud = _header(headers, "aud")
        if aud is not None and str(aud) not in (server, f"mcp:{server}", f"a2a:{server}"):
            return self.deny(cmd, f"delegation audience {aud!r} does not match the server being called ({server})")
        if cmd.kind == "a2a" and aud is None:
            headers["aud"] = server  # a delegation always names its audience
            rewrote.append(f"aud={server}")
        if (server, tool) in WRITE_TOOLS:
            scopes = frozenset(getattr(self.ctx, "scopes", ()) or ())
            needed = f"wiki.write:{server}"
            if needed not in scopes:
                return self.deny(cmd, f"write {server}.{tool} needs scope {needed!r}; granted {sorted(scopes)}")
            if not _header(headers, "if-match"):
                etag = self._etag_for(args)
                if etag is None:
                    return self.deny(cmd, "write without an If-Match etag — read registry.provenance first")
                headers["If-Match"] = etag
                rewrote.append("If-Match from the last registry.provenance read")
            key = _header(headers, "idempotency-key")
            if not key:
                key = _idempotency_key(server, tool, args)
                headers["Idempotency-Key"] = key
                rewrote.append("Idempotency-Key added")
            if key in self._idempotency_keys:
                return self.deny(cmd, f"Idempotency-Key {key!r} already used this duel — refusing a duplicate write")
            pending_key = key
        else:
            pending_key = None

        # ---- JOB 4 — BUDGET ------------------------------------------------
        if is_catalog_trap(server, tool, fields):
            fields = _CHEAP_MASKS.get((server, tool), ("name",))
            rewrote.append(f"catalog mask -> {list(fields)}")
        elif fields == ("*",):
            fields = ()  # the tool's default mask, not the full dump
            rewrote.append("fields * -> default mask")
        credits = int(getattr(self.ctx, "credits", 100) or 0)
        rnd = int(getattr(self.ctx, "round", 1) or 1)
        floor = max(0, 10 - rnd) * _CREDIT_FLOOR_PER_ROUND
        est = _estimate_cost(server, tool, fields)
        if cmd.kind == "discover" and credits - est < floor:
            return self.deny(cmd, f"discovery would leave {credits - est} cr, below the {floor} cr reserve for the remaining rounds")
        if credits - est < 0:
            return self.deny(cmd, f"call costs ~{est} cr but only {credits} cr are left this duel")
        spent = self._spent_by_round.get(rnd, 0)
        allowance = round_allowance(rnd)
        if spent + est > allowance:
            optional = cmd.kind == "discover" or server in _OPTIONAL_PEERS
            if optional:
                return self.deny(cmd, f"round {rnd} allowance is {allowance} cr ({spent} spent); this optional call (~{est} cr) waits for a later round")
            if fields:
                cheaper = _estimate_cost(server, tool, ())
                if cheaper < est:  # fall back to the tool's default mask before refusing
                    fields, est = (), cheaper
                    rewrote.append(f"mask -> default to stay within the round {rnd} allowance")
            if spent + est > WASTEFUL_ROUND_CEILING:
                # A core call over the 11-cr line costs at most a `wasteful` (3);
                # refusing it risks a `wrong_answer` (8). Let it through, on record.
                rewrote.append(f"over the {WASTEFUL_ROUND_CEILING}-cr round line ({spent + est} cr) — core call kept")
        self._spent_by_round[rnd] = spent + est
        self._credits_authorised += est
        if pending_key is not None:
            self._idempotency_keys.add(pending_key)

        call = self._to_tool_call(cmd, server=server, tool=tool, fields=fields, headers=headers)
        if rewrote:
            return Decision(verdict="rewrite", call=call, note="; ".join(rewrote))
        return Decision(verdict="forward", call=call)

    # -- fed by the loop after a call returns (arena/harness may call these) --------
    def note_provenance(self, anchor: str, etag: str) -> None:
        """Remember the etag `registry.provenance` returned for `anchor`; the next
        write to it gets `If-Match` automatically."""
        if isinstance(anchor, str) and isinstance(etag, str) and etag:
            self._etags[anchor] = etag

    def note_card(self, server: str, card: Mapping[str, Any]) -> None:
        """Accepted for interface compatibility; card verification happens on the
        command itself (signature / fingerprint headers)."""
        return None

    def _etag_for(self, args: Mapping[str, Any]) -> str | None:
        """Latest known etag for a write's target: noted via `note_provenance`, or
        read from a successful `registry.provenance` result in `ctx.history`."""
        targets = [str(args[k]) for k in ("anchor", "learner", "learner_id", "act") if isinstance(args.get(k), str)]
        for entry in reversed(tuple(getattr(self.ctx, "history", ()) or ())):
            if not isinstance(entry, Mapping):
                continue
            prior = entry.get("command") or entry.get("cmd")
            if prior is not None and not isinstance(prior, Mapping):
                prior = prior.to_dict() if hasattr(prior, "to_dict") else None
            outcome = entry.get("outcome") or entry.get("result") or {}
            if not isinstance(prior, Mapping) or not isinstance(outcome, Mapping):
                continue
            if (prior.get("server"), prior.get("tool")) != ("registry", "provenance"):
                continue
            anchor = str((prior.get("args") or {}).get("anchor", ""))
            etag = outcome.get("etag")
            if isinstance(etag, str) and etag and anchor and anchor not in self._etags:
                self._etags[anchor] = etag
        for t in targets:
            for anchor, etag in self._etags.items():
                if anchor.casefold() == t.casefold():
                    return etag
        return None

    def deny(self, cmd: Command, reason: str) -> Decision:
        """The shape of a correct denial — no `call`, a non-empty `reason` — built
        and recorded (own telemetry only) in one place."""
        self._denied_cmd_ids.add(cmd.cmd_id)
        decision = Decision(verdict="deny", reason=reason)
        self._telemetry.decision_made(cmd, decision)
        return decision

    def _to_tool_call(self, cmd: Command, *, server: str | None = None, tool: str | None = None,
                      fields: tuple[str, ...] | None = None, headers: dict | None = None) -> "ToolCall":
        """`Command` -> the `ToolCall` (CONTRACTS.md 3.1) the arena will
        actually execute on a `forward`/`rewrite` verdict. When
        `kit.mcp.types` is unavailable (see the module-level import guard),
        falls back to a plain dict carrying the identical fields — `Decision`
        accepts it either way (the `ToolCall` isinstance check inside
        `Decision.__post_init__` only runs when the real class loaded)."""
        fields = {
            "server": server or cmd.server,
            "tool": tool or cmd.tool,
            "args": dict(cmd.args),
            "fields": cmd.fields if fields is None else tuple(fields),
            "headers": dict(cmd.headers) if headers is None else dict(headers),
            "lease_id": cmd.lease_id,
            "call_index": cmd.call_index,
        }
        if _TOOLCALL_AVAILABLE:
            return ToolCall(**fields)
        return fields  # type: ignore[return-value]


if __name__ == "__main__":
    print("=== agent.gateway: Command / Decision validation ===\n")

    good_cmd = Command(
        cmd_id="cmd:0000",
        kind="mcp",
        raw="MCP slides.get_frame anchor=Frame:3f2a9c11/w/041 fields=title,body lease=lse_7f21",
        server="slides",
        tool="get_frame",
        args={"anchor": "Frame:3f2a9c11/w/041"},
        fields=("body", "title"),
        headers={},
        lease_id="lse_7f21",
        call_index=0,
    )
    print(f"  Command constructed: {good_cmd}")
    assert good_cmd.kind == "mcp"

    print("\n  Rejection demo (each must raise ValueError):")

    def _expect_value_error(label: str, fn) -> None:
        try:
            fn()
        except ValueError as exc:
            print(f"    [{label:38}] -> ValueError: {exc}")
        else:
            raise AssertionError(f"expected ValueError for case {label!r}")

    _expect_value_error("Command.kind == 'answer'", lambda: Command(
        cmd_id="cmd:0001", kind="answer", raw="x", server="slides", tool="get_frame",
        args={}, fields=(), headers={}, lease_id=None, call_index=0,
    ))
    _expect_value_error("Decision verdict='deny' with no reason", lambda: Decision(verdict="deny"))
    _expect_value_error(
        "Decision verdict='forward' with no call", lambda: Decision(verdict="forward")
    )
    _expect_value_error(
        "Decision verdict='deny' carrying a call",
        lambda: Decision(verdict="deny", reason="nope", call={"server": "x", "tool": "y"}),
    )
    _expect_value_error("Decision verdict='?' unknown", lambda: Decision(verdict="???"))

    print("\n=== Command.from_action_dict — real canonicaliser integration ===\n")
    if _canonicalise_action is None:
        print("  kit.loop.agent not importable yet — skipping the live canonicaliser demo")
        demo_commands: list[Command] = [good_cmd]
    else:
        raw_actions = [
            "MCP registry.provenance anchor=Frame:3f2a9c11/w/041 fields=etag",
            'MCP slides.query q="streamable http replaces http+sse" fields=title,body',
            "A2A curriculum-analyst.which_days_cover concept=Concept:streamable-http fields=anchor,course_day,track",
            "DISCOVER registry.list_servers fields=name",
        ]
        demo_commands = []
        for i, raw in enumerate(raw_actions):
            action = _canonicalise_action(raw, call_index=i)
            cmd = Command.from_action_dict(action, cmd_id=f"cmd:{i:04d}")
            print(f"  {raw!r}\n    -> {cmd.kind}: {cmd.server}.{cmd.tool} fields={cmd.fields}")
            demo_commands.append(cmd)
        assert {c.kind for c in demo_commands} == {"mcp", "a2a", "discover"}

        answer_action = _canonicalise_action(
            'ANSWER {"text": "day 26, track P2T2"}', call_index=None
        )
        try:
            Command.from_action_dict(answer_action, cmd_id="cmd:9999")
        except ValueError as exc:
            print(f"\n  an 'answer' action correctly refuses to become a Command: {exc}")
        else:
            raise AssertionError("expected ValueError for an 'answer' action")

    print("\n=== Gateway.decide — the naive starter forwards everything ===\n")
    ctx = RecordingGatewayContext(
        act="learner:sv-0401",
        sub="agent:demo-team",
        scopes=frozenset({"wiki.read"}),
        credits=100,
        round=1,
        call_index=0,
        leases=(),
        history=(),
    )
    assert isinstance(ctx, GatewayContext), "RecordingGatewayContext must structurally satisfy GatewayContext"
    gw = Gateway(ctx)
    for cmd in demo_commands:
        gw._spent_by_round.clear()  # independent examples: each starts with a fresh round budget
        decision = gw.decide(cmd)
        print(f"  decide({cmd.server}.{cmd.tool}) -> verdict={decision.verdict!r} quarantine={decision.quarantine}")
        assert decision.verdict in ("forward", "rewrite"), decision
        assert decision.call is not None
        call_dict = decision.call.to_dict() if hasattr(decision.call, "to_dict") else decision.call
        assert call_dict["server"] == cmd.server
        assert call_dict["tool"] == cmd.tool

    print(f"\n=== Gateway.deny — the unused-by-default free-abstention path ===\n")
    denial = gw.deny(demo_commands[0], reason="demo: withholding pending a fresher registry.provenance read")
    print(f"  gw.deny(...) -> verdict={denial.verdict!r} reason={denial.reason!r} call={denial.call!r}")
    assert denial.verdict == "deny"
    assert denial.call is None
    assert demo_commands[0].cmd_id in gw._denied_cmd_ids

    print(f"\n=== own_telemetry — recorded on YOUR side only, never shown to the opponent ===\n")
    print(f"  {len(ctx.events)} events recorded on this ctx this run:")
    for ev in ctx.events:
        print(f"    {ev['name']}: {sorted(ev['payload'].keys())}")
    assert len(ctx.events) >= len(demo_commands) * 2 + 1  # decision_seen + decision_made per call, plus the deny

    print("\nAll agent/gateway.py demos passed.")
