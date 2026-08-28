"""Focused-role selection for spar.py."""

import pytest

from spar import _select_role_components


YOU = ("you-gateway", "you-prosecutor", "you-deck", "you-lineup")
BOT = ("bot-gateway", "bot-prosecutor", "bot-deck", "bot-lineup")


@pytest.mark.parametrize(
    ("role", "expected"),
    (
        ("all", YOU),
        ("defender", (YOU[0], BOT[1], BOT[2], BOT[3])),
        ("attacker", (BOT[0], BOT[1], YOU[2], YOU[3])),
        ("prosecutor", (BOT[0], YOU[1], BOT[2], BOT[3])),
    ),
)
def test_select_role_components_keeps_only_requested_student_component(role, expected):
    assert _select_role_components(role, YOU, BOT) == expected


def test_select_role_components_rejects_unknown_role():
    with pytest.raises(ValueError, match="unknown role"):
        _select_role_components("spectator", YOU, BOT)
