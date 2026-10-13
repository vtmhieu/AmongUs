from __future__ import annotations

import asyncio
import time

import numpy as np

from amongagents.agent.agent import Decision, LLMAgent
from amongagents.agent.llm import LLM, Usage
from amongagents.agent.prompts import (
    BALLOT_TEXT,
    JUSTIFICATION_REPROMPT,
    MEETING_PHASE_INSTRUCTION,
    PROTOCOL_TEXT,
    TASK_PHASE_INSTRUCTION,
    VOTE_RESULT_EJECTED,
    VOTE_RESULT_NONE,
    VOTING_RULE_TEXT,
    VOTING_RULE_UNDISCLOSED,
)
from amongagents.envs.action import Kill, Speak
from amongagents.envs.configs.game_config import STUDY_GAME, validate_game_config
from amongagents.envs.events import Emit, discard
from amongagents.envs.governance import (
    JUSTIFICATION,
    SECRET,
    SKIP,
    Governance,
    counterfactuals,
    parse_justification,
    tally,
)
from amongagents.envs.map import Map
from amongagents.envs.player import PLAYER_COLORS, Crewmate, Impostor
from amongagents.envs.task import TaskAssignment

# check_game_over() codes -> (winner, reason)
OUTCOMES = {
    1: ("impostor", "outnumbered"),  # Impostors are no longer a minority
    2: ("crew", "ejected"),  # every Impostor was voted out
    3: ("crew", "tasks"),  # every living Crewmate finished their tasks
    4: ("impostor", "timeout"),  # the time limit ran out
}


class AmongUs:
    """One game.

    Everything random in the setup (roles, colours, tasks) is drawn from a generator
    seeded per game, so concurrent games do not disturb each other and a seed fixes
    the starting position. The model's own sampling is not reproducible, which is why
    the event log, not the seed, is the record of what happened.
    """

    def __init__(
        self,
        llm: LLM,
        game_config: dict = STUDY_GAME,
        governance: Governance | None = None,
        seed: int = 0,
        game_id: str = "game",
        emit: Emit = discard,
        llm_log: Emit = discard,
    ):
        self.llm = llm
        self.game_config = validate_game_config(game_config)
        self.governance = governance or Governance()
        self.seed = seed
        self.game_id = game_id
        self._emit = emit
        self.llm_log = llm_log
        self.rng = np.random.default_rng(seed)

        self.map = Map()
        self.players = []
        self.agents = []
        self.task_assignment = TaskAssignment(self.map.ship_map, self.game_config)
        self.message_system = MessageSystem()
        self.current_phase = "task"
        self.timestep = 0
        self.camera_record = {}
        self.button_num = 0
        self.meeting_index = 0  # meetings called so far; the current one during a meeting
        # A meeting called in the step that ends the game is never held, so the number
        # that reached a vote is counted separately.
        self.meetings_held = 0
        self.discussion_rounds_left = self.game_config["discussion_rounds"]
        self.ballots = {}  # voter name -> target name or SKIP, for the vote in progress
        self.kills = 0
        self.wrongful_ejections = 0
        self.started = time.time()
        self._seq = 0

    # --- logging --------------------------------------------------------------

    def emit(self, event_type: str, **fields) -> None:
        self._seq += 1
        self._emit(
            {
                "game_id": self.game_id,
                "seq": self._seq,
                "type": event_type,
                "timestep": self.timestep,
                "phase": self.current_phase,
                "meeting": self.meeting_index,
                **fields,
            }
        )

    def snapshot(self) -> dict:
        """Where everyone is and how far the tasks are, for replaying a game."""
        done, total = self.task_assignment.progress()
        return {
            "players": {
                p.name: {
                    "location": p.location,
                    "alive": p.is_alive,
                    "tasks_done": sum(1 for t in p.tasks if t.check_completion()),
                }
                for p in self.players
            },
            "tasks": {"done": done, "total": total},
        }

    # --- setup ----------------------------------------------------------------

    def initialize_game(self):
        self.initialize_players()
        self.initialize_agents()
        self.emit(
            "game_start",
            seed=self.seed,
            governance=self.governance.to_dict(),
            condition=self.governance.condition,
            game_config=self.game_config,
            model=self.llm.config.to_dict(),
            players=[
                {
                    "name": p.name,
                    "color": p.color,
                    "identity": p.identity,
                    "tasks": [{"name": t.name, "location": t.location} for t in p.tasks],
                }
                for p in self.players
            ],
            state=self.snapshot(),
        )

    def initialize_players(self):
        num_players = self.game_config["num_players"]
        num_impostors = self.game_config["num_impostors"]
        identities = ["Crewmate"] * (num_players - num_impostors) + ["Impostor"] * num_impostors
        colors = self.rng.choice(PLAYER_COLORS, num_players, replace=False)
        self.rng.shuffle(identities)
        self.players = []
        for i in range(num_players):
            role = Crewmate if identities[i] == "Crewmate" else Impostor
            player = role(name=f"Player {i+1}", color=str(colors[i]), location="Cafeteria")
            self.players.append(player)
            self.camera_record[player.name] = "stand quietly and do nothing"
        self.task_assignment.assign_tasks_to_players(self.players, self.rng)
        self.update_map()

    def initialize_agents(self):
        impostor_names = [p.name for p in self.players if p.identity == "Impostor"]
        self.agents = [
            LLMAgent(
                player,
                llm=self.llm,
                impostor_names=impostor_names,
                game_id=self.game_id,
                seed=int(self.rng.integers(2**31)),
                llm_log=self.llm_log,
            )
            for player in self.players
        ]

    # --- state ----------------------------------------------------------------

    @property
    def discussion_round(self) -> int:
        """Discussion rounds completed in the current meeting (0 in the first round)."""
        return self.game_config["discussion_rounds"] - self.discussion_rounds_left

    def is_final_discussion_round(self) -> bool:
        return self.current_phase == "meeting" and self.discussion_rounds_left == 1

    def living(self) -> list:
        return [p for p in self.players if p.is_alive]

    def check_game_over(self) -> int:
        num_impostors = sum(1 for p in self.living() if p.identity == "Impostor")
        num_crewmates = sum(1 for p in self.living() if p.identity == "Crewmate")
        if num_impostors >= num_crewmates:
            return 1  # Impostors win
        elif num_impostors == 0:
            return 2  # Crewmates win
        elif self.task_assignment.check_task_completion() == 1.0:
            return 3  # Crewmates win (task completed)
        elif self.timestep >= self.game_config["max_timesteps"]:
            return 4  # Impostors win (time limit)
        return 0  # Game continues

    def check_actions(self):
        for player in self.players:
            available_actions = []
            for action in player.get_all_actions():
                available_actions.extend(action.can_execute_actions(self, player))
            player.set_available_actions(available_actions)

    def update_map(self):
        self.map.reset()
        for player in self.players:
            self.map.add_player(player)
        self.message_system.route_location_info_message(self)

    # --- turns ----------------------------------------------------------------

    async def agent_step(self, agent):
        self.check_actions()
        if not agent.player.is_alive:
            return
        decision = await self.decide(agent)
        self.apply(agent, decision)
        self.update_map()

    async def decide(self, agent) -> Decision:
        """Get one agent's decision for this turn, enforcing the discussion protocol."""
        player = agent.player
        if player.identity == "Impostor" and player.kill_cooldown > 0:
            player.kill_cooldown -= 1
        phase = "Meeting phase" if self.current_phase == "meeting" else "Task phase"
        decision = await agent.choose_action(self.timestep, phase)
        if (
            self.governance.protocol == JUSTIFICATION
            and self.is_final_discussion_round()
            and isinstance(decision.action, Speak)
            and not decision.fallback
            and self.justification_of(decision.action) is None
        ):
            # format check: one re-prompt; a second miss is kept and logged as non-compliant
            retry = await agent.choose_action(self.timestep, phase, note=JUSTIFICATION_REPROMPT)
            retry.usage.add(decision.usage)
            retry.latency_s = round(retry.latency_s + decision.latency_s, 3)
            retry.reprompts += decision.reprompts + 1
            decision = retry
        return decision

    def justification_of(self, speak: Speak):
        return parse_justification(speak.message, [p.name for p in self.living()])

    def apply(self, agent, decision: Decision, broadcast: bool = True):
        """Carry out a decision and log it.

        broadcast=False keeps the action from being shown to the other players as it
        happens, which is how a secret ballot is cast.
        """
        player, action = agent.player, decision.action
        observation_location = ""
        if action.name == "VIEW MONITOR":
            observation_location = str(self.rng.choice(sorted(self.map.ship_map.nodes)))
        witnesses = []
        if isinstance(action, Kill):
            witnesses = [
                p.name
                for p in self.map.get_players_in_room(player.location)
                if p is not player and p is not action.other_player
            ]
        round_index = self.discussion_round if self.current_phase == "meeting" else None
        phase_before = self.current_phase

        self.camera_record[player.name] = action
        if broadcast:
            self.message_system.route_real_time_message(self, player, action)
        player.make_action(self, action, observation_location)

        turn = {
            "player": player.name,
            "identity": player.identity,
            "action": action.name,
            # a speech's words are in "message"; don't repeat them here
            "text": action.name if isinstance(action, Speak) else repr(action),
            **action.details(),
            "thought": decision.thought,
            "fallback": decision.fallback,
            "reprompts": decision.reprompts,
            "refused": decision.refused,
            "usage": decision.usage.to_dict(),
            "latency_s": decision.latency_s,
        }
        if round_index is not None:
            turn["round"] = round_index
        if isinstance(action, Speak) and phase_before == "meeting":
            final_round = self.is_final_discussion_round()
            turn["final_round"] = final_round
            if final_round:
                justification = self.justification_of(action)
                turn["justification"] = (
                    {"accused": justification.accused, "evidence": justification.evidence}
                    if justification
                    else None
                )
        if isinstance(action, Kill):
            self.kills += 1
            turn["witnesses"] = witnesses
        # the phase a turn is logged under is the one it was taken in
        self._seq += 1
        self._emit(
            {
                "game_id": self.game_id,
                "seq": self._seq,
                "type": "turn",
                "timestep": self.timestep,
                "phase": phase_before,
                "meeting": self.meeting_index if phase_before == "meeting" else None,
                **turn,
                "state": self.snapshot(),
            }
        )

    async def game_step(self):
        self.emit("step", alive=[p.name for p in self.living()])
        if self.current_phase == "task":
            await self.task_phase_step()
        elif self.current_phase == "meeting":
            await self.meeting_phase()
        self.timestep += 1

    async def task_phase_step(self):
        for agent in self.agents:
            await self.agent_step(agent)
            if self.current_phase == "meeting":
                break

    # --- meetings -------------------------------------------------------------

    def start_meeting(self, caller, action):
        """Called by CallMeeting.execute."""
        bodies = [p.name for p in self.players if not p.is_alive and not p.reported_death]
        for player in self.players:
            if not player.is_alive:
                player.reported_death = True
        # only the emergency button is rationed; reporting a body is always allowed
        if not action.reports_body:
            self.button_num += 1
        self.meeting_index += 1
        self.current_phase = "meeting"
        self.emit(
            "meeting_start",
            caller=caller.name,
            caller_identity=caller.identity,
            kind="report" if action.reports_body else "button",
            location=action.current_location,
            bodies=bodies,
            living=[p.name for p in self.living()],
        )

    async def meeting_phase(self):
        # Move all players to the Cafeteria
        for player in self.players:
            player.location = "Cafeteria"
        self.update_map()

        # Discussion
        for _ in range(self.game_config["discussion_rounds"]):
            for agent in self.agents:
                await self.agent_step(agent)
            self.discussion_rounds_left -= 1
            self.check_actions()
            self.update_map()

        # Voting
        self.ballots = {}
        if self.governance.ballot == SECRET:
            await self.secret_ballot()
        else:
            for agent in self.agents:
                await self.agent_step(agent)
        self.voteout()
        self.update_map()

    async def secret_ballot(self):
        """Everyone votes at once, seeing no one else's vote."""
        self.check_actions()
        voters = [agent for agent in self.agents if agent.player.is_alive]
        decisions = await asyncio.gather(*(self.decide(agent) for agent in voters))
        for agent, decision in zip(voters, decisions):
            self.apply(agent, decision, broadcast=False)

    def cast_vote(self, voter, target: str):
        """Called by Vote.execute. target is a player's name or SKIP."""
        self.ballots[voter.name] = target

    def voteout(self):
        living = self.living()
        result = tally(self.ballots, len(living), self.governance.threshold)
        alternatives = counterfactuals(self.ballots, len(living))
        ejected = next((p for p in living if p.name == result.ejected), None)
        wrongful = ejected is not None and ejected.identity == "Crewmate"
        if ejected is not None:
            ejected.is_alive = False
            # an ejected player leaves no body to report
            ejected.reported_death = True
            self.wrongful_ejections += wrongful

        if self.governance.ballot == SECRET:
            detail = "Totals: " + ", ".join(f"{option}: {n}" for option, n in result.counts.items())
        else:
            detail = "Votes: " + "; ".join(f"{voter} -> {target}" for voter, target in self.ballots.items())
        template = VOTE_RESULT_EJECTED if ejected else VOTE_RESULT_NONE
        announcement = template.format(player=result.ejected, detail=detail)
        for player in self.living():
            player.receive(f"Timestep {self.timestep}: [meeting phase] {announcement}", "action")

        self.emit(
            "tally",
            rule=result.rule,
            ballots=dict(self.ballots),
            counts=result.counts,
            n_voters=result.n_voters,
            required=result.required,
            ejected=result.ejected,
            ejected_identity=ejected.identity if ejected else None,
            wrongful=wrongful,
            skips=result.counts.get(SKIP, 0),
            counterfactual=alternatives,
            rule_changed_outcome=len(set(alternatives.values())) > 1,
            state=self.snapshot(),
        )
        self.meetings_held += 1
        self.current_phase = "task"
        self.discussion_rounds_left = self.game_config["discussion_rounds"]
        self.ballots = {}

    # --- running --------------------------------------------------------------

    async def run_game(self) -> dict:
        """Play to the end and return the game's summary."""
        self.initialize_game()
        outcome = self.check_game_over()
        while not outcome:
            await self.game_step()
            outcome = self.check_game_over()
        return self.finish(outcome)

    def usage(self) -> Usage:
        total = Usage()
        for agent in self.agents:
            total.add(agent.usage)
        return total

    def summary(self) -> dict:
        """Counters kept by the engine itself, independent of the event log."""
        decisions = sum(a.decisions for a in self.agents)
        fallbacks = sum(a.fallbacks for a in self.agents)
        return {
            "game_id": self.game_id,
            "seed": self.seed,
            "condition": self.governance.condition,
            "governance": self.governance.to_dict(),
            "timesteps": self.timestep,
            "meetings": self.meetings_held,
            "kills": self.kills,
            "wrongful_ejections": self.wrongful_ejections,
            "decisions": decisions,
            "fallbacks": fallbacks,
            "reprompts": sum(a.reprompts for a in self.agents),
            "refusals": sum(a.refusals for a in self.agents),
            "usage": self.usage().to_dict(),
            "duration_s": round(time.time() - self.started, 2),
        }

    def finish(self, outcome: int) -> dict:
        winner, reason = OUTCOMES[outcome]
        summary = {**self.summary(), "winner": winner, "reason": reason}
        self.emit("game_end", **{k: v for k, v in summary.items() if k != "game_id"}, state=self.snapshot())
        return summary


class MessageSystem:
    """Delivers to each player what they can see and hear."""

    def create_action_message(self, env, player, action):
        if env.current_phase == "task":
            return f"Timestep {env.timestep}: [task] {player.name} {action.action_text()}"
        return f"Timestep {env.timestep}: [meeting phase - round {env.discussion_round}] {player.name} {action.action_text()}"

    def meeting_instruction(self, env):
        governance = env.governance
        if governance.disclose_rules:
            voting_rules = f"{VOTING_RULE_TEXT[governance.threshold]} {BALLOT_TEXT[governance.ballot]}"
        else:
            voting_rules = VOTING_RULE_UNDISCLOSED
        instruction = MEETING_PHASE_INSTRUCTION.format(
            discussion_rounds=env.game_config["discussion_rounds"], voting_rules=voting_rules
        )
        if env.is_final_discussion_round():
            instruction += PROTOCOL_TEXT[governance.protocol]
        return instruction

    def create_location_message(self, record, env):
        if env.current_phase == "task":
            phase_info = "Task phase"
            instruction = TASK_PHASE_INSTRUCTION
        else:
            max_rounds = env.game_config["discussion_rounds"]
            if env.discussion_rounds_left > 0:
                phase_info = f"Meeting phase - Discussion round ({env.discussion_round + 1}/{max_rounds})"
            else:
                phase_info = "Meeting phase - Voting"
            instruction = self.meeting_instruction(env)
        message = f"Game Time: {env.timestep}/{env.game_config['max_timesteps']}\n"
        message += f"Current phase: {phase_info}\n"
        message += f"{instruction}\n"
        players_text = ", ".join(record["players"])
        message += f"Current Location: {record['location']}\n"
        message += f"Players in {record['location']}: {players_text}\n\n"
        return message

    def route_location_info_message(self, env):
        for location in env.map.ship_map:
            players = env.map.get_players_in_room(location, include_new_deaths=True)
            player_names = [
                player.name if player.is_alive else f"{player.name} (dead)"
                for player in players
            ]
            record = {"location": location, "players": player_names}
            for player in players:
                player.receive(self.create_location_message(record, env), "location")

    def route_real_time_message(self, env, player, action):
        """Show an action to everyone in the room it happens in (and the room moved to)."""
        location = action.current_location
        new_location = getattr(action, "new_location", location)
        message = self.create_action_message(env, player, action)
        for other_player in env.players:
            if other_player != player and other_player.location in (location, new_location):
                other_player.receive(message, "action")
