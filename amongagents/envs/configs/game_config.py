"""Game presets.

STUDY_GAME is the study configuration: five agents, one insider. Five is the smallest
team in which the vote thresholds can disagree after the first kill, since with four
living voters a 2-1-1 split ejects under plurality but not under majority.

It differs from the upstream five-player preset in task load and time limit. Upstream
gives each Crewmate two one-step tasks, which a crew can finish before the insider has
had time for more than a kill or two, so few games reach a meeting. STUDY_GAME uses the
per-player load of the published seven-player configuration (one common, one short, one
long task) and a time limit to match. These two numbers are the knobs to turn if the
pilot's baseline win rate falls outside [0.15, 0.85] or too few games hold a meeting.

SEVEN_MEMBER_GAME is the configuration published with the upstream sandbox, kept as
the fallback named in the research plan (risk R1).
"""

THREE_MEMBER_GAME = {
    "num_players": 3,
    "num_impostors": 1,
    "num_common_tasks": 1,
    "num_short_tasks": 1,
    "num_long_tasks": 0,
    "discussion_rounds": 3,
    "max_num_buttons": 2,
    "kill_cooldown": 1,
    "max_timesteps": 5,
}

FIVE_MEMBER_GAME = {
    "num_players": 5,
    "num_impostors": 1,
    "num_common_tasks": 1,
    "num_short_tasks": 1,
    "num_long_tasks": 0,
    "discussion_rounds": 3,
    "max_num_buttons": 2,
    "kill_cooldown": 3,
    "max_timesteps": 20,
}

SEVEN_MEMBER_GAME = {
    "num_players": 7,
    "num_impostors": 2,
    "num_common_tasks": 1,
    "num_short_tasks": 1,
    "num_long_tasks": 1,
    "discussion_rounds": 3,
    "max_num_buttons": 2,
    "kill_cooldown": 3,
    "max_timesteps": 50,
}

STUDY_GAME = {**FIVE_MEMBER_GAME, "num_long_tasks": 1, "max_timesteps": 30}

GAME_PRESETS = {
    "study": STUDY_GAME,
    "three": THREE_MEMBER_GAME,
    "five": FIVE_MEMBER_GAME,
    "seven": SEVEN_MEMBER_GAME,
}

# key -> (minimum, maximum)
_BOUNDS = {
    "num_players": (3, 12),  # 12 player colours
    "num_impostors": (1, 3),
    "num_common_tasks": (0, 2),
    "num_short_tasks": (0, 2),
    "num_long_tasks": (0, 1),
    "discussion_rounds": (1, 5),
    "max_num_buttons": (0, 10),
    "kill_cooldown": (0, 20),
    "max_timesteps": (1, 200),
}


def validate_game_config(config: dict) -> dict:
    """Return a clean copy of config, raising ValueError on anything a game cannot run with."""
    missing = [key for key in _BOUNDS if key not in config]
    if missing:
        raise ValueError(f"game config is missing {missing}")
    clean = {}
    for key, (low, high) in _BOUNDS.items():
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{key} must be an integer, got {value!r}")
        if not low <= value <= high:
            raise ValueError(f"{key} must be between {low} and {high}, got {value}")
        clean[key] = value
    if clean["num_impostors"] * 2 >= clean["num_players"]:
        raise ValueError("impostors must be a strict minority at the start of the game")
    tasks_each = clean["num_common_tasks"] + clean["num_short_tasks"] + clean["num_long_tasks"]
    if tasks_each == 0:
        raise ValueError("crewmates need at least one task, or the task win is immediate")
    return clean
