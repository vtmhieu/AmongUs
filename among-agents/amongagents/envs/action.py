import re

from amongagents.envs.discussion import parse_justification


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

    @staticmethod
    def can_execute_actions(env, player):
        return []


class MoveTo(Action):
    def __init__(self, current_location, new_location):
        super().__init__("MOVE", current_location=current_location)
        self.new_location = new_location

    def __repr__(self):
        return f"{self.name} from {self.current_location} to {self.new_location}"

    def execute(self, env, player):
        super().execute(env, player)
        player.location = self.new_location

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
    def __init__(self, current_location):
        super().__init__("CALL MEETING", current_location=current_location)

    def __repr__(self):
        if self.current_location == "Cafeteria":
            return f"{self.name} using the emergency button at {self.current_location}"
        else:
            return f"REPORT DEAD BODY at {self.current_location}"

    def execute(self, env, player):
        super().execute(env, player)
        env.current_phase = "meeting"
        env.button_num += 1
        env.meeting_index += 1
        caller = player
        bodies = []
        for player in env.players:
            if not player.is_alive and not player.reported_death:
                player.reported_death = True
                bodies.append(player.name)
        env.log_event(
            "meeting_start",
            caller=caller.name,
            caller_identity=caller.identity,
            kind="button" if self.current_location == "Cafeteria" else "report",
            location=self.current_location,
            bodies_reported=bodies,
        )

    @staticmethod
    def can_execute_actions(env, player):
        if env.current_phase == "task":
            current_location = player.location
            players_in_the_same_room = env.map.get_players_in_room(
                current_location, include_new_deaths=True
            )
            other_players_in_the_same_room = [
                p for p in players_in_the_same_room if p != player
            ]
            if (
                current_location == "Cafeteria"
                and env.button_num < env.game_config["max_num_buttons"]
            ):
                return [CallMeeting(current_location=current_location)]
            else:
                for other_player in other_players_in_the_same_room:
                    if not other_player.is_alive and not other_player.reported_death:
                        return [CallMeeting(current_location=current_location)]
        return []


class Vote(Action):
    """Vote for a player, or abstain with other_player=None (VOTE SKIP)."""

    def __init__(self, current_location, other_player):
        super().__init__("VOTE", current_location=current_location)
        self.other_player = other_player
        self.fallback = False  # set by the agent when the vote was not parsed from the model

    @property
    def is_skip(self):
        return self.other_player is None

    def __repr__(self):
        if self.is_skip:
            return f"{self.name} SKIP"
        return f"{self.name} {self.other_player.name}"

    def execute(self, env, player):
        super().execute(env, player)
        target = "SKIP" if self.is_skip else self.other_player
        target_name = "SKIP" if self.is_skip else self.other_player.name
        env.vote_info_one_round[player.name] = target_name
        env.votes[target] = env.votes.get(target, 0) + 1
        env.log_event(
            "vote",
            voter=player.name,
            voter_identity=player.identity,
            target=target_name,
            target_identity=None if self.is_skip else self.other_player.identity,
            fallback=self.fallback,
        )

    def can_execute_actions(env, player):
        if env.current_phase == "meeting" and env.discussion_rounds_left == 0:
            alive_players_excluding_self = [
                p for p in env.players if p.is_alive and p != player
            ]
            # SKIP goes first so the agent's last-action fallback never lands on it by accident
            return [Vote(player.location, None)] + [
                Vote(player.location, other_player)
                for other_player in alive_players_excluding_self
            ]
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

    def execute(self, env, player):
        super().execute(env, player)
        if env.current_phase == "meeting":
            fields = {}
            if env.requires_justification():
                parsed = parse_justification(self.message)
                fields = {
                    "justification_ok": parsed is not None,
                    "accused": parsed[0] if parsed else None,
                    "evidence": parsed[1] if parsed else None,
                }
            env.log_event(
                "speech",
                speaker=player.name,
                speaker_identity=player.identity,
                round=env.game_config["discussion_rounds"] - env.discussion_rounds_left,
                final_round=env.is_final_discussion_round(),
                message=self.message,
                **fields,
            )

    def can_execute_actions(env, player):
        if env.current_phase == "meeting" and env.discussion_rounds_left == 0:
            return []
        # ADDITION BY ME
        if env.current_phase == "task":
            return []
        
        return [Speak(current_location=player.location)]


class ViewMonitor(Action):
    def __init__(self, current_location):
        super().__init__("ViewMonitor", current_location=current_location)

    def __repr__(self):
        return f"VIEW MONITOR"

    def execute(self, env, player, choose_location):
        super().execute(env, player)
        message = (
            "Monitor Record: {" + "Location: " + choose_location + ", Observation: {"
        )
        if len(env.check_monitor(choose_location)) == 0:
            message += "No one here"
        else:
            for agent in env.players:
                if agent in env.check_monitor(choose_location):
                    message += "(" + agent.name + "): "

                    pattern = r"MOVE from ([\w\s]+) to ([\w\s]+)"
                    action = str(env.camera_record[agent.name])
                    match = re.match(pattern, action)
                    if match:
                        start_location = match.group(1)
                        end_location = match.group(2)
                        action = "enter " + end_location
                    message += action + ", "

                else:
                    pattern = r"MOVE from ([\w\s]+) to ([\w\s]+)"
                    action = str(env.camera_record[agent.name])
                    print("action", action)
                    match = re.match(pattern, action)
                    if match:
                        start_location = match.group(1)
                        end_location = match.group(2)
                        print("start_location", start_location)
                        print("choose_location", choose_location)
                        if start_location == choose_location:
                            message += "(" + agent.name + "): "
                            action = "leave " + start_location
                            message += action + ", "

        message += "}}"
        print(message)
        player.observation_history.append(message)
        # TODO: Implement this

    def can_execute_actions(env, player):
        available_tasks = []
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
        return f"Seemingly doing task"

    def execute(self, env, player):
        super().execute(env, player)
        self.task.do_task()
        # TODO: Implement this

    def can_execute_actions(env, player):
        available_tasks = []
        if env.current_phase == "task":
            current_location = player.location

            for task in player.tasks:
                if task.location == current_location and not task.check_completion():
                    available_tasks.append(CompleteTask(current_location, task))

        return available_tasks


class Sabotage(Action):
    def __init__(self, current_location):
        super().__init__("SABOTAGE", current_location=current_location)

    def execute(self, env, player):
        super().execute(env, player)
        # TODO: Implement this


class Kill(Action):
    def __init__(self, current_location, other_player):
        super().__init__("KILL", current_location=current_location)
        self.other_player = other_player

    def __repr__(self):
        return f"{self.name} {self.other_player.name}"

    def execute(self, env, player):
        super().execute(env, player)
        witnesses = [
            p.name
            for p in env.map.get_players_in_room(self.current_location)
            if p.is_alive and p not in (player, self.other_player)
        ]
        self.other_player.is_alive = False
        player.kill_cooldown = env.game_config["kill_cooldown"]
        env.log_event(
            "kill",
            killer=player.name,
            victim=self.other_player.name,
            room=self.current_location,
            witnesses=witnesses,
        )

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

    def __repr__(self):
        return f"{self.name} - {self.task.name}"

    def action_text(self):
        return f"Seemingly doing task"

    def execute(self, env, player):
        super().execute(env, player)
        self.task.do_task()  # TODO: Implement this (implement fake task instance)

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
IMPOSTER_ACTIONS = [Sabotage, Vent, Kill, CompleteFakeTask]
