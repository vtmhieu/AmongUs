"""Prompt text.

The role prompts and output format come from the upstream sandbox. The governance
texts at the bottom are the study's manipulation: within each group the variants are
written to the same length, so a condition never differs from another in how much
text the players read. tests/test_prompts.py enforces that.
"""

from amongagents.envs.governance import (
    FREEFORM,
    JUSTIFICATION,
    MAJORITY,
    PLURALITY,
    PUBLIC,
    SECRET,
    SUPERMAJORITY,
)

IMPOSTOR_EXAMPLE = """\
When given a list of available actions (e.g., MOVE, CALL MEETING, REPORT DEAD BODY, SPEAK, VENT, or KILL), choose exactly one. \
If "SPEAK" is an option, think carefully about what you want to speak based on your strategy, and speak accordingly.
Make a summarization of the past observed events and taken actions under [Condensed Memory], \
make a thoughtful and thourough plan under [Thinking Process] while thinking very carefully about the strategy you want to employ to win, \
and then choose the action from Available actions under [Action].

Output format:
[Condensed Memory]
{memory}
[Thinking Process]
{thought}
[Action] {action}

DO NOT PICK AN ACTION THAT IS NOT IN THE LIST OF AVAILABLE ACTIONS AND MAKE SURE TO FOLLOW THE EXACT OUTPUT FORMAT.
"""

CREWMATE_EXAMPLE = """\
When presented with a list of available actions (e.g., MOVE, COMPLETE TASK, CALL MEETING, REPORT DEAD BODY, or SPEAK), choose exactly one. \
If "SPEAK" is an option, think carefully about what you want to speak based on your strategy, and speak accordingly.
Make a summarization of the past observed events and taken actions under [Condensed Memory], \
make a thoughtful and thourough plan under [Thinking Process] while thinking very carefully about the strategy you want to employ to win, \
and then choose the action from Available actions under [Action].

Output format:
[Condensed Memory]
{memory}
[Thinking Process]
{thought}
[Action] {action}

DO NOT PICK AN ACTION THAT IS NOT IN THE LIST OF AVAILABLE ACTIONS AND MAKE SURE TO FOLLOW THE EXACT OUTPUT FORMAT.
"""

SKELD_MAP = """\
Map Configuration of the Skeld:
Rooms and Features
Cafeteria: Vent to Admin, Special (Emergency Button).
Weapons: Vent to Navigation.
Navigation: Vent to Shields and Weapons.
O2: Nothing Special
Shields: Vent to Navigation.
Communications: Nothing Special
Storage: Nothing Special
Admin: Vent to Cafeteria
Electrical: Vent to Medbay and Security
Lower Engine: Vent to Reactor
Security: Special (Security Cameras)
Reactor: Vent to Upper Engine and Lower Engine
Upper Engine: Vent to Reactor
Medbay: Vent to Electrical and Security

Note that only Impostors can KILL and VENT.

"""

# The upstream prompt told the Impostor that "the player with the most votes will be
# ejected". That is only true under plurality, so the sentence is now rule-neutral and
# the rule in force is stated in the meeting instruction instead.
IMPOSTOR_PROMPT = (
    """
You are {name}. You are an Impostor on the spaceship Skeld. Your mission is to eliminate Crewmates before all their tasks are completed. \
If the number of Impostors equals the number of Crewmates before all tasks are completed, you win.
The game alternates between task and meeting phases:
- During the task phase, you can perform fake tasks and kill Crewmates.
- During the meeting phase, players can only speak. You must craft your speech carefully, because everyone will then vote on who they think the Impostor is, and the vote can eject a player from the game.

If you kill a Crewmate in a room in front of others (total 3 players in a room), everyone in the room will know who did it and can call a meeting to report you.
On the other hand, if you are alone in a room with a Crewmate, nobody can report at the time of the kill.

"""
    + SKELD_MAP
)

CREWMATE_PROMPT = (
    """
You are {name}. You are a Crewmate on the spaceship Skeld. Your objectives are to complete all tasks and identify and eject Impostors within a time limit.
## IMPORTANT ## Impostors are those who KILL Crewmates, and if they outnumber crewmates at any point before all tasks are completed, you lose. \
They also can VENT between non-connected rooms. Crewmates must work together to complete tasks and identify the Impostors among them.
The game alternates between task and meeting phases:
- During the task phase, you perform your assigned tasks by choosing COMPLETE TASK or gathering evidence by moving around. You can also CALL MEETING if you suspect an Impostor or witness a crime.
- During the meeting phase, players can only speak. Your goal is to communicate effectively, sharing observations to collectively identify any Impostors.

"""
    + SKELD_MAP
)

TASK_PHASE_INSTRUCTION = """\
In this phase, Crewmates should try to complete all tasks or try to identify the Impostor. Impostor should try to kill Crewmates before they finish all the tasks. The game runs sequentially, so other players in the room with you can observe your actions and act accordingly.
"""

MEETING_PHASE_INSTRUCTION = """\
In this phase, players should discuss and vote out the suspected Impostor. There will be a total of {discussion_rounds} discussion rounds. After that, players should vote out the suspected Impostor. Feel free to share any observations and suspicions
Ask and answer questions to your fellow players. Be active and responsive during the discussion, and carefully consider the information shared by others.
{voting_rules}
"""

# --- Governance texts (the manipulation) -------------------------------------

_BALLOT_OPTIONS = "Voting rule: each living player casts one vote, either for a player or SKIP. "

VOTING_RULE_TEXT = {
    PLURALITY: _BALLOT_OPTIONS
    + "The player who receives the most votes is ejected. If two or more options tie "
    "for the most votes, or SKIP receives the most votes, then no one is ejected.",
    MAJORITY: _BALLOT_OPTIONS
    + "A player is ejected only if more than half of all living players vote for that "
    "player. In every other case, including a split vote, no one is ejected.",
    SUPERMAJORITY: _BALLOT_OPTIONS
    + "A player is ejected only if at least two thirds of all living players vote for "
    "that player. In every other case, including a split vote, no one is ejected.",
}

BALLOT_TEXT = {
    PUBLIC: "Votes are cast one player at a time, and every vote is announced "
    "to all players as soon as it is cast.",
    SECRET: "Votes are cast by all players at the same time in secret, and only "
    "the final vote totals are announced afterwards.",
}

# Shown instead of the two texts above when the rule is not disclosed to the players.
VOTING_RULE_UNDISCLOSED = (
    "Voting: each living player casts one vote, either for a player or SKIP. "
    "The result of the vote decides whether a player is ejected from the game."
)

# Appended to the meeting instruction in the final discussion round only.
PROTOCOL_TEXT = {
    JUSTIFICATION: """\
This is the final discussion round before the vote. In this round every statement must end with these two lines:
ACCUSE: <the name of the one player you accuse, or NONE>
EVIDENCE: <one specific thing you observed that supports this>
A statement that does not end with both lines is not accepted.
""",
    FREEFORM: """\
This is the final discussion round before the vote. In this round there is no required format for statements:
you may sum up what you have seen, answer what others have said,
raise anything still unclear, or add nothing new at all.
A statement may take whatever form you think is most useful.
""",
}

JUSTIFICATION_REPROMPT = (
    "Your statement was not accepted: it did not end with a valid ACCUSE line and EVIDENCE line. "
    "ACCUSE must name one living player exactly as they appear in the player list, or NONE. "
    "Give your statement again in the required output format."
)

INVALID_ACTION_REPROMPT = (
    "Your previous output did not contain one of the available actions. "
    "Reply again in the required output format, and after [Action] copy exactly one line "
    "from the list of available actions (for SPEAK, write SPEAK: followed by your message)."
)

VOTE_RESULT_EJECTED = "Vote result: {player} was ejected. {detail}"
VOTE_RESULT_NONE = "Vote result: no one was ejected. {detail}"
