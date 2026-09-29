"""Vote tally rules for the meeting phase (the vote-threshold factor)."""

SKIP = "SKIP"
PLURALITY = "plurality"
MAJORITY = "majority"
THRESHOLDS = (PLURALITY, MAJORITY)


def tally(counts, n_living_voters, threshold):
    """Return the ejected option from counts, or None if no one is ejected.

    counts: mapping from ballot option (a player, or SKIP) to number of votes.
    n_living_voters: players alive at the vote; the majority denominator.
    threshold:
        plurality -- the option with the most votes, SKIP included; a tie or
                     a SKIP win ejects no one.
        majority  -- a player with more than half of the living voters.
    """
    if threshold == PLURALITY:
        max_votes = max(counts.values(), default=0)
        leaders = [option for option, votes in counts.items() if votes == max_votes]
        if len(leaders) == 1 and leaders[0] != SKIP:
            return leaders[0]
        return None
    if threshold == MAJORITY:
        for option, votes in counts.items():
            if option != SKIP and votes > n_living_voters / 2:
                return option
        return None
    raise ValueError(f"Unknown vote threshold: {threshold!r}")


def other_threshold(threshold):
    return MAJORITY if threshold == PLURALITY else PLURALITY
