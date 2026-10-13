import networkx as nx

from amongagents.envs.configs.map_config import connections, room_data, vent_connections


class Map:
    def __init__(
        self,
        room_data=room_data,
        connections=connections,
        vent_connections=vent_connections,
    ):
        # Defining the graph
        self.ship_map = nx.Graph()

        # Adding rooms (nodes) to the graph and room details to each node
        for room_name, details in room_data.items():
            self.ship_map.add_node(
                room_name,
                tasks=details["tasks"],
                vent=details["vent"],
                special_actions=details["special_actions"],
                players=[],  # per-map list: room_data is module-level and shared by concurrent games
            )

        # Adding 'vent' edges to the graph
        for room1, room2 in vent_connections:
            self.ship_map.add_edge(room1, room2, connection_type="vent", weight=100)

        # Adding edges to the graph
        for room1, room2 in connections:
            self.ship_map.add_edge(room1, room2, connection_type="corridor", weight=1)

    def get_adjacent_rooms(self, room_name):
        """Names of the rooms connected to room_name by a corridor."""
        return [
            adj_room
            for adj_room, attributes in self.ship_map[room_name].items()
            if attributes["connection_type"] == "corridor"
        ]

    def get_adjacent_rooms_vent(self, room_name):
        """Names of the rooms connected to room_name by a vent."""
        return [
            adj_room
            for adj_room, attributes in self.ship_map[room_name].items()
            if attributes["connection_type"] == "vent"
        ]

    def get_players_in_room(self, room_name, include_new_deaths=False):
        players = self.ship_map.nodes[room_name]["players"]
        alive_players = [player for player in players if player.is_alive]
        if include_new_deaths:
            unreported_death_players = [
                player
                for player in players
                if (not player.reported_death and not player.is_alive)
            ]
            return alive_players + unreported_death_players
        else:
            return alive_players

    def reset(self):
        """Resets the map by removing all players from each room."""
        for room in self.ship_map.nodes:
            self.ship_map.nodes[room]["players"] = []

    def add_player(self, player):
        """Adds a player to the room they are currently in."""
        self.ship_map.nodes[player.location]["players"].append(player)
