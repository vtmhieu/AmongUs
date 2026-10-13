import re

from amongagents.envs.governance import SKIP


class Action:
    def __init__(self, name, current_location=None):
        self.name = name
        self.current_location = current_location

    def __repr__(self):
        return self.name

    def __str__(self):
        return self.__repr__()

    def execute(self, env, player):
        return

    def action_text(self):
        return str(self)

    def details(self):
        """Structured fields describing this action, for the event log."""
        return {}

    @staticmethod
    def can_execute_actions(env, player):
        return []


class Wait(Action):
    """Do nothing this turn.

    Never offered to a player. It is what a turn becomes when the model's output could
    not be matched to an available action, so that an unparseable reply never turns
    into a consequential move.
    """

    def __init__(self, current_location):
        super().__init__("WAIT", current_location=current_location)

    def action_text(self):
        return "stands still"


class MoveTo(Action):
    def __init__(self, current_location, new_location):
        super().__init__("MOVE", current_location=current_location)
        self.new_location = new_location

    def __repr__(self):
        return f"{self.name} from {self.current_location} to {self.new_location}"

    def execute(self, env, player):
        super().execute(env, player)
        player.location = self.new_location

    def details(self):
        return {"from": self.current_location, "to": self.new_location}

    @staticmethod
    def can_execute_actions(env, player):
        if env.current_phase == "task":
            new_locations = env.map.get_adjacent_rooms(player.location)
            return [MoveTo(player.location, location) for location in new_locations]
        else:
            return []


class Vent(MoveTo):
    def __init__(self, current_location, new_location):
        super().__init__(current_location, new_location)
        self.name = "VENT"

    @staticmethod
    def can_execute_actions(env, player):
        if env.current_phase == "task":
            new_locations = env.map.get_adjacent_rooms_vent(player.location)
            return [Vent(player.location, location) for location in new_locations]
        else:
            return []


class CallMeeting(Action):
    def __init__(self, current_location, reports_body=False):
        super().__init__("CALL MEETING", current_location=current_location)
        self.reports_body = reports_body

    def __repr__(self):
        if self.reports_body:
            return f"REPORT DEAD BODY at {self.current_location}"
        return f"{self.name} using the emergency button at {self.current_location}"

    def execute(self, env, player):
        super().execute(env, player)
        env.start_meeting(player, self)

    def details(self):
        return {"kind": "report" if self.reports_body else "button"}

    @staticmethod
    def can_execute_actions(env, player):
        if env.current_phase != "task":
            return []
        current_location = player.location
        unreported_bodies = [
            p
            for p in env.map.get_players_in_room(current_location, include_new_deaths=True)
            if p != player and not p.is_alive and not p.reported_death
        ]
        if unreported_bodies:
            return [CallMeeting(current_location, reports_body=True)]
        if (
            current_location == "Cafeteria"
            and env.button_num < env.game_config["max_num_buttons"]
        ):
            return [CallMeeting(current_location, reports_body=False)]
        return []


class Vote(Action):
    """A ballot for another living player, or SKIP when other_player is None."""

    def __init__(self, current_location, other_player=None):
        super().__init__("VOTE", current_location=current_location)
        self.other_player = other_player

    @property
    def target(self):
        return SKIP if self.other_player is None else self.other_player.name

    def __repr__(self):
        if self.other_player is None:
            return "SKIP VOTE"
        return f"{self.name} {self.other_player.name}"

    def execute(self, env, player):
        super().execute(env, player)
        env.cast_vote(player, self.target)

    def details(self):
        return {"target": self.target}

    @staticmethod
    def can_execute_actions(env, player):
        if env.current_phase == "meeting" and env.discussion_rounds_left == 0:
            alive_players_excluding_self = [
                p for p in env.players if p.is_alive and p != player
            ]
            return [
                Vote(player.location, other_player)
                for other_player in alive_players_excluding_self
            ] + [Vote(player.location, None)]
        else:
            return []


class Speak(Action):
    def __init__(self, current_location):
        super().__init__("SPEAK", current_location=current_location)
        self.message = "..."

    def provide_message(self, message):
        self.message = message

    def __repr__(self):
        return f"{self.name}: {self.message}"

    def details(self):
        return {"message": self.message}

    @staticmethod
    def can_execute_actions(env, player):
        # players speak only in the discussion rounds of a meeting
        if env.current_phase == "meeting" and env.discussion_rounds_left > 0:
            return [Speak(current_location=player.location)]
        return []


class ViewMonitor(Action):
    def __init__(self, current_location):
        super().__init__("VIEW MONITOR", current_location=current_location)

    def execute(self, env, player, choose_location):
        super().execute(env, player)
        move = re.compile(r"MOVE from ([\w\s]+) to ([\w\s]+)")
        in_room = env.map.get_players_in_room(choose_location)
        observations = []
        for other in env.players:
            last_action = str(env.camera_record[other.name])
            match = move.match(last_action)
            if other in in_room:
                seen = f"enter {match.group(2)}" if match else last_action
                observations.append(f"({other.name}): {seen}, ")
            elif match and match.group(1) == choose_location:
                observations.append(f"({other.name}): leave {match.group(1)}, ")
        observation = "".join(observations) if in_room else "No one here"
        player.observation_history.append(
            "Monitor Record: {Location: " + choose_location + ", Observation: {" + observation + "}}"
        )

    def details(self):
        return {}

    @staticmethod
    def can_execute_actions(env, player):
        if player.location == "Security":
            return [ViewMonitor("Security")]
        else:
            return []


class CompleteTask(Action):
    def __init__(self, current_location, task):
        super().__init__("COMPLETE TASK", current_location=current_location)
        self.task = task

    def __repr__(self):
        return f"{self.name} - {self.task.name}"

    def action_text(self):
        return "Seemingly doing task"

    def execute(self, env, player):
        super().execute(env, player)
        self.task.do_task()

    def details(self):
        return {"task": self.task.name}

    @staticmethod
    def can_execute_actions(env, player):
        available_tasks = []
        if env.current_phase == "task":
            current_location = player.location

            for task in player.tasks:
                if task.location == current_location and not task.check_completion():
                    available_tasks.append(CompleteTask(current_location, task))

        return available_tasks


class Kill(Action):
    """The Impostor's only destructive action in this sandbox (upstream's Sabotage was a stub)."""

    def __init__(self, current_location, other_player):
        super().__init__("KILL", current_location=current_location)
        self.other_player = other_player

    def __repr__(self):
        return f"{self.name} {self.other_player.name}"

    def execute(self, env, player):
        super().execute(env, player)
        self.other_player.is_alive = False
        player.kill_cooldown = env.game_config["kill_cooldown"]

    def details(self):
        return {"target": self.other_player.name}

    @staticmethod
    def can_execute_actions(env, player):
        if env.current_phase == "task" and player.kill_cooldown == 0:
            current_location = player.location
            other_players = env.map.get_players_in_room(current_location)
            other_players = [p for p in other_players if p.identity != player.identity]
            return [
                Kill(current_location=current_location, other_player=p)
                for p in other_players
            ]
        else:
            return []


class CompleteFakeTask(CompleteTask):
    def __init__(self, current_location, task):
        super().__init__(current_location, task)
        self.name = "COMPLETE FAKE TASK"

    # execute is inherited: the Impostor's own copy of the task is ticked off, which
    # never counts towards the crew's task win (only Crewmates' tasks are tracked).

    @staticmethod
    def can_execute_actions(env, player):
        available_tasks = []
        if env.current_phase == "task":
            current_location = player.location
            for task in player.tasks:
                if task.location == current_location and not task.check_completion():
                    available_tasks.append(CompleteFakeTask(current_location, task))

        return available_tasks


COMMON_ACTIONS = [MoveTo, CallMeeting, Vote, Speak, ViewMonitor]
CREWMATE_ACTIONS = [CompleteTask]
IMPOSTER_ACTIONS = [Vent, Kill, CompleteFakeTask]
