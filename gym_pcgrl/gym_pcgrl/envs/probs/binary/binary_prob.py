import os
from pdb import set_trace as TT

import numpy as np
from PIL import Image
from gym_pcgrl.envs.probs.problem import Problem
from gym_pcgrl.envs.helper import get_path_coords, get_range_reward, get_tile_locations, calc_num_regions, calc_longest_path, run_dijkstra

# from gym_pcgrl.envs.probs.minecraft.mc_render import spawn_2D_maze

"""
Generate a fully connected top down layout where the longest path is greater than a certain threshold
"""
class BinaryProblem(Problem):
    """
    The constructor is responsible of initializing all the game parameters
    """
    def __init__(self):
        super().__init__()
        self._width = 16
        self._height = 16

        # The probability of placing a tile of a given type when initializing a new (uniform) random map at the
        # beginning of a level-generation episode.
        self._prob = {"empty": 0, "solid": 1.0}

        self._border_tile = "solid"

        self._target_path = 20
        self._random_probs = True
        self._max_path_length = np.ceil(self._width / 2) * (self._height) + np.floor(self._height/2)

        self._reward_weights = {
            "regions": 0,
            "path-length": 1,
            "connectivity": self._max_path_length,
        }

        self.render_path = False
        self.path_coords = []
        self.path_length = None
        dummy_bordered_map = np.zeros((self._width + 2, self._height + 2), dtype=np.uint8)
        # Fill in the borders with ones
        dummy_bordered_map[0, 1:-1] = dummy_bordered_map[-1, 1:-1] = 1
        dummy_bordered_map[1:-1, 0] = dummy_bordered_map[1:-1, -1] = 1
        self._border_idxs = np.argwhere(dummy_bordered_map == 1)

    def gen_holes(self):
        """Generate one entrance and one exit hole into/out of the map. Ensure they will not necessarily result in 
        trivial paths in/out of the map. E.g., the below are not valid holes:

        0 0    0 x  
        x      x
        x      0
        0      0

        """
        idxs = np.random.choice(self._border_idxs.shape[0], size=4, replace=False)
        self.start_xy = self._border_idxs[idxs[0]]
        for i in range(1, 4):
            xy = self._border_idxs[idxs[i]]
            if np.max(np.abs(self.start_xy - xy)) != 1: 
                self.end_xy = xy
                return self.start_xy, self.end_xy


    """
    Get a list of all the different tile names

    Returns:`
        string[]: that contains all the tile names
    """
    def get_tile_types(self):
        return ["empty", "solid"]

    """
    Adjust the parameters for the current problem

    Parameters:
        width (int): change the width of the problem level
        height (int): change the height of the problem level
        probs (dict(string, float)): change the probability of each tile
        intiialization, the names are "empty", "solid"
        target_path (int): the current path length that the episode turn when it reaches
        rewards (dict(string,float)): the weights of each reward change between the new_stats and old_stats
    """
    def adjust_param(self, **kwargs):
        self.render_path = kwargs.get('render', self.render_path) or kwargs.get('render_path', self.render_path)
        super().adjust_param(**kwargs)

        self._target_path = kwargs.get('target_path', self._target_path)
        self._random_probs = kwargs.get('random_probs', self._random_probs)

        rewards = kwargs.get('rewards')
        if rewards is not None:
            for t in rewards:
                if t in self._reward_weights:
                    self._reward_weights[t] = rewards[t]

    """
    Resets the problem to the initial state and save the start_stats from the starting map.
    Also, it can be used to change values between different environment resets

    Parameters:
        start_stats (dict(string,any)): the first stats of the map
    """
    def reset(self, start_stats):
        super().reset(start_stats)
        if self._random_probs:
            self._prob["empty"] = self._random.random()
            self._prob["solid"] = 1 - self._prob["empty"]

    """
    Get the current stats of the map

    Returns:
        dict(string,any): stats of the current map to be used in the reward, episode_over, debug_info calculations.
        The used status are "reigons": number of connected empty tiles, "path-length": the longest path across the map
    """
    def get_stats(self, map, lenient_paths=False):
        map_locations = get_tile_locations(map, self.get_tile_types())
        # self.path_length, self.path_coords = calc_longest_path(map, map_locations, ["empty"], get_path=self.render_path)
        dijkstra,_ = run_dijkstra(self.start_xy[1], self.start_xy[0], map, ["empty"])
        self.path_length = dijkstra[self.end_xy[0], self.end_xy[1]]

        # Give a consolation prize if start and end are not connected.
        if self.path_length == -1:
            connectivity_bonus = 0
            max_temp_path = np.max(dijkstra)
            end_xy = np.argwhere(dijkstra == max_temp_path)[0]
            self.path_length = max_temp_path

        # Otherwise, give a bonus (to guarantee we beat the loser above), plus the actual path length.
        else:
            connectivity_bonus = 1
            end_xy = self.end_xy

        if self.render_path:
            # FIXME: This is a hack to prevent weird path coord list of [[0,0]]
            if self.path_length == 0:
                self.path_coords = []
            else:
                self.path_coords = get_path_coords(dijkstra, init_coords=(end_xy[0], end_xy[1]))

        return {
            "regions": calc_num_regions(map, map_locations, ["empty"]),
            "path-length": self.path_length,
            "connectivity": connectivity_bonus,
            "path-coords": self.path_coords,
        }

    """
    Get the current game reward between two stats

    Parameters:
        new_stats (dict(string,any)): the new stats after taking an action
        old_stats (dict(string,any)): the old stats before taking an action

    Returns:
        float: the current reward due to the change between the old map stats and the new map stats
    """
    def get_reward(self, new_stats, old_stats):
        #longer path is rewarded and less number of regions is rewarded
        rewards = {
            "regions": get_range_reward(new_stats["regions"], old_stats["regions"], 1, 1),
            "path-length": get_range_reward(new_stats["path-length"],old_stats["path-length"], 125, 125),
            "connectivity": get_range_reward(new_stats["connectivity"], old_stats["connectivity"], 1, 1),
        }
        #calculate the total reward
        return rewards["regions"] * self._reward_weights["regions"] +\
            rewards["path-length"] * self._reward_weights["path-length"] +\
            rewards["connectivity"] * self._reward_weights["connectivity"]


    """
    Uses the stats to check if the problem ended (episode_over) which means reached
    a satisfying quality based on the stats

    Parameters:
        new_stats (dict(string,any)): the new stats after taking an action
        old_stats (dict(string,any)): the old stats before taking an action

    Returns:
        boolean: True if the level reached satisfying quality based on the stats and False otherwise
    """
    def get_episode_over(self, new_stats, old_stats):
#       return new_stats["regions"] == 1 and new_stats["path-length"] - self._start_stats["path-length"] >= self._target_path
        return new_stats["regions"] == 1 and new_stats["path-length"] == self._max_path_length and \
            new_stats["connectivity"] == 1

    """
    Get any debug information need to be printed

    Parameters:
        new_stats (dict(string,any)): the new stats after taking an action
        old_stats (dict(string,any)): the old stats before taking an action

    Returns:
        dict(any,any): is a debug information that can be used to debug what is
        happening in the problem
    """
    def get_debug_info(self, new_stats, old_stats):
        return {
            "regions": new_stats["regions"],
            "path-length": new_stats["path-length"],
            # "path-imp": new_stats["path-length"] - self._start_stats["path-length"]
            "connectivity": new_stats["connectivity"],
        }

    """
    Get an image on how the map will look like for a specific map

    Parameters:
        map (string[][]): the current game map

    Returns:
        Image: a pillow image on how the map will look like using the binary graphics
    """
    def render(self, map):
        if self._graphics == None:
            if self.GVGAI_SPRITES:
                self._graphics = {
                    "empty": Image.open(os.path.dirname(__file__) + "/sprites/oryx/floor3.png").convert('RGBA'),
                    "solid": Image.open(os.path.dirname(__file__) + "/sprites/oryx/wall3.png").convert('RGBA'),
                    "path" : Image.open(os.path.dirname(__file__) + "/sprites/newset/snowmanchest.png").convert('RGBA'),
                }
            else:
                self._graphics = {
                    "empty": Image.open(os.path.dirname(__file__) + "/binary/empty.png").convert('RGBA'),
                    "solid": Image.open(os.path.dirname(__file__) + "/binary/solid.png").convert('RGBA'),
                    "path" : Image.open(os.path.dirname(__file__) + "/binary/path_g.png").convert('RGBA'),
                }
        return super().render(map, render_path=self.path_coords)
        # spawn_2Dmaze(map, self._border_tile, self._border_size)
