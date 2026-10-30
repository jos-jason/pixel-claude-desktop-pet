#!/usr/bin/env python3
"""Pixel Claude: a tiny orange buddy who lives along the bottom of the screen.

Left-click to pet him, drag to pick him up, right-click for a menu.
Launching the app again while he's running sends him off to bed (quits).

He loosely follows what Claude Code is doing: the claude-hook script (run from
Claude Code hooks) leaves one status file per session in $XDG_RUNTIME_DIR/pixel-claude.
"""
import bisect
import datetime
import json
import math
import os
import random
import re
import signal
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, GLib, GLibUnix, Graphene, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LS  # noqa: E402

CELL = 6            # logical px per sprite pixel
GW, GH = 30, 22     # window size in cells (wide enough for the Omarchy wordmark)
GROUND = GH - 1     # feet rest here; the last cell holds his shadow
FPS = 30


def rgba(hexstr, alpha=1.0):
    c = Gdk.RGBA()
    c.parse(hexstr)
    c.alpha = alpha
    return c


BODY = rgba("#CB7B5D")
EYE = rgba("#1B1310")
SHADOW = rgba("#000000", 0.18)
OUTLINE = rgba("#2A1D18", 0.75)
BUBBLE = rgba("#FFF8F0")
BUBBLE_EDGE = rgba("#3A2A24")
LID = rgba("#9AA0A8")
LID_HI = rgba("#B8BEC6")
LAPTOP_BASE = rgba("#6E747C")
CRATE = rgba("#C08F5A")
CRATE_D = rgba("#8A6136")
HANDLE = rgba("#8B5A2B")
BRISTLE = rgba("#E3B04B")
BRISTLE_D = rgba("#B88A2E")
CODE = [rgba("#CB7B5D"), rgba("#5FB3B3"), rgba("#B48EAD"), rgba("#99C794")]
BOOK = rgba("#5B6EAE")
PAGE = rgba("#FBF6EC")
INK = rgba("#B9B0A4")
MUG = rgba("#F2EEE8")
COFFEE = rgba("#5A3A28")
BODY_D = rgba("#B4664A")  # his far side, when he turns side-on

PALETTE = {
    "w": "#FFFFFF", "r": "#E5484D", "R": "#FF8A8E", "y": "#FFD34D",
    "g": "#8A8F98", "k": "#2A1D18", "o": "#CB7B5D", "G": "#46B979",
    "D": "#2E8B57", "b": "#8A6136", "L": "#8BD17C", "C": "#6FB7E8", "s": "#B7BCC4",
    "O": "#F08A24", "Q": "#C4621A", "P": "#F7A8C4", "T": "#E0A85A", "W": "#F3F7FB",
    "S": "#C9D3DE", "F": "#FFF2A8", "V": "#5B3A7A", "M": "#90D05A", "N": "#3B4F8C",
}
COL = {k: rgba(v) for k, v in PALETTE.items()}

# Tiny pixel glyphs. Each char maps to a PALETTE color; '.' is empty.
GLYPHS = {
    "z": ["wwww", "..w.", ".w..", "wwww"],
    "Z": ["wwwww", "...w.", "..w..", ".w...", "wwwww"],
    "heart": [".rr.rr.", "rRrrrrr", "rrrrrrr", ".rrrrr.", "..rrr..", "...r..."],
    "note": ["..ww.", "..w.w", "..w..", "www..", "www.."],
    "bang": ["y", "y", "y", ".", "y"],
    "q": ["www", "..w", ".ww", "...", ".w."],
    "ask": ["kkk", "..k", ".kk", "...", ".k."],
    "spark": [".y.", "yyy", ".y."],
    "bulb": [".yyy.", "yywyy", "yyyyy", "yyyyy", ".yyy.", ".ggg.", "..g.."],
    "check": ["....G", "...GG", "G.GG.", "GGG..", ".G..."],
    # daydreams about getting outside
    "tree": [
        "....GGGG....",
        "..GGGDGGGG..",
        ".GGDGGGGDGG.",
        "GGGGGGDGGGGG",
        ".GGGDGGGGGG.",
        "GGGGGGGGDGGG",
        ".GGDGGGGGGG.",
        "..GGGGGGGG..",
        ".....bb.....",
        ".....bb.....",
        "..LLLLLLLL..",
    ],
    "trail": [
        "..........yy....",
        "....ww....yy....",
        "...wwss.........",
        "..ssssss..ws....",
        ".sssbssss.sss...",
        "ssssssbssssssss.",
        "sssssbssssssssss",
        "GGGGbGGGDGGGGDGG",
        "GGGbGGGGGGGGGGGG",
        "GGbGGGGGGGGGGGGG",
    ],
    "binoculars": [
        ".kkk....kkk.",
        ".kgk....kgk.",
        "kkkkkkkkkkkk",
        "kkkkk..kkkkk",
        "kCCCk..kCCCk",
        "kCwCk..kCwCk",
        "kCCCk..kCCCk",
        ".kkk....kkk.",
    ],
    # the Omarchy icon (/usr/share/omarchy/icon.png), one cell per stroke width
    "omarchy": [
        "MMMMMMMMMMMMMMM",
        "MwwwwwwMwwwwwwM",
        "MwMMMMMMwwwMMwM",
        "MwMwwwwwwwwwMwM",
        "MwMwwwwwwwwwMwM",
        "MwMwwwwwwwwwMwM",
        "MwMwwwwwwwwwMwM",
        "MMMwwwwwwwwwMwM",
        "MwMwwwwwwwwwMwM",
        "MwMwwwwwwwwwMwM",
        "MwMwwwwwwwwwMwM",
        "MwMwwwwwwwwwMwM",
        "MwMMMMMMMMMMMwM",
        "MwwwwwwMwwwwwwM",
        "MMMMMMMMwMMMMMM",
    ],
    "clover": [".L.L.", "LLLLL", ".LLL.", "..D..", ".D..."],
    "bat": ["V.....V", "VV.V.VV", "VVVVVVV", ".V...V."],
    "flake": [".w.", "www", ".w."],
}
DREAMS = ["tree", "trail", "binoculars"]

# The Omarchy wordmark, exactly as /usr/share/omarchy/logo.txt draws it in half blocks.
LOGO_TXT = [
    '                 ▄▄▄',
    ' ▄█████▄    ▄███████████▄    ▄███████   ▄███████   ▄███████   ▄█   █▄    ▄█   █▄',
    '███   ███  ███   ███   ███  ███   ███  ███   ███  ███   ███  ███   ███  ███   ███',
    '███   ███  ███   ███   ███  ███   ███  ███   ███  ███   █▀   ███   ███  ███   ███',
    '███   ███  ███   ███   ███ ▄███▄▄▄███ ▄███▄▄▄██▀  ███       ▄███▄▄▄███▄ ███▄▄▄███',
    '███   ███  ███   ███   ███ ▀███▀▀▀███ ▀███▀▀▀▀    ███      ▀▀███▀▀▀███  ▀▀▀▀▀▀███',
    '███   ███  ███   ███   ███  ███   ███ ██████████  ███   █▄   ███   ███  ▄██   ███',
    '███   ███  ███   ███   ███  ███   ███  ███   ███  ███   ███  ███   ███  ███   ███',
    ' ▀█████▀    ▀█   ███   █▀   ███   █▀   ███   ███  ███████▀   ███   █▀    ▀█████▀',
    '                                       ███   █▀',
]


def _logo_pixels(lines):
    halves = {" ": "..", "\u2588": "xx", "\u2580": "x.", "\u2584": ".x"}
    w = max(map(len, lines))
    rows = []
    for line in lines:
        cells = [halves.get(ch, "..") for ch in line.ljust(w)]
        rows += ["".join(c[0] for c in cells), "".join(c[1] for c in cells)]
    return [r for r in rows if "x" in r]


LOGO = _logo_pixels(LOGO_TXT)
# Color schemes for the wordmark: (bubble background, letter colors left to right).
LOGO_SCHEMES = [
    ("#121212", ["#9ECE6A"]),               # terminal green, like omarchy-show-logo
    ("#1A1B26", ["#7AA2F7"]),               # Tokyo Night
    ("#1E1E2E", ["#F38BA8", "#FAB387", "#F9E2AF", "#A6E3A1", "#94E2D5", "#89B4FA", "#CBA6F7"]),  # Catppuccin rainbow
    ("#282828", ["#D8A657"]),               # Gruvbox
    ("#121212", ["#E68E0D"]),               # Matte Black
    ("#FAF4ED", ["#56949F"]),               # Rosé Pine
]
THEME_COLORS = os.path.expanduser("~/.local/state/omarchy/current/theme/colors.toml")


def current_theme_scheme():
    """The running Omarchy theme's background and accent, if it can be read."""
    try:
        with open(THEME_COLORS) as f:
            colors = dict(re.findall(r'^(\w+)\s*=\s*"(#[0-9A-Fa-f]{6})"', f.read(), re.M))
        return colors["background"], [colors["accent"]]
    except (OSError, KeyError):
        return None

# Props and costumes for the seasonal acts, drawn at half-cell pixels.
SPRITES = {
    "santa": [
        ".............ww...",
        "..........rrrww...",
        "........rrrrrr....",
        "......rrrrrrrr....",
        "....rrrrrrrrrr....",
        "...rrrrrrrrrrrr...",
        ".wwwwwwwwwwwwwwww.",
        ".wwwwwwwwwwwwwwww.",
    ],
    "party": [
        "....yy....",
        "....yy....",
        "....RR....",
        "...RRRR...",
        "...CCCC...",
        "..CCyCCC..",
        "..RRRRRR..",
        ".RRRRyRRR.",
        ".CCCCCCCC.",
        "CCyCCCCyCC",
    ],
    "tophat": [
        "...GGGGGGGGGGGG...",
        "...GGGGGGGGGGGG...",
        "...GGGGGGGGGGGG...",
        "...kkkkyyyykkkk...",
        "...kkkkyGGykkkk...",
        "...kkkkyyyykkkk...",
        "...GGGGGGGGGGGG...",
        "DDDDDDDDDDDDDDDDDD",
    ],
    "ear": [".ww.", "wwww", "wPPw", "wPPw", "wPPw", "wPPw", "wPPw", "wwww", ".ww."],
    "glasses": ["kkkkkkkkkkkkkkkk", ".kwkkk....kwkkk.", "..kkk......kkk.."],
    "bigheart": [
        "..rrr....rrr..",
        ".rRRrr..rrrrr.",
        "rRRrrrrrrrrrrr",
        "rRrrrrrrrrrrrr",
        "rrrrrrrrrrrrrr",
        ".rrrrrrrrrrrr.",
        "..rrrrrrrrrr..",
        "...rrrrrrrr...",
        "....rrrrrr....",
        ".....rrrr.....",
        "......rr......",
    ],
    "pumpkin": [
        "......DD......",
        "...OOOQQOOO...",
        ".OOOOOQQOOOOO.",
        "OOOyOOQQOOyOOO",
        "OOyyyOQQOyyyOO",
        "OOOOOOQQOOOOOO",
        "OOyOyyyyyyOyOO",
        "OOOyyQyyQyyOOO",
        ".OOOOOQQOOOOO.",
        "...OOOQQOOO...",
    ],
    "gift": [
        "...rr..rr...",
        "....rrrr....",
        "GGGGGrrGGGGG",
        "GGGGGrrGGGGG",
        "rrrrrrrrrrrr",
        "GGGGGrrGGGGG",
        "GGGGGrrGGGGG",
        "GGGGGrrGGGGG",
        "GGGGGrrGGGGG",
    ],
    "pie": [
        "..TTTTTTTTTT..",
        ".TOOOOOOOOOOT.",
        "TOOwwOOOOOOOOT",
        "TTTTTTTTTTTTTT",
        "ssssssssssssss",
        ".ssssssssssss.",
    ],
    "egg": [".PP.", "PPPP", "CCCC", "PPPP", "yyyy", ".PP."],
    "cone": [".RR.", "RRRR", "RRRR", "TTTT", "TbTT", ".TT.", ".TT.", ".T.."],
    "can": [
        ".sss......",
        "s...s.....",
        "CCCCCC...s",
        "CCCCCCC.ss",
        "CCCCCCCss.",
        "CCCCCC....",
        "CCCCCC....",
    ],
    "sprout": [".L.L.", "..L..", "..D.."],
    "seedling": [".L...", "..L.L", "..LL.", "..D..", "..D.."],
    "flower": [".PPP.", "PPyPP", ".PPP.", "L.D..", ".LD.L", "..D.."],
    "snowman": [
        "...WWWW...",
        "..WkWWkW..",
        "..WWWWOOO.",
        "...WWWW...",
        "..WWWWWW..",
        ".WWWkWWWS.",
        ".WWWkWWWS.",
        "..WWWWWS..",
        ".WWWWWWWS.",
        "WWWWWWWWWS",
        "WWWWWWWWWS",
        ".WWWWWWWS.",
    ],
}
FIREWORKS = {"newyear": ["#FFD34D", "#FF8A8E", "#6FB7E8", "#8BD17C", "#FFFFFF"],
             "fireworks": ["#E5484D", "#FFFFFF", "#6FB7E8"]}
LEAVES = ["#F08A24", "#D9534F", "#F2C14E", "#C4621A"]

# The four acts from Claude's own mascot clips (explore, flag, stomp, gym), with timings
# from Ayotomiwa Wale-Durojaye's frame-by-frame GSAP rebuild of them (Codrops, May 2026).


def ease_out(k):     # GSAP power2.out
    return 1 - (1 - k) ** 3


def ease_in(k):      # power3.in
    return k ** 4


def ease_inout(k):   # power1.inOut
    return 2 * k * k if k < 0.5 else 1 - (2 - 2 * k) ** 2 / 2


def sine_out(k):
    return math.sin(k * math.pi / 2)


def tween(t, t0, dur, ease=None):
    """Progress 0..1 through [t0, t0 + dur], optionally eased."""
    k = min(1.0, max(0.0, (t - t0) / dur))
    return ease(k) if ease else k


# explore: lean back to look, lean ahead, leap, walk on, peer down, turn and leap back
LOOK_BACK, LOOK_AHEAD, UPRIGHT = 0.0, 1.0, 2.0
CROUCHES = (2.3, 5.8)  # a 0.1s crouch, then the leap
WALK_ON, PEER = 3.45, 5.0
EXPLORE_DUR = 7.8
LEAP_PX, LEAP_H, WALK_PX = 110, 7.0, 56


def leap_height(j):
    """Height in cells j seconds into a leap: sine.out up, a hang, power3.in down."""
    if j < 0.6:
        return LEAP_H * tween(j, 0, 0.42, sine_out)
    return LEAP_H * (1 - tween(j, 0.6, 0.2, ease_in))


# flag: 12 frames; the first 3 raise the limp flag, then 3-11 loop as it whips around the pole.
FLAG_FRAME = 0.1
HAND_PULL = [0, -0.25, -0.75, -0.75, -0.5, 0, 0, 0, -0.25, -0.5, -1, -1]  # hand meets the cloth
SWAY = [0, 0, -0.5, -0.5, 0, 0.5, 0.5, 0.5, 0, 0, -0.5, -0.5]           # body leans against it
BACK_DROP = [0, 0, 0.5, 0.5, 0, 0, 0, 0, 0, 0, 0.5, 0.5]                 # other hand dips
FLAG_SHAPES = [  # (first column from the pole, width, droop, wave phase), in half-cell pixels
    (0, 6, 1.0, None), (0, 9, 0.6, None), (0, 12, 0, 0.0),
    (-1, 6, 0.3, None),                                  # wrapping round the front of the pole
    (-9, 9, 0.6, None), (-12, 12, 0, 2.1), (-12, 12, 0, 4.2), (-6, 6, 0.3, None),
    (-2, 4, 1.2, None),                                  # wound round the pole
    (0, 6, 1.0, None), (0, 9, 0.7, None), (0, 12, 0, 1.0),
]
STAR = ["o.o.o", ".ooo.", "ooooo", ".ooo.", "o.o.o"]  # a Claude-ish spark on the cloth


def _flag_frame(x0, width, droop, ph):
    """(x0, cloth rows), with 2 spare rows on top for the wave's crests."""
    H = 7
    dist = [x if x >= 0 else -x - 1 for x in range(x0, x0 + width)]  # columns out from the pole
    if ph is None:
        offs = [round(droop * d) for d in dist]
    else:
        offs = [round(2.5 * d / 11 * math.sin(d / 11 * 1.5 * math.pi - ph)) for d in dist]
    by_d = dict(zip(dist, offs))
    mid = max(dist) // 2
    grid = [["."] * width for _ in range(H + 2 + max(offs))]
    for c, (d, off) in enumerate(zip(dist, offs)):
        shade = "S" if d and off > by_d[d - 1] else "w"
        for r in range(H):
            emblem = (width >= 9 and 0 <= r - 1 < 5 and 0 <= d - mid + 2 < 5
                      and STAR[r - 1][d - mid + 2] == "o")
            grid[r + off + 2][c] = "o" if emblem else shade
    return x0, ["".join(row) for row in grid]


FLAG_FRAMES = [_flag_frame(*f) for f in FLAG_SHAPES]

# stomp: 8 frames at 125ms of (tilt, bob, arms): crouch, then tip up onto one side with that
# corner thrown up as a hand, and the same the other way. Confetti leaves the raised corner.
STOMP_FRAME = 0.125
STOMP = [
    (0, 1, ["side", "side"]), (1, -0.5, ["side", "nub"]), (1.5, -1, ["side", "nub2"]),
    (1, -0.5, ["side", "nub"]), (0, 1, ["side", "side"]), (-1, -0.5, ["nub", "side"]),
    (-1.5, -1, ["nub2", "side"]), (-1, -0.5, ["nub", "side"]),
]
CONFETTI = ["#D97757", "#C46A8A", "#7A9FD4"]
CONFETTI_BITS = [[(0, 0)], [(0, 0), (0.5, 0)], [(0, 0), (0, 0.5)], [(0, 0), (0.5, 0.5)],
                 [(0, 0.5), (0.5, 0)]]

# gym: 36 frames of (bob, tilt, arms, sweatband, dumbbells in hand, eyes). Sweatband on, a
# stretch, alternating one-arm curls (frames 13-24 play twice), then the band comes off.
GYM_FRAMES = [
    (0, 0, ("side", "side"), None, False, "open"),
    (0, 0, ("low", "side"), None, False, "open"),
    (0, 0, ("low", "side"), "low", False, "open"),        # picks up the band
    (0, 0, ("side", "side"), "mid", False, "open"),
    (0, 0, ("nub", "side"), "up", False, "open"),
    (0, 0, ("nub", "nub"), "stretch", False, "open"),
    (0, 0, ("nub", "nub"), "on", False, "closed"),        # 6-7: snug it down
    (0, 0, ("nub", "nub"), "on", False, "closed"),
    (0, 0, ("nub", "nub"), "on", False, "open"),
    (0, 0, ("vee", "vee"), "on", False, "open"),
    (0, 0, ("vee", "vee"), "on", False, "happy"),
    (0, 0, ("side", "side"), "on", False, "wide"),
    (1, 0, ("low", "low"), "on", True, "open"),           # dumbbells in hand
    (0.5, 0.5, ("low", "mid"), "on", True, "open"),
    (0, 1, ("low", "nub"), "on", True, "closed"),
    (0, 1, ("low", "nub"), "on", True, "happy"),          # 15: held up
    (0, 1, ("low", "nub"), "on", True, "open"),
    (0.5, 0.5, ("low", "mid"), "on", True, "open"),
    (1, 0, ("low", "low"), "on", True, "open"),
    (0.5, -0.5, ("mid", "low"), "on", True, "open"),
    (0, -1, ("nub", "low"), "on", True, "closed"),
    (0, -1, ("nub", "low"), "on", True, "happy"),         # 21: held up
    (0, -1, ("nub", "low"), "on", True, "open"),
    (0.5, -0.5, ("mid", "low"), "on", True, "open"),
    (1, 0, ("low", "low"), "on", True, "open"),
    (0.5, 0, ("low", "low"), "on", True, "open"),
    (0, 0, ("none", "none"), "on", False, "open"),        # dumbbells put away
    (0, 0, ("low", "low"), "on", False, "open"),
    (0, 0, ("none", "none"), "on", False, "happy"),
    (0, 0, ("side", "side"), "on", False, "happy"),
    (0, 0, ("nub", "nub"), "stretch", False, "open"),     # band off
    (0, 0, ("nub", "side"), "up", False, "open"),
    (0, 0, ("side", "side"), "mid", False, "open"),
    (0, 0, ("low", "side"), "low", False, "open"),
    (0, 0, ("low", "side"), None, False, "open"),
    (0, 0, ("side", "side"), None, False, "happy"),
]
GYM_SEQ = list(range(25)) + list(range(13, 25)) + list(range(25, 36))
BAND = {  # loose sweatband: (rows, x, y), held by the back hand or stretched over his head
    "low": ([".NNNN.", "N....N", ".NNNN."], -7.5, 4.5),
    "mid": ([".NNNN.", "N....N", ".NNNN."], -7.5, 1.5),
    "up": ([".NNNN.", "N....N", ".NNNN."], -4.75, -3),
    "stretch": (["..NNNNNNNNNNNN..", ".N............N.", "NNNNNNNNNNNNNNNN"], -4, -1.5),
}
BELL = [".kk.", "kkkk", "kkkk", ".kk."]
BELLS = {  # a dumbbell in the front hand for each arm mode: (rows, x, y)
    "low": (BELL, 5.5, 2.75),
    "mid": (BELL, 4.5, -0.5),
    "nub": ([".kk....kk.", "kkkk..kkkk", "kkkkggkkkk", ".kk....kk."], 0.75, -3.5),
}


def _gym_hold(i, frame):
    if i == len(GYM_SEQ) - 1:
        return 1.5
    return {6: 0.27, 7: 0.27, 15: 0.4, 21: 0.4}.get(frame, 0.085)


GYM_STARTS = [0.0]
for _i, _f in enumerate(GYM_SEQ):
    GYM_STARTS.append(GYM_STARTS[-1] + _gym_hold(_i, _f))
GYM_DUR = GYM_STARTS.pop()

# sidetype: the side-on laptop GIF, 100ms frames: 11 to bring the laptop out, a 16-frame typing
# loop (1 = a key press), 6 to pack it away.
SIDETYPE_FRAME = 0.1
SIDETYPE_TAPS = "0100101000100100"

SEASON_EVERY = 40 * 60        # a seasonal act at most this often
HOLIDAY_EVERY = 15 * 60       # holiday acts in the days around a holiday
HOLIDAY_DAY_EVERY = 6 * 60    # and more often on the day itself


def today():
    """The date he celebrates; PIXEL_CLAUDE_DATE=2026-12-25 previews another day."""
    try:
        return datetime.date.fromisoformat(os.environ["PIXEL_CLAUDE_DATE"])
    except (KeyError, ValueError):
        return datetime.date.today()


def easter(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    n = h + l - 7 * m + 114
    return datetime.date(y, n // 31, n % 31 + 1)


def occasions(d):
    """(holiday acts, is it the day itself, season acts) for date d."""
    D, day = datetime.date, datetime.timedelta(days=1)
    y = d.year
    nov1 = D(y, 11, 1)
    thanks = nov1 + ((3 - nov1.weekday()) % 7 + 21) * day  # 4th Thursday of November
    holidays = [  # (first day, the day, last day, acts)
        (D(y, 1, 1), D(y, 1, 1), D(y, 1, 2), ["newyear"]),
        (D(y, 2, 10), D(y, 2, 14), D(y, 2, 14), ["valentine"]),
        (D(y, 3, 14), D(y, 3, 17), D(y, 3, 17), ["stpatrick"]),
        (easter(y) - 4 * day, easter(y), easter(y) + day, ["easter"]),
        (D(y, 7, 1), D(y, 7, 4), D(y, 7, 5), ["fireworks"]),
        (D(y, 10, 24), D(y, 10, 31), D(y, 10, 31), ["ghost", "pumpkin"]),
        (thanks - 3 * day, thanks, thanks + day, ["pie"]),
        (D(y, 12, 18), D(y, 12, 25), D(y, 12, 26), ["christmas"]),
        (D(y, 12, 31), D(y, 12, 31), D(y, 12, 31), ["newyear"]),
    ]
    acts, on_day = [], False
    for first, the_day, last, names in holidays:
        if first <= d <= last:
            acts += names
            on_day |= d == the_day
    md = (d.month, d.day)
    if (3, 20) <= md <= (6, 20):
        season = ["garden"]
    elif (6, 21) <= md <= (9, 22):
        season = ["icecream"]
    elif (9, 23) <= md <= (12, 20):
        season = ["leaves"]
    else:
        season = ["snowman"]
    return acts, on_day, season


class Particle:
    __slots__ = ("kind", "wx", "y", "vx", "vy", "life", "ttl", "size", "col", "grav")

    def __init__(self, kind, wx, y, vx, vy, ttl, size=0.5, col=None, grav=0.0):
        self.kind, self.wx, self.y, self.vx, self.vy = kind, wx, y, vx, vy
        self.life, self.ttl, self.size, self.col, self.grav = 0.0, ttl, size, col, grav


ACTIVITIES = {  # name: (weight, min seconds, max seconds)
    "idle": (3, 2, 5),
    "look": (2, 2.5, 4),
    "walk": (4, 3, 8),
    "type": (4, 6, 12),
    "think": (2, 3, 5),
    "sweep": (2, 4, 8),
    "carry": (2, 3, 7),
    "dance": (1, 3, 5),
    "sleep": (1, 8, 16),
    "read": (2, 5, 9),
    "coffee": (2, 4, 7),
    "daydream": (0, 7, 10),  # only when you've been at the computer a long time
    "festive": (0, 8, 12),   # only around holidays and once in a while each season
    "omarchy": (0.6, 5, 7),  # a happy thought about Omarchy
    "explore": (2, 0, 0),    # fixed length: EXPLORE_DUR
    "flag": (1, 5, 8),
    "stomp": (1, 3, 5),
    "gym": (1.5, 0, 0),      # fixed length: GYM_DUR
    "content": (2, 5, 9),    # smiling, a gentle sway, all is well
    "sidetype": (2, 5, 9),   # pulls out a laptop, turns side-on and types
}

INPUT_BREAK = 5 * 60   # this long with no keyboard/mouse input counts as a real break
LONG_ACTIVE = 60 * 60  # after this much unbroken activity he starts daydreaming of the outdoors
DREAM_EVERY = 8 * 60   # and then daydreams at most this often

# What he does while Claude uses each tool ("bash" means typing or hauling crates).
WORK_FOR_TOOL = {
    "Edit": "type", "Write": "type", "MultiEdit": "type", "NotebookEdit": "type",
    "Read": "read", "Grep": "read", "Glob": "read", "WebFetch": "read", "WebSearch": "read",
    "Bash": "bash", "Agent": "carry", "Task": "carry",
}
# Little breaks he takes even while Claude is busy, so he isn't a strict mirror.
BREAKS = ["dance", "look", "walk", "coffee", "idle", "sweep", "explore", "gym", "content"]

STATUS_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "pixel-claude")
STALE_AFTER = {"waiting": 1800, "working": 900, "thinking": 900, "done": 600, "hello": 600}
PRIORITY = ["waiting", "working", "thinking", "done", "hello"]


class ActivityWatch:
    """How long the user has been at the computer without a real break.

    Input shows up as ticking interrupt counters for the virtio keyboard/mouse in
    /proc/interrupts (readable without the input group). If there are no virtio
    input devices, it falls back to watching the pointer position.
    """

    def __init__(self):
        base = "/sys/bus/virtio/devices"
        try:
            self.irqs = tuple(d + "-" for d in os.listdir(base)
                              if os.path.isdir(os.path.join(base, d, "input")))
        except OSError:
            self.irqs = ()
        self.sig = None
        self.last_input = self.active_since = time.time()

    def signature(self):
        if not self.irqs:
            try:
                return subprocess.run(["hyprctl", "cursorpos"], capture_output=True,
                                      text=True, timeout=2).stdout
            except (OSError, subprocess.SubprocessError):
                return None
        total = 0
        with open("/proc/interrupts") as f:
            for line in f:
                parts = line.split()
                if parts and parts[-1].startswith(self.irqs):
                    for tok in parts[1:]:
                        if not tok.isdigit():
                            break
                        total += int(tok)
        return total

    def poll(self):
        sig, now = self.signature(), time.time()
        if self.sig is not None and sig != self.sig:
            if now - self.last_input > INPUT_BREAK:
                self.active_since = now  # back from a break: start counting again
            self.last_input = now
        self.sig = sig

    @property
    def active_for(self):
        now = time.time()
        return 0 if now - self.last_input > INPUT_BREAK else now - self.active_since


class ClaudeWatch:
    """Folds the per-session status files into one mood: the most urgent session wins."""

    def __init__(self):
        self.state, self.tool = "idle", ""
        self.last_busy = 0.0

    def poll(self):
        """Refresh; returns the previous state if it changed, else None."""
        now = time.time()
        best = None
        try:
            names = os.listdir(STATUS_DIR)
        except OSError:
            names = []
        for name in names:
            if name.startswith("."):
                continue
            try:
                with open(os.path.join(STATUS_DIR, name)) as f:
                    d = json.load(f)
                st, ts = d["state"], float(d["ts"])
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if st not in STALE_AFTER or now - ts > STALE_AFTER[st]:
                continue
            key = (PRIORITY.index(st), -ts)
            if best is None or key < best[0]:
                best = (key, st, d.get("tool") or "")
        state, tool = (best[1], best[2]) if best else ("idle", "")
        if state in ("working", "thinking"):
            self.last_busy = now
        if tool:
            self.tool = tool
        prev, self.state = self.state, state
        return prev if prev != state else None

    @property
    def busy(self):
        return self.state in ("working", "thinking")

    @property
    def idle_for(self):
        return time.time() - self.last_busy if self.last_busy else 1e9


class Buddy:
    def __init__(self, screen_w, screen_h):
        self.screen_w, self.screen_h = screen_w, screen_h
        self.x = random.uniform(0.2, 0.8) * self.max_x
        self.lift = screen_h * 0.45   # px above the bottom edge (drag / fall)
        self.vy = 0.0
        self.facing = 1
        self.t = 0.0
        self.particles = []
        self.blink_at, self.blink_until = 2.0, 0.0
        self.target = self.x
        self.greeted = False
        self.on_bye = None
        self.claude = ClaudeWatch()
        self.poll_t = 0.0
        self.user = ActivityWatch()
        self.user_poll_t = 0.0
        self.last_dream = 0.0
        self.last_holiday = self.last_season = time.time() - 10 * 60
        self.fest = None
        self.set_state("fall", 99)

    @property
    def max_x(self):
        return max(0, self.screen_w - GW * CELL)

    # ---------- state machine ----------
    def set_state(self, name, dur=None):
        self.state, self.st = name, 0.0
        if dur is None:
            _, lo, hi = ACTIVITIES.get(name, (0, 2, 4))
            dur = random.uniform(lo, hi)
        self.dur = dur
        self.mark = 0.0  # per-state spawn timer
        self.beat_k = -1  # last one-off moment fired (see beat)
        self.frame_k = -1  # last frame seen (see advanced)
        self.cheer = False
        if name == "explore":  # head for whichever side has room for the trip
            self.dur = EXPLORE_DUR
            self.ex0 = self.x
            self.ex_dir = 1 if self.x + LEAP_PX + WALK_PX <= self.max_x else -1
            if self.ex_dir < 0 and self.x - LEAP_PX - WALK_PX < 0:
                self.ex_dir = 1 if self.max_x - self.x > self.x else -1
            self.facing = self.ex_dir
        elif name == "gym":
            self.dur = GYM_DUR
        elif name in ("walk", "carry"):
            span = self.screen_w * random.uniform(0.15, 0.45)
            self.target = min(self.max_x, max(0, self.x + random.choice((-1, 1)) * span))
            if abs(self.target - self.x) < 40:
                self.target = self.max_x - self.x
            self.facing = 1 if self.target > self.x else -1
            self.dur = 30
        elif name == "sweep":
            self.facing = random.choice((-1, 1))
        elif name == "think":
            self.facing = random.choice((-1, 1))
        elif name == "daydream":
            self.facing = random.choice((-1, 1))
            self.dream = random.choice(DREAMS)  # one scene for the whole daydream
            self.last_dream = time.time()
        elif name == "omarchy":  # the icon, or the wordmark in one of several color schemes
            self.dream = "omarchy"
            schemes = LOGO_SCHEMES + [current_theme_scheme()] * 2
            self.logo = None if random.random() < 0.25 else random.choice([x for x in schemes if x])
            if self.logo:
                bg, fgs = self.logo
                self.logo = (rgba(bg), [rgba(c) for c in fgs])

    def next_activity(self):
        c = self.claude
        if c.state == "waiting" and random.random() < 0.7:
            self.set_state(random.choice(("call", "flag")), random.uniform(5, 8))
            return
        if (self.user.active_for > LONG_ACTIVE and time.time() - self.last_dream > DREAM_EVERY
                and random.random() < 0.6):
            self.set_state("daydream")
            return
        fest = self.festive_due()
        if fest and random.random() < (0.2 if c.busy else 0.5):
            self.start_festive(*fest)
            return
        if c.busy:
            if random.random() < 0.75:
                if c.state == "thinking" and random.random() < 0.5:
                    name = "think"
                else:
                    name = WORK_FOR_TOOL.get(c.tool, "type")
                    if name == "bash":
                        name = random.choice(("type", "type", "carry"))
                    if name == "type" and random.random() < 0.4:
                        name = "sidetype"
                self.set_state(name, random.uniform(4, 8))
            else:
                self.set_state(random.choice(BREAKS), random.uniform(2.5, 4.5))
            return

        weights = {k: v[0] for k, v in ACTIVITIES.items()}
        if self.state in weights:
            weights[self.state] *= 0.15
        weights["type"] = weights["think"] = 1  # the real work happens when Claude is busy
        hour = time.localtime().tm_hour
        if hour >= 23 or hour < 6:
            weights["sleep"] *= 6
        if c.idle_for > 600:
            weights["sleep"] *= 4
        if self.state == "think":
            weights["type"] += 10
        if self.state == "type":
            weights["think"] += 2
            weights["dance"] += 1
        names = list(weights)
        self.set_state(random.choices(names, [weights[n] for n in names])[0])

    def festive_due(self, force=False):
        """(act, kind) if a holiday or seasonal act is due today, else None."""
        holiday, on_day, season = occasions(today())
        now = time.time()
        every = HOLIDAY_DAY_EVERY if on_day else HOLIDAY_EVERY
        if holiday and (now - self.last_holiday > every or (force and random.random() < 0.75)):
            return random.choice(holiday), "holiday"
        if force or now - self.last_season > SEASON_EVERY:
            return random.choice(season), "season"
        return None

    def start_festive(self, act, kind):
        if kind == "holiday":
            self.last_holiday = time.time()
        else:
            self.last_season = time.time()
        self.fest = act
        self.facing = random.choice((-1, 1))
        if act == "leaves":  # a fresh leaf pile to jump in
            self.pile = ["".join(random.choice("OrQy") if abs(c - 10.5) < w / 2 else "."
                                 for c in range(22)) for w in (12, 18, 22)]
        self.set_state("festive")

    def beat(self, period, offset=0.0):
        """True once each time the state's clock passes offset + k * period."""
        k = int((self.st - offset) // period) if self.st >= offset else -1
        if k > self.beat_k:
            self.beat_k = k
            return True
        return False

    def advanced(self, k):
        """True the first time the state's frame counter reaches k."""
        if k != self.frame_k:
            self.frame_k = k
            return True
        return False

    def finish(self):
        s = self.state
        if s == "fall":
            self.set_state("land", 0.3)
        elif s == "land":
            if not self.greeted:
                self.greeted = True
                self.set_state("wave", 1.6)
            else:
                self.spawn("bang", 0, -9, 0, 0, 0.8)
                self.set_state("idle", 1.5)
        elif s == "drop":
            self.set_state("hop", 0.6)
        elif s == "bye":
            if self.on_bye:
                self.on_bye()
            self.set_state("idle", 99)
        else:
            self.next_activity()

    def on_claude(self, prev):
        """React right away to Claude starting, finishing, or needing the user."""
        if self.state in ("held", "fall", "land", "bye"):
            return
        c = self.claude
        if self.state == "petted" and c.state != "waiting":
            return  # let him enjoy it; only a permission prompt cuts it short
        was_busy = prev in ("working", "thinking")
        if c.state == "waiting":
            self.set_state(random.choice(("call", "flag")), random.uniform(5, 8))
        elif c.state == "done" and was_busy:
            if random.random() < 0.85:
                self.celebrate()
        elif c.busy and not was_busy:
            if self.state == "sleep":
                self.spawn("bang", 0, -9, 0, 0, 0.8)
                self.set_state("idle", 0.8)  # startled awake; work comes next
            elif self.state in ("call", "flag") or random.random() < 0.7:
                self.set_state("think", random.uniform(2, 4))
        elif prev == "waiting" and self.state in ("call", "flag"):
            self.set_state("idle", 0.6)
        elif c.state == "hello" and self.state not in ("type", "read", "think"):
            self.set_state("wave", 1.6)

    def celebrate(self):
        if random.random() < 0.4:  # a confetti stomp instead of the usual hop
            self.set_state("stomp", 2.0)
            self.cheer = True
            return
        for _ in range(8):
            self.spawn("spark", random.uniform(-6, 6), random.uniform(-12, -7),
                       random.uniform(-3, 3), random.uniform(-4, -1), 0.9)
        self.set_state("celebrate", 1.2)

    # ---------- interactions ----------
    def pet(self):
        if self.state in ("bye", "held", "fall"):
            return
        for i in range(3):
            self.spawn("heart", random.uniform(-4, 1), -11 - i, random.uniform(-1, 1), -3, 1.4)
        self.chill_at = 0.6 + random.uniform(1.5, 2.0)  # hop, bask, then 2s of calm
        self.set_state("petted", self.chill_at + 2.0)

    def grab(self):
        if self.state != "bye":
            self.set_state("held", 999)

    def drag(self, dx, dy):
        self.x = min(self.max_x, max(0, self.x + dx))
        self.lift = min(self.screen_h - GH * CELL, max(0, self.lift - dy))
        if dx:
            self.facing = 1 if dx > 0 else -1

    def release(self):
        if self.state == "held":
            self.vy = 0
            self.set_state("fall", 99)

    def command(self, name):
        if self.state in ("bye", "held", "fall"):
            return
        if name == "bye":
            for i in range(4):
                self.spawn("heart", random.uniform(-5, 2), -11 - i, random.uniform(-1, 1), -3, 1.6)
            self.set_state("bye", 2.0)
        elif name == "festive":
            self.start_festive(*self.festive_due(force=True))
        else:
            self.set_state(name)

    # ---------- simulation ----------
    def spawn(self, kind, dx, dy, vx, vy, ttl, size=0.5, col=None, grav=0.0):
        """dx/dy are cells relative to his center-bottom."""
        wx = self.x / CELL + GW / 2 + dx
        self.particles.append(Particle(kind, wx, GROUND + dy, vx, vy, ttl, size, col, grav))

    def update(self, dt):
        self.t += dt
        self.st += dt
        self.mark += dt
        s = self.state

        self.user_poll_t += dt
        if self.user_poll_t > 5:
            self.user_poll_t = 0
            self.user.poll()

        self.poll_t += dt
        if self.poll_t > 0.5:
            self.poll_t = 0
            prev = self.claude.poll()
            if prev is not None:
                self.on_claude(prev)
                s = self.state

        if self.t > self.blink_at:
            self.blink_until = self.t + 0.13
            self.blink_at = self.t + random.choice((0.25, 2.5, 3.5, 5.0))

        if s in ("walk", "carry", "sweep"):
            speed = {"walk": 36, "carry": 24, "sweep": 10}[s]
            if s == "sweep":
                nx = self.x + self.facing * speed * dt
                if nx <= 0 or nx >= self.max_x:
                    self.facing *= -1
                self.x = min(self.max_x, max(0, nx))
            else:
                step = speed * dt
                if abs(self.target - self.x) <= step:
                    self.x = self.target
                    if s == "carry":
                        for _ in range(6):
                            self.spawn("spark", random.uniform(-4, 4), random.uniform(-12, -8),
                                       random.uniform(-3, 3), random.uniform(-4, -1), 0.7)
                        self.set_state("drop", 0.35)
                    else:
                        self.set_state("idle", random.uniform(1, 3))
                else:
                    self.x += step * self.facing

        if s == "explore":
            st = self.st
            off = (LEAP_PX * tween(st, CROUCHES[0] + 0.1, 0.85, ease_inout)
                   + WALK_PX * tween(st, WALK_ON, PEER - WALK_ON)
                   - LEAP_PX * tween(st, CROUCHES[1] + 0.1, 0.85, ease_inout))
            self.x = min(self.max_x, max(0, self.ex0 + self.ex_dir * off))
            self.facing = self.ex_dir if st < CROUCHES[1] else -self.ex_dir
            if self.advanced(sum(st >= c + 0.9 for c in CROUCHES)) and self.frame_k:
                self.puff(4)  # touchdown

        if s == "stomp" and self.advanced(int(self.st / STOMP_FRAME)):
            fr = self.frame_k % 8
            if fr in (1, 6):  # a corner is up: throw! (timed like the original's two bursts)
                self.confetti(1 if fr == 1 else -1)
            elif fr in (0, 4) and self.frame_k:
                self.puff(2)

        if s == "gym":
            i = bisect.bisect_right(GYM_STARTS, self.st) - 1
            if self.advanced(i):
                frame = GYM_SEQ[i]
                if frame in (11, 14, 20):  # a bead of sweat
                    self.spawn("dot", -self.facing * 3, -8, -self.facing * 1.5, -3, 0.7,
                               0.5, "#6FB7E8", 12)
                elif frame == 35:
                    self.celebrate_sparks(0, -10, 6)

        if s == "festive" and self.fest == "ghost":  # a slow spooky drift
            nx = self.x + self.facing * 10 * dt
            if nx <= 0 or nx >= self.max_x:
                self.facing *= -1
            self.x = min(self.max_x, max(0, nx))

        if s == "fall":
            self.vy += 1800 * dt
            self.lift -= self.vy * dt
            if self.lift <= 0:
                self.lift = 0
                self.finish()

        # timed particle emitters
        if s == "sleep" and self.mark > 1.3:
            self.mark = 0
            self.spawn(random.choice("zZ"), 2 * self.facing, -8, 1.2 * self.facing, -2.2, 3.2)
        elif s == "dance" and self.mark > 0.55:
            self.mark = 0
            self.spawn("note", random.uniform(-5, 5), -9, random.uniform(-1, 1), -2.5, 1.8)
        elif s == "petted" and 1.2 < self.st < self.chill_at and self.mark > 0.9:
            self.mark = 0
            self.spawn("heart", random.uniform(-2, 2), -10, 0, -2, 1.2)
        elif s == "coffee" and self.mark > 0.45:
            self.mark = 0
            self.spawn("steam", self.facing * random.uniform(5.5, 7.5), -7.5,
                       random.uniform(-0.3, 0.3), -1.6, 1.6)
        elif s == "sweep" and self.mark > 0.3:
            self.mark = 0
            self.spawn("dust", self.facing * random.uniform(7, 10), -0.5,
                       self.facing * random.uniform(1, 3), random.uniform(-1.5, -0.3), 0.9)
        elif s == "festive":
            self.festive_fx()

        for p in self.particles:
            p.life += dt
            p.vy += p.grav * dt
            p.wx += p.vx * dt
            p.y += p.vy * dt
            if p.kind in ("z", "Z", "steam", "flake") or (p.kind == "leaf" and p.vy > 0):
                p.vx = math.sin(p.life * 3) * 1.5
            if p.kind in ("flake", "leaf"):
                p.vy = min(p.vy, 2.5)  # drift down gently
        self.particles = [p for p in self.particles if p.life < p.ttl
                          and not (p.kind in ("flake", "leaf") and p.y > GROUND)]

        if self.st >= self.dur:
            self.finish()

    def festive_fx(self):
        """Particles for the current seasonal act."""
        v, f, st = self.fest, self.facing, self.st
        sky = -GROUND  # top of the window, relative to the ground

        def every(sec):
            if self.mark > sec:
                self.mark = 0
                return True
            return False

        if v in ("newyear", "fireworks"):
            if every(1.1):
                cx, cy = random.uniform(-8, 8), random.uniform(-17, -13)
                col = random.choice(FIREWORKS[v])
                for i in range(12):
                    a, sp = i / 12 * 2 * math.pi, random.uniform(3, 4)
                    self.spawn("dot", cx, cy, math.cos(a) * sp, math.sin(a) * sp, 1.1, 0.5, col, 2.5)
            if random.random() < 0.6:  # the sparkler fizzes
                self.spawn("dot", f * 4.75, -11.5, random.uniform(-3, 3), random.uniform(-3, 0.5),
                           0.35, 0.5, random.choice(("#FFD34D", "#FFFFFF")), 8)
        elif v == "valentine" and every(0.9):
            self.spawn("heart", random.uniform(-4, 4), -12, random.uniform(-0.5, 0.5), -2, 1.6)
        elif v == "stpatrick" and every(0.6):
            self.spawn("clover", random.uniform(-6, 6), -13, random.uniform(-1, 1), -2.5, 1.8)
        elif v == "easter" and self.beat(999, self.dur * 0.65):  # found the egg!
            self.celebrate_sparks(f * 4.75, -12, 6)
        elif v in ("ghost", "pumpkin") and every(2.6):
            self.spawn("bat", -f * 12, random.uniform(-19, -14), f * random.uniform(5, 7),
                       random.uniform(-0.5, 0.5), 4.5)
        elif v in ("christmas", "snowman"):
            if every(0.3):
                self.spawn("flake", random.uniform(-12, 12), sky, 0, random.uniform(1.5, 2.5), 12, 0.25)
            if v == "snowman" and self.beat(999, self.dur * 0.75):
                self.celebrate_sparks(f * 8, -7, 5)
        elif v == "pie" and self.beat(1.6, 1.3):  # crumbs from each bite
            for _ in range(4):
                self.spawn("dot", f * random.uniform(1, 3), -4.5, random.uniform(-1.5, 1.5),
                           random.uniform(-2.5, -1), 0.6, 0.5, "#E0A85A", 10)
        elif v == "garden":
            if st < self.dur * 0.7:
                if every(0.12):  # a little stream from the spout
                    self.spawn("dot", f * 10.25, -5.5, f * 0.5, 0, 0.6, 0.5, "#6FB7E8", 12)
            elif self.beat(999, self.dur * 0.7):
                self.celebrate_sparks(f * 10, -5, 5)
        elif v == "leaves":
            if self.beat(2.0, 0.6):  # landing in the pile sends leaves flying
                for _ in range(8):
                    self.spawn("leaf", random.uniform(-4, 4), -1, random.uniform(-4, 4),
                               random.uniform(-6, -3), 3.0, 0.75, random.choice(LEAVES), 6)
            if every(0.8):
                self.spawn("leaf", random.uniform(-12, 12), sky, 0, 1.5, 12, 0.75,
                           random.choice(LEAVES), 1)

    def confetti(self, side):
        """A burst from the raised hand on that side: shoots up, spreads, thins out, falls."""
        f = self.facing * side
        for _ in range(12):  # little bits and strips, moving as one piece
            vx, vy = f * 1.5 + random.uniform(-6, 6), random.uniform(-26, -18)
            ttl, col = random.uniform(0.5, 1.0), random.choice(CONFETTI)
            x, y = f * 3 + random.uniform(-1.5, 1.5), -11 + random.uniform(-1, 1)
            for bx, by in random.choice(CONFETTI_BITS):
                self.spawn("dot", x + bx, y + by, vx, vy, ttl, 0.5, col, 60)

    def puff(self, n):
        for _ in range(n):
            d = random.choice((-1, 1))
            self.spawn("dust", d * random.uniform(2, 5), -0.5, d * random.uniform(1, 3),
                       random.uniform(-1.5, -0.3), 0.6)

    def celebrate_sparks(self, dx, dy, n):
        for _ in range(n):
            self.spawn("spark", dx + random.uniform(-2, 2), dy + random.uniform(-2, 1),
                       random.uniform(-2, 2), random.uniform(-3, -1), 0.8)

    # ---------- drawing ----------
    def pose(self):
        """Describe this frame: how the body is arranged and what props to draw."""
        s, st, t = self.state, self.st, self.t
        p = {"bob": 0, "legs": [0, 0, 0, 0], "leg_h": 1.5, "arms": ["side", "side"],
             "arm_dy": [0, 0], "eyes": "open", "edx": 0, "edy": 0, "dx": 0, "jump": 0, "lean": 0,
             "tilt": 0, "side": False,
             "front": [], "bubble": None, "over": [], "grip": [], "hat": None, "glasses": False}
        breathe = 0.5 if int(t / 1.1) % 2 else 0
        if s == "idle":
            p["bob"] = breathe
            p["arm_dy"] = [breathe, breathe]
        elif s == "look":
            seq = [(0, 0), (-0.5, 0), (-0.5, 0), (0.5, 0), (0.5, -0.25), (0, 0)]
            p["edx"], p["edy"] = seq[min(len(seq) - 1, int(st / self.dur * len(seq)))]
            p["bob"] = breathe
            if st > self.dur * 0.6:
                p["bubble"] = ("pop", "q")
        elif s in ("walk", "carry", "held"):
            rate = 10 if s == "held" else 7
            ph = int(st * rate) % 2
            p["legs"] = [0.5, 0, 0.5, 0] if ph else [0, 0.5, 0, 0.5]
            p["bob"] = 0.5 * ph if s != "held" else 0
            p["edx"] = 0.5 if s != "held" else 0
            p["arm_dy"] = [0.5 * ph, 0.5 * (1 - ph)]
            if s == "carry":
                p["arms"] = ["up", "up"]
                p["front"].append(self.draw_box)
            if s == "held":
                p["arms"] = ["up", "side"] if ph else ["side", "up"]
                p["eyes"] = "wide"
                p["bubble"] = ("pop", "bang")
        elif s == "type":
            p["leg_h"] = 0.5
            p["edy"] = 0.25
            tap = int(st * 9)
            p["arms"] = ["type", "type"]
            p["arm_dy"] = [0.5 * (tap % 2), 0.5 * ((tap + 1) % 2)] if (tap // 6) % 3 else [0, 0]
            p["front"].append(self.draw_laptop)
            p["bubble"] = ("code",)
        elif s == "think":
            p["edx"], p["edy"] = 0.5, -0.25
            p["arms"] = ["side", "chin"]
            p["bob"] = breathe
            p["bubble"] = ("think", "bulb" if st > self.dur - 1.0 else None)
            if st > self.dur - 1.0:
                p["eyes"] = "wide"
        elif s == "read":
            p["leg_h"] = 0.5
            p["edy"] = 0.25
            p["edx"] = -0.5 + (st % 2.4) / 2.4  # eyes scan across the page
            p["front"].append(self.draw_book)
        elif s == "coffee":
            sip = (st % 3.5) > 2.6
            p["arms"] = ["side", "sip" if sip else "mug"]
            p["eyes"] = "closed" if sip else "open"
            p["bob"] = breathe
            p["front"].append(lambda B, g: self.draw_mug(B, sip))
        elif s == "petted":  # a happy hop, then a moment of basking before moving on
            p["eyes"] = "happy"
            if st < 0.6:
                p["jump"] = 3.0 * math.sin(math.pi * st / 0.6)
                p["arms"] = ["up", "up"]
            elif st < self.chill_at:
                p["bob"] = 0.5 if int(st / 0.5) % 2 else 0
                p["arm_dy"] = [p["bob"], p["bob"]]
            else:  # calm: contented closed eyes, slow breaths
                p["eyes"] = "closed"
                p["bob"] = 0.5 if int((st - self.chill_at) / 1.0) % 2 else 0
                p["arm_dy"] = [p["bob"], p["bob"]]
        elif s == "call":  # Claude needs the user: wave, hop, and ask
            p["arms"] = ["side", "wave1" if int(st * 5) % 2 else "wave2"]
            ph = st % 1.5
            p["jump"] = 1.5 * math.sin(math.pi * ph / 0.4) if ph < 0.4 else 0
            p["bubble"] = ("speak", "ask")
        elif s == "celebrate":
            p["jump"] = 2.5 * abs(math.sin(math.pi * st / 0.6))
            p["arms"] = ["up", "up"]
            p["eyes"] = "happy"
            p["bubble"] = ("pop", "check")
        elif s == "daydream":  # gazing up at a bubble full of outdoors
            p["edx"], p["edy"] = 0.5, -0.25
            p["arms"] = ["side", "chin"]
            p["bob"] = 0.5 if int(t / 1.6) % 2 else 0
            p["bubble"] = ("dream",)
        elif s == "omarchy":  # a little hop, then a fond wave at the Omarchy logo
            p["eyes"] = "happy"
            if st < 0.6:  # the bubble waits until he lands
                p["jump"] = 2.5 * math.sin(math.pi * st / 0.6)
                p["arms"] = ["up", "up"]
            else:
                p["bubble"] = ("logo",) if self.logo else ("dream",)
                p["bob"] = 0.5 if int(t / 1.2) % 2 else 0
                p["arms"] = ["side", "wave1" if int(st * 3) % 2 else "wave2"]
        elif s == "festive":
            self.festive_pose(p, breathe)
        elif s == "explore":
            self.explore_pose(p, breathe)
        elif s == "flag":  # pole up, cloth rising then rippling, body leaning against it
            f = int(st / FLAG_FRAME)
            k = f if f < 12 else 3 + (f - 3) % 9
            hx = HAND_PULL[k]
            p["lean"] = SWAY[k]
            p["arm_dy"] = [BACK_DROP[k], 0]
            p["arms"] = ["side", "none"]
            p["eyes"] = "happy"
            p["front"].append(lambda B, g: self.draw_flag(B, k, hx))
            p["grip"].append((1, 2.5 + hx, -1.5, 1.5, 1.5))  # his front corner, raised as a hand
            if self.claude.state == "waiting":
                p["bubble"] = ("pop", "q")
        elif s == "stomp":
            p["tilt"], p["bob"], p["arms"] = STOMP[int(st / STOMP_FRAME) % 8]
            p["eyes"] = "happy"
            if self.cheer:
                p["bubble"] = ("pop", "check")
        elif s == "gym":
            frame = GYM_SEQ[bisect.bisect_right(GYM_STARTS, st) - 1]
            p["bob"], p["tilt"], arms, band, bells, p["eyes"] = GYM_FRAMES[frame]
            p["arms"] = list(arms)
            p["over"].append(lambda B, g: self.draw_gym(B, arms, band, bells))
        elif s == "sidetype":
            self.sidetype_pose(p)
        elif s == "content":  # eyes smiling shut now and then, swaying to a slow tune
            p["eyes"] = "closed" if (st % 4.5) > 3.2 else "happy"
            p["lean"] = 0.25 * math.sin(st * math.pi / 1.4)
            p["bob"] = 0.5 if int(t / 1.6) % 2 else 0
            p["arm_dy"] = [p["bob"], p["bob"]]
        elif s == "sleep":
            p["leg_h"] = 0.5
            p["eyes"] = "closed"
            p["bob"] = 0.5 if int(t / 1.8) % 2 else 0
            p["arm_dy"] = [0.5, 0.5]
        elif s == "sweep":
            ph = int(st * 3.5) % 2
            p["arms"] = ["side", "hold"]
            p["legs"] = [0.5, 0, 0.5, 0] if int(st * 3.5) % 4 == 0 else [0, 0, 0, 0]
            p["edy"] = 0.25
            p["edx"] = 0.5
            p["front"].append(lambda B, g: self.draw_broom(B, g, 1.0 if ph else -0.5))
        elif s == "dance":
            ph = int(st * 4) % 2
            p["dx"] = 0.5 if ph else -0.5
            p["legs"] = [0.5, 0, 0, 0.5] if ph else [0, 0.5, 0.5, 0]
            p["arms"] = ["up", "side"] if ph else ["side", "up"]
            p["eyes"] = "happy"
            p["bob"] = 0.5 * ph
        elif s in ("hop", "drop"):
            prog = min(1, st / self.dur)
            p["jump"] = 3.0 * math.sin(math.pi * prog) if s == "hop" else 0
            p["arms"] = ["up", "up"]
            p["eyes"] = "happy"
        elif s == "fall":
            p["arms"] = ["up", "up"]
            p["eyes"] = "wide"
            p["legs"] = [0.5, 0.5, 0.5, 0.5]
        elif s == "land":
            p["bob"] = 1
            p["eyes"] = "happy"
        elif s in ("wave", "bye"):
            p["arms"] = ["side", "wave1" if int(st * 5) % 2 else "wave2"]
            p["eyes"] = "happy"
            p["bob"] = breathe
        if p["eyes"] == "open" and self.t < self.blink_until:
            p["eyes"] = "blink"
        return p

    def explore_pose(self, p, breathe):
        st = self.st
        # Body, eyes and legs lean together in one beat: back, ahead, upright.
        lean = 0.5 * (-tween(st, LOOK_BACK, 0.4, ease_out) + 2 * tween(st, LOOK_AHEAD, 0.4, ease_out)
                      - tween(st, UPRIGHT, 0.3, ease_out))
        if WALK_ON <= st < CROUCHES[1]:
            ph = int(st * 7) % 2
            p["legs"] = [0.5, 0, 0.5, 0] if ph else [0, 0.5, 0, 0.5]
            p["bob"] = 0.5 * ph
            p["edx"] = 0.5
            if st >= PEER:  # lean out and peer down
                lean = 0.5 * tween(st, PEER, 0.3, ease_out)
                p["legs"], p["bob"], p["edy"] = [0, 0, 0, 0], -lean, 0.5
        elif st >= CROUCHES[1] + 1.05:
            p["eyes"] = "happy"
            p["bob"] = breathe
        else:
            p["edx"] = lean
            p["bob"] = -abs(lean)  # leaning stretches the legs
        p["lean"] = lean
        for crouch in CROUCHES:
            j = st - crouch - 0.1
            if -0.1 <= j < 0:  # a quick snap down to gather momentum
                k = tween(j, -0.1, 0.1, ease_in)
                p["bob"], p["arm_dy"], p["lean"], p["edx"] = k, [k, k], 0, 0.5
            elif 0 <= j < 1.05:
                p["lean"], p["edx"] = 0, 0.5
                p["jump"] = leap_height(j)
                if j < 0.8:
                    p["legs"] = [0.5, 0.5, 0.5, 0.5]
                    p["arms"] = ["up", "up"] if j < 0.42 else ["side", "side"]
                    p["arm_dy"] = [-0.5, -0.5] if j >= 0.42 else [0, 0]
                    p["eyes"] = "happy"
                else:  # land with a squash, the hands overshooting down then settling
                    p["bob"] = 1 - tween(j, 0.8, 0.2, ease_out)
                    p["arm_dy"] = [1, 1] if j < 0.85 else [p["bob"], p["bob"]]

    def sidetype_pose(self, p):
        """Pull a laptop out of thin air, set it down, turn side-on and type; then pack up."""
        f = int(self.st / SIDETYPE_FRAME)
        left = int((self.dur - self.st) / SIDETYPE_FRAME)
        if f < 11:
            if 1 <= f <= 5:  # a wink while reaching round the back
                p["eyes"], p["arms"] = "wink", ["side", "tuck"]
            elif f in (6, 7):  # ta-da: up it comes, held by a corner
                p["arms"] = ["side", "nub"]
                p["front"].append(lambda B, g: (B(3.75, -3.5, 0.5, 2.5, LID), B(3.75, -3.5, 1.5, 0.5, LID)))
            elif f == 8:  # swung down in front
                p["arms"] = ["side", "type"]
                p["front"].append(lambda B, g: B(5.5, 2.25, 2.5, 1.25, LID))
            elif f >= 9:  # set on the floor, lid coming up
                p["front"].append(lambda B, g: self.draw_side_laptop(B, g, False))
            return
        if left < 6:
            k = 5 - left
            if k == 0:  # lid down
                p["side"], p["bob"], p["arms"] = True, 0.5, ["none", "key"]
                p["front"].append(lambda B, g: self.draw_side_laptop(B, g, False))
            elif k == 1:  # tucked under his arm
                p["arms"] = ["side", "type"]
                p["front"].append(lambda B, g: B(4.5, 3, 2.5, 1, LID))
            elif k == 2:  # and tucked away again
                p["eyes"], p["arms"] = "wink", ["side", "tuck"]
            return
        tap = SIDETYPE_TAPS[(f - 11) % len(SIDETYPE_TAPS)] == "1"
        p["side"], p["bob"] = True, 0.5
        p["arms"] = ["none", "tap" if tap else "key"]
        p["edy"] = 0.25
        p["front"].append(lambda B, g: self.draw_side_laptop(B, g, True))
        if self.claude.busy:
            p["bubble"] = ("code",)

    def festive_pose(self, p, breathe):
        v, st, t, dur = self.fest, self.st, self.t, self.dur
        spr = self.sprite

        def hold(y):  # both hands on a prop held in front
            p["arms"] = ["none", "none"]
            p["grip"] += [(-1, 3, y, 1.5, 1), (1, 3, y, 1.5, 1)]

        def on_ground(name, x, outline=False):  # stays put while he hops
            j, rows = p["jump"], SPRITES[name] if isinstance(name, str) else name
            p["front"].append(lambda B, g: spr(B, rows, x, g + j - len(rows) * 0.5, outline))

        if v in ("newyear", "fireworks"):  # watching fireworks with a sparkler
            p["arms"] = ["side", "up"]
            p["eyes"] = "happy"
            p["bob"] = breathe
            p["hat"] = "party" if v == "newyear" else None
            p["front"].append(self.draw_sparkler)
        elif v == "valentine":  # hugging a big heart
            hold(4)
            p["eyes"] = "happy"
            p["dx"] = 0.5 if int(st / 0.8) % 2 else -0.5
            lub = 0.5 if (st % 1.2) < 0.25 else 0
            p["front"].append(lambda B, g: spr(B, SPRITES["bigheart"], -3.5, 2 - lub))
        elif v == "stpatrick":  # a little jig in a green top hat
            ph = int(st * 4) % 2
            p["dx"] = 0.5 if ph else -0.5
            p["legs"] = [0.5, 0, 0, 0.5] if ph else [0, 0.5, 0.5, 0]
            p["arms"] = ["up", "side"] if ph else ["side", "up"]
            p["eyes"] = "happy"
            p["bob"] = 0.5 * ph
            p["hat"] = "tophat"
        elif v == "easter":  # bunny hops, then finds an egg
            p["hat"] = "ears"
            p["eyes"] = "happy"
            if st < dur * 0.65:
                ph = st % 1.0
                p["jump"] = 2.5 * math.sin(math.pi * ph / 0.5) if ph < 0.5 else 0
                p["arms"] = ["up", "up"] if ph < 0.5 else ["side", "side"]
                on_ground("egg", 6)
            else:
                p["arms"] = ["side", "up"]
                p["bob"] = breathe
                p["front"].append(lambda B, g: spr(B, SPRITES["egg"], 3.75, -4.5))
        elif v == "ghost":  # a sheet-ghost costume, floating along
            p["arms"] = ["none", "none"]
            p["jump"] = 0.75 + 0.75 * math.sin(t * 2.5)
            p["edx"] = 0.5
            p["over"].append(self.draw_sheet)
        elif v == "pumpkin":  # showing off a glowing jack-o'-lantern
            hold(4.5)
            p["bob"] = breathe
            glow = "F" if int(t * 7) % 3 == 0 else "y"
            rows = [r.replace("y", glow) for r in SPRITES["pumpkin"]]
            p["front"].append(lambda B, g: spr(B, rows, -3.5, g - 5.5))
        elif v == "christmas":  # Santa hat and a present, swaying in the snow
            hold(4.5)
            p["eyes"] = "happy"
            p["hat"] = "santa"
            p["dx"] = 0.5 if int(st / 0.9) % 2 else 0
            p["front"].append(lambda B, g: spr(B, SPRITES["gift"], -3, g - 5))
        elif v == "pie":  # working through a pumpkin pie, bite by bite
            hold(5)
            chomp = (st % 1.6) > 1.2
            if chomp:
                p["eyes"], p["edy"], p["bob"] = "closed", 0.25, 0.5
            left = 14 - 2 * min(6, int(st / 1.6))
            rows = [r[:left] + "." * (14 - left) if i < 4 else r
                    for i, r in enumerate(SPRITES["pie"])]
            p["front"].append(lambda B, g: spr(B, rows, -3.5, 3.5))
        elif v == "garden":  # watering a flower until it blooms
            stage = min(2, int(st / (dur * 0.7) * 3))
            on_ground(("sprout", "seedling", "flower")[stage], 8.75)
            if st < dur * 0.7:
                p["arms"] = ["side", "hold"]
                p["edx"], p["edy"] = 0.5, 0.25
                p["front"].append(lambda B, g: spr(B, SPRITES["can"], 5.5, 1))
            else:
                p["eyes"] = "happy"
                p["bob"] = breathe
                on_ground("can", -10.5)
        elif v == "icecream":  # sunglasses and an ice cream cone
            p["glasses"] = True
            p["eyes"] = "none"
            p["bob"] = breathe
            lick = (st % 2.2) > 1.6
            scoop = min(2, int(st / 2.2))
            rows = ["...." if i < scoop else r for i, r in enumerate(SPRITES["cone"])]
            if lick:
                p["arms"] = ["side", "sip"]
                p["front"].append(lambda B, g: spr(B, rows, 3, -0.5))
                p["grip"].append((1, 3.75, 2.5, 1.5, 1))
            else:
                p["arms"] = ["side", "mug"]
                p["front"].append(lambda B, g: spr(B, rows, 4.25, -1))
                p["grip"].append((1, 4, 2.5, 2, 1.5))
        elif v == "leaves":  # jumping into a leaf pile
            cyc = st % 2.0
            air = cyc < 0.6
            p["jump"] = 3.5 * math.sin(math.pi * cyc / 0.6) if air else 0
            p["arms"] = ["up", "up"] if air else ["side", "side"]
            p["eyes"] = "happy"
            on_ground(self.pile, -5.5)
        elif v == "snowman":  # building a snowman, then waving at it
            build = dur * 0.75
            stage = min(3, int(4 * st / build))
            rows = SPRITES["snowman"]
            if stage < 3:
                rows = [r.replace("k", "W").replace("O", "W") if i < 4 else r
                        for i, r in enumerate(rows)]
            first = (8, 4, 0, 0)[stage]
            rows = ["." * 10] * first + rows[first:]
            on_ground(rows, 5.5, True)
            if st < build:
                p["arms"] = ["side", "hold"]
                p["arm_dy"] = [0, 0.5 * (int(st * 4) % 2)]
                p["edx"], p["edy"] = 0.5, 0.25
            else:
                p["arms"] = ["side", "wave1" if int(st * 5) % 2 else "wave2"]
                p["eyes"] = "happy"

    def render(self):
        """Return [(x, y, w, h, rgba)] in cells, window coordinates."""
        out = []
        p = self.pose()
        f = self.facing
        cx = GW / 2 + p["dx"]
        ground = GROUND - p["jump"]
        top = ground - p["leg_h"] - 6 + p["bob"]
        g = ground - top  # ground, relative to the top of his head

        def rise(x):  # tipped onto one side, the other side lifts (tilt > 0 lifts his front)
            t = p["tilt"]
            return -t * (x + 4) / 8 if t > 0 else t * (4 - x) / 8

        def B(x, y, w, h, c, sway=1.0, tilted=True):  # body-relative rect, mirrored when facing left
            if tilted and p["tilt"]:
                y += rise(x + w / 2)
            x += p["lean"] * sway
            if f < 0:
                x = -(x + w)
            out.append((cx + x, top + y, w, h, c))

        def A(side, x, y, w, h):  # arm rect: side=+1 is the side he's facing
            if side < 0:
                x = -(x + w)
            B(x, y, w, h, BODY)

        if self.lift <= 0:
            sw = max(4, 9 - p["jump"] * 1.4)
            out.append((GW / 2 - sw / 2, GROUND, sw, 0.5, SHADOW))

        # legs, torso, arms
        for i, lx in enumerate((-3, -1.5, 0.5, 2) if p["side"] else (-4, -2, 1, 3)):
            hip = 6 + (rise(lx + 0.5) if p["tilt"] else 0)
            h = g - hip - p["legs"][i]
            if h > 0 and p["lean"]:  # slant from the leaning hips down to planted feet
                for j in range(3):
                    B(lx, hip + h * j / 3, 1, h / 3 + 0.01, BODY, (2 - j) / 2, False)
            elif h > 0:
                B(lx, hip, 1, h, BODY, tilted=False)
        if p["tilt"]:  # a stepped slope, one column at a time
            for c in range(8):
                B(-4 + c, 0, 1, 6, BODY)
        elif p["side"]:  # side-on: narrower, with his far side in shade
            B(-3, 0, 6, 6, BODY)
            B(-3, 0, 1, 6, BODY_D)
        else:
            B(-4, 0, 8, 6, BODY)
        for side, mode, dy in ((-1, p["arms"][0], p["arm_dy"][0]), (1, p["arms"][1], p["arm_dy"][1])):
            if mode == "side":
                A(side, 4, 2 + dy, 2, 2)
            elif mode == "up":
                A(side, 4, -1.5 + dy, 1.5, 4.5)
            elif mode in ("nub", "nub2"):  # his top corner thrown up as a hand
                A(side, 2.5, -1.5 if mode == "nub" else -2.5, 1.5, 1.5 if mode == "nub" else 2.5)
            elif mode == "low":
                A(side, 4, 3, 2, 1.5)
            elif mode == "tuck":
                A(side, 4, 2.5, 1, 1.5)
            elif mode == "key":  # side-on, hand poised over the keys
                A(side, 3, 2.5, 1.5, 2)
            elif mode == "tap":
                A(side, 3, 3, 1.5, 2)
                A(side, 3.5, 4.5, 1, g - 5)
            elif mode == "mid":
                A(side, 4, 0.5, 1.5, 3)
            elif mode == "vee":
                A(side, 4, 1, 2, 2)
                A(side, 5, 0, 1, 1)
            elif mode == "wave1":
                A(side, 4, -1.5, 1.5, 4.5)
            elif mode == "wave2":
                A(side, 5.5, -1.5, 1.5, 1.5)
                A(side, 5, 0, 1.5, 1.5)
                A(side, 4, 1.5, 1.5, 1.5)
            elif mode == "chin":
                A(side, 4, 2, 1.5, 2)
                A(side, 4.5, 1, 1.5, 1.5)
            elif mode == "hold":
                A(side, 4, 2.5, 2.5, 1.5)
            elif mode == "type":
                A(side, 4, 2.5, 1.5, 1.5)
            elif mode == "mug":
                A(side, 4, 2.5, 2, 1.5)
            elif mode == "sip":
                A(side, 4, 1, 1.5, 3)
        for draw in p["over"]:
            draw(B, g)

        # eyes
        ex, ey = p["edx"], p["edy"]
        for x in ((-1, 1.5) if p["side"] else (-3, 2)):
            e = p["eyes"]
            if e == "wink":  # the far eye shut
                e = "closed" if x < 0 else "open"
            if e == "open":
                B(x + ex, 0.75 + ey, 1, 1, EYE)
            elif e == "wide":
                B(x + ex, 0.5 + ey, 1, 1.5, EYE)
            elif e in ("blink", "closed"):
                B(x + ex, 1.25 + ey, 1, 0.5, EYE)
            elif e == "happy":
                B(x - 0.25, 1.0, 0.5, 0.5, EYE)
                B(x + 0.25, 0.5, 0.5, 0.5, EYE)
                B(x + 0.75, 1.0, 0.5, 0.5, EYE)
        if p["glasses"]:
            self.sprite(B, SPRITES["glasses"], -4, 0.5)
        if p["hat"] == "ears":
            twitch = 0.5 if int(self.t * 1.5) % 4 == 0 else 0
            self.sprite(B, SPRITES["ear"], -3.5, -4.5 + twitch)
            self.sprite(B, SPRITES["ear"], 1.5, -4.5)
        elif p["hat"]:
            rows = SPRITES[p["hat"]]
            self.sprite(B, rows, -len(rows[0]) / 4, 0.5 - len(rows) / 2)

        for draw in p["front"]:
            draw(B, g)
        if self.state == "type":  # hands reach over the lid onto the keys
            for side, dy in ((-1, p["arm_dy"][0]), (1, p["arm_dy"][1])):
                A(side, 2.5, 3 + dy, 2, 1)
        elif self.state == "read":  # hands hold the book's edges
            for side in (-1, 1):
                A(side, 3.5, g - 3.5, 1.5, 1)
        for grip in p["grip"]:  # hands in front of whatever they're holding
            A(*grip)

        if p["bubble"]:
            self.draw_bubble(out, p["bubble"], cx, top)

        for pt in self.particles:
            fade = 1 - max(0, (pt.life - pt.ttl * 0.6) / (pt.ttl * 0.4))
            lx = pt.wx - self.x / CELL
            if pt.kind == "dust":
                out.append((lx, pt.y, 0.75, 0.75, rgba("#D8CFC4", 0.8 * fade)))
            elif pt.kind == "steam":
                out.append((lx, pt.y, 0.5, 0.5, rgba("#FFFFFF", 0.7 * fade)))
            elif pt.kind in ("dot", "leaf"):
                out.append((lx, pt.y, pt.size, pt.size, rgba(pt.col, fade)))
            else:
                self.glyph(out, pt.kind, lx, pt.y, pt.size, fade)
        return out

    def draw_side_laptop(self, B, g, opened):
        """The laptop on the floor in front of him, seen side-on, lid open to some angle."""
        B(4.5, g - 0.5, 3, 0.5, LAPTOP_BASE)
        dx, dy = (0.3, 0.5) if opened else (0.5, 0.15)
        for i in range(6):
            B(7.25 + i * dx, g - 1 - i * dy, 0.5, 0.5 + dy, LID)

    def draw_laptop(self, B, g):
        B(-3.5, g - 3.5, 7, 3, LID)
        B(-3.5, g - 3.5, 7, 0.5, LID_HI)
        B(-0.5, g - 2.5, 1, 1, BODY)  # tiny orange logo on the lid
        B(-4.5, g - 0.5, 9, 0.5, LAPTOP_BASE)
        glow = 0.10 + 0.06 * (int(self.t * 6) % 2)
        B(-4, 2, 8, 1, rgba("#BFE6FF", glow))  # screen light on his face

    def sprite(self, B, rows, x, y, outline=False, px=0.5):
        """Draw ASCII art (PALETTE chars, '.' empty) through B, so it mirrors with him."""
        cells = [(c, r, ch) for r, row in enumerate(rows) for c, ch in enumerate(row) if ch != "."]
        if outline:  # keeps pale things like snow visible on a light wallpaper
            o = 1 / CELL
            for c, r, _ in cells:
                B(x + c * px - o, y + r * px - o, px + 2 * o, px + 2 * o, OUTLINE)
        for c, r, ch in cells:
            B(x + c * px, y + r * px, px, px, COL[ch])

    def draw_flag(self, B, k, hx):
        B(3 + hx, -8, 0.5, 7.5, COL["s"])  # pole, held up in his front corner
        B(2.75 + hx, -8.75, 1, 1, COL["y"])
        x0, rows = FLAG_FRAMES[k]
        self.sprite(B, rows, (3.5 if x0 >= 0 else 3) + x0 * 0.5 + hx, -9, outline=True)

    def draw_gym(self, B, arms, band, bells):
        if band == "on":  # sweatband across his forehead
            B(-4, 0.25, 8, 0.5, COL["N"])
        elif band:
            rows, x, y = BAND[band]
            self.sprite(B, rows, x, y)
        if bells:
            for side, mode in zip((-1, 1), arms):
                rows, x, y = BELLS[mode]
                if side < 0:
                    x = -(x + len(rows[0]) * 0.5)
                self.sprite(B, rows, x, y)

    def draw_sparkler(self, B, g):
        B(4.5, -4, 0.5, 2.5, COL["s"])
        B(4.25, -4.5, 1, 1, COL["y"] if int(self.t * 10) % 2 else COL["w"])

    def draw_sheet(self, B, g):
        rects = [(-3.5, -1, 7, 1), (-4.5, 0, 9, g - 1.5)]
        rects += [(-4.5 + 2 * i, g - 1.5, 1, 0.5) for i in range(5) if (i + int(self.t * 3)) % 2]
        o = 1 / CELL
        for x, y, w, h in rects:
            B(x - o, y - o, w + 2 * o, h + 2 * o, OUTLINE)
        for x, y, w, h in rects:
            B(x, y, w, h, COL["w"])

    def draw_book(self, B, g):
        B(-4.25, g - 4.5, 8.5, 3, BOOK)
        B(-4, g - 4.25, 3.75, 2.5, PAGE)
        B(0.25, g - 4.25, 3.75, 2.5, PAGE)
        for y in (g - 3.75, g - 2.75):
            B(-3.5, y, 2.75, 0.5, INK)
            B(0.75, y, 2.75, 0.5, INK)
        if (self.st % 2.4) > 2.05:  # flip a page
            B(-0.25, g - 6, 2, 2, PAGE)
            B(-0.25, g - 6, 0.5, 2, INK)

    def draw_mug(self, B, sip):
        x, y = (2.75, 0.5) if sip else (5.25, 0.75)
        B(x, y, 2, 2, MUG)
        B(x + 2, y + 0.5, 0.5, 1, MUG)
        B(x, y, 2, 0.5, COFFEE)

    def draw_box(self, B, g):
        B(-5, -5, 10, 3.5, CRATE)
        B(-5, -5, 10, 0.5, CRATE_D)
        B(-5, -2, 10, 0.5, CRATE_D)
        B(-0.5, -5, 1, 3.5, CRATE_D)

    def draw_broom(self, B, g, sw):
        # handle: a staircase from his front hand down to the bristles
        x0, y0, x1, y1 = 6.0, 2.5, 8.0 + sw, g - 1.5
        for i in range(7):
            k = i / 6
            B(x0 + (x1 - x0) * k, y0 + (y1 - y0) * k, 0.75, 0.75, HANDLE)
        B(x1 - 1, y1, 3, 1.5, BRISTLE)
        B(x1 - 1, y1, 3, 0.5, BRISTLE_D)
        B(x1 - 0.5, y1 + 0.5, 0.5, 1, BRISTLE_D)
        B(x1 + 1, y1 + 0.5, 0.5, 1, BRISTLE_D)

    def draw_bubble(self, out, spec, cx, top):
        kind = spec[0]
        if kind == "pop":  # just a glyph floating over his head
            gl = GLYPHS[spec[1]]
            gw = len(gl[0]) * 0.5
            bob = 0.5 if int(self.t * 3) % 2 else 0
            self.glyph(out, spec[1], cx - gw / 2, top - 4.5 - bob, 0.5, 1)
            return
        w, h = (11, 7) if kind == "dream" else (9, 5)
        fill = BUBBLE
        if kind == "dream":  # grow to fit taller scenes like the Omarchy icon
            h = max(h, len(GLYPHS[self.dream]) * 0.5 + 1.5)
        elif kind == "logo":  # the wordmark at 1/3-cell pixels, on its scheme's background
            w = math.ceil((len(LOGO[0]) / 3 + 1.5) * 2) / 2
            h = math.ceil((len(LOGO) / 3 + 1.5) * 2) / 2
            fill = self.logo[0]
        bx = cx - w / 2 + self.facing * 3.5
        by = top - h - 2.5
        bx = min(GW - w - 0.5, max(0.5, bx))
        # pixel-rounded box: outline then fill, corners clipped
        e = 0.5
        out.append((bx + e, by - e, w - 2 * e, h + 2 * e, BUBBLE_EDGE))
        out.append((bx - e, by + e, w + 2 * e, h - 2 * e, BUBBLE_EDGE))
        out.append((bx, by, w, h, BUBBLE_EDGE))
        out.append((bx + e, by, w - 2 * e, h, fill))
        out.append((bx, by + e, w, h - 2 * e, fill))
        # tail toward his head
        tx = cx + self.facing * 1.5
        if kind in ("think", "dream", "logo"):
            out.append((tx - 0.5, by + h + 0.5, 1, 1, BUBBLE_EDGE))
            out.append((tx - 0.25, by + h + 0.75, 0.5, 0.5, fill))
            out.append((tx - 0.25 + self.facing * -0.5, by + h + 2, 0.5, 0.5, BUBBLE_EDGE))
        else:
            out.append((tx - 0.5, by + h, 1, 0.5, BUBBLE))
            out.append((tx - 0.5, by + h + 0.5, 0.5, 0.5, BUBBLE_EDGE))

        if kind == "logo":
            fgs = self.logo[1]
            if self.st < 1.2:
                for i in range(3):
                    out.append((bx + w / 2 - 2.5 + i * 1.75, by + h / 2 - 0.5, 1, 1, fgs[0]))
                return
            third = 1 / 3  # snap to whole 1/3 cells so every logo pixel is the same size
            lx = round((bx + (w - len(LOGO[0]) * third) / 2) * 3) * third
            ly = round((by + (h - len(LOGO) * third) / 2) * 3) * third
            n = len(LOGO[0])
            for r, row in enumerate(LOGO):
                for c, ch in enumerate(row):
                    if ch == "x":
                        out.append((lx + c * third, ly + r * third, third, third,
                                    fgs[c * len(fgs) // n]))
        elif kind == "dream":
            if self.st < 1.2:  # a wistful "..." before the scene appears
                for i in range(3):
                    out.append((bx + 3.25 + i * 1.75, by + h / 2 - 0.5, 1, 1, BUBBLE_EDGE))
            else:
                gl = GLYPHS[self.dream]
                self.glyph(out, self.dream, bx + w / 2 - len(gl[0]) * 0.25,
                           by + h / 2 - len(gl) * 0.25, 0.5, 1, self.dream != "omarchy")
        elif kind == "speak":
            gl = GLYPHS[spec[1]]
            self.glyph(out, spec[1], bx + w / 2 - len(gl[0]) * 0.25, by + 1.25, 0.5, 1)
        elif kind == "code":
            lines = [(5.5, 1, 0), (3.5, 2, 1), (6.5, 1, 2), (2.5, 3, 3)]
            total = sum(L for L, _, _ in lines)
            prog = (self.st * 6) % (total + 6)
            if prog > total + 3:
                gl = GLYPHS["check"]
                self.glyph(out, "check", bx + w / 2 - len(gl[0]) * 0.25, by + 1.25, 0.5, 1)
                return
            yy = by + 0.75
            for L, indent, ci in lines:
                n = min(L, max(0, prog))
                prog -= L
                if n > 0:
                    out.append((bx + 0.5 * indent + 0.5, yy, round(n * 2) / 2, 0.5, CODE[ci]))
                yy += 1
        elif kind == "think":
            if spec[1]:
                gl = GLYPHS[spec[1]]
                self.glyph(out, spec[1], bx + w / 2 - len(gl[0]) * 0.25, by + 0.75, 0.5, 1)
            else:
                n = int(self.st * 2.5) % 4
                for i in range(n):
                    out.append((bx + 2.25 + i * 1.75, by + 2.25, 1, 1, BUBBLE_EDGE))

    def glyph(self, out, name, x, y, px, alpha, outline=True):
        rows = GLYPHS[name]
        cells = [(c, r, ch) for r, row in enumerate(rows) for c, ch in enumerate(row) if ch != "."]
        edge = rgba("#2A1D18", 0.6 * alpha)
        o = 1 / CELL  # a 1-logical-px outline keeps light glyphs visible on any wallpaper
        for c, r, _ in cells if outline else ():
            out.append((x + c * px - o, y + r * px - o, px + 2 * o, px + 2 * o, edge))
        for c, r, ch in cells:
            out.append((x + c * px, y + r * px, px, px, rgba(PALETTE[ch], alpha)))


class Canvas(Gtk.Widget):
    def __init__(self, buddy):
        super().__init__()
        self.buddy = buddy
        self.set_size_request(GW * CELL, GH * CELL)

    def do_snapshot(self, snap):
        s = self.get_scale_factor()  # round to device pixels, so 1/3-cell logo pixels stay even

        def px(v):
            return round(v * CELL * s) / s

        for x, y, w, h, c in self.buddy.render():
            x0, y0, x1, y1 = px(x), px(y), px(x + w), px(y + h)
            if x1 > x0 and y1 > y0:
                snap.append_color(c, Graphene.Rect().init(x0, y0, x1 - x0, y1 - y0))


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="io.github.jos_jason.PixelClaude")
        self.win = None

    def do_activate(self):
        if self.win:  # launched a second time: say goodbye
            self.buddy.command("bye")
            return
        css = Gtk.CssProvider()
        css.load_from_string("window, window.background { background: transparent; }")
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        mon = Gdk.Display.get_default().get_monitors().get_item(0).get_geometry()
        self.buddy = Buddy(mon.width, mon.height)
        self.buddy.on_bye = self.quit

        win = self.win = Gtk.ApplicationWindow(application=self, title="Pixel Claude")
        LS.init_for_window(win)
        LS.set_namespace(win, "pixel-claude")
        LS.set_layer(win, LS.Layer.TOP)
        LS.set_anchor(win, LS.Edge.BOTTOM, True)
        LS.set_anchor(win, LS.Edge.LEFT, True)
        LS.set_keyboard_mode(win, LS.KeyboardMode.ON_DEMAND)
        LS.set_exclusive_zone(win, -1)

        self.canvas = Canvas(self.buddy)
        win.set_child(self.canvas)
        self.margins = (None, None)
        self.apply_margins()
        self.build_menu()
        self.attach_input()
        win.present()

        self.last = time.monotonic()
        GLib.timeout_add(1000 // FPS, self.tick)

    def apply_margins(self):
        m = (int(self.buddy.x), int(self.buddy.lift))
        if m != self.margins:
            self.margins = m
            LS.set_margin(self.win, LS.Edge.LEFT, m[0])
            LS.set_margin(self.win, LS.Edge.BOTTOM, m[1])

    def tick(self):
        now = time.monotonic()
        self.buddy.update(min(0.1, now - self.last))
        self.last = now
        self.apply_margins()
        self.canvas.queue_draw()
        return True

    def attach_input(self):
        self.dragging = False
        click = Gtk.GestureClick(button=0)
        click.connect("released", self.on_click)
        self.canvas.add_controller(click)

        drag = Gtk.GestureDrag()
        drag.connect("drag-update", self.on_drag)
        drag.connect("drag-end", self.on_drag_end)
        self.canvas.add_controller(drag)

    def on_click(self, gesture, n, x, y):
        if self.dragging:
            return
        if gesture.get_current_button() == Gdk.BUTTON_SECONDARY:
            self.menu.set_pointing_to(Gdk.Rectangle(x=int(x), y=int(y), width=1, height=1))
            self.menu.popup()
        else:
            self.buddy.pet()

    def on_drag(self, gesture, ox, oy):
        if not self.dragging and math.hypot(ox, oy) > 4:
            self.dragging = True
            self.buddy.grab()
        if self.dragging:
            # the window follows the pointer, so each offset is relative to its last position
            self.buddy.drag(ox, oy)
            self.apply_margins()

    def on_drag_end(self, gesture, ox, oy):
        if self.dragging:
            self.buddy.release()
            GLib.idle_add(self.clear_drag)

    def clear_drag(self):
        self.dragging = False
        return False

    def build_menu(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        items = [("Pet", lambda: self.buddy.pet()),
                 ("Get to work", lambda: self.buddy.command("type")),
                 ("Tidy up", lambda: self.buddy.command("sweep")),
                 ("Read a book", lambda: self.buddy.command("read")),
                 ("Coffee break", lambda: self.buddy.command("coffee")),
                 ("Daydream", lambda: self.buddy.command("daydream")),
                 ("Celebrate the season", lambda: self.buddy.command("festive")),
                 ("Omarchy love", lambda: self.buddy.command("omarchy")),
                 ("Dance", lambda: self.buddy.command("dance")),
                 ("Go exploring", lambda: self.buddy.command("explore")),
                 ("Wave the flag", lambda: self.buddy.command("flag")),
                 ("Confetti!", lambda: self.buddy.command("stomp")),
                 ("Hit the gym", lambda: self.buddy.command("gym")),
                 ("Happy & content", lambda: self.buddy.command("content")),
                 ("Laptop on the floor", lambda: self.buddy.command("sidetype")),
                 ("Nap time", lambda: self.buddy.command("sleep")),
                 ("Goodbye", lambda: self.buddy.command("bye"))]
        self.menu = Gtk.Popover(has_arrow=False)
        for label, fn in items:
            b = Gtk.Button(label=label, has_frame=False)
            b.connect("clicked", lambda _b, fn=fn: (self.menu.popdown(), fn()))
            box.append(b)
        self.menu.set_child(box)
        self.menu.set_parent(self.canvas)


def main():
    app = App()
    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, app.quit)
    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, app.quit)
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
