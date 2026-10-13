import copy

import networkx as nx

from amongagents.envs.configs.task_config import task_config


class Task:
    def __init__(self, name, duration, task_type, location, map_graph):
        self.name = name
        self.max_duration = duration
        self.duration = duration
        self.location = location
        self.task_type = task_type
        self.is_completed = False
        self.assigned = False
        self.assigned_player = None
        self.map_graph = map_graph

    def find_path(self, start, identity):
        # edge type could only be corridor
        if identity == "Impostor":
            return nx.shortest_path(self.map_graph, start, self.location)
        else:
            return nx.shortest_path(self.map_graph, start, self.location, weight="weight")

    def __repr__(self):
        return f"{self.task_type}: {self.name} ({self.location})"

    def __str__(self):
        return self.__repr__()

    def assign_to(self, player):
        self.assigned = True
        self.assigned_player = player

    def do_task(self):
        self.duration -= 1

    def reset_task(self):
        self.duration = self.max_duration
        self.is_completed = False
        self.assigned = False
        self.assigned_player = None

    def check_completion(self):
        if self.is_completed:
            return True
        elif self.duration <= 0:
            self.is_completed = True
        return self.is_completed


class TaskAssignment:
    def __init__(self, map_graph, game_config):
        self.map_graph = map_graph
        self.game_config = game_config
        self.tasks = []
        for room in self.map_graph.nodes:
            task_names = self.map_graph.nodes[room]["tasks"]
            self.tasks.extend(
                [
                    Task(
                        task_name,
                        task_config[task_name]["duration"],
                        task_config[task_name]["task_type"],
                        room,
                        map_graph,
                    )
                    for task_name in task_names
                ]
            )
        self.short_tasks = [task for task in self.tasks if task.task_type == "short"]
        self.long_tasks = [task for task in self.tasks if task.task_type == "long"]
        self.common_tasks = [task for task in self.tasks if task.task_type == "common"]
        self.assigned_tasks = []

    def reset_task_assignments(self):
        for task in self.tasks:
            task.reset_task()
        self.assigned_tasks = []

    def assign_tasks_to_players(self, players, rng):
        """Give every player their tasks, drawing from rng (a numpy Generator).

        Tasks are drawn without replacement, so a player never holds the same task twice.
        """
        self.reset_task_assignments()
        common = self._draw(rng, self.common_tasks, self.game_config["num_common_tasks"])
        for player in players:
            # every player gets their own copy of the common tasks to complete
            common_tasks = [copy.copy(task) for task in common]
            if player.identity == "Impostor":
                all_tasks = common_tasks
            else:
                short_tasks = self._draw(
                    rng,
                    [task for task in self.short_tasks if not task.assigned],
                    self.game_config["num_short_tasks"],
                )
                long_tasks = self._draw(
                    rng,
                    [task for task in self.long_tasks if not task.assigned],
                    self.game_config["num_long_tasks"],
                )
                all_tasks = common_tasks + short_tasks + long_tasks
                self.assigned_tasks.extend(all_tasks)
            player.assign_tasks(all_tasks)

    @staticmethod
    def _draw(rng, pool, count):
        if count == 0:
            return []
        if count > len(pool):
            raise ValueError(f"cannot draw {count} tasks from a pool of {len(pool)}")
        return [pool[i] for i in rng.choice(len(pool), size=count, replace=False)]

    def progress(self):
        """(completed, total) over the tasks of living Crewmates.

        A dead Crewmate's tasks no longer count towards the task win.
        """
        counted = [task for task in self.assigned_tasks if task.assigned_player.is_alive]
        return sum(1 for task in counted if task.check_completion()), len(counted)

    def check_task_completion(self):
        completed, total = self.progress()
        return completed / total if total > 0 else 0
