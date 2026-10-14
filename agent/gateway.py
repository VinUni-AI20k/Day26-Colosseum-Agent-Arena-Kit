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

from dataclasses import dataclass, replace
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

from agent.telemetry import RecordingGatewayContext, Telemetry
from agent.strategy import BudgetPacer, cheap_mask, pick_replica, successor_of, should_delegate
from kit.mcp.specs import TOOL_SPECS, A2A_PEERS
from kit.mcp.servers import _LOCAL_TOOL_SPECS

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
        self._etags: dict[str, str] = {}
        self._cards: dict[str, dict] = {}
        self._write_keys: set[str] = set()
        self._calls: dict[tuple[str, str], list[int]] = {}
        self._pacer = BudgetPacer(starting_pool=ctx.credits)
        self._history_seen = 0
        self._failures: list[tuple[dict, str]] = []
        self._suspicious_anchors: set[str] = set()

    def note_provenance(self, anchor: str, etag: str) -> None:
        """Record an arena-delivered provenance result, never model arguments."""
        self._etags[anchor] = etag

    def note_card(self, server: str, card: dict) -> None:
        """Integration hook: only registry-verified cards admit peers."""
        self._cards[server] = dict(card)

    def note_result(self, call: ToolCall, result: Mapping[str, Any]) -> None:
        """Optional trusted-loop hook; model-supplied claims are never observations."""
        if not result.get("ok"):
            code = (result.get("error") or {}).get("code")
            if isinstance(code, str):
                self._failures.append((call.to_dict(), code))
            return
        anchor = call.args.get("anchor")
        if call.server == "registry" and call.tool == "provenance" and anchor:
            rows = result.get("rows") or []
            etag = result.get("etag") or (rows[0].get("etag") if rows else None)
            if isinstance(etag, str) and etag:
                self.note_provenance(anchor, etag)
        if call.server == "slides" and call.tool == "get_frame" and isinstance(anchor, str):
            parts = anchor.split("/")
            replica = result.get("replica")
            if len(parts) > 1 and replica in ("w", "c") and parts[1] != replica:
                self._suspicious_anchors.add(anchor)

    def _read_history(self) -> None:
        # Context history is arena-owned (command, decision, outcome), not raw content.
        history = self.ctx.history
        if len(history) < self._history_seen:
            self._history_seen = 0
        for item in history[self._history_seen:]:
            if not isinstance(item, Mapping):
                continue
            command = item.get("command")
            outcome = item.get("outcome")
            decision = item.get("decision")
            if hasattr(decision, "call"):
                call = decision.call
            elif isinstance(decision, Mapping):
                call = decision.get("call")
            else:
                call = command
            if isinstance(call, Mapping):
                try:
                    call = ToolCall.from_dict(call)
                except (KeyError, TypeError, ValueError):
                    continue
            if isinstance(call, ToolCall) and isinstance(outcome, Mapping):
                self.note_result(call, outcome)
        self._history_seen = len(history)

    def decide(self, cmd: Command) -> Decision:
        """Route, admit, authorize and meter without executing the request."""
        self._telemetry.decision_seen(cmd)
        self._read_history()
        specs = {**TOOL_SPECS, **_LOCAL_TOOL_SPECS}
        headers = {}
        for key, value in cmd.headers.items():
            if not isinstance(key, str):
                return self.deny(cmd, "malformed header name")
            key = key.lower()
            if key in headers and headers[key] != value:
                return self.deny(cmd, "conflicting header values")
            headers[key] = value
        server, tool = cmd.server, cmd.tool
        # search's snippet corresponds to query's body; anchors are envelope data.
        fields = tuple(cmd.fields)
        successor = successor_of(server, tool)
        if successor:
            server, tool = successor
            fields = tuple("body" if f == "snippet" else f for f in fields if f != "anchor")
        spec = specs.get((server, tool))
        if spec is None:
            return self.deny(cmd, "unknown server or tool")
        if (server in A2A_PEERS) != (cmd.kind == "a2a"):
            return self.deny(cmd, "command transport does not match server")
        if any(cmd.args.get(k) for k in ("route", "_route", "replica")):
            return self.deny(cmd, "routing must be declared in headers")
        if "x-mcp-body-route" in headers:
            return self.deny(cmd, "body routing header is not supported")
        replica = headers.get("mcp-replica")
        if replica is not None and replica not in ("w", "c"):
            return self.deny(cmd, "invalid replica")
        # Explicit anchor revisions are semantic intent: never silently switch them.
        anchor = cmd.args.get("anchor")
        if anchor is not None and not isinstance(anchor, str):
            return self.deny(cmd, "malformed resource anchor")
        if server == "slides":
            parts = anchor.split("/") if isinstance(anchor, str) else []
            pinned = parts[1] if len(parts) > 1 and parts[1] in ("w", "c") else None
            headers["mcp-replica"] = pinned or replica or pick_replica(
                path_id=cmd.args.get("path_id"), known_drifting=False).replica
        routed = replace(cmd, server=server, tool=tool, fields=fields, headers=headers)

        # ADMIT: unknown masks, missing prerequisites and invalid leases are free denials.
        if any(not isinstance(f, str) for f in fields):
            return self.deny(cmd, "malformed field mask")
        if "*" in fields and fields != ("*",):
            return self.deny(cmd, "wildcard must be the entire mask")
        if fields != ("*",) and not set(fields) <= set(spec.all_fields):
            return self.deny(cmd, "unsupported field mask")
        if cmd.lease_id is not None and not isinstance(cmd.lease_id, str):
            return self.deny(cmd, "malformed lease id")
        if spec.needs_lease and (not cmd.lease_id or cmd.lease_id not in self.ctx.leases):
            return self.deny(cmd, "get_frame requires a live arena lease")
        if spec.needs_lease and not isinstance(anchor, str):
            return self.deny(cmd, "get_frame requires an anchor")
        if isinstance(anchor, str) and anchor in self._suspicious_anchors:
            return self.deny(cmd, "replica evidence conflicts; obtain provenance before reuse")
        retry_args = dict(cmd.args)
        if server == "slides" and tool in ("query", "search") and retry_args.get("ns") is None:
            retry_args["ns"] = "Frame"
        for prior, code in self._failures:
            if code in {"bad_request", "not_found", "lease_required", "lease_expired", "conflict", "precondition_missing"}:
                if (prior["server"], prior["tool"], prior["args"], prior["headers"], prior["lease_id"]) == (server, tool, retry_args, headers, cmd.lease_id):
                    return self.deny(cmd, "unchanged retry of a mechanically failed call")
        args = dict(cmd.args)
        if server == "slides" and tool in ("query", "search"):
            if isinstance(args.get("ns"), str) and args["ns"].lower() == "learner":
                return self.deny(cmd, "learner data requires an ownership-scoped tool")
            # The slide search endpoint otherwise searches every namespace, including
            # private Learner bodies. A slide lookup should be scoped to frames.
            if args.get("ns") is None:
                args["ns"] = "Frame"
        if tool in ("query", "search"):
            if not isinstance(args.get("q"), str) or not args["q"].strip():
                return self.deny(cmd, "search requires a nonempty query")
            try:
                if int(args.get("cursor", "0")) < 0:
                    return self.deny(cmd, "invalid search cursor")
            except (ValueError, TypeError):
                return self.deny(cmd, "invalid search cursor")
        if tool in ("provenance", "get_frame", "whatlinkshere", "flag_stale_slide", "file_content_bug") and (not isinstance(anchor, str) or not anchor.strip()):
            return self.deny(cmd, "tool requires a nonempty anchor")
        if tool == "define" and (not isinstance(args.get("term"), str) or not args["term"].strip()):
            return self.deny(cmd, "define requires a term")
        if spec.is_write:
            if server == "progress" and not args.get("anchor") and args.get("learner"):
                args["anchor"] = args["learner"]
            anchor = args.get("anchor")
            if not isinstance(anchor, str) or not anchor.strip():
                return self.deny(cmd, "write requires a resource anchor")
            if server == "progress" and not isinstance(args.get("concept"), str):
                return self.deny(cmd, "mastery write requires a concept")
            if tool == "file_content_bug" and not isinstance(args.get("description"), str):
                return self.deny(cmd, "content bug requires a description")
            if any(not isinstance(headers.get(k), str) or not headers[k].strip()
                   for k in spec.required_headers):
                return self.deny(cmd, "write requires If-Match and Idempotency-Key")
            if self._etags.get(anchor) != headers["if-match"]:
                return self.deny(cmd, "write needs matching retrieved provenance")
            if headers["idempotency-key"] in self._write_keys:
                return self.deny(cmd, "write key already authorized; reconcile before retry")

        # AUTHORIZE: every identity alias is checked, including the primary anchor.
        def own(value):
            return isinstance(value, str) and value.partition(":")[0].lower() == "learner" and self.ctx.act.startswith("learner:") and value.partition(":")[2] == self.ctx.act.partition(":")[2]
        for key in ("learner", "learner_id", "subject", "act", "delegation_act"):
            if key in args and not own(args[key]):
                return self.deny(cmd, "target identity differs from ctx.act")
        for key in ("anchor", "target"):
            value = args.get(key)
            if isinstance(value, str) and value.lower().startswith("learner:") and not own(value):
                return self.deny(cmd, "cross-learner resource access")
        if server in ("progress", "roster"):
            target = args.get("anchor") or args.get("learner")
            if not own(target):
                return self.deny(cmd, "learner resource must belong to ctx.act")
        scope = f"wiki.write:{server}" if spec.is_write else "wiki.read"
        if scope not in self.ctx.scopes:
            return self.deny(cmd, "required scope not granted to ctx.act")
        if "act" in headers and headers["act"] != self.ctx.act:
            return self.deny(cmd, "request act mismatch")
        if server in A2A_PEERS:
            card = self._cards.get(server, {})
            if not card.get("verified") or tool not in card.get("skills", ()):
                return self.deny(cmd, "peer or skill not admitted by registry")
            if headers.get("aud") not in (server, f"a2a:{server}"):
                return self.deny(cmd, "A2A audience mismatch")
            if "act" in headers and headers["act"] != self.ctx.act:
                return self.deny(cmd, "delegation act mismatch")
            if args.get("skill", tool) not in card.get("skills", ()):
                return self.deny(cmd, "undeclared delegation skill")

        # BUDGET: preserve explicit masks; narrow wildcard to useful evidence defaults.
        if fields == ("*",) or (not fields and (server, tool) in
                {("registry", "list_servers"), ("glossary", "list_terms")}):
            defaults = {("registry", "list_servers"): ("name",),
                        ("glossary", "list_terms"): ("term",),
                        ("slides", "query"): ("body", "title"),
                        ("slides", "get_frame"): ("body", "meta", "title")}
            fields = cheap_mask(server, tool, defaults.get((server, tool), spec.default_fields)) if (server, tool) in TOOL_SPECS else spec.default_fields
        routed = replace(routed, args=args, fields=fields)
        effective = fields or spec.default_fields
        # Reserve the declared maximum row cost, without assuming result count.
        limit = args.get("limit", 5) if spec.row_weight else 0
        if not isinstance(limit, int) or isinstance(limit, bool) or (spec.row_weight and limit < 1):
            return self.deny(cmd, "invalid row limit")
        cost = spec.base + sum(spec.field_weight[f] for f in effective) + limit * spec.row_weight
        rounds = self._calls.setdefault((server, tool), [])
        used = sum(r > self.ctx.round - spec.rate_limit[1] for r in rounds) if spec.rate_limit else 0
        if spec.rate_limit and used >= spec.rate_limit[0]:
            return self.deny(cmd, "tool rate window exhausted")
        if server in A2A_PEERS and not should_delegate(own_confidence=0.0,
                calls_used_this_window=used, calls_allowed_this_window=spec.rate_limit[0] if spec.rate_limit else 100,
                credits_left=self.ctx.credits, delegate_cost=cost):
            return self.deny(cmd, "delegation cannot be afforded")
        self._pacer.reconcile(self.ctx.credits)
        reserve = max(0, 10 - self.ctx.round) * 4 / max(1, self._pacer.starting_pool)
        if cost > self.ctx.credits or not self._pacer.is_affordable(self.ctx.round, cost, reserve=reserve):
            return self.deny(cmd, "insufficient duel credits after future-round reserve")
        if spec.is_write:
            self._write_keys.add(headers["idempotency-key"])
            self._etags.pop(anchor, None)
        rounds.append(self.ctx.round)
        self._credits_authorised += cost
        decision = Decision(verdict="rewrite" if routed != cmd else "forward",
                            call=self._to_tool_call(routed))
        self._telemetry.decision_made(cmd, decision)
        return decision

    def deny(self, cmd: Command, reason: str) -> Decision:
        """Not called anywhere in this starter's `decide()` — a ready-made
        helper for when you fill in JOB 2 / JOB 3 above, so denying doesn't
        mean hand-building a `Decision` inline at every call site. Kept as
        a real method (not a stub) because the shape of a correct denial —
        no `call`, a non-empty `reason` — is exactly the thing worth
        getting right by construction rather than by convention."""
        self._denied_cmd_ids.add(cmd.cmd_id)
        decision = Decision(verdict="deny", reason=reason)
        self._telemetry.decision_made(cmd, decision)
        return decision

    def _to_tool_call(self, cmd: Command) -> "ToolCall":
        """`Command` -> the `ToolCall` (CONTRACTS.md 3.1) the arena will
        actually execute on a `forward`/`rewrite` verdict. When
        `kit.mcp.types` is unavailable (see the module-level import guard),
        falls back to a plain dict carrying the identical fields — `Decision`
        accepts it either way (the `ToolCall` isinstance check inside
        `Decision.__post_init__` only runs when the real class loaded)."""
        fields = {
            "server": cmd.server,
            "tool": cmd.tool,
            "args": dict(cmd.args),
            "fields": cmd.fields,
            "headers": dict(cmd.headers),
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
        decision = gw.decide(cmd)
        print(f"  decide({cmd.server}.{cmd.tool}) -> verdict={decision.verdict!r} quarantine={decision.quarantine}")
        assert decision.verdict == "forward"
        assert decision.call is not None
        call_dict = decision.call.to_dict() if hasattr(decision.call, "to_dict") else decision.call
        assert call_dict["server"] == cmd.server
        assert call_dict["tool"] == cmd.tool
        assert tuple(call_dict["fields"]) == cmd.fields

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
