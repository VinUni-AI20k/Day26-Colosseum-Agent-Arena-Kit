"""tests/test_anchor.py — property-style round-trip + rejection tests for
kit/world/anchor.py and the etag purity of kit/world/page.py.

pytest only (permitted in tests/ per the workspace's hard rules). No
network, no unseeded randomness — the "generated corpus" below is a full
combinatorial matrix built with itertools.product, not sampling, so the
test set is identical on every run.
"""

from __future__ import annotations

import itertools
import re
import sys
from pathlib import Path

import pytest

# Make the repo root importable when pytest is invoked from anywhere.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from kit.world.anchor import NAMESPACES, Anchor, AnchorSyntaxError, path_id
from kit.world.page import compute_etag


# ---------------------------------------------------------------------------
# A deterministic, combinatorial corpus of valid anchors.
# ---------------------------------------------------------------------------

_SLUGS = ["a", "z9", "streamable-http", "3f2a9c11", "x-y-z-000"]
_REVS = [None, "w", "c"]
_IDXS = [None, "000", "041", "999"]
_SPANS = [None, "L1-1", "L812-848", "s0", "s42"]


def _valid_anchor_corpus() -> list[Anchor]:
    """Every (ns, slug, rev, idx, span) combination that the grammar
    actually allows, built once, deterministically, from the cross product
    of small fixtures — not random sampling."""
    corpus: list[Anchor] = []
    for ns, slug, rev, idx, span in itertools.product(
        sorted(NAMESPACES), _SLUGS, _REVS, _IDXS, _SPANS
    ):
        corpus.append(Anchor(ns=ns, slug=slug, rev=rev, idx=idx, span=span))
    return corpus


_CORPUS = _valid_anchor_corpus()


# ---------------------------------------------------------------------------
# 1. NAMESPACES sanity
# ---------------------------------------------------------------------------


def test_namespaces_has_exactly_13() -> None:
    assert len(NAMESPACES) == 13
    assert isinstance(NAMESPACES, frozenset)
    expected = {
        "Concept",
        "Frame",
        "Deck",
        "Section",
        "Claim",
        "Talk",
        "Source",
        "KC",
        "Lab",
        "Code",
        "Note",
        "Learner",
        "Glossary",
    }
    assert NAMESPACES == expected


def test_corpus_is_nonempty_and_deterministic() -> None:
    assert len(_CORPUS) == 13 * 5 * 3 * 4 * 5  # 3,900 anchors
    # Building it twice must yield an identical (equal) sequence — no
    # dict-order or hash-order leakage into the generated fixtures.
    assert _valid_anchor_corpus() == _CORPUS


# ---------------------------------------------------------------------------
# 2. Round-trip property: Anchor.parse(str(a)) == a, for every anchor in
#    the generated corpus.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("anchor", _CORPUS, ids=lambda a: str(a))
def test_round_trip_over_generated_corpus(anchor: Anchor) -> None:
    s = str(anchor)
    reparsed = Anchor.parse(s)
    assert reparsed == anchor
    # And the string form is stable under a second round trip.
    assert str(reparsed) == s


def test_round_trip_examples_from_contracts_md() -> None:
    # Literal examples pulled from CONTRACTS.md section 1 / FINAL-PLAN.md
    # section 3 (excluding the one FINAL-PLAN example, `c-day24`, that does
    # not fit the frozen grammar — see the task report for that call).
    examples = [
        "Frame:3f2a9c11/w/041",
        "Concept:streamable-http",
        "Deck:9a1b2c3d/c",
        "Section:9a1b2c3d/w/002#s4",
        "Frame:3f2a9c11/w/041#L812-848",
    ]
    for s in examples:
        a = Anchor.parse(s)
        assert str(a) == s
        assert Anchor.parse(str(a)) == a


# ---------------------------------------------------------------------------
# 3. .key() — span-insensitive dedup key
# ---------------------------------------------------------------------------


def test_key_is_span_insensitive_but_full_equality_is_not() -> None:
    a1 = Anchor.parse("Frame:3f2a9c11/w/041#L812-848")
    a2 = Anchor.parse("Frame:3f2a9c11/w/041#s4")
    a3 = Anchor.parse("Frame:3f2a9c11/w/041")
    assert a1.key() == a2.key() == a3.key() == ("Frame", "3f2a9c11", "w", "041")
    assert a1 != a2
    assert a1 != a3


def test_key_distinguishes_ns_slug_rev_idx() -> None:
    base = Anchor.parse("Frame:3f2a9c11/w/041")
    variants = [
        Anchor.parse("Deck:3f2a9c11/w/041"),
        Anchor.parse("Frame:deadbeef/w/041"),
        Anchor.parse("Frame:3f2a9c11/c/041"),
        Anchor.parse("Frame:3f2a9c11/w/042"),
    ]
    keys = {base.key()} | {v.key() for v in variants}
    assert len(keys) == 5  # all five are distinct


# ---------------------------------------------------------------------------
# 4. Rejection tests — malformed input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad,label",
    [
        ("", "empty string"),
        (":slug", "empty ns"),
        ("Bogus:slug", "unknown/bad ns"),
        ("frame:slug", "lowercase ns (case-sensitive)"),
        ("Frame:", "empty slug"),
        ("Frame:UPPER", "uppercase slug"),
        ("Frame:-leading-hyphen", "slug starting with hyphen"),
        ("Frame:has space", "slug with space"),
        ("Frame:3f2a9c11/x", "bad rev, no idx"),
        ("Frame:3f2a9c11/W", "uppercase rev"),
        ("Frame:3f2a9c11/w/abc", "non-numeric idx"),
        ("Frame:3f2a9c11/w/41", "idx too short"),
        ("Frame:3f2a9c11/w/0041", "idx too long"),
        ("Frame:3f2a9c11/w/", "empty idx segment"),
        ("Frame:3f2a9c11//041", "empty rev segment"),
        ("Frame:3f2a9c11#", "empty span"),
        ("Frame:3f2a9c11#Lstart-end", "malformed span"),
        ("Frame:3f2a9c11#x9", "unknown span kind"),
        ("Frame:3f2a9c11/w/041/999", "too many slash segments"),
        ("no-colon-at-all", "missing ':' separator"),
        (123, "non-string input"),  # type: ignore[list-item]
    ],
)
def test_parse_rejects_malformed_input(bad: object, label: str) -> None:
    with pytest.raises(AnchorSyntaxError) as excinfo:
        Anchor.parse(bad)  # type: ignore[arg-type]
    assert str(excinfo.value), f"empty error message for case: {label}"


def test_direct_construction_also_validates() -> None:
    # __post_init__ must catch malformed components even when Anchor is
    # built directly rather than through parse() — parse()'s guarantee
    # only holds if construction itself is airtight.
    with pytest.raises(AnchorSyntaxError):
        Anchor(ns="NotANamespace", slug="ok")
    with pytest.raises(AnchorSyntaxError):
        Anchor(ns="Frame", slug="UPPER")
    with pytest.raises(AnchorSyntaxError):
        Anchor(ns="Frame", slug="ok", rev="x")
    with pytest.raises(AnchorSyntaxError):
        Anchor(ns="Frame", slug="ok", idx="7")
    with pytest.raises(AnchorSyntaxError):
        Anchor(ns="Frame", slug="ok", span="bad-span")


def test_anchor_is_frozen() -> None:
    a = Anchor.parse("Frame:3f2a9c11/w/041")
    with pytest.raises(Exception):
        a.slug = "different"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 5. path_id() stability and non-collision on real corpus files
# ---------------------------------------------------------------------------

_CORPUS_MARKER = Path("day26/day26-mcp-a2a-infrastructure-agentic-routing.tex")


def _find_real_corpus_root(start: Path) -> Path | None:
    """Find the optional course corpus without assuming clone depth."""
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / _CORPUS_MARKER).is_file():
            return candidate
    return None


def test_find_real_corpus_root_is_independent_of_clone_depth(tmp_path: Path) -> None:
    corpus_root = tmp_path / "workspace"
    marker = corpus_root / _CORPUS_MARKER
    marker.parent.mkdir(parents=True)
    marker.touch()
    nested_repo = corpus_root / "arbitrary" / "clone" / "depth" / "kit"
    nested_repo.mkdir(parents=True)

    assert _find_real_corpus_root(nested_repo) == corpus_root.resolve()


def test_path_id_is_8_lowercase_hex_and_deterministic() -> None:
    p = "day26/day26-mcp-a2a-infrastructure-agentic-routing.tex"
    pid1 = path_id(p)
    pid2 = path_id(p)
    assert pid1 == pid2
    assert re.fullmatch(r"[0-9a-f]{8}", pid1)


def test_path_id_stable_across_process_style_calls() -> None:
    # "Stable" means: calling it fresh, many times, in any order, always
    # gives the same answer for the same input — simulated here by
    # shuffling call order deterministically (no `random`).
    paths = [
        "day26/day26-mcp-a2a-infrastructure-agentic-routing.tex",
        "day11/day11-guardrails-ai-safety.tex",
        "day10/_flat-day10.tex",
    ]
    first_pass = {p: path_id(p) for p in paths}
    second_pass = {p: path_id(p) for p in reversed(paths)}
    assert first_pass == second_pass


def test_path_id_never_a_day_number_disambiguates_day11_trio() -> None:
    # CORPUS-FACTS.md section 3: day11 resolves to two entirely different
    # canonical .tex files, plus one working file. A day-number-keyed
    # scheme would collide all three onto "day11"; path_id must not.
    day11_paths = [
        "day11/day11-guardrails-ai-safety.tex",
        "CourseMaterial/GD1/Latex/Latex Files/01_phase1_nen-tang/"
        "day11-guardrails-ai-safety.tex",
        "CourseMaterial/GD1/Latex/Latex Files/01_phase1_nen-tang/"
        "day11-guardrails-ai-safety_E403_v2_linh.tex",
    ]
    ids = [path_id(p) for p in day11_paths]
    assert len(set(ids)) == 3, f"day11 trio collided: {dict(zip(day11_paths, ids))}"
    for pid in ids:
        assert pid != "day11"
        assert re.fullmatch(r"[0-9a-f]{8}", pid)


def test_path_id_decoy_and_real_day10_content_differ() -> None:
    # CORPUS-FACTS.md section 6: day10/day10-....tex is a 4,625 B \input
    # decoy; the real 202,840 B content is day10/_flat-day10.tex. Both are
    # real files, both must resolve to distinct path_ids.
    decoy = path_id("day10/day10-data-pipeline-observability.tex")
    real = path_id("day10/_flat-day10.tex")
    assert decoy != real


def test_path_id_over_the_real_corpus_has_no_collisions() -> None:
    ai20k_root = _find_real_corpus_root(_REPO_ROOT)
    if ai20k_root is None:
        pytest.skip("real corpus not present in this environment")
    deck_paths = sorted(ai20k_root.glob("day*/day*.tex"))
    rels = [str(p.relative_to(ai20k_root)) for p in deck_paths]
    ids = [path_id(r) for r in rels]
    dupes = {pid for pid in ids if ids.count(pid) > 1}
    assert not dupes, f"path_id collisions among real deck files: {dupes}"
    assert len(deck_paths) >= 20  # sanity: CORPUS-FACTS.md says 24 working decks


def test_path_id_normalizes_leading_dot_slash_and_backslash() -> None:
    assert path_id("./day26/x.tex") == path_id("day26/x.tex")
    assert path_id("day26\\x.tex") == path_id("day26/x.tex")


# ---------------------------------------------------------------------------
# 6. etag purity — compute_etag is a pure function of body text
# ---------------------------------------------------------------------------


def test_compute_etag_is_pure_and_deterministic() -> None:
    body = "Streamable HTTP thay the HTTP+SSE tu 2026-07-28."
    e1 = compute_etag(body)
    e2 = compute_etag(body)
    assert e1 == e2
    assert e1.startswith("sha256:")
    assert re.fullmatch(r"sha256:[0-9a-f]{16}", e1)


def test_compute_etag_changes_with_body() -> None:
    e1 = compute_etag("A")
    e2 = compute_etag("B")
    e3 = compute_etag("A ")  # trailing space matters
    assert len({e1, e2, e3}) == 3


def test_compute_etag_over_real_corpus_bodies_reproduces() -> None:
    ai20k_root = _find_real_corpus_root(_REPO_ROOT)
    if ai20k_root is None:
        pytest.skip("real corpus not present in this environment")
    deck_path = ai20k_root / "day26" / "day26-mcp-a2a-infrastructure-agentic-routing.tex"
    text = deck_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    for start in (100, 500, 900):
        body = "\n".join(lines[start : start + 5])
        etag = compute_etag(body)
        # Recomputing from the same body text must reproduce it exactly —
        # this IS the invariant CONTRACTS.md section 2 names.
        assert compute_etag(body) == etag


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
