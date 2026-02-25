"""launcher.py  —  Unified entry point for the Russian Learning Games.

Flow
----
  Home  →  Level Test (subprocess)  →  A1 Hub  or  A2 Hub
  Hub   →  Game (subprocess)        →  back to Hub
  Hub   →  Retake Level Test        →  Home  →  Level Test

Run from the repo root
    python lvl_games/launcher.py
or from the lvl_games directory
    python launcher.py
"""

import os
import sys
import json
import math
import subprocess
import pygame
from pathlib import Path

# ── paths ──────────────────────────────────────────────────────────────────────
_HERE  = Path(__file__).resolve().parent    # lvl_games/
_ROOT  = _HERE.parent                       # repo root
PYTHON = sys.executable

PROFILE_FILE = _HERE / "player_profile.json"

CMD: dict[str, list[str]] = {
    "level_test":   [PYTHON, str(_HERE / "lvl_game_connected.py")],
    "game_animals": [PYTHON, str(_ROOT / "main.py")],
    "game_colors":  [PYTHON, str(_HERE / "game2_connected.py")],
    "game_words":   [PYTHON, str(_ROOT / "game3.py")],
}

# ── design resolution ──────────────────────────────────────────────────────────
DW, DH = 1024, 700
FPS    = 60

# ── toddler-friendly colour palette ───────────────────────────────────────────
# Backgrounds
BG_MAIN   = (245, 245, 245)   # #F5F5F5  Very Light Gray
BG_CREAM  = (255, 248, 225)   # #FFF8E1  Light Yellow

# Header / accent
CORAL     = (255, 127,  80)   # #FF7F50  Coral
CORAL_L   = (255, 168, 132)   # lighter coral (hover / gradient fade)
CORAL_D   = (228,  98,  52)   # darker coral (bottom edge stripe)

# Play button  –  Bright Green
GREEN_P   = ( 76, 175,  80)   # #4CAF50
GREEN_PL  = (108, 200, 112)   # hover

# Progress bar  –  Soft Green
GREEN_PB  = (129, 199, 132)   # #81C784

# Retake button  –  Bright Orange
ORANGE_R  = (255,  87,  34)   # #FF5722
ORANGE_RL = (255, 130,  88)   # hover

# Exit button  –  Cool Gray
GRAY_EX   = (176, 190, 197)   # #B0BEC5
GRAY_EXL  = (210, 218, 224)   # hover

# Level badge
AMBER     = (255, 193,   7)   # #FFC107
AMBER_D   = (230, 165,   0)   # border ring

# A2 accent (blue)
BLUE_A2   = ( 68, 116, 225)
BLUE_A2L  = (104, 148, 248)

# Text
TEXT_D    = ( 33,  33,  33)   # #212121  Dark Gray
TEXT_HEAD = (255, 112,  67)   # #FF7043  Soft Red-Orange (headings)
WHITE     = (255, 255, 255)
SHADOW    = (190, 185, 174)

# ── utilities ──────────────────────────────────────────────────────────────────

def _sc(v: float, s: float) -> int:
    """Scale a design-pixel value by the current window scale factor."""
    return max(1, int(v * s))


def _best_font(size: int, bold: bool = False) -> pygame.font.Font:
    """Return the friendliest available rounded font."""
    for name in ("Ubuntu", "Noto Sans", "DejaVu Sans",
                 "FreeSans", "Liberation Sans", "Arial", ""):
        try:
            f = pygame.font.SysFont(name, size, bold=bold)
            if f:
                return f
        except Exception:
            pass
    return pygame.font.Font(None, size)


def load_profile() -> dict | None:
    try:
        if PROFILE_FILE.exists():
            return json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _make_env() -> dict:
    e = os.environ.copy()
    dri = "/usr/lib/x86_64-linux-gnu/dri"
    if Path(dri).exists():
        e["LIBGL_DRIVERS_PATH"] = dri
    return e


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{int(v * 100)} %"


def _wrap(text: str, font: pygame.font.Font, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = (line + " " + word).strip()
        if font.size(candidate)[0] <= max_w:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


# ── draw primitives ────────────────────────────────────────────────────────────

def _shadow(surf: pygame.Surface, rect: pygame.Rect,
            radius: int, offset: int = 4, color: tuple = SHADOW):
    pygame.draw.rect(surf, color, rect.move(offset, offset),
                     border_radius=radius)


def draw_card(surf: pygame.Surface, rect: pygame.Rect,
              color: tuple = WHITE, radius: int = 18):
    _shadow(surf, rect, radius)
    pygame.draw.rect(surf, color, rect, border_radius=radius)


def draw_btn(surf: pygame.Surface, rect: pygame.Rect,
             label: str, font: pygame.font.Font,
             bg: tuple, light: tuple,
             hovered: bool = False, tc: tuple = WHITE,
             radius: int = 30) -> pygame.Rect:
    col = light if hovered else bg
    _shadow(surf, rect, radius, offset=4, color=(158, 152, 140))
    pygame.draw.rect(surf, col, rect, border_radius=radius)
    lbl = font.render(label, True, tc)
    surf.blit(lbl, lbl.get_rect(center=rect.center))
    return rect


def draw_progress_bar(surf: pygame.Surface, rect: pygame.Rect,
                      progress: float,
                      bg: tuple = (218, 218, 218),
                      fill: tuple = GREEN_PB,
                      radius: int = 20):
    """Rounded progress bar with animated fill."""
    pygame.draw.rect(surf, bg, rect, border_radius=radius)
    if progress > 0.01:
        fw = max(2 * radius, int(rect.w * min(progress, 1.0)))
        pygame.draw.rect(surf, fill,
                         pygame.Rect(rect.x, rect.y, fw, rect.h),
                         border_radius=radius)
    pygame.draw.rect(surf, (175, 175, 175), rect, 2, border_radius=radius)


def draw_star(surf: pygame.Surface, cx: int, cy: int,
              r: int, color: tuple, points: int = 5):
    """Draw a filled n-pointed star."""
    pts = []
    for i in range(points * 2):
        angle = math.pi / points * i - math.pi / 2
        rad   = r if i % 2 == 0 else int(r * 0.42)
        pts.append((cx + rad * math.cos(angle),
                    cy + rad * math.sin(angle)))
    if len(pts) >= 3:
        pygame.draw.polygon(surf, color, pts)


def center_text(surf: pygame.Surface, text: str,
                font: pygame.font.Font, color: tuple,
                cx: int, cy: int):
    lbl = font.render(text, True, color)
    surf.blit(lbl, lbl.get_rect(center=(cx, cy)))


# ── Launcher ───────────────────────────────────────────────────────────────────

class Launcher:
    """State-machine launcher: home → level-test → hub → game → hub."""

    def __init__(self):
        pygame.init()
        info = pygame.display.Info()
        sw   = min(info.current_w, DW)
        sh   = min(info.current_h, DH)
        self.screen  = pygame.display.set_mode((sw, sh), pygame.RESIZABLE)
        pygame.display.set_caption("Russian Learning Games")
        self.clock   = pygame.time.Clock()
        self.profile = load_profile()
        self.state   = "home"   # home | waiting | a1_hub | a2_hub | launching
        self.proc: subprocess.Popen | None = None
        self._env    = _make_env()
        self._tick   = 0
        self._hover: str | None = None
        self._bar    = 0.0      # animated progress-bar fill [0 → target]

    # ── internal helpers ───────────────────────────────────────────────────────

    def _scale(self) -> float:
        w, h = self.screen.get_size()
        return min(w / DW, h / DH)

    def _launch(self, key: str):
        self.proc  = subprocess.Popen(CMD[key], cwd=str(_ROOT), env=self._env)
        self.state = "waiting" if key == "level_test" else "launching"

    def _poll(self):
        """Check whether the active subprocess finished; update state."""
        if self.proc is None or self.proc.poll() is None:
            return
        self.proc    = None
        self.profile = load_profile()
        self._bar    = 0.0          # re-animate bar after new profile
        if self.state == "waiting":
            if self.profile:
                level      = self.profile.get("level", "A1")
                self.state = f"{level.lower()}_hub"
            else:
                self.state = "home"   # player closed window early
        else:
            level      = (self.profile or {}).get("level", "A1")
            self.state = f"{level.lower()}_hub"

    # ── HOME screen ────────────────────────────────────────────────────────────

    def draw_home(self) -> dict[str, pygame.Rect]:
        surf  = self.screen
        w, h  = surf.get_size()
        s     = self._scale()
        surf.fill(BG_MAIN)

        # ── coral header ──────────────────────────────────────────────────────
        hdr_h = _sc(158, s)
        pygame.draw.rect(surf, CORAL,   (0, 0, w, hdr_h))
        # gradient-fade bottom strip
        pygame.draw.rect(surf, CORAL_D, (0, hdr_h - _sc(18, s), w, _sc(9, s)))
        pygame.draw.rect(surf, CORAL_L, (0, hdr_h - _sc(9,  s), w, _sc(9, s)))

        # decorative stars (4 corners of header)
        STAR_C = (255, 228, 196)
        draw_star(surf, _sc(52, s),       _sc(48, s),       _sc(22, s), STAR_C)
        draw_star(surf, _sc(130, s),      _sc(106, s),      _sc(14, s), STAR_C)
        draw_star(surf, w - _sc(52, s),   _sc(48, s),       _sc(22, s), STAR_C)
        draw_star(surf, w - _sc(130, s),  _sc(106, s),      _sc(14, s), STAR_C)

        f_title = _best_font(_sc(44, s), bold=True)
        f_sub   = _best_font(_sc(22, s))
        f_btn   = _best_font(_sc(28, s), bold=True)
        f_mid   = _best_font(_sc(22, s), bold=True)
        f_small = _best_font(_sc(18, s))

        # header text
        center_text(surf, "Russian Learning Games",
                    f_title, WHITE,          w // 2, _sc(57, s))
        center_text(surf, "Учим Русский вместе!",
                    f_sub,   (255, 234, 196), w // 2, _sc(112, s))

        btns: dict[str, pygame.Rect] = {}

        if self.profile:
            level  = self.profile.get("level", "A1")
            a1_acc = self.profile.get("a1_accuracy") or 0.0
            a2_acc = self.profile.get("a2_accuracy")
            prog   = a1_acc if level == "A1" else (a2_acc or 0.0)
            lvl_c  = GREEN_P  if level == "A1" else BLUE_A2
            lvl_cl = GREEN_PL if level == "A1" else BLUE_A2L

            # ── amber level badge ──────────────────────────────────────────────
            bw, bh = _sc(340, s), _sc(66, s)
            badge  = pygame.Rect((w - bw) // 2, _sc(172, s), bw, bh)
            _shadow(surf, badge, radius=_sc(33, s), offset=4,
                    color=(190, 165, 0))
            pygame.draw.rect(surf, AMBER,   badge, border_radius=_sc(33, s))
            pygame.draw.rect(surf, AMBER_D, badge, 3, border_radius=_sc(33, s))
            center_text(surf, f"Your Level:  {level}",
                        f_btn, TEXT_D, w // 2, _sc(205, s))

            # ── animated progress bar ──────────────────────────────────────────
            target      = max(0.0, min(1.0, prog))
            self._bar  += (target - self._bar) * 0.06
            if abs(self._bar - target) < 0.003:
                self._bar = target

            pb_w = _sc(440, s)
            pb_h = _sc(40, s)
            pb   = pygame.Rect((w - pb_w) // 2, _sc(253, s), pb_w, pb_h)
            draw_progress_bar(surf, pb, self._bar, radius=_sc(20, s))

            pct_f = _best_font(_sc(18, s), bold=True)
            pct_l = pct_f.render(f"{int(self._bar * 100)} %", True, TEXT_D)
            surf.blit(pct_l, pct_l.get_rect(center=(w // 2, _sc(273, s))))

            # ── Play button (pulsing) ──────────────────────────────────────────
            pulse   = 1.0 + 0.038 * math.sin(self._tick * 0.10)
            base_gw = _sc(400, s)
            base_gh = _sc(78, s)
            gw = int(base_gw * pulse)
            gh = int(base_gh * pulse)
            go = pygame.Rect((w - gw) // 2,
                             _sc(320, s) - (gh - base_gh) // 2, gw, gh)
            draw_btn(surf, go, f"Play  Level {level}  Games!",
                     f_btn, lvl_c, lvl_cl,
                     hovered=(self._hover == "go"), radius=_sc(39, s))
            btns["go"] = go

            # ── Retake button ──────────────────────────────────────────────────
            rw, rh = _sc(296, s), _sc(58, s)
            rt = pygame.Rect((w - rw) // 2, _sc(424, s), rw, rh)
            draw_btn(surf, rt, "Retake Level Test",
                     f_mid, ORANGE_R, ORANGE_RL,
                     hovered=(self._hover == "retake_home"),
                     radius=_sc(29, s))
            btns["retake_home"] = rt

        else:
            # ── first-visit card ───────────────────────────────────────────────
            iw, ih = _sc(640, s), _sc(76, s)
            ic = pygame.Rect((w - iw) // 2, _sc(174, s), iw, ih)
            draw_card(surf, ic, color=BG_CREAM, radius=_sc(20, s))
            center_text(surf,
                        "First, let us find out your Russian level!",
                        f_mid, TEXT_D, w // 2, _sc(212, s))

            # pulsing Start button
            pulse   = 1.0 + 0.038 * math.sin(self._tick * 0.10)
            base_sw = _sc(400, s)
            base_sh = _sc(86, s)
            sw2 = int(base_sw * pulse)
            sh2 = int(base_sh * pulse)
            st  = pygame.Rect((w - sw2) // 2,
                              _sc(295, s) - (sh2 - base_sh) // 2, sw2, sh2)
            draw_btn(surf, st, "Start Level Test",
                     f_btn, CORAL, CORAL_L,
                     hovered=(self._hover == "start"), radius=_sc(43, s))
            btns["start"] = st

        # ── Exit button (bottom-right, 60 × 40, 30 px from edge) ──────────────
        ew, eh = _sc(110, s), _sc(42, s)
        ex = pygame.Rect(w - ew - _sc(30, s), h - eh - _sc(30, s), ew, eh)
        draw_btn(surf, ex, "Exit", f_small,
                 GRAY_EX, GRAY_EXL,
                 hovered=(self._hover == "exit"),
                 tc=TEXT_D, radius=_sc(21, s))
        btns["exit"] = ex

        return btns

    # ── GAME HUB screen ────────────────────────────────────────────────────────

    def draw_hub(self, level: str) -> dict[str, pygame.Rect]:
        surf  = self.screen
        w, _h = surf.get_size()
        s     = self._scale()
        surf.fill(BG_MAIN)

        if level == "A1":
            accent, accent_l = GREEN_P,  GREEN_PL
            hdr_stripe       = (52, 148, 56)
        else:
            accent, accent_l = BLUE_A2,  BLUE_A2L
            hdr_stripe       = (46,  88, 195)

        f_hdr   = _best_font(_sc(34, s), bold=True)
        f_card  = _best_font(_sc(22, s), bold=True)
        f_desc  = _best_font(_sc(15, s))
        f_play  = _best_font(_sc(24, s), bold=True)
        f_small = _best_font(_sc(17, s))

        # ── header ────────────────────────────────────────────────────────────
        hdr = _sc(88, s)
        pygame.draw.rect(surf, accent,     (0, 0, w, hdr))
        pygame.draw.rect(surf, hdr_stripe, (0, hdr - _sc(8, s), w, _sc(8, s)))
        # corner stars
        draw_star(surf, _sc(44, s),     hdr // 2, _sc(14, s), (255, 255, 200))
        draw_star(surf, w - _sc(44, s), hdr // 2, _sc(14, s), (255, 255, 200))
        center_text(surf, f"Level {level}  —  Choose a Game",
                    f_hdr, WHITE, w // 2, hdr // 2)

        btns: dict[str, pygame.Rect] = {}

        # ── two game cards ─────────────────────────────────────────────────────
        cw  = _sc(382, s)
        ch  = _sc(360, s)
        gap = _sc(36, s)
        cy  = hdr + _sc(24, s)
        x1  = (w - cw * 2 - gap) // 2
        x2  = x1 + cw + gap

        for pos_x, phase_offset, (cmd_key, title, desc, icon_col) in zip(
            [x1, x2], [0.0, math.pi], self._card_defs(level)
        ):
            r = pygame.Rect(pos_x, cy, cw, ch)
            draw_card(surf, r, color=WHITE, radius=_sc(20, s))

            # coloured icon circle with star inside
            icx = pos_x + cw // 2
            icy = cy + _sc(72, s)
            pygame.draw.circle(surf, icon_col, (icx, icy), _sc(46, s))
            pygame.draw.circle(surf, WHITE,    (icx, icy), _sc(46, s), 3)
            draw_star(surf, icx, icy, _sc(22, s), WHITE)

            # game title
            center_text(surf, title, f_card, TEXT_D, icx, cy + _sc(136, s))

            # description lines
            lines = _wrap(desc, f_desc, cw - _sc(36, s))
            dy = cy + _sc(162, s)
            for line in lines[:3]:
                lbl = f_desc.render(line, True, (105, 105, 120))
                surf.blit(lbl, lbl.get_rect(centerx=icx, y=dy))
                dy += f_desc.get_linesize() + 2

            # pulsing Play button (cards pulse slightly out-of-phase)
            pulse   = 1.0 + 0.030 * math.sin(self._tick * 0.10 + phase_offset)
            pb_bw   = _sc(162, s)
            pb_bh   = _sc(54,  s)
            pb_w    = int(pb_bw * pulse)
            pb_h    = int(pb_bh * pulse)
            pb      = pygame.Rect(pos_x + (cw - pb_w) // 2,
                                  cy + ch - _sc(76, s) - (pb_h - pb_bh) // 2,
                                  pb_w, pb_h)
            draw_btn(surf, pb, "Play!", f_play, accent, accent_l,
                     hovered=(self._hover == f"play_{cmd_key}"),
                     radius=_sc(27, s))
            btns[f"play_{cmd_key}"] = pb

        # ── bottom bar ─────────────────────────────────────────────────────────
        bar_y = cy + ch + _sc(18, s)

        hw, hh = _sc(130, s), _sc(46, s)
        hb = pygame.Rect(_sc(30, s), bar_y, hw, hh)
        draw_btn(surf, hb, "Home", f_small,
                 GRAY_EX, GRAY_EXL,
                 hovered=(self._hover == "hub_home"),
                 tc=TEXT_D, radius=_sc(23, s))
        btns["hub_home"] = hb

        rw, rh = _sc(224, s), _sc(46, s)
        rb = pygame.Rect(w - rw - _sc(30, s), bar_y, rw, rh)
        draw_btn(surf, rb, "Retake Level Test", f_small,
                 ORANGE_R, ORANGE_RL,
                 hovered=(self._hover == "retake_hub"),
                 radius=_sc(23, s))
        btns["retake_hub"] = rb

        return btns

    def _card_defs(self, level: str) -> list[tuple]:
        """(cmd_key, title, description, icon_colour) for each game card."""
        game2 = (
            "game_colors",
            "Colors & Numbers",
            "Count objects and identify colours in pictures.",
            ORANGE_R,
        )
        if level == "A1":
            return [
                ("game_animals",
                 "Animal Game",
                 "Match animal images to their Russian names!",
                 GREEN_P),
                game2,
            ]
        return [
            ("game_words",
             "Word Positions",
             "Learn Russian cases and prepositions with scenes.",
             BLUE_A2),
            game2,
        ]

    # ── WAITING / LOADING screen ───────────────────────────────────────────────

    def draw_waiting(self,
                     msg: str = "Finding Your Level...",
                     sub: str = "Complete the test window to continue"):
        surf = self.screen
        w, h = surf.get_size()
        s    = self._scale()
        surf.fill(BG_MAIN)

        # decorative background circles
        pygame.draw.circle(surf, (255, 210, 190),
                           (_sc(70, s),  _sc(70, s)),  _sc(58, s))
        pygame.draw.circle(surf, (255, 210, 190),
                           (w - _sc(70, s), h - _sc(70, s)), _sc(58, s))
        pygame.draw.circle(surf, (255, 232, 215),
                           (_sc(46, s),  h - _sc(46, s)), _sc(36, s))
        pygame.draw.circle(surf, (255, 232, 215),
                           (w - _sc(46, s), _sc(46, s)),  _sc(36, s))

        # top accent strip
        pygame.draw.rect(surf, CORAL, (0, 0, w, _sc(10, s)))

        f_big = _best_font(_sc(38, s), bold=True)
        f_sub = _best_font(_sc(20, s))
        center_text(surf, msg, f_big, TEXT_HEAD, w // 2, h // 2 - _sc(55, s))
        center_text(surf, sub, f_sub, (130, 132, 148), w // 2, h // 2)

        # three bouncing dots (coral / green / amber)
        for i, col in enumerate([CORAL, GREEN_P, AMBER]):
            phase = self._tick * 0.14 + i * math.pi * 0.72
            dy    = int(math.sin(phase) * _sc(14, s))
            cx    = w // 2 + (i - 1) * _sc(42, s)
            cy    = h // 2 + _sc(60, s) + dy
            pygame.draw.circle(surf, col, (cx, cy), _sc(13, s))

    # ── main loop ──────────────────────────────────────────────────────────────

    def run(self):
        while True:
            self._tick += 1
            events    = pygame.event.get()
            clicks:   list[tuple[int, int]] = []
            mouse_pos = pygame.mouse.get_pos()

            for ev in events:
                if ev.type == pygame.QUIT:
                    if self.proc:
                        self.proc.terminate()
                    pygame.quit()
                    sys.exit()
                if ev.type == pygame.VIDEORESIZE:
                    self.screen = pygame.display.set_mode(
                        (ev.w, ev.h), pygame.RESIZABLE
                    )
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    clicks.append(ev.pos)

            # ── draw current state ─────────────────────────────────────────────
            btns: dict[str, pygame.Rect] = {}

            if self.state == "home":
                btns = self.draw_home()
            elif self.state in ("a1_hub", "a2_hub"):
                btns = self.draw_hub("A1" if self.state == "a1_hub" else "A2")
            elif self.state == "waiting":
                self.draw_waiting()
                self._poll()
            elif self.state == "launching":
                self.draw_waiting(
                    msg="Game Running...",
                    sub="Close the game window to return here.",
                )
                self._poll()

            # ── hover highlight ────────────────────────────────────────────────
            self._hover = None
            for key, rect in btns.items():
                if rect.collidepoint(mouse_pos):
                    self._hover = key
                    break

            # ── click dispatch ─────────────────────────────────────────────────
            for pos in clicks:
                for key, rect in btns.items():
                    if rect.collidepoint(pos):
                        self._on_click(key)
                        break

            pygame.display.flip()
            self.clock.tick(FPS)

    def _on_click(self, key: str):
        if key == "exit":
            pygame.quit()
            sys.exit()
        elif key == "start":
            self._launch("level_test")
        elif key == "go":
            level      = (self.profile or {}).get("level", "A1")
            self.state = f"{level.lower()}_hub"
        elif key in ("retake_home", "retake_hub"):
            self._launch("level_test")
        elif key == "hub_home":
            self._bar  = 0.0        # re-animate bar next time home is shown
            self.state = "home"
        elif key.startswith("play_"):
            self._launch(key[len("play_"):])


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    Launcher().run()
