"""
Template Environment for SpelunkyRL

This template demonstrates how to create a custom Spelunky 2 RL environment by subclassing
SpelunkyRLEngine. Copy this file and modify it to create your own custom environment.

"""

import numpy as np
import gymnasium as gym
from gymnasium.spaces import Dict, Box, Discrete

from spelunky2rl import SpelunkyRLEngine


class SpelunkyEnv(SpelunkyRLEngine):
    """
    Custom Spelunky RL Environment Template

    This class demonstrates all the required and optional methods/properties you can
    define when creating a custom environment.
    """

    ################## REQUIRED: OBSERVATION SPACE ##################

    observation_space = Dict({
        # Define what the agent observes each step
        # Example observation components:

        # Map information: 11x21 grid of entity IDs around the player
        'map_info': Box(low=0, high=1000, shape=(11, 21), dtype=np.int32),

        # Character state: integer representing player state (0-22)
        # See overlunky docs for state meanings
        "char_state": Discrete(23),

        # Can the character jump? (0 or 1)
        "can_jump": Discrete(2),

        # Distance to goal (if using dist_to_goal in data_to_send)
        # "dist_to_goal": Box(low=0, high=np.inf, shape=(1,), dtype=np.float32),

        # Other useful observations you might add:
        # "health": Discrete(100),
        # "bombs": Discrete(100),
        # "ropes": Discrete(100),
        # "money": Box(low=0, high=np.inf, shape=(1,), dtype=np.int32),
    })


    ################## OPTIONAL: CUSTOM ACTION SPACE ##################

    # If not defined, uses the default action space from SpelunkyRLEngine:
    # MultiDiscrete([3, 3, 2, 2, 2, 2, 2, 2])
    # Which corresponds to: [Movement X, Movement Y, Jump, Whip, Bomb, Rope, Run, Door]

    # Example: Simplified action space (movement + jump only)
    action_space = gym.spaces.MultiDiscrete([
        3,  # Movement X: 0=left, 1=nothing, 2=right
        3,  # Movement Y: 0=down, 1=nothing, 2=up
        2,  # Jump: 0=no jump, 1=jump
    ])

    # NOTE: If you define a custom action_space, you MUST also define action_to_input()


    ################## OPTIONAL: DEFAULT RESET OPTIONS ##################

    reset_options = {
        # Entities to destroy at level start (by type ID)
        # Example: Remove all enemies and traps
        "ent_types_to_destroy": [
            # 600, 601,  # Example: Shopkeepers
            # *list(range(219, 342)),  # Example: All monsters
            # *list(range(899, 906)),  # Example: All traps
        ],

        # Other reset options you can set:
        # "manual_control": False,  # Allow manual control for testing
        # "god_mode": False,        # Invulnerability
        # "hp": 4,                  # Starting health
        # "bombs": 4,               # Starting bombs
        # "ropes": 4,               # Starting ropes
        # "gold": 0,                # Starting gold
        # "world": 1,               # Which world (1-16, see overlunky THEME enum)
        # "level": 1,               # Which level in the world
        # "theme": None,            # THEME id; None = the world's default (e.g. 3 = Volcana for world 2)
        # "speedup": True,          # As fast as the machine allows; False = real time (60 FPS)
    }


    ################## REQUIRED: DATA TO REQUEST FROM LUA ##################

    data_to_send = [
        # Specify which data to receive from the Lua script
        # Available options:

        "map_info",      # 11x21 grid of entity IDs around player
        # "dist_to_goal",  # Distance to level exit
        # "entity_info",   # Detailed info about all nearby entities
    ]


    ################## OPTIONAL: ACTION CONVERSION ##################

    def action_to_input(self, action):
        """
        Convert custom action space to the default input format.

        REQUIRED if you define a custom action_space.
        OPTIONAL if you use the default action_space.

        The default input format is: [move_x, move_y, jump, whip, bomb, rope, run, door]
        Each value corresponds to: [0-2, 0-2, 0-1, 0-1, 0-1, 0-1, 0-1, 0-1]

        Args:
            action: Action from your custom action_space

        Returns:
            list: Action in default format [move_x, move_y, jump, whip, bomb, rope, run, door]

        Examples:
            # If your action_space is [move_x, move_y, jump]:
            return action + [0, 0, 0, 1, 0]  # Add: whip=0, bomb=0, rope=0, run=1, door=0

            # If your action_space is a single discrete (e.g., 4 directions):
            if action == 0: return [0, 1, 0, 0, 0, 0, 1, 0]  # Left
            if action == 1: return [2, 1, 0, 0, 0, 0, 1, 0]  # Right
            if action == 2: return [1, 0, 1, 0, 0, 0, 1, 0]  # Jump
            # etc...
        """
        # Example: Add default values for whip, bomb, rope, run, door
        return action + [0, 0, 0, 1, 0]


    ################## REQUIRED: REWARD FUNCTION ##################

    def reward_function(self, gamestate, last_gamestate, action, info):
        """
        Define the reward logic for your environment.

        REQUIRED: Must be implemented.

        Args:
            gamestate (dict): Current game state from Lua script containing:
                - basic_info: {time, health, bombs, ropes, money, x_rest, y_rest,
                               char_state, can_jump, win, etc.}
                - map_info: 11x21 array (if requested in data_to_send)
                - dist_to_goal: float (if requested in data_to_send)
                - entity_info: list of entities (if requested in data_to_send)

            last_gamestate (dict): Previous game state (same structure as gamestate)

            action (list): The action that was taken

            info (dict): Info dictionary to populate (should contain at least "success": bool)

        Returns:
            tuple: (reward, done, truncated, info)
                - reward (float): Reward value for this step
                - done (bool): True if episode should end (goal reached)
                - truncated (bool): True if episode should end (time limit, failure, etc.)
                - info (dict): Additional information for logging/debugging

        """
        reward_val = 0.0
        done = False
        truncated = False

        # Example: Time-based penalty (encourage efficiency)
        reward_val -= 0.01

        # Example: Reward for collecting gold
        if last_gamestate is not None:
            gold_delta = gamestate["basic_info"]["money"] - last_gamestate["basic_info"]["money"]
            reward_val += gold_delta / 100.0

        # Example: Success condition (reaching exit)
        if gamestate.get("dist_to_goal", float("inf")) == 0:
            done = True
            reward_val += 10.0
            info["success"] = True

        # Example: Time limit truncation
        max_time = 60 * 90  # 90 seconds at 60 FPS
        if gamestate["basic_info"]["time"] >= max_time:
            truncated = True
            info["truncation_reason"] = "time_limit"

        # The engine automatically checks for death (health <= 0) and win conditions
        # You don't need to handle those here unless you want custom behavior

        return float(reward_val), done, truncated, info


    ################## REQUIRED: OBSERVATION CONVERSION ##################

    def gamestate_to_observation(self, gamestate):
        """
        Convert raw gamestate from Lua to your observation_space format.

        REQUIRED: Must be implemented.

        Args:
            gamestate (dict): Raw game state from Lua script

        Returns:
            dict: Observation matching your observation_space definition

        Important notes:
            - Ensure all values match the types/shapes defined in observation_space
            - Use np.int32, np.float32 as needed to match space definitions
            - Handle any data validation/clamping here
        """
        observation = {}

        # Example: Map info (if requested in data_to_send)
        observation["map_info"] = np.array(gamestate["map_info"], dtype=np.int32)

        # Example: Character state (ensure it's within valid range)
        char_state_raw = gamestate["basic_info"]["char_state"]
        observation["char_state"] = np.int64(np.clip(char_state_raw, 0, 22))

        # Example: Can jump (ensure boolean is converted to int)
        observation["can_jump"] = np.int64(int(gamestate["basic_info"]["can_jump"]))

        # Example: Distance to goal (if requested in data_to_send)
        # observation["dist_to_goal"] = np.array([gamestate["dist_to_goal"]], dtype=np.float32)

        # Example: Process entity_info (if requested in data_to_send)
        # if "entity_info" in gamestate:
        #     # Each entity: [x, y, vx, vy, type_id, ...]
        #     for entity in gamestate["entity_info"]:
        #         x, y, vx, vy, type_id = entity[:5]
        #         # Process entities as needed...

        return observation
