"""The tally and the justification parser, on synthetic ballots and statements."""

import pytest

from amongagents.envs.governance import (
    MAJORITY,
    PLURALITY,
    SKIP,
    SUPERMAJORITY,
    THRESHOLDS,
    Governance,
    counterfactuals,
    parse_justification,
    tally,
    votes_required,
)

A, B, C, D, E = (
    "Player 1: red",
    "Player 2: blue",
    "Player 3: green",
    "Player 4: pink",
    "Player 5: cyan",
)


def ejected(ballots, n_voters, rule):
    return tally(ballots, n_voters, rule).ejected


class TestPlurality:
    def test_most_voted_player_is_ejected(self):
        assert ejected({A: C, B: C, C: A, D: SKIP, E: B}, 5, PLURALITY) == C

    def test_tie_between_players_ejects_no_one(self):
        assert ejected({A: C, B: C, C: A, D: A}, 4, PLURALITY) is None

    def test_tie_between_a_player_and_skip_ejects_no_one(self):
        assert ejected({A: C, B: C, C: SKIP, D: SKIP}, 4, PLURALITY) is None

    def test_skip_on_top_ejects_no_one(self):
        assert ejected({A: SKIP, B: SKIP, C: SKIP, D: A, E: A}, 5, PLURALITY) is None

    def test_all_skip_ejects_no_one(self):
        assert ejected({A: SKIP, B: SKIP, C: SKIP}, 3, PLURALITY) is None

    def test_a_single_vote_can_eject_when_everyone_else_scatters(self):
        # 2-1-1: the split that separates plurality from majority with four voters
        assert ejected({A: C, B: C, C: A, D: B}, 4, PLURALITY) == C


class TestMajority:
    def test_needs_more_than_half_of_the_living_voters(self):
        assert ejected({A: C, B: C, C: A, D: B}, 4, MAJORITY) is None
        assert ejected({A: C, B: C, D: C, C: A}, 4, MAJORITY) == C

    def test_exactly_half_is_not_enough(self):
        assert ejected({A: C, B: C, C: SKIP, D: SKIP}, 4, MAJORITY) is None

    def test_skips_count_in_the_denominator(self):
        # 2 of 5 is the most-voted option but not a majority of the electorate
        assert ejected({A: C, B: C, C: SKIP, D: SKIP, E: A}, 5, MAJORITY) is None

    def test_all_skip_ejects_no_one(self):
        assert ejected({A: SKIP, B: SKIP, C: SKIP, D: SKIP}, 4, MAJORITY) is None


class TestSupermajority:
    def test_needs_two_thirds(self):
        assert ejected({A: C, B: C, D: C, C: A, E: A}, 5, SUPERMAJORITY) is None  # 3 of 5
        assert ejected({A: C, B: C, D: C, E: C, C: A}, 5, SUPERMAJORITY) == C  # 4 of 5


@pytest.mark.parametrize(
    "n_voters, majority, supermajority",
    [(5, 3, 4), (4, 3, 3), (3, 2, 2), (2, 2, 2)],
)
def test_thresholds_shrink_with_the_electorate(n_voters, majority, supermajority):
    assert votes_required(MAJORITY, n_voters) == majority
    assert votes_required(SUPERMAJORITY, n_voters) == supermajority
    assert votes_required(PLURALITY, n_voters) is None


def test_with_three_voters_plurality_already_needs_a_majority():
    """The research plan's argument for five players: rules cannot diverge below four voters."""
    import itertools

    names = [A, B, C]
    options = {A: [B, C, SKIP], B: [A, C, SKIP], C: [A, B, SKIP]}
    for votes in itertools.product(*(options[name] for name in names)):
        ballots = dict(zip(names, votes))
        assert ejected(ballots, 3, PLURALITY) == ejected(ballots, 3, MAJORITY)


def test_a_missing_ballot_counts_as_skip():
    result = tally({A: C, B: C}, 4, MAJORITY)
    assert result.counts == {C: 2, SKIP: 2}
    assert result.ejected is None
    # and it can turn a plurality win into a tie
    assert ejected({A: C, B: C}, 4, PLURALITY) is None


def test_no_ballots_at_all():
    for rule in THRESHOLDS:
        assert tally({}, 4, rule).ejected is None


def test_more_ballots_than_voters_is_an_error():
    with pytest.raises(ValueError):
        tally({A: B, B: A, C: A}, 2, PLURALITY)


def test_unknown_rule_is_an_error():
    with pytest.raises(ValueError):
        tally({A: B}, 3, "unanimity")


def test_counterfactuals_report_every_rule_on_the_same_ballots():
    ballots = {A: C, B: C, C: A, D: B}
    assert counterfactuals(ballots, 4) == {PLURALITY: C, MAJORITY: None, SUPERMAJORITY: None}


class TestGovernance:
    def test_defaults_are_the_upstream_rules(self):
        g = Governance()
        assert (g.threshold, g.protocol, g.ballot) == ("plurality", "freeform", "public")
        assert g.condition == "plurality/freeform"

    def test_condition_names_the_ballot_only_when_secret(self):
        assert (
            Governance(threshold="majority", protocol="justification").condition
            == "majority/justification"
        )
        assert Governance(ballot="secret").condition == "plurality/freeform/secret"

    def test_round_trip(self):
        g = Governance(threshold="majority", ballot="secret", disclose_rules=False)
        assert Governance.from_dict(g.to_dict()) == g

    @pytest.mark.parametrize("field", ["threshold", "protocol", "ballot"])
    def test_rejects_unknown_levels(self, field):
        with pytest.raises(ValueError):
            Governance(**{field: "nonsense"})


class TestJustification:
    players = [A, B, C, D]

    def test_accusation_with_evidence(self):
        j = parse_justification(
            "I was in Admin the whole time.\nACCUSE: Player 3: green\nEVIDENCE: I saw them vent in Electrical.",
            self.players,
        )
        assert j.accused == C
        assert j.evidence == "I saw them vent in Electrical."

    def test_abstention_is_a_valid_accusation(self):
        j = parse_justification(
            "ACCUSE: NONE\nEVIDENCE: I have not seen anything suspicious.", self.players
        )
        assert j is not None and j.accused is None

    @pytest.mark.parametrize(
        "line, expected",
        [
            ("ACCUSE: Player 2", B),
            ("accuse: player 2: blue", B),
            ("**ACCUSE:** Player 2: blue", B),
            ("ACCUSE: blue", B),
            ("ACCUSE: nobody", None),
        ],
    )
    def test_accusation_spellings(self, line, expected):
        j = parse_justification(f"{line}\nEVIDENCE: they followed me into Storage", self.players)
        assert j is not None and j.accused == expected

    @pytest.mark.parametrize(
        "message",
        [
            "I think Player 3 did it.",  # no lines at all
            "ACCUSE: Player 3: green",  # no evidence
            "EVIDENCE: they vented",  # no accusation
            "ACCUSE: Player 3: green\nEVIDENCE:",  # empty evidence
            "ACCUSE: Player 3: green\nEVIDENCE: <one specific thing you observed>",  # placeholder
            "ACCUSE: Player 9: lime\nEVIDENCE: they vented",  # not a living player
            "ACCUSE: someone\nEVIDENCE: a feeling",  # names nobody
        ],
    )
    def test_statements_that_break_the_protocol(self, message):
        assert parse_justification(message, self.players) is None
