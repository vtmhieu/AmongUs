"""Discussion protocols for the meeting phase (the discussion-protocol factor)."""

import re

FREEFORM = "freeform"
JUSTIFICATION = "justification"
PROTOCOLS = (FREEFORM, JUSTIFICATION)

# e.g. "ACCUSE: Player 3: red | EVIDENCE: I saw them leave Electrical right after the kill."
JUSTIFICATION_PATTERN = re.compile(
    r"ACCUSE:\s*(?P<accused>.+?)\s*\|\s*EVIDENCE:\s*(?P<evidence>\S.*)",
    re.IGNORECASE | re.DOTALL,
)
ACCUSED_PATTERN = re.compile(r"^(NONE|Player \d+(: \w+)?)$", re.IGNORECASE)


def parse_justification(message):
    """Return (accused, evidence) if message follows the justification format, else None.

    accused is a player name such as "Player 3: red" (or "Player 3"), or "NONE" to abstain.
    """
    match = JUSTIFICATION_PATTERN.search(message or "")
    if not match:
        return None
    accused = match.group("accused").strip().strip("\"'")
    evidence = match.group("evidence").strip().strip("\"'")
    if not ACCUSED_PATTERN.match(accused) or not evidence:
        return None
    return accused, evidence
