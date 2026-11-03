"""Equipment in NHL 19: a player's gear, a team's gear colours and sticks in the team's colours. Ported from PS3 Legacy
(`equipment.py`, `sticks.py`); facts and checks in docs/notes/editors.md.

Player gear: exhibitionskaterequipment (one row per skater, keyed by his game_id) and exhibitiongoalieequipment. The
numbers are the game's model ids, the ones its Creation Zone lists (creation_zone_csv/*.csv in inxp_00.big: the
renderassetid column, which equals the asset id for every model; NAMES below are made from those files and the game's
English text by tools/gear_tables.py). Tape colours are 0xRRGGBB.

Team gear: stockteamequipmenttable (custom teams: customteamequipmenttable), rows of (team, equipment, brand, variant,
era) holding 15 zone colours 0xRRGGBB. `equipment` is the game's RecolourEquipment enum (boot service-defs
creation_zone/team.json, EquipmentId 0-12): CATEGORIES. Team -1 rows are the brands' own colours. A team's colours are
its exhibitionteams fe*color values (the ones WS8 sets for Utah); `proposal` moves the team's gear from its old colours
to new ones and `recolour` writes such a mapping, `copy_gear` gives a team another team's rows (for a team without gear).

Sticks: a skater stick's colours are baked into the model's texture (rendering/characters/player/playerstick_*_cm.gnf,
no tint masks, unlike goalie sticks and the rest of the team gear), so as in Legacy a player whose stick shows a colour
his team does not wear gets another model of the same brand that fits (`team_sticks`). STICK_COLOURS are measured on
the Creation Zone's stick pictures (creationzone/equipment/stick/stick<id>.gnf) by tools/gear_tables.py.
"""
import colorsys

PLAYERS, BIOS, ROSTER, TEAMS = 'exhibitionplayers', 'exhibitionplayerbiotable', 'exhibitionrostertable', 'exhibitionteams'
SKATER_TABLE, GOALIE_TABLE = 'exhibitionskaterequipment', 'exhibitiongoalieequipment'
STOCK, CUSTOM = 'stockteamequipmenttable', 'customteamequipmenttable'
GOALIE = 4  # bio position

# choice -> (field, label, NAMES key or None for a colour)
SKATER = {
    'stick': ('stick', 'Stick', 'stick'),
    'helmet': ('helmetbrand', 'Helmet', 'helmet'),
    'gloves': ('gloves', 'Gloves', 'gloves'),
    'skates': ('skatebrand', 'Skates', 'skates'),
    'visor': ('visortype', 'Visor', 'visor'),
    'visor_tint': ('visorcolor', 'Visor tint', 'visor_tint'),
    'jersey_tuck': ('jerseytuck', 'Jersey tuck', 'jersey_tuck'),
    'sock_tuck': ('skatesocktuck', 'Sock tuck', 'sock_tuck'),
    'pant_length': ('pantstypecode', 'Pant length', 'pant_length'),
    'blade_tape': ('stickbladetapecolor', 'Blade tape', None),
    'shaft_tape': ('stickshafttapecolor', 'Shaft tape', None),
}
GOALIE_GEAR = {
    'stick': ('stick', 'Stick', 'goalie_stick'),
    'pads': ('pads', 'Pads', 'pads'),
    'blocker': ('blocker', 'Blocker', 'blocker'),
    'trapper': ('trapper', 'Trapper', 'trapper'),
    'mask': ('maskid', 'Mask', None),
    'neck': ('neckprotector', 'Neck guard', 'neck'),
    'jersey_tuck': ('jerseytuck', 'Jersey tuck', 'jersey_tuck'),
    'tape': ('sticktapecolor', 'Stick tape', None),
}
KINDS = {'skater': (SKATER_TABLE, SKATER), 'goalie': (GOALIE_TABLE, GOALIE_GEAR)}
COLOUR_CHOICES = frozenset({'blade_tape', 'shaft_tape', 'tape'})
# what the whole team may share (the editor's "same for the whole team")
TEAM_WIDE = ('helmet', 'gloves', 'visor', 'visor_tint', 'jersey_tuck', 'sock_tuck', 'pant_length', 'blade_tape',
             'shaft_tape')
# what a player the update makes wears instead of his donor's choices (Legacy's equipment.NEW_PLAYER): the value most of
# NHL 19's own players have (a straight clear visor, no jersey tuck, socks Full, short pants, white tape; a goalie the
# plain mask, no neck guard). The models stay the donor's; real gear (rosterupdate._real_gear, _pack_gear) comes on top.
NEW_PLAYER = {'skater': {'visor': 0, 'visor_tint': 0, 'jersey_tuck': 0, 'sock_tuck': 0, 'pant_length': 0,
                         'blade_tape': 0xDFDDD7, 'shaft_tape': 0xDFDDD7},
              'goalie': {'mask': 120, 'neck': 0, 'jersey_tuck': 0, 'tape': 0}}

CATEGORIES = {0: 'Goalie trapper', 1: 'Goalie blocker', 2: 'Goalie pads', 3: 'Goalie stick', 4: 'Gloves', 5: 'Socks',
              6: 'Pants', 7: 'Helmet', 8: 'Jersey', 9: 'Font', 10: 'Logo', 11: 'Logo 2', 12: 'Logo 3'}
GEAR = (7, 4, 2, 1, 0, 3)  # the categories the Equipment tab recolours (the jersey's are the uniform's business)
ZONES = tuple(f'zone{k}' for k in range(1, 16))
TEAM_COLOURS = ('feprimarycolor', 'fesecondarycolor', 'fetertiarycolor')

CLEAR = 0.06    # a colour covering this share of the stick picture or more is the stick's colour; less is an accent
NEAR = 25       # degrees of hue: colours this close are the same colour

# --- tables made by tools/gear_tables.py from the game's creation-zone files; run it again rather than editing ---
NAMES = {
    'stick': {
        35: 'TITAN Retro Stick',
        36: 'SHER-WOOD Retro Stick',
        84: 'WARRIOR Covert QR1',
        86: 'CCM RBZ Superfast',
        87: 'CCM Tacks',
        98: 'WARRIOR Dynasty HD1',
        99: 'CCM Ultra Tacks',
        102: 'CCM RBZ Speedburner',
        103: 'CCM Ribcor Reckoner',
        107: 'STX Surgeon RX',
        109: 'SHER-WOOD REKKER EK60',
        110: 'STX Stallion 600',
        112: 'CCM Ribcor 40K',
        113: 'STX Surgeon RX2',
        114: 'SHER-WOOD BPM 150',
        115: 'CCM Super Tacks',
        116: 'CCM RBZ Revolution',
        117: 'CCM Ribcor Trigger',
        118: 'WARRIOR Covert QRL',
        123: 'CCM RBZ FT1',
        124: 'CCM Ribcor Trigger 2',
        125: 'CCM Super Tacks 2.0',
        126: 'Sher-Wood EK Rekker 365',
        127: 'STX Stallion HPR IH',
        128: 'Warrior Alpha QX',
        130: 'Bauer Vapor 1X Lite',
        131: 'TRUE Hockey A6.0 SBP',
        132: 'TRUE Hockey XC9 ACF',
        133: 'True Hockey A6.0 HT',
        134: 'Warrior Covert QR Edge',
        135: 'Warrior Covert QR Edge Super Light',
        136: 'CCM Jetspeed',
        137: 'CCM Ribcor Trigger 3D',
        138: 'CCM Super Tacks AS1',
        139: 'Bauer Nexus 2N PRO',
        140: 'Bauer Supreme 2S Pro',
        141: 'STX Surgeon RX3',
        300: 'Frosted Tip',
        301: 'Glacier',
        302: 'Canadian Pride',
        303: 'The Twig',
        304: 'Alien Technology',
        305: 'Hush',
        306: 'Hey, Zebra',
        307: 'Cold War',
        308: 'Wild Thing',
        309: 'Scarlet Streak',
        310: 'Diva',
        311: 'Racing Gear',
        312: 'Radioactive',
        313: 'Hazard',
        314: 'Electric Wave',
        315: 'Pine',
        316: 'Frog',
        317: 'Alpine Frost',
        318: 'Northern Light',
        319: 'Sticks and Stripes',
        320: 'Black Forest',
        321: 'White Hot',
        322: 'Rave',
        323: 'Bursts',
        324: 'Aura',
        325: 'Cyber Groove',
        326: 'Orchid',
        327: 'Hot Blood',
        328: 'The Deep',
        329: 'Voltage',
        330: 'BioFrost',
        331: 'Good Canadian Kid',
        332: 'Redwood',
        333: 'Fire And Lightning',
        334: 'Blazing Sun',
        335: 'Crimson Tide',
        336: 'Raindrop',
        337: 'Silhouette',
        338: 'Emperor Penguin',
        339: 'Left Right Left',
        340: 'Side of Mustard',
        341: 'Plasma',
        342: 'Red Special',
        343: 'Pyramid',
        344: 'Arctic Lime',
        345: 'Touche',
        346: 'Pacific Northwest',
        347: 'En Garde',
        348: 'Blood Moon',
        349: 'True North',
    },
    'helmet': {
        1: 'BAUER 4500',
        6: 'CCM V10',
        7: 'JOFA',
        19: 'BAUER 5100',
        20: 'CCM Tacks 710',
        21: 'BAUER RE-AKT 100',
        23: 'CCM Fitlite',
        25: 'WARRIOR Krown PX3',
        26: 'CCM Fitlite 3DS',
        28: 'WARRIOR Covert PX2',
        29: 'Bauer Re-Akt 200',
        30: 'Warrior Alpha One',
        110: 'College Helmet',
        111: 'Half cage',
        112: 'Full Shield',
        113: 'Hybrid Shield',
    },
    'gloves': {
        53: 'CCM CL 500',
        58: 'WARRIOR Dynasty AX1',
        65: 'STX Stallion',
        66: 'WARRIOR Covert QR1',
        67: 'STX Surgeon',
        68: 'CCM Ultra Tacks',
        69: 'CCM 30K',
        82: 'Bauer Vapor 1X Lite',
        84: 'CCM 4 Roll Pro III',
        85: 'CCM Quicklite',
        86: 'WARRIOR Covert QRL',
        87: 'Sher-Wood BPM 120',
        91: 'CCM Super Tacks',
        92: 'STX Surgeon HPR',
        93: 'Warrior Alpha QX',
        94: 'BAUER Supreme 1S',
        95: 'TRUE Hockey A6.0',
        96: 'TRUE Hockey XC9',
        97: 'Verbero Cypress Pro V1000',
        98: 'Verbero Dextra Pro III',
        99: 'Verbero Mercury HG80',
        100: 'Warrior Alpha QR Edge',
        101: 'CCM Jetspeed FT1',
        102: 'Bauer Nexus 2N PRO',
        103: 'STX Surgeon RX3',
    },
    'skates': {
        39: 'CCM Tacks',
        43: 'CCM Jetspeed',
        44: 'CCM Ribcor 50K',
        47: 'Bauer Vapor 1X 2.0',
        49: 'CCM Super Tacks',
        53: 'CCM Jetspeed FT1',
        54: 'CCM Ribcor 70K',
        55: 'True Hockey Pro Custom',
        56: 'CCM Super Tacks AS1',
        57: 'Bauer Nexus 2N PRO',
        58: 'Bauer Supreme 2S Pro',
        300: 'Electric Green',
        301: 'Fast Lane',
        302: "Shockin'",
        303: 'Timbas',
        304: 'Tiger Shark',
        305: 'Festive Specials',
        306: 'Arctic Camo',
        307: 'Pure Class',
        308: 'WHAT ARE THOSE?',
        309: 'Invisible Skates',
        310: 'The Wild',
        311: 'Blow Your Mind',
        312: 'Toony',
        313: "70's Sofa",
        314: 'Corks',
        315: 'Paint Splatter',
        316: 'The Future, Baby',
        317: 'Rugged Boots',
        318: "NHL 19's Own",
        319: 'Hey, Zebra',
        320: 'Baby Narwhals',
        321: 'Captain Wonderful',
        322: 'Caution',
        323: 'Electric Blue "Macaw"',
        324: 'The Pollock',
        325: 'The Lumberjack - Skate',
        326: 'B.O.O.T.S',
        327: 'Vintage Wood',
        328: 'Glacier Boots',
        329: 'Check and Mate',
    },
    'goalie_stick': {
        6: 'sherwoodretro',
        15: 'SHER-WOOD T100',
        18: 'KOHO',
        21: 'VAUGHN VGS 7600',
        22: 'VAUGHN VGS 8800',
        25: "BRIAN'S Zero G Foam",
        28: 'WARRIOR Ritual',
        30: 'CCM 500',
        31: "BRIAN'S G-Netik",
        35: 'CCM Retro Flex',
        38: 'WARRIOR SWAGGER PRO',
        39: 'CCM Extreme Flex 2 Pro',
        40: 'SHER-WOOD GS350',
        41: 'SHER-WOOD GS650',
        45: 'CCM Eflex',
        46: 'CCM Premier',
        47: 'BAUER Vapor 1X',
        48: 'Warrior Heritage Swagger',
        49: 'Warrior Ritual CR1',
        50: 'CCM Premier 2',
        51: 'Bauer Supreme 2S Pro',
        52: 'Warrior Swagger Pro 2',
        53: 'Bauer Vapor 2X Pro',
        300: 'GoalieStick 1',
        301: 'GoalieStick 2',
        302: 'GoalieStick 3',
        303: 'GoalieStick 4',
        304: 'GoalieStick 5',
        305: 'GoalieStick 6',
        306: 'GoalieStick 7',
        307: 'GoalieStick 8',
        308: 'GoalieStick 9',
        309: 'GoalieStick 10',
        310: 'GoalieStick 11',
        311: 'GoalieStick 12',
        312: 'GoalieStick 13',
        313: 'GoalieStick 14',
        314: 'GoalieStick 15',
        315: 'GoalieStick 16',
        316: 'GoalieStick 17',
        317: 'GoalieStick 18',
        318: 'GoalieStick 19',
        319: 'GoalieStick 20',
        320: 'GoalieStick 21',
        321: 'GoalieStick 22',
        322: 'GoalieStick 23',
        323: 'GoalieStick 24',
        324: 'GoalieStick 25',
        325: 'GoalieStick 26',
        326: 'GoalieStick 27',
        327: 'GoalieStick 28',
        328: 'GoalieStick 29',
        329: 'GoalieStick 30',
        330: 'GoalieStick 31',
        331: 'GoalieStick 32',
        332: 'GoalieStick 33',
        333: 'GoalieStick 34',
        334: 'GoalieStick 35',
        335: 'GoalieStick 36',
        336: 'GoalieStick 37',
        337: 'GoalieStick 38',
        338: 'GoalieStick 39',
        339: 'GoalieStick 40',
    },
    'pads': {
        11: 'VAUGHN Velocity Iceberg',
        19: 'VAUGHN Velocity V3',
        25: 'VAUGHN Pulse',
        26: 'VAUGHN 7700',
        34: "BRIAN'S Beast",
        36: 'KOHO 700',
        38: 'VAUGHN V4',
        46: 'VAUGHN VINTAGE',
        49: 'VAUGHN Vision',
        59: "BRIAN'S H Series",
        60: 'VAUGHN 7800',
        61: 'VAUGHN 7800 Diamond',
        62: 'VAUGHN 7990',
        64: 'KOHO 588',
        65: 'CCM Extreme Flex pro',
        66: "BRIAN'S G-Netik",
        67: "BRIAN'S Vintage",
        69: 'VAUGHN Ventus LT90',
        70: 'WARRIOR Ritual G2',
        74: 'WARRIOR Ritual G2 Euro',
        75: 'CCM Retro Flex',
        78: "BRIAN'S Sub-Zero II",
        79: 'VAUGHN V6',
        80: 'CCM Extreme Flex II Pro',
        81: "BRIAN'S G-Netik 2",
        83: 'KOHO Revolution 587',
        85: 'VAUGHN Ventus LT98',
        86: 'VAUGHN Vintage Sock',
        87: 'CCM GP Premier',
        88: "BRIAN'S SubZero Pro 3",
        89: 'CCM Extreme Flex III Pro',
        90: 'WARRIOR G3',
        91: 'WARRIOR Classic',
        94: "BRIAN'S G-Netik 3",
        95: 'Vaughn V7',
        96: 'Vaughn Pro V Elite',
        97: 'Vaughn SLR',
        98: 'Warrior Ritual GT',
        99: 'Warrior Ritual GT Classic',
        100: 'Bauer Supreme 2S Pro',
        101: 'CCM Premier 2',
        102: "Brian's Optik",
        103: 'Vaughn VE8',
        104: 'Warrior Ritual G4 Protective',
        105: 'CCM Extreme Flex 4 Pro',
        106: 'Bauer Vapor 2X Pro',
        300: 'King of Crimson',
        301: 'Blue Wreck',
        302: 'Blue-lin Wall',
        303: 'Green Ruin',
        304: 'Slickness',
        305: 'Righteous Hazard',
    },
    'blocker': {
        11: 'VAUGHN Velocity Iceberg',
        19: 'VAUGHN Velocity V3',
        25: 'VAUGHN Pulse',
        26: 'VAUGHN 7700',
        34: "BRIAN'S Beast",
        36: 'KOHO 700',
        38: 'VAUGHN V4',
        46: 'VAUGHN VINTAGE',
        49: 'VAUGHN Vision',
        52: 'VAUGHN V4 7600',
        59: "BRIAN'S H Series",
        60: 'VAUGHN 7800',
        61: 'VAUGHN 7800 Diamond',
        62: 'VAUGHN 7990',
        64: 'KOHO 588',
        65: 'CCM Extreme Flex pro',
        66: "BRIAN'S G-Netik",
        67: "BRIAN'S Vintage",
        69: 'VAUGHN Ventus LT90',
        70: 'WARRIOR Ritual G2',
        74: 'WARRIOR Ritual G2 Euro',
        75: 'CCM Retro Flex',
        78: "BRIAN'S Sub-Zero II",
        79: 'VAUGHN V6',
        80: 'CCM Extreme Flex II Pro',
        81: "BRIAN'S G-Netik 2",
        83: 'KOHO Revolution 587',
        85: 'VAUGHN Ventus LT98',
        86: 'VAUGHN Vintage Sock',
        87: 'CCM GP Premier',
        88: "BRIAN'S SubZero Pro 3",
        89: 'CCM Extreme Flex III Pro',
        90: 'WARRIOR G3',
        91: 'WARRIOR Classic',
        94: "BRIAN'S G-Netik 3",
        95: 'Vaughn V7',
        96: 'Vaughn Pro V Elite',
        97: 'Vaughn SLR',
        98: 'Warrior Ritual GT',
        99: 'Warrior Ritual GT Classic',
        100: 'Bauer Supreme 2S Pro',
        101: 'CCM Premier 2',
        102: "Brian's Optik",
        103: 'Vaughn VE8',
        104: 'Warrior Ritual G4 Protective',
        105: 'CCM Extreme Flex 4 Pro',
        106: 'Bauer Vapor 2X Pro',
        300: 'King of Crimson',
        301: 'Blue Wreck',
        302: 'Blue-lin Wall',
        303: 'Green Ruin',
        304: 'Slickness',
        305: 'Righteous Hazard',
    },
    'trapper': {
        11: 'VAUGHN Velocity Iceberg',
        19: 'VAUGHN Velocity V3',
        25: 'VAUGHN Pulse',
        26: 'VAUGHN 7700',
        34: "BRIAN'S Beast",
        36: 'KOHO 700',
        38: 'VAUGHN V4',
        49: 'VAUGHN Vision',
        59: "BRIAN'S H Series",
        60: 'VAUGHN 7800',
        62: 'VAUGHN 7990',
        64: 'KOHO 588',
        65: 'CCM Extreme Flex pro',
        66: "BRIAN'S G-Netik",
        67: "BRIAN'S Vintage",
        69: 'VAUGHN Ventus LT90',
        70: 'WARRIOR Ritual G2',
        74: 'WARRIOR Ritual G2 Euro',
        75: 'CCM Retro Flex',
        78: "BRIAN'S Sub-Zero II",
        79: 'VAUGHN V6',
        80: 'CCM Extreme Flex II Pro',
        81: "BRIAN'S G-Netik 2",
        83: 'KOHO Revolution 587',
        85: 'VAUGHN Ventus LT98',
        86: 'VAUGHN Vintage Sock',
        87: 'CCM GP Premier',
        88: "BRIAN'S SubZero Pro 3",
        89: 'CCM Extreme Flex III Pro',
        90: 'WARRIOR G3',
        91: 'WARRIOR Classic',
        94: "BRIAN'S G-Netik 3",
        95: 'Vaughn V7',
        96: 'Vaughn Pro V Elite',
        97: 'Vaughn SLR',
        98: 'Warrior Ritual GT',
        99: 'Warrior Ritual GT Classic',
        100: 'Bauer Supreme 2S Pro',
        101: 'CCM Premier 2',
        102: "Brian's Optik",
        103: 'Vaughn VE8',
        104: 'Warrior Ritual G4 Protective',
        105: 'CCM Extreme Flex 4 Pro',
        106: 'Bauer Vapor 2X Pro',
        300: 'King of Crimson',
        301: 'Blue Wreck',
        302: 'Blue-lin Wall',
        303: 'Green Ruin',
        304: 'Slickness',
        305: 'Righteous Hazard',
    },
    'visor': {
        0: 'Straight BAUER',
        1: 'Curved BAUER',
        2: 'None',
        3: 'Aviator',
        4: 'Large',
        5: 'Tilted',
        6: 'High Tilted',
    },
    'visor_tint': {
        0: 'Clear',
        1: 'Grey',
        2: 'Yellow',
        3: 'Orange',
        4: 'Green',
        5: 'Light Blue',
        6: 'Blue',
        7: 'Red',
        8: 'Purple',
        9: 'Pink',
        10: 'White',
        11: 'Sky',
        12: 'Sunburst',
        13: 'Aqua',
        14: 'Haze',
    },
    'jersey_tuck': {
        0: 'None',
        1: 'Left Tuck',
        2: 'Right Tuck',
        3: 'Full Tuck',
    },
    'sock_tuck': {
        0: 'Full',
        1: 'None',
        2: 'Front',
        3: 'Back',
    },
    'pant_length': {
        0: 'Short',
        1: 'Long',
    },
    'neck': {
        0: 'Off',
        1: 'On',
    },
}
STICK_BRAND = {
    35: 'titan',
    36: 'sherwood',
    84: 'warrior',
    86: 'ccm',
    87: 'ccm',
    98: 'warrior',
    99: 'ccm',
    102: 'ccm',
    103: 'ccm',
    107: 'stx',
    109: 'sherwood',
    110: 'stx',
    112: 'ccm',
    113: 'stx',
    114: 'sherwood',
    115: 'ccm',
    116: 'ccm',
    117: 'ccm',
    118: 'warrior',
    123: 'ccm',
    124: 'ccm',
    125: 'ccm',
    126: 'sherwood',
    127: 'stx',
    128: 'warrior',
    130: 'bauer',
    131: 'truehockey',
    132: 'truehockey',
    133: 'truehockey',
    134: 'warrior',
    135: 'warrior',
    136: 'ccm',
    137: 'ccm',
    138: 'ccm',
    139: 'bauer',
    140: 'bauer',
    141: 'stx',
    300: 'textured',
    301: 'textured',
    302: 'textured',
    303: 'textured',
    304: 'textured',
    305: 'textured',
    306: 'textured',
    307: 'textured',
    308: 'textured',
    309: 'textured',
    310: 'textured',
    311: 'textured',
    312: 'textured',
    313: 'textured',
    314: 'textured',
    315: 'textured',
    316: 'textured',
    317: 'textured',
    318: 'textured',
    319: 'textured',
    320: 'textured',
    321: 'textured',
    322: 'textured',
    323: 'textured',
    324: 'textured',
    325: 'textured',
    326: 'textured',
    327: 'textured',
    328: 'textured',
    329: 'textured',
    330: 'textured',
    331: 'textured',
    332: 'textured',
    333: 'textured',
    334: 'textured',
    335: 'textured',
    336: 'textured',
    337: 'textured',
    338: 'textured',
    339: 'textured',
    340: 'textured',
    341: 'textured',
    342: 'textured',
    343: 'textured',
    344: 'textured',
    345: 'textured',
    346: 'textured',
    347: 'textured',
    348: 'textured',
    349: 'textured',
}
STICK_COLOURS = {
    35: ((1, 0.095), (36, 0.022)),
    36: ((34, 0.034),),
    84: ((14, 0.058), (194, 0.057)),
    86: ((358, 0.487),),
    87: ((53, 0.057),),
    98: (),
    99: ((59, 0.103),),
    102: ((3, 0.714),),
    103: ((74, 0.043),),
    107: ((196, 0.047),),
    109: ((16, 0.137),),
    110: ((354, 0.182),),
    112: (),
    113: (),
    114: ((41, 0.041),),
    115: ((57, 0.064),),
    116: ((349, 0.033),),
    117: (),
    118: ((13, 0.052), (197, 0.039)),
    123: ((357, 0.105),),
    124: (),
    125: ((59, 0.03),),
    126: (),
    127: ((2, 0.111),),
    128: ((59, 0.031),),
    130: ((3, 0.088),),
    131: (),
    132: ((194, 0.03),),
    133: ((195, 0.059),),
    134: ((193, 0.09), (357, 0.084)),
    135: ((358, 0.063),),
    136: ((356, 0.053),),
    137: (),
    138: ((51, 0.021),),
    139: ((206, 0.044),),
    140: ((52, 0.029),),
    141: (),
    300: ((35, 0.06),),
    301: ((216, 0.046),),
    302: ((79, 0.155),),
    303: ((28, 0.207),),
    304: ((0, 0.176),),
    305: (),
    306: ((32, 0.038),),
    307: (),
    308: ((42, 0.173),),
    309: ((0, 0.021),),
    310: ((190, 0.036),),
    311: ((7, 0.186),),
    312: ((131, 0.636), (174, 0.066)),
    313: ((59, 0.237),),
    314: ((230, 0.262),),
    315: ((161, 0.094), (70, 0.075)),
    316: ((32, 0.147), (147, 0.057), (235, 0.031)),
    317: ((192, 0.081),),
    318: ((88, 0.135), (194, 0.074)),
    319: ((0, 0.041), (223, 0.02)),
    320: ((127, 0.023),),
    321: ((244, 0.169), (59, 0.056), (359, 0.039)),
    322: ((305, 0.047), (197, 0.036)),
    323: ((45, 0.175),),
    324: ((236, 0.095),),
    325: ((219, 0.096), (270, 0.034)),
    326: ((275, 0.273),),
    327: ((0, 0.191),),
    328: ((238, 0.118),),
    329: ((112, 0.15),),
    330: ((288, 0.046),),
    331: ((0, 0.197),),
    332: ((1, 0.133),),
    333: ((40, 0.132), (359, 0.082)),
    334: ((47, 0.276),),
    335: ((0, 0.071),),
    336: ((199, 0.299),),
    337: (),
    338: ((44, 0.049),),
    339: (),
    340: ((75, 0.042),),
    341: ((291, 0.057),),
    342: ((0, 0.044),),
    343: ((41, 0.054),),
    344: (),
    345: ((182, 0.397),),
    346: ((95, 0.069), (208, 0.044)),
    347: ((161, 0.025),),
    348: ((359, 0.509),),
    349: ((0, 0.215),),
}
CURRENT = frozenset({35, 36, 84, 86, 87, 98, 99, 102, 103, 107, 109, 110, 112, 113, 114, 115, 116, 117, 118, 123, 124, 125, 127, 128, 130, 131, 132, 134, 135, 136, 137, 138, 139, 140, 300, 301, 305, 337, 342, 349})
DEFAULT = 139
# --- end of the made tables ---


# --- player gear -------------------------------------------------------------------------------------------------
def kind_of(position):
    return 'goalie' if position == GOALIE else 'skater'


def row_of(db, game_id, kind='skater'):
    """The player's row of his equipment table, or None."""
    t = db[KINDS[kind][0]]
    return next((i for i in range(t.count) if t.get(i, 'game_id') == game_id), None)


def read(db, row, kind='skater'):
    """{choice: number} of one row."""
    table, choices = KINDS[kind]
    return {c: db[table].get(row, f) for c, (f, _l, _n) in choices.items()}


def clean(db, values, kind='skater'):
    """(the choices that can be written, problems): whole numbers the table's fields hold; a model the game's Creation
    Zone does not list is a problem unless it is a colour or a mask."""
    table, choices = KINDS[kind]
    ok, problems = {}, []
    for choice, v in (values or {}).items():
        if choice not in choices:
            problems.append(f'unknown equipment choice {choice}')
            continue
        field, label, names = choices[choice]
        try:
            n = int(v)
        except (TypeError, ValueError):
            problems.append(f'{label}: {v!r} is not a number')
            continue
        meta = db[table].by_name[field]
        if not meta.low <= n <= meta.low + (1 << meta.depth) - 1:
            problems.append(f'{label}: {n} is outside what the game can hold')
            continue
        if names and NAMES.get(names) and n not in NAMES[names]:
            problems.append(f'{label}: the game has no model {n}')
            continue
        ok[choice] = n
    return ok, problems


def write(db, row, values, kind='skater', setter=None):
    """Write cleaned choices to a row; returns how many values changed."""
    table, choices = KINDS[kind]
    set_ = setter or (lambda t, r, f, v: db[t].set(r, f, v))
    changed = 0
    for choice, n in values.items():
        field = choices[choice][0]
        if db[table].get(row, field) != n:
            set_(table, row, field, n)
            changed += 1
    return changed


def options(kind, choice, current=None):
    """[(number, label)] the editor offers for a model choice (its current value too, when the game lists no such
    model)."""
    names = NAMES.get(KINDS[kind][1][choice][2] or '', {})
    out = sorted(names.items(), key=lambda kv: (kv[1].lower(), kv[0]))
    if current is not None and current not in names:
        out.insert(0, (current, f'Model {current}'))
    return [(n, label) for n, label in out]


def model_problems(db, also=None):
    """Models the game's Creation Zone does not list, one line per model. `also`: {(kind, choice): models} to accept
    anyway (`worn(default roster)`: what the game's own roster carries)."""
    count = {}
    for kind, (table, choices) in KINDS.items():
        t = db[table]
        for choice, (field, label, names) in choices.items():
            if not names or not NAMES.get(names):
                continue
            accept = (also or {}).get((kind, choice), ())
            for i in range(t.count):
                n = t.get(i, field)
                if n not in NAMES[names] and n not in accept:
                    count[(kind, label, n)] = count.get((kind, label, n), 0) + 1
    return [f"{c} {kind} row(s) have {label.lower()} model {n}, which the game does not list"
            for (kind, label, n), c in sorted(count.items())]


def worn(db):
    """{(kind, choice): models} a roster's rows carry."""
    out = {}
    for kind, (table, choices) in KINDS.items():
        t = db[table]
        for choice, (field, _label, names) in choices.items():
            if names:
                out[(kind, choice)] = {t.get(i, field) for i in range(t.count)}
    return out


# --- team gear -----------------------------------------------------------------------------------------------------
def gear_rows(db, team, table=STOCK, categories=None):
    """Rows of a team's gear (all categories, or those named)."""
    t = db[table]
    return [i for i in range(t.count) if t.get(i, 'team') == team
            and (categories is None or t.get(i, 'equipment') in categories)]


def palette(db, team, table=STOCK, categories=GEAR):
    """[(0xRRGGBB, zones)] of a team's gear, the most used first."""
    t, count = db[table], {}
    for i in gear_rows(db, team, table, categories):
        for z in ZONES:
            c = t.get(i, z)
            count[c] = count.get(c, 0) + 1
    return sorted(count.items(), key=lambda kv: (-kv[1], kv[0]))


def team_colours(db, team):
    """[primary, secondary, tertiary] 0xRRGGBB of a team (exhibitionteams), [] when it has no record."""
    T = db[TEAMS]
    row = next((i for i in range(T.count) if T.get(i, 'index') == team), None)
    return [] if row is None else [T.get(row, f) for f in TEAM_COLOURS]


def rgb(c):
    return (c >> 16) & 255, (c >> 8) & 255, c & 255


def hue_of(c):
    """The hue (degrees) of a colour 0xRRGGBB, or None for black, white, grey and silver."""
    h, s, v = colorsys.rgb_to_hsv(*(x / 255 for x in rgb(c)))
    return round(h * 360) % 360 if s >= 0.40 and v >= 0.20 else None


def _apart(a, b):
    return min((a - b) % 360, (b - a) % 360)


def proposal(db, team, new, old, table=STOCK, categories=GEAR):
    """{gear colour: new colour} that moves a team's gear from its old colours to `new` (both [primary, secondary,
    tertiary] 0xRRGGBB; `old` usually the game's default roster's, `new` the team's now: Utah in Arizona's slot).
    The gear's colours other than black, white and grey are grouped by hue, the most used group first: a group with
    the hue of an old colour that changed takes the new colour of the same rank; a group no old colour has takes a new
    colour not used yet (black, white and grey ones last); black, white and grey gear stays. Empty when nothing
    changed."""
    new, old = list(new), list(old)
    if new == old or not new:
        return {}
    groups = []  # [hue, [colours], zones]
    for c, n in palette(db, team, table, categories):
        h = hue_of(c)
        if h is None:
            continue
        g = next((g for g in groups if _apart(g[0], h) <= NEAR), None)
        if g is None:
            groups.append([h, [c], n])
        else:
            g[1].append(c)
            g[2] += n
    groups.sort(key=lambda g: -g[2])
    used, out, later = set(), {}, []
    for h, cs, _n in groups:
        k = next((k for k, c in enumerate(old) if k < len(new) and hue_of(c) is not None
                  and _apart(hue_of(c), h) <= NEAR), None)
        if k is None:
            later.append(cs)
            continue
        used.add(new[k])
        if new[k] != old[k]:
            out.update({c: new[k] for c in cs})
    free = sorted((c for c in new if c not in used), key=lambda c: hue_of(c) is None)
    for cs, c in zip(later, free):
        out.update({x: c for x in cs})
    return out


def recolour(db, team, mapping, table=STOCK, categories=GEAR, setter=None):
    """Replace colours (mapping {old: new}) in every zone of a team's gear rows; returns the number of zones changed."""
    t = db[table]
    set_ = setter or (lambda tb, r, f, v: db[tb].set(r, f, v))
    n = 0
    for i in gear_rows(db, team, table, categories):
        for z in ZONES:
            c = t.get(i, z)
            if c in mapping and mapping[c] != c:
                set_(table, i, z, int(mapping[c]))
                n += 1
    return n


def copy_gear(db, src, dst, table=STOCK, categories=GEAR):
    """Give team `dst` the gear rows of team `src` (its own rows of those categories go). Changes the number of
    records: run it where the whole table is kept for Undo (RosterSession.bulk). Returns the number of rows given."""
    t = db[table]
    for i in sorted(gear_rows(db, dst, table, categories), reverse=True):
        t.delete(i)
    rows = gear_rows(db, src, table, categories)
    top = max((t.get(i, 'index') for i in range(t.count)), default=-1)
    for k, i in enumerate(rows):
        new = t.append(like=i)
        t.set(new, 'team', dst)
        t.set(new, 'index', top + 1 + k)
    return len(rows)


# --- sticks --------------------------------------------------------------------------------------------------------
def stick_colours(stick):
    """[(hue, share)] of the stick's own colours (covering CLEAR or more of its picture)."""
    return [(h, s) for h, s in STICK_COLOURS.get(stick, ()) if s >= CLEAR]


def fits(stick, hues):
    """Every colour of the stick is near one of the team's hues (a plain stick fits every team)."""
    return all(any(_apart(h, t) <= NEAR for t in hues) for h, _s in stick_colours(stick))


def pick(stick, hues):
    """The stick a player of a team with these hues gets instead of `stick`: the same brand's in a team colour (one
    the game's own roster uses first, the closest hue first), else its plain one, else DEFAULT."""
    brand = STICK_BRAND.get(stick)
    best = []
    for other in sorted(STICK_COLOURS):
        if other == stick or STICK_BRAND.get(other) != brand or not fits(other, hues):
            continue
        own = stick_colours(other)
        near = max(min(_apart(h, t) for t in hues) for h, _s in own) if own else 0
        best.append((0 if own else 1, other not in CURRENT, near, sum(s for _h, s in STICK_COLOURS[other]), other))
    return min(best)[-1] if best else DEFAULT


def team_hues(db, team):
    return [h for h in (hue_of(c) for c in team_colours(db, team)) if h is not None]


def team_sticks(db, teams, keep=(), setter=None, hues_of=None):
    """Give every skater of `teams` whose stick shows a colour his team does not wear a stick that fits (`pick`).
    `keep`: game ids to leave alone (their own choice); `hues_of(team)` -> hues (default: the team's colours).
    Returns [(team, game_id, old, new)] in roster order; a second run changes nothing."""
    hues_of = hues_of or (lambda team: team_hues(db, team))
    P, B, R, E = db[PLAYERS], db[BIOS], db[ROSTER], db[SKATER_TABLE]
    gid_of = {P.get(i, 'index'): P.get(i, 'playerid') for i in range(P.count) if P.get(i, 'table') == 0}
    pos = {B.get(i, 'game_id'): B.get(i, 'position') for i in range(B.count)}
    erow = {E.get(i, 'game_id'): i for i in range(E.count)}
    set_ = setter or (lambda t, r, f, v: db[t].set(r, f, v))
    teams, cache, seen, out = set(teams), {}, set(keep), []
    for i in range(R.count):
        team = R.get(i, 'team')
        if team not in teams:
            continue
        gid = gid_of.get(R.get(i, 'playerindex'))
        if gid is None or gid in seen or pos.get(gid) == GOALIE or gid not in erow:
            continue
        seen.add(gid)
        if team not in cache:
            cache[team] = hues_of(team)
        old = E.get(erow[gid], 'stick')
        if not cache[team] or old not in STICK_COLOURS or fits(old, cache[team]):
            continue
        new = pick(old, cache[team])
        if new != old:
            set_(SKATER_TABLE, erow[gid], 'stick', new)
            out.append((team, gid, old, new))
    return out
