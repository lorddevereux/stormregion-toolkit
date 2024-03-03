import os
import struct
import math
import sys
from PIL import Image
from enum import Enum

sr_trigger_action = Enum('sr_trigger_action', ['attack_ground'
                                               'attack_move_ai_group',
                                               'attack_move_ai_group_path',
                                               'attack_move_on_path',
                                               'attack_move_units',
                                               'auto-decrement-variable',
                                               'auto_increment_variable',
                                               'enter_unit',
                                               'cannonade',
                                               'create_model',
                                               'create_unit',
                                               'create_unit_advanced',
                                               'create_unit_export',
                                               'decrease_variable',
                                               'defeat',
                                               'disable_auto_equipment',
                                               'disable_night',
                                               'disable_time_counter',
                                               'disable_unit_counter',
                                               'do_nothing',
                                               'drop_container',
                                               'echo_message',
                                               'enable_auto_equipment',
                                               'enable_night',
                                               'enable_time_counter',
                                               'enable_unit_counter',
                                               'flip_variable',
                                               'focus_camera',
                                               'heavy_bomber',
                                               'hide_objective_target',
                                               'hide_units',
                                               'increase_variable',
                                               'increase_xp',
                                               'kill_units',
                                               'lay_tankmines_on_path',
                                               'local_fading_message',
                                               'local_static_message',
                                               'message_box',
                                               'move_ai_grp',
                                               'move_units',
                                               'move_units_advanced',
                                               'move_units_backwards',
                                               'move_units_backwards_advanced',
                                               'move_units_on_path',
                                               'move_units_on_path_convoy',
                                               'objective_completed',
                                               'objective_failed',
                                               'parachute',
                                               'play_cutscene',
                                               'play_effect',
                                               'play_music',
                                               'preserve_trigger',
                                               'recon_plane',
                                               'remove_buildings',
                                               'remove_units',
                                               'run_script',
                                               'save_unit_xp',
                                               'set_ai_grp_base',
                                               'set_ai_grp_tactics',
                                               'set_player',
                                               'set_shadow_mode',
                                               'set_unit_ammo',
                                               'set_unit_behaviour',
                                               'set_unit_equipment',
                                               'set_unit_hp',
                                               'set_unit_state',
                                               'set_variable',
                                               'set_weather',
                                               'show_minimap_signal',
                                               'show_objective',
                                               'show_tutorial_text',
                                               'speech',
                                               'speech_and_wait',
                                               'start_effect',
                                               'stop_unit',
                                               'stop_effect',
                                               'stop_variable',
                                               'tactical_bomber',
                                               'teleport_units',
                                               'tow',
                                               'turn_light_off',
                                               'turn_light_on',
                                               'unhide_units',
                                               'unload_all',
                                               'untow',
                                               'use_boat',
                                               'victory',
                                               'wait'])

sr_trigger_event = Enum('sr_trigger_event', ['all_main_objectives_complete',
                                             'dropcontainer_sent_to_location',
                                             'heavybomber_sent_to_location',
                                             'parachute_sent_to_location'
                                             'periodical',
                                             'unit_attacked',
                                             'unit_died',
                                             'unit_enters_object',
                                             'unit_enters_location',
                                             'unit_leaves_object',
                                             'unit_leaves_location'
                                             'unit_starts_towing',
                                             'unit_stops_towing',
                                             'unit_player_changes'])

sr_trigger_condition = Enum('sr_trigger_condition', ['always',
                                                     'compare_two_vars',
                                                     'compare_vars',
                                                     'find_building_by_id',
                                                     'find_unit_by_id',
                                                     'find_units_at',
                                                     'find_units_in_ai_grp',
                                                     'trigger_unit_location',
                                                     'trigger_unit_2_location',
                                                     'never',
                                                     'owner_of_trigger_unit',
                                                     'owner_of_trigger_unit_2',
                                                     'put_trigger_unit_2_in_grp',
                                                     'put_trigger_unit_in_grp',
                                                     'trigger_unit_member_ai_grp',
                                                     'type_of_trigger_unit',
                                                     'type_of_trigger_unit_2'])

class stormregion_loc:
    name: str = ""
    x1 : float
    y1 : float
    x2 : float
    y2 : float
    color: int


    def __init__(self, name, _x, _y, _x1, _y1, _color):
        self.name = name
        self.x1 = _x
        self.y1 = _y
        self.x2 = _x1
        self.y2 = _y1
        self.color = _color


class stormregion_tvar:
    name: str = ""
    initial_value : int
    increment : int
    state: int

    def __init__(self, name, _init, _increment):
        self.name = name
        self.initial_value = _init
        self.increment = _increment
        self.state = _init


class stormregion_map_unit_def:
    classname: str = ""
    player: int = 0
    xp: int = 0
    x : float
    z : float
    y : float       # off ground
    dir : float     # radians...?
    hp  : float     # 0 - 1 (%)
    ammo: float
    script_id : str = ""
    ai_group : int
    armor : list = [ 0, 0, 0, 0]    # F, L, R, Back
    behaviour: float
    global_active : int
    slot_0 : int
    slot_1 : int
    stored_units : list = []
    cargo : float
    firstkill : bool
    firstblood : bool
    firstshot : bool
    firstvehiclelost : bool
    firstarmouredvehiclekill : bool
    towed_units  = None
    stored_special : int


class stormregion_path:
    name = ""
    nodes = []      # list of xy tuples

    def __init__(self, _name, _nodes):
        self.name = _name
        self.nodes = _nodes


class stormregion_sfx:
    sound = ""
    x : float
    y : float
    z : float
    v : float
    index: int

    def __init__(self, _m, _x, _y, _z, _v, _index):
        self.sound = _m
        self.x = _x
        self.y = _y
        self.z = _z
        self.v = _v
        self.index = _index


class stormregion_road_node:
    x : float
    y : float
    r1 : float
    r2 : float
    r3 : float
    alpha_l : float
    alpha_r : float
    interp : float
    jcn_id : int

    def __init__(self, _x, _y, _r1, _r2, _r3, _al, _ar, _interp, _jcn):
        self.x = _x
        self.y = _y
        self.r1 = _r1
        self.r2 = _r2
        self.r3 = _r3
        self.alpha_l = _al
        self.alpha_r = _ar
        self.interp = _interp
        self.jcn_id = _jcn


class stormregion_road:
    U_MIRROR = 0x20
    V_MIRROR = 0x40

    material: str
    tesselation: float
    config: int
    nodes : list

    def __init__(self, _mat, _tes, _cfg):
        self.material = _mat
        self.tesselation = _tes
        self.config = _cfg
        self.nodes = []

    def add_node(self, node: stormregion_road_node):
        self.nodes.append(node)


class stormregion_jcn:
    U_MIRROR = 0x20
    V_MIRROR = 0x40

    material: str
    config: int
    x : float
    y : float
    r1 : float
    r2 : float
    r3 : float

    def __init__(self, _mat, _cfg, _x, _y, _r1, _r2, _r3):
        self.material = _mat
        self.config = _cfg
        self.x = _x
        self.y = _y
        self.r1 = _r1
        self.r2 = _r2
        self.r3 = _r3


class stormregion_decal:
    material = ""
    x : float
    z : float
    r : int     # degrees

    def __init__(self, _m, _x, _z, _r):
        self.material = _m
        self.x = _x
        self.z = _z
        self.r = _r


class stormregion_object:
    model_file = ""
    x : float
    y : float
    z : float
    r : float   # some random format
    index : int 

    def __init__(self, _m, _x, _y, _z, _r, _index):
        self.model_file = _m
        self.x = _x
        self.y = _y
        self.z = _z
        self.r = _r
        self.index = _index
