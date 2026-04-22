import json
import ctypes
import importlib
import logging
import math
import random
import re
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import traceback
from collections import deque
from ctypes import wintypes
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox

import pyautogui
from PIL import Image, ImageGrab

from screenshot_selector import ScreenshotSelector
from sudoku_filler import FillCancelledError, SudokuFiller
from sudoku_ocr import SudokuOCR
from sudoku_solver import SudokuSolver

_tkinterdnd2 = None
try:
    _tkinterdnd2 = importlib.import_module("tkinterdnd2")
except Exception:
    pass

DND_FILES = getattr(_tkinterdnd2, "DND_FILES", None)
TkinterDnD = getattr(_tkinterdnd2, "TkinterDnD", None)


def _rounded_canvas_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
    radius = max(0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    points = [
        x1 + radius,
        y1,
        x2 - radius,
        y1,
        x2,
        y1,
        x2,
        y1 + radius,
        x2,
        y2 - radius,
        x2,
        y2,
        x2 - radius,
        y2,
        x1 + radius,
        y2,
        x1,
        y2,
        x1,
        y2 - radius,
        x1,
        y1 + radius,
        x1,
        y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class RoundedSurface(tk.Frame):
    def __init__(self, parent, bg, border, parent_bg, radius=16, padding=6, border_width=1):
        super().__init__(parent, bg=parent_bg, bd=0, highlightthickness=0)
        self.surface_bg = bg
        self.surface_border = border
        self.surface_parent_bg = parent_bg
        self.radius = radius
        self.padding = padding
        self.border_width = border_width
        self.canvas = tk.Canvas(self, bg=parent_bg, bd=0, highlightthickness=0, relief="flat")
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.content = tk.Frame(self, bg=bg, bd=0, highlightthickness=0)
        self.content.pack(fill="both", expand=True, padx=padding, pady=padding)
        self.bind("<Configure>", self._redraw, add="+")

    def set_colors(self, bg=None, border=None, parent_bg=None):
        if bg is not None:
            self.surface_bg = bg
            self.content.configure(bg=bg)
        if border is not None:
            self.surface_border = border
        if parent_bg is not None:
            self.surface_parent_bg = parent_bg
            super().configure(bg=parent_bg)
            self.canvas.configure(bg=parent_bg)
        self._redraw()

    def _redraw(self, _event=None):
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        inset = max(0, self.border_width // 2)
        self.canvas.delete("surface")
        _rounded_canvas_rect(
            self.canvas,
            inset,
            inset,
            width - inset,
            height - inset,
            self.radius,
            fill=self.surface_bg,
            outline=self.surface_border,
            width=self.border_width,
            tags="surface",
        )
        self.canvas.tag_lower("surface")


class RoundedButton(tk.Canvas):
    _CUSTOM_OPTIONS = {
        "activebackground",
        "activeforeground",
        "anchor",
        "background",
        "bg",
        "command",
        "fg",
        "font",
        "foreground",
        "highlightbackground",
        "highlightcolor",
        "justify",
        "padx",
        "pady",
        "state",
        "text",
    }
    _IGNORED_OPTIONS = {"bd", "borderwidth", "overrelief", "relief", "takefocus"}

    def __init__(
        self,
        parent,
        text,
        command,
        bg,
        fg,
        outline=None,
        hover_bg=None,
        font=None,
        padx=8,
        pady=5,
        radius=8,
    ):
        self._button_options = {
            "text": text,
            "command": command,
            "bg": bg,
            "fg": fg,
            "activebackground": hover_bg or bg,
            "activeforeground": fg,
            "highlightbackground": outline or bg,
            "highlightcolor": outline or bg,
            "font": font or ("Microsoft YaHei UI", 9, "bold"),
            "padx": padx,
            "pady": pady,
            "anchor": "center",
            "justify": "center",
            "state": tk.NORMAL,
        }
        self.radius = radius
        self._hover = False
        self._pressed = False
        width, height = self._measure()
        parent_bg = self._parent_bg(parent)
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=parent_bg,
            bd=0,
            highlightthickness=0,
            relief="flat",
            cursor="hand2",
        )
        self.bind("<Configure>", self._redraw, add="+")
        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")
        self.bind("<ButtonPress-1>", self._on_press, add="+")
        self.bind("<ButtonRelease-1>", self._on_release, add="+")
        self._redraw()

    def configure(self, cnf=None, **kw):
        if isinstance(cnf, str):
            return self.cget(cnf)
        options = {}
        if cnf:
            options.update(cnf)
        options.update(kw)
        redraw = False
        resize = False
        canvas_options = {}
        for key, value in options.items():
            if key in self._IGNORED_OPTIONS:
                continue
            normalized = self._normalize_option(key)
            if normalized in self._CUSTOM_OPTIONS:
                self._button_options[normalized] = value
                redraw = True
                if normalized in {"text", "font", "padx", "pady"}:
                    resize = True
                continue
            canvas_options[key] = value
        if canvas_options:
            super().configure(**canvas_options)
        if resize:
            width, height = self._measure()
            super().configure(width=width, height=height)
        if redraw:
            self._redraw()

    config = configure

    def cget(self, key):
        normalized = self._normalize_option(key)
        if normalized in self._CUSTOM_OPTIONS:
            return self._button_options.get(normalized)
        return super().cget(key)

    def _normalize_option(self, key):
        if key == "background":
            return "bg"
        if key == "foreground":
            return "fg"
        return key

    def _parent_bg(self, parent):
        try:
            return parent.cget("bg")
        except tk.TclError:
            return "#ffffff"

    def _measure(self):
        font = tkfont.Font(font=self._button_options["font"])
        lines = str(self._button_options["text"]).splitlines() or [""]
        text_width = max(font.measure(line) for line in lines)
        line_height = font.metrics("linespace")
        width = text_width + int(self._button_options["padx"]) * 2 + 4
        height = line_height * len(lines) + max(0, len(lines) - 1) * 3 + int(self._button_options["pady"]) * 2
        return max(28, width), max(26, height)

    def _redraw(self, _event=None):
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        disabled = str(self._button_options.get("state")) == tk.DISABLED
        fill = self._button_options["activebackground"] if self._hover and not disabled else self._button_options["bg"]
        text_color = self._button_options["activeforeground"] if self._hover and not disabled else self._button_options["fg"]
        outline = self._button_options.get("highlightbackground") or fill
        self.delete("button")
        _rounded_canvas_rect(
            self,
            1,
            1,
            width - 1,
            height - 1,
            self.radius,
            fill=fill,
            outline=outline,
            width=1,
            tags="button",
        )
        anchor = self._button_options.get("anchor", "center")
        padx = int(self._button_options["padx"])
        if anchor in {"w", "nw", "sw"}:
            x = padx + 4
            text_anchor = "w"
        elif anchor in {"e", "ne", "se"}:
            x = width - padx - 4
            text_anchor = "e"
        else:
            x = width / 2
            text_anchor = "center"
        self.create_text(
            x,
            height / 2,
            text=self._button_options["text"],
            fill=text_color,
            font=self._button_options["font"],
            justify=self._button_options.get("justify", "center"),
            anchor=text_anchor,
            tags="button",
        )
        self.configure(cursor="arrow" if disabled else "hand2")

    def _on_enter(self, _event=None):
        self._hover = True
        self._redraw()

    def _on_leave(self, _event=None):
        self._hover = False
        self._pressed = False
        self._redraw()

    def _on_press(self, _event=None):
        if str(self._button_options.get("state")) == tk.DISABLED:
            return
        self._pressed = True

    def _on_release(self, event=None):
        if str(self._button_options.get("state")) == tk.DISABLED:
            return
        inside = event is None or (0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height())
        command = self._button_options.get("command")
        if self._pressed and inside and command is not None:
            command()
        self._pressed = False


TEACHING_STRATEGIES = [
    "single_candidate",
    "single_position",
    "row_elimination",
    "column_elimination",
    "block_elimination",
    "naked_pair",
    "hidden_pair",
    "x_wing",
]

TEACHING_STRATEGY_LABELS = {
    "single_candidate": "唯一候选数",
    "single_position": "唯一位置",
    "row_elimination": "行排除",
    "column_elimination": "列排除",
    "block_elimination": "宫排除",
    "naked_pair": "裸对",
    "hidden_pair": "隐对",
    "x_wing": "X-Wing",
}


def teaching_candidates_for_cell(board, row, col):
    if board[row][col]:
        return []
    used = set(board[row])
    used.update(board[r][col] for r in range(9))
    box_row = (row // 3) * 3
    box_col = (col // 3) * 3
    for r in range(box_row, box_row + 3):
        for c in range(box_col, box_col + 3):
            used.add(board[r][c])
    return [value for value in range(1, 10) if value not in used]


def _teaching_cell(row, col):
    return {"row": row + 1, "col": col + 1}


def _teaching_box_index(row, col):
    return (row // 3) * 3 + (col // 3) + 1


def _teaching_peer_cells(row, col):
    peers = {(row, index) for index in range(9)}
    peers.update((index, col) for index in range(9))
    box_row = (row // 3) * 3
    box_col = (col // 3) * 3
    peers.update((box_row + r, box_col + c) for r in range(3) for c in range(3))
    peers.discard((row, col))
    return peers


def _teaching_digits_text(values):
    values = sorted(value for value in set(values) if value)
    return "、".join(str(value) for value in values) if values else "无"


def _teaching_candidate_map(board):
    candidates = {}
    for row in range(9):
        for col in range(9):
            if board[row][col] == 0:
                candidates[(row, col)] = teaching_candidates_for_cell(board, row, col)
    return candidates


def _teaching_unit_definitions():
    units = []
    units.extend(("row", row, f"第{row + 1}行", [(row, col) for col in range(9)]) for row in range(9))
    units.extend(("column", col, f"第{col + 1}列", [(row, col) for row in range(9)]) for col in range(9))
    for box_row in range(3):
        for box_col in range(3):
            box = box_row * 3 + box_col
            cells = [
                (row, col)
                for row in range(box_row * 3, box_row * 3 + 3)
                for col in range(box_col * 3, box_col * 3 + 3)
            ]
            units.append(("block", box, f"第{box + 1}宫", cells))
    return units


def _teaching_highlight(board, row, col, context_cells):
    peers = sorted(_teaching_peer_cells(row, col))
    eliminated = sorted(cell for cell in peers if board[cell[0]][cell[1]])
    return {
        "row": row + 1,
        "col": col + 1,
        "block": _teaching_box_index(row, col),
        "context_cells": [_teaching_cell(r, c) for r, c in sorted(context_cells)],
        "eliminated_cells": [_teaching_cell(r, c) for r, c in eliminated],
    }


def _make_teaching_step(board, row, col, value, strategy, explanation, context_cells, unit=None):
    return {
        "step": 0,
        "total_steps": 0,
        "position": _teaching_cell(row, col),
        "value": value,
        "strategy": strategy,
        "strategy_label": TEACHING_STRATEGY_LABELS[strategy],
        "explanation": explanation,
        "highlight": _teaching_highlight(board, row, col, context_cells),
        "candidates_before": list(range(1, 10)),
        "candidates_after": [value],
        "unit": unit,
    }


def _explain_single_candidate(board, row, col, value):
    row_numbers = _teaching_digits_text(board[row])
    col_numbers = _teaching_digits_text(board[r][col] for r in range(9))
    box_row = (row // 3) * 3
    box_col = (col // 3) * 3
    block_numbers = _teaching_digits_text(
        board[r][c]
        for r in range(box_row, box_row + 3)
        for c in range(box_col, box_col + 3)
    )
    return (
        f"第{row + 1}行第{col + 1}列只能填 {value}。"
        f"因为该行已有 {row_numbers}，该列已有 {col_numbers}，"
        f"第{_teaching_box_index(row, col)}宫已有 {block_numbers}，排除后仅剩 {value}。"
    )


def _teaching_position_in_unit(unit_type, row, col):
    if unit_type == "row":
        return f"第{col + 1}列"
    if unit_type == "column":
        return f"第{row + 1}行"
    return f"第{row + 1}行第{col + 1}列"


def _teaching_exclusion_reason(board, row, col, value, unit_type):
    if unit_type != "row" and value in board[row]:
        return f"第{row + 1}行已有{value}"
    if unit_type != "column" and any(board[r][col] == value for r in range(9)):
        return f"第{col + 1}列已有{value}"
    box_row = (row // 3) * 3
    box_col = (col // 3) * 3
    if unit_type != "block":
        for r in range(box_row, box_row + 3):
            for c in range(box_col, box_col + 3):
                if board[r][c] == value:
                    return f"第{_teaching_box_index(row, col)}宫已有{value}"
    return f"候选数不包含{value}"


def _explain_single_position(board, unit_type, unit_label, cells, row, col, value):
    existing = {board[r][c] for r, c in cells if board[r][c]}
    missing = _teaching_digits_text(value for value in range(1, 10) if value not in existing)
    empty_cells = [(r, c) for r, c in cells if board[r][c] == 0]
    excluded = []
    for other_row, other_col in empty_cells:
        if (other_row, other_col) == (row, col):
            continue
        candidates = teaching_candidates_for_cell(board, other_row, other_col)
        if value in candidates:
            continue
        position = _teaching_position_in_unit(unit_type, other_row, other_col)
        reason = _teaching_exclusion_reason(board, other_row, other_col, value, unit_type)
        excluded.append(f"{position}不能填{value}（{reason}）")
    excluded_text = "；".join(excluded) if excluded else "其它位置都被行、列或宫排除"
    target_position = _teaching_position_in_unit(unit_type, row, col)
    return (
        f"{unit_label}缺少 {missing}。现在看数字 {value}：{excluded_text}。"
        f"因此{unit_label}只剩{target_position}可以放{value}，"
        f"所以第{row + 1}行第{col + 1}列填 {value}。"
    )


def find_next_teaching_step(board):
    candidates = _teaching_candidate_map(board)
    for (row, col), values in candidates.items():
        if len(values) == 1:
            value = values[0]
            return _make_teaching_step(
                board,
                row,
                col,
                value,
                "single_candidate",
                _explain_single_candidate(board, row, col, value),
                _teaching_peer_cells(row, col),
            )

    for unit_type, unit_index, label, cells in _teaching_unit_definitions():
        for value in range(1, 10):
            places = [cell for cell in cells if value in candidates.get(cell, [])]
            if len(places) == 1:
                row, col = places[0]
                return _make_teaching_step(
                    board,
                    row,
                    col,
                    value,
                    "single_position",
                    _explain_single_position(board, unit_type, label, cells, row, col, value),
                    set(cells),
                    {"type": unit_type, "index": unit_index + 1, "label": label},
                )
    return None


def build_teaching_plan(board, max_steps=81):
    working = [row[:] for row in board]
    steps = []
    message = "已生成完整教学步骤。"

    for _ in range(max_steps):
        if all(value for row in working for value in row):
            break
        step = find_next_teaching_step(working)
        if step is None:
            result = SudokuSolver(working).solve_with_uniqueness_check(max_solutions=2)
            if result["solved"]:
                message = "当前题目需要高级推理或试探法，已保留可解释的教学步骤。"
            else:
                message = "当前盘面无解或存在识别错误，请检查冲突位置后重试。"
            break
        row = step["position"]["row"] - 1
        col = step["position"]["col"] - 1
        working[row][col] = step["value"]
        steps.append(step)

    solved = all(value for row in working for value in row)
    if not solved and len(steps) >= max_steps:
        message = "教学步骤已达到缓存上限，请检查题目是否需要高级策略。"
    for index, step in enumerate(steps, start=1):
        step["step"] = index
        step["total_steps"] = len(steps)
    return {
        "steps": steps,
        "solved": solved,
        "message": message,
        "final_board": working,
    }


class SudokuApp:
    BG = "#F5F5F7"
    PANEL = "#ffffff"
    SUBTLE = "#EEF1F5"
    GRID_BG = "#D8E4F6"
    GRID_CELL = "#ffffff"
    GRID_CELL_ALT = "#F6F9FF"
    BORDER = "#D9DCE3"
    BORDER_STRONG = "#8C97A9"
    TEXT = "#1D1D1F"
    MUTED = "#6E6E73"
    PRIMARY = "#007AFF"
    PRIMARY_HOVER = "#0062CC"
    SOFT_BLUE = "#EAF2FF"
    DANGER = "#d64545"
    BOARD_STAGE = "#FFFFFF"
    BOARD_RING = "#DCE6F5"
    BOARD_SHADOW = "#E8ECF3"
    BOX_RING = "#7A92B6"
    CELL_RING = "#D3DBE9"
    CELL_RING_ACTIVE = "#B2C7E6"
    CELL_FOCUS = "#89B4FF"
    CELL_WARNING = "#f6c85f"
    SAME_NUMBER_BG = "#EAF2FF"
    MANUAL_COLOR = "#246BDB"
    OCR_COLOR = "#1D1D1F"
    FILL_COLOR = "#007AFF"
    CELL_FONT = ("Segoe UI Semibold", 16)
    CELL_FONT_LIGHT = ("Segoe UI", 16)
    CELL_WIDTH = 2
    CELL_IPAD_X = 4
    CELL_IPAD_Y = 5
    DEFAULT_PANE_RATIO = 3 / 8
    MIN_BOARD_PANEL_WIDTH = 220
    MIN_SIDEBAR_WIDTH = 180
    MIN_TEACHING_PANEL_WIDTH = 300
    MIN_SIDEBAR_ACTIONS_HEIGHT = 220
    MIN_LOG_PANEL_HEIGHT = 120
    MIN_WINDOW_OPACITY = 0.40
    BUTTON_MODE_GEOMETRY = "156x42"
    PANE_LAYOUT_KEY = "sidebar_left"
    BOARD_SHRINK_FLOOR = 0.56
    LOG_FLUSH_DELAY_MS = 60
    MAX_LOG_LINES = 400
    HISTORY_LIMIT = 60
    TURBO_STEP_DELAY = 0.008
    TURBO_CLICK_SETTLE_DELAY = 0.012
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
    THEMES = {
        "light": {
            "BG": "#F5F5F7",
            "PANEL": "#ffffff",
            "SUBTLE": "#EEF1F5",
            "GRID_BG": "#D8E4F6",
            "GRID_CELL": "#ffffff",
            "GRID_CELL_ALT": "#F6F9FF",
            "BORDER": "#D9DCE3",
            "BORDER_STRONG": "#8C97A9",
            "TEXT": "#1D1D1F",
            "MUTED": "#6E6E73",
            "PRIMARY": "#007AFF",
            "PRIMARY_HOVER": "#0062CC",
            "SOFT_BLUE": "#EAF2FF",
            "DANGER": "#d64545",
            "BOARD_STAGE": "#FFFFFF",
            "BOARD_RING": "#DCE6F5",
            "BOARD_SHADOW": "#E8ECF3",
            "BOX_RING": "#7A92B6",
            "CELL_RING": "#D3DBE9",
            "CELL_RING_ACTIVE": "#B2C7E6",
            "CELL_FOCUS": "#89B4FF",
            "CELL_WARNING": "#f6c85f",
            "SAME_NUMBER_BG": "#EAF2FF",
            "MANUAL_COLOR": "#246BDB",
            "OCR_COLOR": "#1D1D1F",
            "FILL_COLOR": "#007AFF",
            "LOG_BG": "#fbfcfe",
            "SOLUTION_BG": "#F2F7FF",
            "CONFLICT_RING": "#b63535",
        },
        "dark": {
            "BG": "#14171c",
            "PANEL": "#20242b",
            "SUBTLE": "#2b313a",
            "GRID_BG": "#3a4555",
            "GRID_CELL": "#262c35",
            "GRID_CELL_ALT": "#2d3440",
            "BORDER": "#3b4655",
            "BORDER_STRONG": "#65748a",
            "TEXT": "#eef3f8",
            "MUTED": "#a7b2c1",
            "PRIMARY": "#4c8dff",
            "PRIMARY_HOVER": "#3477e8",
            "SOFT_BLUE": "#253856",
            "DANGER": "#cc4b4b",
            "BOARD_STAGE": "#1b2027",
            "BOARD_RING": "#303946",
            "BOARD_SHADOW": "#11151a",
            "BOX_RING": "#6d7f99",
            "CELL_RING": "#465265",
            "CELL_RING_ACTIVE": "#5d7291",
            "CELL_FOCUS": "#83a6d8",
            "CELL_WARNING": "#d6a642",
            "SAME_NUMBER_BG": "#4a4424",
            "MANUAL_COLOR": "#8db4ff",
            "OCR_COLOR": "#f1f5f9",
            "FILL_COLOR": "#72d083",
            "LOG_BG": "#171b21",
            "SOLUTION_BG": "#253028",
            "CONFLICT_RING": "#a83d3d",
        },
    }

    def __init__(self, root):
        self.root = root
        self.root.title("数独助手")
        self.root.geometry("1040x720")
        self.root.minsize(860, 500)
        self.root.resizable(True, True)

        self.code_dir = Path(__file__).resolve().parent
        self.runtime_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else self.code_dir
        self.assets_dir = self.runtime_dir / "assets"
        if not self.assets_dir.exists():
            self.assets_dir = self.code_dir / "assets"
        self.icon_png_path = self.assets_dir / "sudoku_icon.png"
        self.icon_ico_path = self.assets_dir / "sudoku_icon.ico"
        self.ui_state_path = self.runtime_dir / "sudoku_gui_state.json"
        self.history_path = self.runtime_dir / "sudoku_history.json"
        self._ui_state = self._load_ui_state()

        self.ocr = SudokuOCR()
        self.filler = SudokuFiller()
        self.original_board = [[0 for _ in range(9)] for _ in range(9)]
        self.recognized_board = None
        self.solution = None
        self.grid_coords = None
        self.fill_target_window = None
        self.pinned = False
        saved_auto_fill_enabled = bool(self._ui_state.get("auto_fill_enabled", True))
        self.auto_fill_enabled = tk.BooleanVar(value=saved_auto_fill_enabled)
        self.turbo_fill_enabled = tk.BooleanVar(value=saved_auto_fill_enabled)
        self.minimize_after_fill_enabled = tk.BooleanVar(value=bool(self._ui_state.get("minimize_after_fill", False)))
        self.theme_name = tk.StringVar(value=self._load_saved_theme_name())
        saved_opacity = self._normalize_window_opacity(self._ui_state.get("window_opacity", 1.0))
        self.window_opacity_var = tk.IntVar(value=int(round(saved_opacity * 100)))
        saved_difficulty = self._ui_state.get("generate_difficulty", "中等")
        if saved_difficulty not in {"简单", "中等", "困难", "专家"}:
            saved_difficulty = "中等"
        self.generate_difficulty = tk.StringVar(value=saved_difficulty)
        self.status_var = tk.StringVar(value="可按 Ctrl+O 导入图片，方向键可移动盘面")
        self.metrics_var = tk.StringVar(value="已填 0/81 · 识别 - · 求解 - · 难度 -")
        self.last_fill_payload = None
        self.cell_sources = [["empty" for _ in range(9)] for _ in range(9)]
        self.ocr_confidence_map = None
        self.low_confidence_cells: set[tuple[int, int]] = set()
        self.selected_cell = None
        self.selected_digit = None
        self.selected_candidate_cell = None
        self.candidate_popup = None
        self.hint_popup = None
        self.hint_focus_cells: set[tuple[int, int]] = set()
        self.hint_context_cells: set[tuple[int, int]] = set()
        self.teaching_active = False
        self.teaching_steps = []
        self.teaching_current_step = -1
        self.teaching_base_board = None
        self.teaching_base_sources = None
        self.teaching_focus_cells: set[tuple[int, int]] = set()
        self.teaching_context_cells: set[tuple[int, int]] = set()
        self.teaching_elimination_cells: set[tuple[int, int]] = set()
        self.teaching_auto_play = False
        self._teaching_autoplay_job = None
        self.teaching_speed_var = tk.StringVar(value="1x")
        self.teaching_step_var = tk.StringVar(value="步骤 0 / 0")
        self.teaching_strategy_var = tk.StringVar(value="当前策略：未开始")
        self.teaching_explanation_var = tk.StringVar(value="点击“开始教学”，系统会按人类可理解策略生成分步讲解。")
        self.teaching_candidate_var = tk.StringVar(value="候选数：-")
        self.teaching_message_var = tk.StringVar(value="优先使用唯一候选数和唯一位置。")
        self.log_stage_title_var = tk.StringVar(value="等待任务")
        self.log_stage_detail_var = tk.StringVar(value="准备就绪")
        self.updating_ui = False
        self.custom_accent = self._ui_state.get("custom_accent")
        self._theme_palette = {}
        self._apply_theme_values(self.theme_name.get(), self.custom_accent)
        self.root.configure(bg=self.BG)
        self._apply_window_opacity(saved_opacity)
        self.saved_pane_ratio = self._load_saved_pane_ratio()
        self._pane_save_job = None
        self._board_resize_job = None
        self.current_cell_font_size = self.CELL_FONT[1]
        self._applied_board_metrics = None
        self._last_sidebar_wraplength = None
        self._pending_log_messages = deque()
        self._log_flush_job = None
        self._log_stage_reset_job = None
        self.log_collapsed = False
        self._recognizing = False
        self._recognition_anim_job = None
        self._recognition_anim_step = 0
        self._ocr_trigger_active = False
        self._recognition_started_at = None
        self._recognition_generation = 0
        self.pin_button = None
        self.settings_button = None
        self.button_mode_toggle_button = None
        self.settings_window = None
        self.settings_panel = None
        self.settings_theme_check = None
        self.settings_auto_fill_check = None
        self.settings_clipboard_check = None
        self.settings_minimize_fill_check = None
        self.settings_opacity_scale = None
        self.settings_opacity_value_label = None
        self.settings_accent_button = None
        self.settings_accent_preview = None
        self._settings_dark_mode_var = tk.BooleanVar(value=self.theme_name.get() == "dark")
        self._pin_hover = False
        self.button_mode_active = False
        self.button_mode_frame = None
        self.button_mode_button = None
        self.button_mode_ocr_button = None
        self._normal_window_geometry = None
        self._normal_window_minsize = None
        self.button_mode_position = self._load_saved_button_mode_position()
        self._button_mode_drag_offset = None
        self._button_mode_drag_start = None
        self._button_mode_drag_moved = False
        self._button_mode_pending_action = None
        self._enter_button_mode_job = None
        self._global_hotkey_thread = None
        self._global_hotkey_thread_id = None
        self._global_hotkey_id = 0x5344
        self._global_hotkeys_registered = False
        self._global_hotkey_retry_job = None
        self.action_buttons = []
        self.rounded_surfaces = []
        self._closing = False
        self.history = self._load_history()
        self.performance = {
            "last_ocr_ms": None,
            "last_solve_ms": None,
            "last_difficulty": None,
            "ocr_runs": 0,
            "solve_runs": 0,
            "ocr_total_ms": 0.0,
            "solve_total_ms": 0.0,
        }
        self._solution_anim_job = None
        self._solution_anim_prev_cell = None
        self._hint_clear_job = None
        self._generation_running = False
        self._drop_enabled = False
        self.clipboard_monitor_enabled = tk.BooleanVar(value=bool(self._ui_state.get("clipboard_monitor", False)))
        self._clipboard_poll_job = None
        self._last_clipboard_signature = None

        self.log_path = self.runtime_dir / "logs" / "sudoku_gui.log"
        self.logger = self._setup_logger()

        self._setup_windows_app_id()
        self._setup_window_icon()
        self._setup_ui()
        self.root.bind("<Unmap>", self._on_root_unmap, add="+")
        self._setup_global_hotkeys()
        self._setup_clipboard_monitor()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._log("INFO", "程序已启动")

    def _setup_logger(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("sudoku_gui")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()
        handler = logging.FileHandler(self.log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False
        return logger

    def _setup_windows_app_id(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Datacode.SudokuAssistant")
        except Exception:
            return

    def _setup_window_icon(self):
        self.icon_image = None
        if sys.platform == "win32" and self.icon_ico_path.exists():
            try:
                self.root.iconbitmap(default=str(self.icon_ico_path))
            except Exception:
                pass
        try:
            if self.icon_png_path.exists():
                self.icon_image = tk.PhotoImage(file=str(self.icon_png_path))
                self.root.iconphoto(True, self.icon_image)
            elif self.icon_ico_path.exists():
                self.root.iconbitmap(default=str(self.icon_ico_path))
        except Exception:
            self.icon_image = None

    def _release_tk_images(self):
        icon_image = getattr(self, "icon_image", None)
        if icon_image is None:
            return
        try:
            self.root.tk.call("image", "delete", str(icon_image))
        except tk.TclError:
            pass
        self.icon_image = None

    def _make_rounded_panel(
        self,
        parent,
        bg_role="PANEL",
        border_role="BORDER",
        parent_bg_role="BG",
        radius=16,
        padding=6,
        border_width=1,
    ):
        panel = RoundedSurface(
            parent,
            self._color_from_role(bg_role),
            self._color_from_role(border_role) if border_role else self._color_from_role(bg_role),
            self._color_from_role(parent_bg_role),
            radius=radius,
            padding=padding,
            border_width=border_width,
        )
        self.rounded_surfaces.append(
            {
                "surface": panel,
                "bg_role": bg_role,
                "border_role": border_role,
                "parent_bg_role": parent_bg_role,
            }
        )
        return panel

    def _refresh_rounded_surfaces(self):
        active_items = []
        for item in self.rounded_surfaces:
            surface = item["surface"]
            try:
                if not surface.winfo_exists():
                    continue
                bg = self._color_from_role(item["bg_role"])
                border_role = item.get("border_role")
                border = self._color_from_role(border_role) if border_role else bg
                parent_bg = self._color_from_role(item["parent_bg_role"])
                surface.set_colors(bg=bg, border=border, parent_bg=parent_bg)
                active_items.append(item)
            except tk.TclError:
                continue
        self.rounded_surfaces = active_items

    def _setup_ui(self):
        self.root.option_add("*Font", "{Microsoft YaHei UI} 10")

        self.shell = tk.Frame(self.root, bg=self.BG)
        self.shell.pack(fill="both", expand=True, padx=14, pady=14)
        self.shell.grid_columnconfigure(0, weight=1)
        self.shell.grid_rowconfigure(1, weight=1)

        self._build_topbar(self.shell)
        self.main_pane = tk.PanedWindow(self.shell, orient="horizontal", bg=self.BG, bd=0, sashwidth=10, opaqueresize=True)
        self.main_pane.grid(row=1, column=0, sticky="nsew")

        self.sidebar_column = tk.Frame(self.main_pane, bg=self.BG)
        self.sidebar_pane = tk.PanedWindow(
            self.sidebar_column,
            orient="vertical",
            bg=self.BG,
            bd=0,
            sashwidth=8,
            opaqueresize=True,
        )
        self.sidebar_pane.pack(fill="both", expand=True)
        self.sidebar_actions_pane = tk.Frame(self.sidebar_pane, bg=self.BG)
        self.sidebar_log_pane = tk.Frame(self.sidebar_pane, bg=self.BG)
        self._build_sidebar(self.sidebar_actions_pane)
        self._build_log_panel(self.sidebar_log_pane)
        self.sidebar_pane.add(self.sidebar_actions_pane, minsize=self.MIN_SIDEBAR_ACTIONS_HEIGHT)
        self.sidebar_pane.add(self.sidebar_log_pane, minsize=self.MIN_LOG_PANEL_HEIGHT)
        board_panel = self._build_board(self.main_pane)
        self._build_teaching_panel(self.main_pane)

        self.main_pane.add(self.sidebar_column, minsize=self.MIN_SIDEBAR_WIDTH)
        self.main_pane.add(board_panel, minsize=self.MIN_BOARD_PANEL_WIDTH)
        self.main_pane.bind("<ButtonRelease-1>", self._on_pane_drag_end, add="+")
        self.main_pane.bind("<Configure>", self._schedule_board_resize, add="+")
        self._setup_pin_control()
        self._setup_shortcuts()
        self._setup_file_drop()
        self._update_metrics()
        self.root.after_idle(self._restore_pane_ratio)

    def _build_topbar_legacy(self, parent):
        top = tk.Frame(parent, bg=self.BG)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        top.grid_columnconfigure(0, weight=1)

        title_box = tk.Frame(top, bg=self.BG)
        title_box.grid(row=0, column=0, sticky="w")

        pin_wrap = tk.Frame(top, bg=self.BG)
        pin_wrap.grid(row=0, column=1, sticky="e")
        self.pin_button = tk.Button(
            pin_wrap,
            text="",
            command=self.on_toggle_pin,
            bg=self.BG,
            fg=self.MUTED,
            activebackground=self.BG,
            activeforeground=self.PRIMARY,
            relief="flat",
            bd=0,
            padx=6,
            pady=4,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        self.pin_button.pack(side="right")

    def _build_topbar(self, parent):
        top = tk.Frame(parent, bg=self.BG)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        top.grid_columnconfigure(0, weight=1)
        top.bind("<Configure>", self._update_sidebar_wraplength, add="+")

        title_box = tk.Frame(top, bg=self.BG)
        title_box.grid(row=0, column=0, sticky="ew")
        title_box.grid_columnconfigure(0, weight=1)

        summary_row = tk.Frame(title_box, bg=self.BG)
        summary_row.grid(row=0, column=0, sticky="ew")
        summary_row.grid_columnconfigure(0, weight=1)
        self.status_label = tk.Label(
            summary_row,
            textvariable=self.status_var,
            bg=self.BG,
            fg=self.TEXT,
            font=("Microsoft YaHei UI", 9),
            anchor="w",
            justify="left",
            wraplength=240,
        )
        self.status_label.grid(row=0, column=0, sticky="ew")
        self.metrics_label = tk.Label(
            summary_row,
            textvariable=self.metrics_var,
            bg=self.BG,
            fg=self.MUTED,
            font=("Microsoft YaHei UI", 8),
            anchor="e",
            justify="right",
        )
        self.metrics_label.grid(row=0, column=1, sticky="e", padx=(14, 0))

        self.topbar_tools = tk.Frame(top, bg=self.BG)
        self.topbar_tools.grid(row=0, column=1, sticky="e")

        self.button_mode_toggle_button = self._make_action_button(
            self.topbar_tools,
            "按钮模式",
            self.on_request_button_mode,
            self.PANEL,
            self.TEXT,
            outline=self.BORDER,
            hover_bg=self.SOFT_BLUE,
            padx=10,
            pady=4,
        )
        self.button_mode_toggle_button.pack(side="right", padx=(0, 8))

        self.settings_button = self._make_action_button(
            self.topbar_tools,
            "设置",
            self.on_open_settings,
            self.PANEL,
            self.TEXT,
            outline=self.BORDER,
            hover_bg=self.SOFT_BLUE,
            font=("Microsoft YaHei UI", 9, "bold"),
            padx=10,
            pady=4,
        )
        self.settings_button.pack(side="right", padx=(0, 8))

    def _setup_pin_control(self):
        self._create_inline_pin()

    def _create_inline_pin(self):
        if not hasattr(self, "topbar_tools") or self.pin_button is not None:
            return
        pin_wrap = tk.Frame(self.topbar_tools, bg=self.BG)
        pin_wrap.pack(side="right", anchor="n", padx=(0, 8))
        self.pin_button = self._make_action_button(
            pin_wrap,
            "置顶",
            self.on_toggle_pin,
            self.PANEL,
            self.TEXT,
            outline=self.BORDER,
            hover_bg=self.SOFT_BLUE,
            padx=8,
            pady=4,
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        self.pin_button.pack(side="right")
        self.pin_button.bind("<Enter>", self._on_pin_enter, add="+")
        self.pin_button.bind("<Leave>", self._on_pin_leave, add="+")
        self._refresh_pin_visual()

    def _build_button_mode_frame(self):
        if self.button_mode_frame is not None:
            return
        frame = tk.Frame(self.root, bg=self.BG, padx=4, pady=4)
        self.button_mode_frame = frame
        buttons = tk.Frame(frame, bg=self.BG)
        buttons.pack(fill="both", expand=True)
        self.button_mode_button = tk.Label(
            buttons,
            text="展开",
            bg=self.PRIMARY,
            fg="white",
            activebackground=self.PRIMARY_HOVER,
            activeforeground="white",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=self.PRIMARY,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9, "bold"),
            padx=14,
            pady=7,
        )
        self.button_mode_button.pack(side="left", fill="both", expand=True)
        self.button_mode_ocr_button = tk.Label(
            buttons,
            text="识别",
            bg=self.SOFT_BLUE,
            fg=self.TEXT,
            activebackground=self._hover_color(self.SOFT_BLUE),
            activeforeground=self.TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=self.BORDER,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9, "bold"),
            padx=10,
            pady=7,
        )
        self.button_mode_ocr_button.pack(side="left", padx=(6, 0))
        self._bind_button_mode_widget(frame, self.on_exit_button_mode)
        self._bind_button_mode_widget(buttons, self.on_exit_button_mode)
        self._bind_button_mode_widget(self.button_mode_button, self.on_exit_button_mode)
        self._bind_button_mode_widget(self.button_mode_ocr_button, self.on_ocr)

    def _bind_button_mode_widget(self, widget, action):
        widget.bind("<ButtonPress-1>", lambda event, command=action: self._on_button_mode_drag_start(event, command), add="+")
        widget.bind("<B1-Motion>", self._on_button_mode_drag, add="+")
        widget.bind("<ButtonRelease-1>", self._on_button_mode_release, add="+")

    def _button_mode_geometry(self):
        if self.button_mode_position:
            x = int(self.button_mode_position["x"])
            y = int(self.button_mode_position["y"])
            return f"{self.BUTTON_MODE_GEOMETRY}+{x}+{y}"
        return self.BUTTON_MODE_GEOMETRY

    def _button_mode_topmost_enabled(self):
        return True if self.button_mode_active else self.pinned

    def _apply_button_mode_window_state(self):
        self.root.overrideredirect(True)
        self.root.geometry(self._button_mode_geometry())
        self.root.attributes("-topmost", True)

    def _on_button_mode_drag_start(self, event, action=None):
        self._button_mode_pending_action = action
        try:
            self._button_mode_drag_offset = (
                int(event.x_root) - self.root.winfo_x(),
                int(event.y_root) - self.root.winfo_y(),
            )
            self._button_mode_drag_start = (int(event.x_root), int(event.y_root))
        except (tk.TclError, TypeError, ValueError):
            self._button_mode_drag_offset = None
            self._button_mode_drag_start = None
        self._button_mode_drag_moved = False

    def _on_button_mode_drag(self, event):
        if not self.button_mode_active or self._button_mode_drag_offset is None:
            return
        try:
            event_x = int(event.x_root)
            event_y = int(event.y_root)
        except (TypeError, ValueError):
            return
        offset_x, offset_y = self._button_mode_drag_offset
        target_x = event_x - offset_x
        target_y = event_y - offset_y
        if self._button_mode_drag_start is not None:
            start_x, start_y = self._button_mode_drag_start
            self._button_mode_drag_moved = self._button_mode_drag_moved or abs(event_x - start_x) > 3 or abs(event_y - start_y) > 3
        try:
            self.root.geometry(f"{self.BUTTON_MODE_GEOMETRY}+{target_x}+{target_y}")
            self.button_mode_position = {"x": target_x, "y": target_y}
        except tk.TclError:
            pass

    def _on_button_mode_release(self, _event=None):
        moved = self._button_mode_drag_moved
        action = self._button_mode_pending_action
        self._button_mode_drag_offset = None
        self._button_mode_drag_start = None
        self._button_mode_drag_moved = False
        self._button_mode_pending_action = None
        if moved:
            self._schedule_ui_state_save()
            return
        if action is not None:
            action()
            return
        self.on_exit_button_mode()

    def on_request_button_mode(self):
        if self.button_mode_active or self._closing:
            return False
        if self._enter_button_mode_job is not None:
            return True

        def enter():
            self._enter_button_mode_job = None
            if not self.button_mode_active and not self._closing:
                self.on_enter_button_mode()

        try:
            self._enter_button_mode_job = self.root.after(80, enter)
        except (tk.TclError, RuntimeError):
            self._enter_button_mode_job = None
            self.on_enter_button_mode()
        return True

    def on_enter_button_mode(self):
        if self.button_mode_active:
            return
        self._close_settings_window()
        self._hide_candidate_popup()
        self._build_button_mode_frame()
        self._ensure_global_hotkeys()

        self.button_mode_active = True
        self._normal_window_geometry = self.root.geometry()
        try:
            self._normal_window_minsize = self.root.minsize()
        except tk.TclError:
            self._normal_window_minsize = (860, 500)

        self.shell.pack_forget()
        self.button_mode_frame.pack(fill="both", expand=True)
        try:
            self.root.minsize(1, 1)
            self.root.resizable(False, False)
            self._apply_button_mode_window_state()
        except tk.TclError:
            pass
        self._set_status("已进入按钮模式，可点击识别或展开完整界面")

    def on_exit_button_mode(self):
        if not self.button_mode_active:
            return
        self.button_mode_active = False

        if self.button_mode_frame is not None:
            self.button_mode_frame.pack_forget()
        self.shell.pack(fill="both", expand=True, padx=14, pady=14)
        try:
            self.root.overrideredirect(False)
            min_width, min_height = self._normal_window_minsize or (860, 500)
            self.root.minsize(min_width, min_height)
            self.root.resizable(True, True)
            if self._normal_window_geometry:
                self.root.geometry(self._normal_window_geometry)
            self.root.attributes("-topmost", self.pinned)
        except tk.TclError:
            pass
        self._normal_window_geometry = None
        self._normal_window_minsize = None
        self._restore_pane_ratio()
        self._schedule_board_resize()
        self._set_status("已恢复完整界面")

    def _on_pin_enter(self, _event=None):
        self._pin_hover = True
        self._refresh_pin_visual()

    def _on_pin_leave(self, _event=None):
        self._pin_hover = False
        self._refresh_pin_visual()

    def _refresh_pin_visual(self):
        if self.pin_button is None:
            return
        if self.pinned:
            bg = self.PRIMARY_HOVER if self._pin_hover else self.PRIMARY
            fg = "white"
            active_bg = self.PRIMARY_HOVER
            relief = "sunken"
            text = "已置顶"
            border = self.PRIMARY
        else:
            bg = self.SOFT_BLUE if self._pin_hover else self.PANEL
            fg = self.PRIMARY if self._pin_hover else self.TEXT
            active_bg = self._hover_color(self.SOFT_BLUE)
            relief = "raised"
            text = "置顶"
            border = self.BORDER
        self.pin_button.config(
            text=text,
            bg=bg,
            fg=fg,
            activebackground=active_bg,
            activeforeground=fg,
            relief=relief,
            highlightbackground=border,
        )

    def _build_board_legacy(self, parent):
        board_panel = tk.Frame(parent, bg=self.PANEL, highlightthickness=1, highlightbackground=self.BORDER)

        info = tk.Frame(board_panel, bg=self.PANEL)
        info.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(info, text="盘面", bg=self.PANEL, fg=self.TEXT, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")

        holder = tk.Frame(board_panel, bg=self.PANEL, padx=12, pady=12)
        holder.pack()

        self.grid_frame = tk.Frame(holder, bg=self.GRID_BG, padx=2, pady=2)
        self.grid_frame.pack()
        self.cells = [[None for _ in range(9)] for _ in range(9)]

        for box_row in range(3):
            for box_col in range(3):
                subgrid = tk.Frame(self.grid_frame, bg=self.BORDER_STRONG)
                subgrid.grid(row=box_row, column=box_col, padx=1, pady=1)
                for inner_row in range(3):
                    for inner_col in range(3):
                        row = box_row * 3 + inner_row
                        col = box_col * 3 + inner_col
                        bg = self._cell_base_bg(row, col)
                        entry = tk.Entry(
                            subgrid,
                            width=self.CELL_WIDTH,
                            justify="center",
                            bg=bg,
                            fg=self.TEXT,
                            relief="flat",
                            bd=0,
                            highlightthickness=1,
                            highlightbackground="#d7e0ea",
                            highlightcolor=self.PRIMARY,
                            insertbackground=self.TEXT,
                            font=self.CELL_FONT,
                        )
                        entry.grid(row=inner_row, column=inner_col, padx=1, pady=1, ipady=self.CELL_IPAD_Y)
                        entry.bind("<KeyRelease>", lambda _e, r=row, c=col: self._on_cell_edit(r, c))
                        entry.bind("<FocusOut>", lambda _e, r=row, c=col: self._on_cell_edit(r, c))
                        self.cells[row][col] = entry
        return board_panel

    def _build_board(self, parent):
        board_panel = self._make_rounded_panel(parent, radius=18, padding=5)
        self.board_panel = board_panel
        board_body = board_panel.content

        info = tk.Frame(board_body, bg=self.PANEL)
        self.board_info = info
        info.pack(fill="x", padx=14, pady=(12, 3))
        tk.Label(info, text="盘面", bg=self.PANEL, fg=self.TEXT, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")

        holder = tk.Frame(board_body, bg=self.PANEL, padx=12, pady=10)
        self.board_holder = holder
        holder.pack(fill="both", expand=True)
        holder.pack_propagate(False)
        holder.bind("<Configure>", self._schedule_board_resize, add="+")

        stage = self._make_rounded_panel(
            holder,
            bg_role="BOARD_STAGE",
            border_role="BOARD_RING",
            parent_bg_role="PANEL",
            radius=20,
            padding=5,
        )
        self.board_stage = stage
        stage.place(relx=0.5, rely=0.5, anchor="center")
        stage.pack_propagate(False)

        shadow = self._make_rounded_panel(
            stage.content,
            bg_role="BOARD_SHADOW",
            border_role=None,
            parent_bg_role="BOARD_STAGE",
            radius=16,
            padding=4,
            border_width=0,
        )
        self.board_shadow = shadow
        shadow.place(relx=0.5, rely=0.5, anchor="center")

        self.grid_frame = tk.Frame(shadow.content, bg=self.BOX_RING)
        self.grid_frame.place(relx=0.5, rely=0.5, anchor="center")
        self.cells = [[None for _ in range(9)] for _ in range(9)]
        self.cell_frames = [[None for _ in range(9)] for _ in range(9)]
        self.subgrids = []

        for box_row in range(3):
            for box_col in range(3):
                subgrid = tk.Frame(self.grid_frame, bg=self.CELL_RING, padx=2, pady=2)
                subgrid.grid(row=box_row, column=box_col, padx=3, pady=3)
                self.subgrids.append(subgrid)
                for inner_row in range(3):
                    for inner_col in range(3):
                        row = box_row * 3 + inner_row
                        col = box_col * 3 + inner_col
                        bg = self._cell_base_bg(row, col)
                        cell_frame = tk.Frame(subgrid, bg=self.CELL_RING, padx=1, pady=1)
                        cell_frame.grid(row=inner_row, column=inner_col, padx=1, pady=1)
                        cell_frame.grid_propagate(False)
                        cell_frame.pack_propagate(False)
                        entry = tk.Entry(
                            cell_frame,
                            width=1,
                            justify="center",
                            bg=bg,
                            fg=self.TEXT,
                            relief="flat",
                            bd=0,
                            highlightthickness=0,
                            insertbackground=self.TEXT,
                            selectbackground=self.PRIMARY,
                            selectforeground="white",
                            font=self.CELL_FONT,
                        )
                        entry.pack(fill="both", expand=True)
                        entry.bind("<KeyPress>", lambda e, r=row, c=col: self._on_cell_keypress(r, c, e), add="+")
                        entry.bind("<KeyRelease>", lambda _e, r=row, c=col: self._on_cell_edit(r, c))
                        entry.bind("<FocusOut>", lambda _e, r=row, c=col: self._on_cell_edit(r, c))
                        entry.bind("<Button-1>", lambda e, r=row, c=col: self._on_cell_click(r, c, e), add="+")
                        self.cells[row][col] = entry
                        self.cell_frames[row][col] = cell_frame
        self._build_recognition_overlay()
        self.board_panel.bind("<Configure>", self._schedule_board_resize, add="+")
        self.root.after_idle(self._resize_board_to_fit)
        return board_panel

    def _build_recognition_overlay(self):
        self.recognition_overlay = tk.Frame(self.board_stage, bg=self.BOARD_STAGE)
        self.recognition_canvas = tk.Canvas(
            self.recognition_overlay,
            bg=self.BOARD_STAGE,
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        self.recognition_canvas.pack(fill="both", expand=True)
        self.recognition_overlay.bind("<Configure>", lambda _event: self._draw_recognition_overlay())

    def _draw_recognition_overlay(self):
        if not hasattr(self, "recognition_canvas"):
            return
        try:
            canvas = self.recognition_canvas
            canvas.delete("all")
            width = max(1, canvas.winfo_width())
            height = max(1, canvas.winfo_height())
            canvas.create_rectangle(0, 0, width, height, fill=self.BOARD_STAGE, outline="")

            board_bounds = self._draw_board_snapshot_on_canvas(canvas)
            if board_bounds is None:
                board_bounds = self._draw_placeholder_board(canvas, width, height)

            left, top, right, bottom = board_bounds
            canvas.create_rectangle(left, top, right, bottom, fill=self.SOFT_BLUE, outline="", stipple="gray50")
            scan_height = max(10, int((bottom - top) * 0.08))
            scan_span = max(1, int(bottom - top + scan_height * 2))
            scan_y = top - scan_height + (self._recognition_anim_step * 11) % scan_span
            canvas.create_rectangle(left, scan_y, right, scan_y + scan_height, fill=self.PRIMARY, outline="", stipple="gray25")
        except tk.TclError:
            return

    def _draw_board_snapshot_on_canvas(self, canvas):
        try:
            canvas_x = canvas.winfo_rootx()
            canvas_y = canvas.winfo_rooty()
        except tk.TclError:
            return None

        cell_rects = []
        for row in range(9):
            for col in range(9):
                frame = self.cell_frames[row][col]
                if frame.winfo_width() <= 1 or frame.winfo_height() <= 1:
                    return None
                x1 = frame.winfo_rootx() - canvas_x
                y1 = frame.winfo_rooty() - canvas_y
                x2 = x1 + frame.winfo_width()
                y2 = y1 + frame.winfo_height()
                cell_rects.append((row, col, x1, y1, x2, y2))

        left = min(rect[2] for rect in cell_rects) - 6
        top = min(rect[3] for rect in cell_rects) - 6
        right = max(rect[4] for rect in cell_rects) + 6
        bottom = max(rect[5] for rect in cell_rects) + 6
        canvas.create_rectangle(left - 6, top - 6, right + 6, bottom + 6, fill=self.BOARD_SHADOW, outline=self.BOARD_RING)
        canvas.create_rectangle(left, top, right, bottom, fill=self.GRID_BG, outline=self.BOX_RING, width=2)

        for row, col, x1, y1, x2, y2 in cell_rects:
            source = self.cell_sources[row][col]
            base_bg = self._cell_base_bg(row, col)
            frame_color = self.CELL_RING_ACTIVE if source in {"manual", "solution"} else self.CELL_RING
            canvas.create_rectangle(x1, y1, x2, y2, fill=frame_color, outline="")
            canvas.create_rectangle(x1 + 1, y1 + 1, x2 - 1, y2 - 1, fill=base_bg, outline="")
            value = self.cells[row][col].get().strip()[:1]
            if value:
                font_size = max(8, getattr(self, "current_cell_font_size", self.CELL_FONT[1]))
                canvas.create_text(
                    (x1 + x2) / 2,
                    (y1 + y2) / 2,
                    text=value,
                    fill=self._overlay_text_color(source),
                    font=self._cell_font_for_source(source, font_size),
                )

        first_row = [rect for rect in cell_rects if rect[0] == 0]
        first_col = [rect for rect in cell_rects if rect[1] == 0]
        first_row.sort(key=lambda rect: rect[1])
        first_col.sort(key=lambda rect: rect[0])
        xs = [first_row[index][2] for index in range(9)] + [first_row[-1][4]]
        ys = [first_col[index][3] for index in range(9)] + [first_col[-1][5]]
        thin_width, thick_width = self._board_line_widths(min(xs[-1] - xs[0], ys[-1] - ys[0]))
        for index in range(10):
            line_width = thick_width if index % 3 == 0 else thin_width
            line_color = self.BOX_RING if index % 3 == 0 else self.CELL_RING
            canvas.create_line(xs[index], ys[0], xs[index], ys[-1], fill=line_color, width=line_width)
            canvas.create_line(xs[0], ys[index], xs[-1], ys[index], fill=line_color, width=line_width)
        return left - 6, top - 6, right + 6, bottom + 6

    def _draw_placeholder_board(self, canvas, width, height):
        size = max(110, min(width, height) - 44)
        left = (width - size) / 2
        top = (height - size) / 2
        cell = size / 9
        canvas.create_rectangle(left - 12, top - 12, left + size + 12, top + size + 12, fill=self.BOARD_SHADOW, outline=self.BOARD_RING)
        for row in range(9):
            for col in range(9):
                x1 = left + col * cell
                y1 = top + row * cell
                x2 = left + (col + 1) * cell
                y2 = top + (row + 1) * cell
                bg = self._cell_base_bg(row, col)
                canvas.create_rectangle(x1, y1, x2, y2, fill=bg, outline=self.CELL_RING)
        thin_width, thick_width = self._board_line_widths(size)
        for index in range(10):
            line_width = thick_width if index % 3 == 0 else thin_width
            pos = left + index * cell
            canvas.create_line(pos, top, pos, top + size, fill=self.BOX_RING if index % 3 == 0 else self.CELL_RING, width=line_width)
            pos = top + index * cell
            canvas.create_line(left, pos, left + size, pos, fill=self.BOX_RING if index % 3 == 0 else self.CELL_RING, width=line_width)
        return left - 12, top - 12, left + size + 12, top + size + 12

    def _overlay_text_color(self, source):
        if source == "solution":
            return self.FILL_COLOR
        if source == "manual":
            return self.MANUAL_COLOR
        if source == "ocr":
            return self.TEXT
        return self.TEXT

    def _create_canvas_round_rect(self, canvas, x1, y1, x2, y2, radius, **kwargs):
        radius = min(radius, (x2 - x1) / 2, (y2 - y1) / 2)
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        return canvas.create_polygon(points, smooth=True, **kwargs)

    def _next_recognition_generation(self):
        self._recognition_generation += 1
        return self._recognition_generation

    def _is_recognition_generation_current(self, generation):
        return generation == self._recognition_generation

    def _cancel_active_recognition(self, reason="已取消当前识别", silent=False):
        if not (self._recognizing or self._ocr_trigger_active):
            return False
        self._next_recognition_generation()
        self._ocr_trigger_active = False
        self._recognition_started_at = None
        self._stop_recognition_animation(force=True)
        self._restore_window()
        if not silent:
            self._log("WARNING", reason)
        self._set_status("识别已取消，可重新按 F2 截图")
        return True

    def _start_recognition_animation(self, generation=None):
        def start():
            if self._recognition_anim_job is not None:
                self.root.after_cancel(self._recognition_anim_job)
                self._recognition_anim_job = None
            self._recognizing = True
            self._recognition_anim_step = 0
            self.board_holder.focus_set()
            self.root.update_idletasks()
            self.recognition_overlay.place(x=0, y=0, relwidth=1, relheight=1)
            self.recognition_overlay.lift()
            self._animate_recognition_overlay()

        self._run_on_ui_thread(start)

    def _animate_recognition_overlay(self):
        if not self._recognizing:
            self._recognition_anim_job = None
            return
        self._draw_recognition_overlay()
        self._recognition_anim_step += 1
        self._recognition_anim_job = self.root.after(120, self._animate_recognition_overlay)

    def _stop_recognition_animation(self, generation=None, force=False):
        def stop():
            if not force and generation is not None and not self._is_recognition_generation_current(generation):
                return
            self._recognizing = False
            if self._recognition_anim_job is not None:
                self.root.after_cancel(self._recognition_anim_job)
                self._recognition_anim_job = None
            if hasattr(self, "recognition_overlay"):
                self.recognition_overlay.place_forget()

        self._run_on_ui_thread(stop)

    def _make_legend_chip(self, parent, text, bg, fg):
        return tk.Label(
            parent,
            text=text,
            bg=bg,
            fg=fg,
            padx=7,
            pady=2,
            relief="flat",
            bd=0,
            font=("Segoe UI", 8, "bold"),
        )

    def _schedule_board_resize(self, _event=None):
        if self._board_resize_job is not None:
            self.root.after_cancel(self._board_resize_job)
        self._board_resize_job = self.root.after(60, self._resize_board_to_fit)

    def _resize_board_to_fit(self):
        self._board_resize_job = None
        if not hasattr(self, "board_holder"):
            return
        holder_width = self.board_holder.winfo_width()
        holder_height = self.board_holder.winfo_height()
        if holder_width <= 1 or holder_height <= 1:
            return

        available = max(150, min(holder_width, holder_height) - 8)
        metrics = self._board_metrics_for_available(available)
        if self._apply_board_metrics(metrics):
            self._refresh_all_cell_styles()
        if self._recognizing:
            self._draw_recognition_overlay()

    def _cell_font_for_source(self, source, size):
        if source == "solution":
            return ("Segoe UI", max(8, size - 1))
        if source in {"ocr", "manual"}:
            return ("Segoe UI Semibold", size)
        return ("Segoe UI", size)

    def _board_box_tint(self):
        return self.BOARD_RING if self.theme_name.get() == "dark" else self.PRIMARY

    def _cell_base_bg(self, row, col, base_bg=None):
        bg = base_bg if base_bg is not None else (self.GRID_CELL if (row + col) % 2 == 0 else self.GRID_CELL_ALT)
        if (row // 3 + col // 3) % 2 == 1:
            blend = 0.08 if self.theme_name.get() == "dark" else 0.045
            bg = self._blend_color(bg, self._board_box_tint(), blend)
        return bg

    def _board_line_widths(self, board_span):
        thick = max(3, int(round(board_span / 135)))
        thin = max(1, int(round(thick / 3)))
        return thin, thick

    def _board_metrics_for_available(self, board_size):
        stage_size = max(150, int(board_size))
        stage_pad = max(10, min(26, stage_size // 18))
        shadow_pad = max(3, min(8, stage_size // 58))
        grid_pad = max(4, min(10, stage_size // 50))
        box_pad = max(2, min(4, stage_size // 120))
        box_gap = max(4, min(9, stage_size // 55))
        cell_gap = max(1, min(2, stage_size // 150))
        fixed = (stage_pad + shadow_pad + grid_pad) * 2 + box_gap * 6 + box_pad * 6 + cell_gap * 18
        cell_size = max(16, (stage_size - fixed) // 9)
        grid_size = grid_pad * 2 + box_gap * 6 + box_pad * 6 + cell_gap * 18 + cell_size * 9
        shadow_size = grid_size + shadow_pad * 2
        content_size = shadow_size + stage_pad * 2
        if content_size > stage_size:
            overflow = content_size - stage_size
            cell_size = max(14, cell_size - ((overflow + 8) // 9))
            grid_size = grid_pad * 2 + box_gap * 6 + box_pad * 6 + cell_gap * 18 + cell_size * 9
            shadow_size = grid_size + shadow_pad * 2
            content_size = shadow_size + stage_pad * 2
        font_size = max(8, min(24, int(cell_size * 0.52)))
        return {
            "font_size": font_size,
            "stage_size": stage_size,
            "stage_pad": stage_pad,
            "shadow_size": shadow_size,
            "shadow_pad": shadow_pad,
            "grid_size": grid_size,
            "grid_pad": grid_pad,
            "box_pad": box_pad,
            "box_gap": box_gap,
            "cell_gap": cell_gap,
            "cell_size": cell_size,
        }

    def _apply_board_metrics(self, metrics):
        signature = tuple(metrics[key] for key in (
            "font_size",
            "stage_size",
            "stage_pad",
            "shadow_size",
            "shadow_pad",
            "grid_size",
            "grid_pad",
            "box_pad",
            "box_gap",
            "cell_gap",
            "cell_size",
        ))
        if signature == self._applied_board_metrics:
            return False

        font_size = metrics["font_size"]
        font_changed = font_size != self.current_cell_font_size
        self.current_cell_font_size = font_size
        self.board_holder.config(padx=0, pady=0)
        self.board_stage.place_configure(
            relx=0.5,
            rely=0.5,
            anchor="center",
            width=metrics["stage_size"],
            height=metrics["stage_size"],
        )
        self.board_shadow.place_configure(
            relx=0.5,
            rely=0.5,
            anchor="center",
            width=metrics["shadow_size"],
            height=metrics["shadow_size"],
        )
        self.board_shadow.config(padx=0, pady=0)
        self.grid_frame.place_configure(
            relx=0.5,
            rely=0.5,
            anchor="center",
            width=metrics["grid_size"],
            height=metrics["grid_size"],
        )
        self.grid_frame.config(padx=metrics["grid_pad"], pady=metrics["grid_pad"])

        for subgrid in getattr(self, "subgrids", []):
            subgrid.config(padx=metrics["box_pad"], pady=metrics["box_pad"])
            subgrid.grid_configure(padx=metrics["box_gap"], pady=metrics["box_gap"])

        for row in range(9):
            for col in range(9):
                frame = self.cell_frames[row][col]
                cell = self.cells[row][col]
                frame.config(width=metrics["cell_size"], height=metrics["cell_size"], padx=1, pady=1)
                frame.grid_configure(padx=metrics["cell_gap"], pady=metrics["cell_gap"])
                cell.config(width=1)
                cell.pack_configure(fill="both", expand=True, ipadx=0, ipady=0)
        self._applied_board_metrics = signature
        return font_changed

    def _build_sidebar_legacy(self, parent):
        side = tk.Frame(parent, bg=self.BG)
        side.pack(fill="x")

        actions = tk.Frame(side, bg=self.PANEL, highlightthickness=1, highlightbackground=self.BORDER)
        actions.pack(fill="x")
        tk.Label(actions, text="功能", bg=self.PANEL, fg=self.TEXT, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=12, pady=(10, 6))

        btns = tk.Frame(actions, bg=self.PANEL)
        btns.pack(fill="x", padx=10, pady=(0, 8))
        btns.grid_columnconfigure(0, weight=1)
        btns.grid_columnconfigure(1, weight=1)

        self._make_action_button(
            btns,
            "▣ 截图识别\nF2",
            self.on_ocr,
            self.PRIMARY,
            "white",
            outline=self.PRIMARY,
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=10,
            pady=9,
        ).grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self._make_action_button(
            btns,
            "◎ 导入图片\nCtrl+O",
            self.on_import_image,
            self.SOFT_BLUE,
            self.TEXT,
            outline=self.BORDER,
            hover_bg=self._blend_color(self.SOFT_BLUE, self.PRIMARY, 0.12),
            padx=10,
            pady=8,
        ).grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        self._make_action_button(
            btns,
            "▶ 一键求解\nCtrl+Enter",
            self.on_solve,
            self.FILL_COLOR,
            "white",
            outline=self.FILL_COLOR,
            hover_bg=self._blend_color(self.FILL_COLOR, "#000000", 0.14),
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=10,
            pady=9,
        ).grid(row=1, column=0, sticky="ew", padx=4, pady=4)
        self._make_action_button(
            btns,
            "◇ 生成题目\nCtrl+G",
            self.on_generate_puzzle,
            self.SOFT_BLUE,
            self.TEXT,
            outline=self.BORDER,
            hover_bg=self._blend_color(self.SOFT_BLUE, self.FILL_COLOR, 0.08),
            padx=10,
            pady=8,
        ).grid(row=1, column=1, sticky="ew", padx=4, pady=4)
        self._make_action_button(
            btns,
            "↗ 自动填充",
            self.on_fill,
            self.SOFT_BLUE,
            self.TEXT,
            outline=self.BORDER,
            padx=10,
            pady=7,
        ).grid(row=2, column=0, sticky="ew", padx=4, pady=4)
        self._make_action_button(
            btns,
            "⌫ 清除求解",
            self.on_clear_solution,
            self.PANEL,
            self.MUTED,
            outline=self.BORDER,
            hover_bg=self.SUBTLE,
            padx=10,
            pady=7,
        ).grid(row=2, column=1, sticky="ew", padx=4, pady=4)
        self._make_action_button(
            btns,
            "⌖ 校准坐标",
            self.on_calibrate,
            self.SOFT_BLUE,
            self.TEXT,
            outline=self.BORDER,
            padx=10,
            pady=7,
        ).grid(row=3, column=0, sticky="ew", padx=4, pady=4)
        self._make_action_button(
            btns,
            "↺ 清空重置",
            self.on_clear,
            self.PANEL,
            self.MUTED,
            outline=self.BORDER,
            hover_bg=self.SUBTLE,
            padx=10,
            pady=7,
        ).grid(row=3, column=1, sticky="ew", padx=4, pady=4)
        self._make_action_button(
            btns,
            "▤ 历史记录\nCtrl+H",
            self.on_show_history,
            self.SUBTLE,
            self.TEXT,
            outline=self.BORDER,
            padx=10,
            pady=7,
        ).grid(row=4, column=0, sticky="ew", padx=4, pady=4)
        self._make_action_button(
            btns,
            "⎘ 复制分享",
            self.on_copy_board,
            self.PANEL,
            self.MUTED,
            outline=self.BORDER,
            hover_bg=self.SUBTLE,
            padx=10,
            pady=7,
        ).grid(row=4, column=1, sticky="ew", padx=4, pady=4)
        self._make_action_button(
            btns,
            "✦ 提示一步",
            self.on_hint_step,
            self.SOFT_BLUE,
            self.TEXT,
            outline=self.PRIMARY,
            hover_bg=self._blend_color(self.SOFT_BLUE, self.PRIMARY, 0.10),
            font=("Microsoft YaHei UI", 9, "bold"),
            padx=10,
            pady=8,
        ).grid(row=5, column=0, columnspan=2, sticky="ew", padx=4, pady=4)

        generate_row = tk.Frame(actions, bg=self.PANEL)
        generate_row.pack(fill="x", padx=14, pady=(2, 4))
        tk.Label(generate_row, text="生成难度", bg=self.PANEL, fg=self.MUTED, font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.generate_menu = tk.OptionMenu(generate_row, self.generate_difficulty, "简单", "中等", "困难", "专家")
        self.generate_menu.config(
            bg=self.PANEL,
            fg=self.TEXT,
            activebackground=self.SOFT_BLUE,
            activeforeground=self.TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=self.BORDER,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9),
        )
        self.generate_menu.pack(side="right")

    def _build_sidebar(self, parent):
        side = tk.Frame(parent, bg=self.BG)
        side.pack(fill="x")

        actions_panel = self._make_rounded_panel(side, radius=16, padding=5)
        actions_panel.pack(fill="x")
        actions = actions_panel.content

        head = tk.Frame(actions, bg=self.PANEL)
        head.pack(fill="x", padx=14, pady=(12, 8))
        tk.Label(head, text="操作", bg=self.PANEL, fg=self.TEXT, font=("Microsoft YaHei UI", 12, "bold")).pack(side="left")
        tk.Label(
            head,
            text="识别 · 求解 · 填充",
            bg=self.PANEL,
            fg=self.MUTED,
            font=("Microsoft YaHei UI", 8, "bold"),
        ).pack(side="right")

        hero = tk.Frame(actions, bg=self.PANEL)
        hero.pack(fill="x", padx=14, pady=(0, 10))
        hero.grid_columnconfigure(0, weight=1)

        capture_btn = self._make_action_button(
            hero,
            "▣  截图识别\nF2",
            self.on_ocr,
            self.PRIMARY,
            "white",
            outline=self.PRIMARY,
            hover_bg=self.PRIMARY_HOVER,
            font=("Microsoft YaHei UI", 11, "bold"),
            padx=16,
            pady=14,
        )
        capture_btn.config(anchor="w", justify="left")
        capture_btn.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        solve_cta = "#34C759"
        solve_btn = self._make_action_button(
            hero,
            "▶  一键求解\nCtrl+Enter",
            self.on_solve,
            solve_cta,
            "white",
            outline=solve_cta,
            hover_bg=self._blend_color(solve_cta, "#000000", 0.14),
            font=("Microsoft YaHei UI", 11, "bold"),
            padx=16,
            pady=14,
        )
        solve_btn.config(anchor="w", justify="left")
        solve_btn.grid(row=1, column=0, sticky="ew")

        tools = tk.Frame(actions, bg=self.PANEL)
        tools.pack(fill="x", padx=14, pady=(0, 8))
        for column in range(3):
            tools.grid_columnconfigure(column, weight=1)

        compact_actions = [
            ("◎ 导入图片", self.on_import_image, self.SOFT_BLUE, self.TEXT, self.BORDER),
            ("↗ 自动填充", self.on_fill, self.SOFT_BLUE, self.TEXT, self.BORDER),
            ("⌖ 校准坐标", self.on_calibrate, self.SOFT_BLUE, self.TEXT, self.BORDER),
            ("◇ 生成题目", self.on_generate_puzzle, self.SOFT_BLUE, self.TEXT, self.BORDER),
            ("✦ 提示一步", self.on_hint_step, self.SOFT_BLUE, self.TEXT, self.PRIMARY),
            ("▤ 历史记录", self.on_show_history, self.SUBTLE, self.TEXT, self.BORDER),
            ("▥ 教学模式", self.on_start_teaching, self.SOFT_BLUE, self.TEXT, self.PRIMARY),
            ("⌫ 清除求解", self.on_clear_solution, self.PANEL, self.MUTED, self.BORDER),
            ("↺ 清空重置", self.on_clear, self.PANEL, self.MUTED, self.BORDER),
            ("⎘ 复制分享", self.on_copy_board, self.PANEL, self.MUTED, self.BORDER),
        ]
        for index, (label, command, bg, fg, outline) in enumerate(compact_actions):
            button = self._make_action_button(
                tools,
                label,
                command,
                bg,
                fg,
                outline=outline,
                hover_bg=self._blend_color(bg, self.TEXT if bg != self.PANEL else self.SUBTLE, 0.08) if bg != self.PANEL else self.SUBTLE,
                font=("Microsoft YaHei UI", 9, "bold"),
                padx=8,
                pady=7,
            )
            button.grid(row=index // 3, column=index % 3, sticky="ew", padx=4, pady=4)

        generate_row = tk.Frame(actions, bg=self.PANEL)
        generate_row.pack(fill="x", padx=14, pady=(2, 10))
        tk.Label(generate_row, text="生成难度", bg=self.PANEL, fg=self.MUTED, font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.generate_menu = tk.OptionMenu(generate_row, self.generate_difficulty, "简单", "中等", "困难", "专家")
        self.generate_menu.config(
            bg=self.PANEL,
            fg=self.TEXT,
            activebackground=self.SOFT_BLUE,
            activeforeground=self.TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=self.BORDER,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9),
        )
        self.generate_menu.pack(side="right")

    def _build_teaching_panel(self, parent):
        panel = self._make_rounded_panel(parent, radius=18, padding=5)
        self.teaching_panel = panel
        panel.bind("<Configure>", self._update_teaching_wraplength, add="+")
        panel_body = panel.content

        head = tk.Frame(panel_body, bg=self.PANEL)
        head.pack(fill="x", padx=14, pady=(12, 8))
        tk.Label(head, text="教学模式", bg=self.PANEL, fg=self.TEXT, font=("Microsoft YaHei UI", 12, "bold")).pack(side="left")
        self.teaching_start_button = self._make_action_button(
            head,
            "开始",
            self.on_start_teaching,
            self.PRIMARY,
            "white",
            outline=self.PRIMARY,
            hover_bg=self.PRIMARY_HOVER,
            font=("Microsoft YaHei UI", 8, "bold"),
            padx=8,
            pady=3,
        )
        self.teaching_start_button.pack(side="right")
        self.teaching_header_exit_button = self._make_action_button(
            head,
            "退出",
            self.on_teaching_exit,
            self.PANEL,
            self.MUTED,
            outline=self.BORDER,
            hover_bg=self.SUBTLE,
            font=("Microsoft YaHei UI", 8, "bold"),
            padx=8,
            pady=3,
        )
        self.teaching_header_exit_button.pack(side="right", padx=(0, 8))

        body = tk.Frame(panel_body, bg=self.PANEL)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        self.teaching_step_label = tk.Label(
            body,
            textvariable=self.teaching_step_var,
            bg=self.PANEL,
            fg=self.PRIMARY,
            font=("Microsoft YaHei UI", 13, "bold"),
            anchor="w",
        )
        self.teaching_step_label.pack(fill="x", pady=(0, 8))
        self.teaching_strategy_label = tk.Label(
            body,
            textvariable=self.teaching_strategy_var,
            bg=self.SOFT_BLUE,
            fg=self.TEXT,
            font=("Microsoft YaHei UI", 10, "bold"),
            anchor="w",
            padx=10,
            pady=7,
            wraplength=220,
        )
        self.teaching_strategy_label.pack(fill="x", pady=(0, 8))
        self.teaching_explanation_label = tk.Label(
            body,
            textvariable=self.teaching_explanation_var,
            bg=self.PANEL,
            fg=self.TEXT,
            font=("Microsoft YaHei UI", 10),
            anchor="nw",
            justify="left",
            wraplength=230,
        )
        self.teaching_explanation_label.pack(fill="both", expand=True, pady=(0, 10))
        self.teaching_candidate_label = tk.Label(
            body,
            textvariable=self.teaching_candidate_var,
            bg=self.SUBTLE,
            fg=self.MUTED,
            font=("Microsoft YaHei UI", 9),
            anchor="w",
            justify="left",
            padx=10,
            pady=7,
            wraplength=220,
        )
        self.teaching_candidate_label.pack(fill="x", pady=(0, 10))

        controls = tk.Frame(body, bg=self.PANEL)
        controls.pack(fill="x", pady=(0, 8))
        for column in range(3):
            controls.grid_columnconfigure(column, weight=1)
        self.teaching_prev_button = self._make_action_button(
            controls,
            "上一步",
            self.on_teaching_prev,
            self.PANEL,
            self.TEXT,
            outline=self.BORDER,
            hover_bg=self.SUBTLE,
            font=("Microsoft YaHei UI", 9, "bold"),
            padx=6,
            pady=7,
        )
        self.teaching_prev_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.teaching_next_button = self._make_action_button(
            controls,
            "下一步",
            self.on_teaching_next,
            self.PRIMARY,
            "white",
            outline=self.PRIMARY,
            hover_bg=self.PRIMARY_HOVER,
            font=("Microsoft YaHei UI", 9, "bold"),
            padx=6,
            pady=7,
        )
        self.teaching_next_button.grid(row=0, column=1, sticky="ew", padx=4)
        self.teaching_autoplay_button = self._make_action_button(
            controls,
            "自动播放 ▶",
            self.on_teaching_autoplay,
            self.SOFT_BLUE,
            self.TEXT,
            outline=self.BORDER,
            hover_bg=self._blend_color(self.SOFT_BLUE, self.TEXT, 0.08),
            font=("Microsoft YaHei UI", 9, "bold"),
            padx=6,
            pady=7,
        )
        self.teaching_autoplay_button.grid(row=0, column=2, sticky="ew", padx=(4, 0))

        speed_row = tk.Frame(body, bg=self.PANEL)
        speed_row.pack(fill="x", pady=(0, 8))
        tk.Label(speed_row, text="播放速度", bg=self.PANEL, fg=self.MUTED, font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.teaching_speed_menu = tk.OptionMenu(speed_row, self.teaching_speed_var, "0.5x", "1x", "2x")
        self.teaching_speed_menu.config(
            bg=self.PANEL,
            fg=self.TEXT,
            activebackground=self.SOFT_BLUE,
            activeforeground=self.TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=self.BORDER,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9),
        )
        self.teaching_speed_menu.pack(side="right")

        self.teaching_exit_button = self._make_action_button(
            body,
            "退出教学",
            self.on_teaching_exit,
            self.PANEL,
            self.MUTED,
            outline=self.BORDER,
            hover_bg=self.SUBTLE,
            font=("Microsoft YaHei UI", 9, "bold"),
            padx=8,
            pady=7,
        )
        self.teaching_exit_button.pack(fill="x", pady=(0, 8))
        self.teaching_message_label = tk.Label(
            body,
            textvariable=self.teaching_message_var,
            bg=self.PANEL,
            fg=self.MUTED,
            font=("Microsoft YaHei UI", 8),
            anchor="w",
            justify="left",
            wraplength=230,
        )
        self.teaching_message_label.pack(fill="x")
        self._refresh_teaching_buttons()
        return panel

    def _teaching_wraplength_for_width(self, width):
        try:
            width = int(width)
        except (TypeError, ValueError):
            width = self.MIN_TEACHING_PANEL_WIDTH
        return max(150, min(360, width - 44))

    def _update_teaching_wraplength(self, event=None):
        width = getattr(event, "width", None)
        if width is None and hasattr(self, "teaching_panel"):
            try:
                width = self.teaching_panel.winfo_width()
            except tk.TclError:
                width = self.MIN_TEACHING_PANEL_WIDTH
        wraplength = self._teaching_wraplength_for_width(width)
        for name in (
            "teaching_strategy_label",
            "teaching_explanation_label",
            "teaching_candidate_label",
            "teaching_message_label",
        ):
            label = getattr(self, name, None)
            if label is not None:
                try:
                    label.config(wraplength=wraplength)
                except tk.TclError:
                    pass

    def _build_log_panel(self, parent):
        panel = self._make_rounded_panel(parent, radius=16, padding=5)
        panel.pack(fill="both", expand=True, pady=(10, 0))
        self.log_panel = panel
        panel_body = panel.content

        head = tk.Frame(panel_body, bg=self.PANEL)
        head.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(head, text="日志", bg=self.PANEL, fg=self.TEXT, font=("Microsoft YaHei UI", 12, "bold")).pack(side="left")
        self.log_toggle_button = self._make_action_button(
            head,
            "收起",
            self.on_toggle_log_panel,
            self.PANEL,
            self.MUTED,
            outline=self.BORDER,
            hover_bg=self.SUBTLE,
            font=("Microsoft YaHei UI", 8, "bold"),
            padx=8,
            pady=3,
        )
        self.log_toggle_button.pack(side="right")
        self._make_action_button(
            head,
            "清空日志",
            self.on_clear_log,
            self.PANEL,
            self.MUTED,
            outline=self.BORDER,
            hover_bg=self.SUBTLE,
            font=("Microsoft YaHei UI", 8, "bold"),
            padx=8,
            pady=3,
        ).pack(side="right", padx=(0, 6))

        body = tk.Frame(panel_body, bg=self.PANEL)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self.log_body = body

        stage_panel = tk.Frame(body, bg=self.PANEL)
        stage_panel.pack(fill="x", pady=(0, 8))
        self.log_stage_panel = stage_panel

        stage_head = tk.Frame(stage_panel, bg=self.PANEL)
        stage_head.pack(fill="x")
        self.log_stage_title_label = tk.Label(
            stage_head,
            textvariable=self.log_stage_title_var,
            bg=self.PANEL,
            fg=self.TEXT,
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        self.log_stage_title_label.pack(side="left")
        self.log_stage_detail_label = tk.Label(
            stage_head,
            textvariable=self.log_stage_detail_var,
            bg=self.PANEL,
            fg=self.MUTED,
            font=("Microsoft YaHei UI", 8),
        )
        self.log_stage_detail_label.pack(side="right")

        stage_track = tk.Frame(stage_panel, bg=self.SUBTLE, height=6)
        stage_track.pack(fill="x", pady=(6, 0))
        stage_track.pack_propagate(False)
        self.log_stage_track = stage_track
        self.log_stage_fill = tk.Frame(stage_track, bg=self.PRIMARY)
        self.log_stage_fill.place(x=0, y=0, relheight=1, relwidth=0)

        self.log_text = tk.Text(
            body,
            height=12,
            state="disabled",
            wrap="word",
            relief="flat",
            bd=0,
            padx=12,
            pady=10,
            font=("Consolas", 9),
        )
        self.log_text.pack(fill="both", expand=True)
        self._configure_log_tags()
        self._set_log_stage("等待任务", "准备就绪", 0.0, reset_after_ms=None)

    def _configure_log_tags(self):
        if not hasattr(self, "log_text"):
            return
        palette = self._log_color_palette()
        self.log_text.config(
            bg=palette["bg"],
            fg=palette["text"],
            insertbackground=palette["text"],
            selectbackground=self.PRIMARY,
            selectforeground="white",
        )
        self.log_text.tag_configure("timestamp", foreground=palette["timestamp"])
        self.log_text.tag_configure("info", foreground=palette["info"])
        self.log_text.tag_configure("warning", foreground=palette["warning"])
        self.log_text.tag_configure("error", foreground=palette["error"])
        self.log_text.tag_configure("timing", foreground=palette["accent"], font=("Consolas", 9, "bold"))
        self.log_text.tag_configure("detail", foreground=palette["text"])
        self.log_text.tag_configure("logic", foreground=palette["logic"], font=("Consolas", 9, "bold"))
        if hasattr(self, "log_stage_panel"):
            self.log_stage_panel.config(bg=self.PANEL)
        if hasattr(self, "log_stage_title_label"):
            self.log_stage_title_label.config(bg=self.PANEL, fg=self.TEXT)
        if hasattr(self, "log_stage_detail_label"):
            self.log_stage_detail_label.config(bg=self.PANEL, fg=self.MUTED)
        if hasattr(self, "log_stage_track"):
            self.log_stage_track.config(bg=self.SUBTLE)
        if hasattr(self, "log_stage_fill"):
            self.log_stage_fill.config(bg=self.PRIMARY)

    def _log_color_palette(self):
        if self.theme_name.get() == "dark":
            return {
                "bg": "#0d1118",
                "text": "#dce6f7",
                "timestamp": "#7f8ea3",
                "info": "#7ee787",
                "warning": "#f2cc60",
                "error": "#ff8e8e",
                "accent": "#7ab7ff",
                "logic": "#8de1ff",
            }
        return {
            "bg": "#101722",
            "text": "#d8e4f5",
            "timestamp": "#7a899f",
            "info": "#7fe089",
            "warning": "#f0c96a",
            "error": "#ff8f88",
            "accent": "#79b8ff",
                "logic": "#92e4ff",
            }

    def _set_log_stage(self, title, detail="", progress=0.0, reset_after_ms=None):
        def apply():
            if self._log_stage_reset_job is not None:
                try:
                    self.root.after_cancel(self._log_stage_reset_job)
                except tk.TclError:
                    pass
                self._log_stage_reset_job = None
            self.log_stage_title_var.set(title)
            self.log_stage_detail_var.set(detail)
            progress_value = max(0.0, min(1.0, float(progress)))
            if hasattr(self, "log_stage_fill"):
                self.log_stage_fill.place_configure(relwidth=progress_value)
            if reset_after_ms:
                self._log_stage_reset_job = self.root.after(
                    int(reset_after_ms),
                    lambda: self._set_log_stage("等待任务", "准备就绪", 0.0, reset_after_ms=None),
                )

        self._run_on_ui_thread(apply)

    def _make_action_button(self, parent, text, command, bg, fg, outline=None, hover_bg=None, font=None, padx=8, pady=5):
        button = RoundedButton(
            parent,
            text,
            command,
            bg,
            fg,
            outline=outline,
            hover_bg=hover_bg or self._hover_color(bg),
            font=font or ("Microsoft YaHei UI", 9, "bold"),
            padx=padx,
            pady=pady,
        )
        self.action_buttons.append(
            {
                "button": button,
                "bg_role": self._color_role(bg),
                "fg_role": self._color_role(fg),
                "outline_role": self._color_role(outline) if outline else None,
                "hover_role": self._color_role(hover_bg) if hover_bg else None,
            }
        )
        return button

    def _color_role(self, color):
        for name in (
            "PRIMARY",
            "SOFT_BLUE",
            "SUBTLE",
            "PANEL",
            "BG",
            "TEXT",
            "MUTED",
            "FILL_COLOR",
            "OCR_COLOR",
            "MANUAL_COLOR",
        ):
            if color == getattr(self, name, None):
                return name
        return color

    def _color_from_role(self, role):
        return getattr(self, role, role)

    def _hover_color(self, color):
        if color == self.PRIMARY:
            return self.PRIMARY_HOVER
        if color == self.FILL_COLOR:
            return self._blend_color(color, "#000000", 0.14)
        if color == self.SOFT_BLUE:
            return self._blend_color(color, self.TEXT, 0.08)
        if color == self.SUBTLE:
            return self._blend_color(color, self.TEXT, 0.06)
        if color == self.PANEL:
            return self.SUBTLE
        return color

    def _blend_color(self, color, target, weight):
        try:
            color = color.lstrip("#")
            target = target.lstrip("#")
            base_rgb = [int(color[index:index + 2], 16) for index in (0, 2, 4)]
            target_rgb = [int(target[index:index + 2], 16) for index in (0, 2, 4)]
            mixed = [
                max(0, min(255, round(base_rgb[index] * (1 - weight) + target_rgb[index] * weight)))
                for index in range(3)
            ]
        except (TypeError, ValueError):
            return f"#{color}" if isinstance(color, str) and not color.startswith("#") else color
        return "#" + "".join(f"{value:02x}" for value in mixed)

    def _valid_hex_color(self, color):
        if not isinstance(color, str) or len(color) != 7 or not color.startswith("#"):
            return False
        try:
            int(color[1:], 16)
            return True
        except ValueError:
            return False

    def _apply_theme_values(self, theme_name, custom_accent=None):
        theme_name = theme_name if theme_name in self.THEMES else "light"
        palette = dict(self.THEMES[theme_name])
        if self._valid_hex_color(custom_accent):
            palette["PRIMARY"] = custom_accent
            palette["PRIMARY_HOVER"] = self._blend_color(custom_accent, "#000000", 0.16)
            palette["SOFT_BLUE"] = self._blend_color(palette["PANEL"], custom_accent, 0.14)
            if theme_name == "dark":
                palette["SOFT_BLUE"] = self._blend_color(palette["PANEL"], custom_accent, 0.22)
        self._theme_palette = palette
        for name, value in palette.items():
            setattr(self, name, value)
        self.theme_name.set(theme_name)

    def _theme_button_text(self):
        return "浅色" if self.theme_name.get() == "dark" else "深色"

    def _normalize_window_opacity(self, value, fallback=1.0):
        try:
            opacity = float(value)
        except (TypeError, ValueError):
            return fallback
        if opacity > 1:
            opacity /= 100
        return min(1.0, max(self.MIN_WINDOW_OPACITY, opacity))

    def _update_opacity_value_label(self):
        if getattr(self, "settings_opacity_value_label", None) is None:
            return
        try:
            self.settings_opacity_value_label.config(text=f"{self.window_opacity_var.get()}%")
        except tk.TclError:
            pass

    def _apply_window_opacity(self, opacity):
        opacity = self._normalize_window_opacity(opacity)
        percent = int(round(opacity * 100))
        if self.window_opacity_var.get() != percent:
            self.window_opacity_var.set(percent)
        try:
            self.root.attributes("-alpha", opacity)
        except tk.TclError:
            pass
        if getattr(self, "settings_window", None) is not None:
            try:
                if self.settings_window.winfo_exists():
                    self.settings_window.attributes("-alpha", opacity)
            except tk.TclError:
                pass
        self._update_opacity_value_label()
        return opacity

    def _clear_settings_window_refs(self):
        self.settings_window = None
        self.settings_panel = None
        self.settings_theme_check = None
        self.settings_auto_fill_check = None
        self.settings_clipboard_check = None
        self.settings_minimize_fill_check = None
        self.settings_opacity_scale = None
        self.settings_opacity_value_label = None
        self.settings_accent_button = None
        self.settings_accent_preview = None

    def _refresh_settings_window(self):
        self._settings_dark_mode_var.set(self.theme_name.get() == "dark")
        if self.settings_button is not None:
            try:
                self.settings_button.config(
                    bg=self.PANEL,
                    fg=self.TEXT,
                    activebackground=self.SOFT_BLUE,
                    activeforeground=self.TEXT,
                    highlightbackground=self.BORDER,
                )
            except tk.TclError:
                pass

        if self.settings_window is None:
            return
        try:
            if not self.settings_window.winfo_exists():
                self._clear_settings_window_refs()
                return
            self.settings_window.configure(bg=self.BG)
            if self.settings_panel is not None:
                self.settings_panel.config(bg=self.PANEL, highlightbackground=self.BORDER)
            if self.settings_opacity_scale is not None:
                self.settings_opacity_scale.config(
                    bg=self.PANEL,
                    fg=self.TEXT,
                    activebackground=self.PRIMARY,
                    troughcolor=self.SUBTLE,
                    highlightbackground=self.PANEL,
                )
            if self.settings_opacity_value_label is not None:
                self.settings_opacity_value_label.config(bg=self.PANEL, fg=self.MUTED)
            for check in (
                self.settings_theme_check,
                self.settings_auto_fill_check,
                self.settings_clipboard_check,
                self.settings_minimize_fill_check,
            ):
                if check is not None:
                    check.config(
                        bg=self.PANEL,
                        fg=self.TEXT,
                        activebackground=self.PANEL,
                        activeforeground=self.TEXT,
                        selectcolor=self.PANEL,
                        highlightbackground=self.PANEL,
                    )
            if self.settings_accent_preview is not None:
                self.settings_accent_preview.config(bg=self.custom_accent or self.PRIMARY, highlightbackground=self.BORDER)
            self._apply_window_opacity(self.window_opacity_var.get() / 100)
        except tk.TclError:
            self._clear_settings_window_refs()

    def on_open_settings(self):
        if self.settings_window is not None:
            try:
                if self.settings_window.winfo_exists():
                    self._refresh_settings_window()
                    self.settings_window.deiconify()
                    self.settings_window.lift()
                    self.settings_window.focus_force()
                    return
            except tk.TclError:
                self._clear_settings_window_refs()

        window = tk.Toplevel(self.root)
        window.title("设置")
        window.transient(self.root)
        window.resizable(False, False)
        window.configure(bg=self.BG)
        window.protocol("WM_DELETE_WINDOW", self._close_settings_window)
        self.settings_window = window

        panel = tk.Frame(window, bg=self.PANEL, highlightthickness=1, highlightbackground=self.BORDER, padx=16, pady=16)
        panel.pack(fill="both", expand=True, padx=14, pady=14)
        self.settings_panel = panel

        tk.Label(panel, text="设置", bg=self.PANEL, fg=self.TEXT, font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")

        def add_section(title, top_pad):
            tk.Label(
                panel,
                text=title,
                bg=self.PANEL,
                fg=self.MUTED,
                font=("Microsoft YaHei UI", 9, "bold"),
            ).pack(anchor="w", pady=(top_pad, 8))

        def add_row(title, detail):
            row = tk.Frame(panel, bg=self.PANEL)
            row.pack(fill="x", pady=(0, 10))
            text_box = tk.Frame(row, bg=self.PANEL)
            text_box.pack(side="left", fill="x", expand=True)
            tk.Label(
                text_box,
                text=title,
                bg=self.PANEL,
                fg=self.TEXT,
                font=("Microsoft YaHei UI", 10, "bold"),
            ).pack(anchor="w")
            tk.Label(
                text_box,
                text=detail,
                bg=self.PANEL,
                fg=self.MUTED,
                font=("Microsoft YaHei UI", 9),
                justify="left",
            ).pack(anchor="w", pady=(2, 0))
            return row

        add_section("外观", 12)
        theme_row = add_row("深色模式", "切换浅色或深色界面")
        self.settings_theme_check = tk.Checkbutton(
            theme_row,
            text="启用",
            variable=self._settings_dark_mode_var,
            onvalue=True,
            offvalue=False,
            command=self.on_toggle_theme,
            bg=self.PANEL,
            fg=self.TEXT,
            activebackground=self.PANEL,
            activeforeground=self.TEXT,
            selectcolor=self.PANEL,
            font=("Microsoft YaHei UI", 9),
            padx=8,
            pady=4,
        )
        self.settings_theme_check.pack(side="right")

        opacity_row = add_row("窗口透明度", "调整整个软件窗口透明度")
        opacity_controls = tk.Frame(opacity_row, bg=self.PANEL)
        opacity_controls.pack(side="right")
        self.settings_opacity_value_label = tk.Label(
            opacity_controls,
            text=f"{self.window_opacity_var.get()}%",
            bg=self.PANEL,
            fg=self.MUTED,
            font=("Microsoft YaHei UI", 9, "bold"),
            width=5,
            anchor="e",
        )
        self.settings_opacity_value_label.pack(side="right", padx=(8, 0))
        self.settings_opacity_scale = tk.Scale(
            opacity_controls,
            from_=int(self.MIN_WINDOW_OPACITY * 100),
            to=100,
            orient="horizontal",
            variable=self.window_opacity_var,
            command=self.on_window_opacity_change,
            showvalue=False,
            resolution=5,
            length=150,
            bg=self.PANEL,
            fg=self.TEXT,
            activebackground=self.PRIMARY,
            troughcolor=self.SUBTLE,
            highlightthickness=0,
        )
        self.settings_opacity_scale.pack(side="right")

        accent_row = add_row("主配色", "修改主要按钮和高亮颜色")
        accent_actions = tk.Frame(accent_row, bg=self.PANEL)
        accent_actions.pack(side="right")
        self.settings_accent_preview = tk.Label(
            accent_actions,
            width=2,
            height=1,
            bg=self.custom_accent or self.PRIMARY,
            highlightthickness=1,
            highlightbackground=self.BORDER,
        )
        self.settings_accent_preview.pack(side="right")
        self.settings_accent_button = self._make_action_button(
            accent_actions,
            "选择",
            self.on_pick_accent_color,
            self.SOFT_BLUE,
            self.TEXT,
            outline=self.BORDER,
            padx=10,
            pady=5,
        )
        self.settings_accent_button.pack(side="right", padx=(0, 8))

        add_section("辅助", 6)
        auto_fill_row = add_row("极速自动填充", "识别和求解完成后自动回到目标网页快速填充")
        self.settings_auto_fill_check = tk.Checkbutton(
            auto_fill_row,
            text="启用",
            variable=self.auto_fill_enabled,
            onvalue=True,
            offvalue=False,
            command=self.on_toggle_fast_auto_fill,
            bg=self.PANEL,
            fg=self.TEXT,
            activebackground=self.PANEL,
            activeforeground=self.TEXT,
            selectcolor=self.PANEL,
            font=("Microsoft YaHei UI", 9),
            padx=8,
            pady=4,
        )
        self.settings_auto_fill_check.pack(side="right")

        clipboard_row = add_row("剪贴板识别", "检测系统剪贴板里的截图并自动识别")
        self.settings_clipboard_check = tk.Checkbutton(
            clipboard_row,
            text="启用",
            variable=self.clipboard_monitor_enabled,
            onvalue=True,
            offvalue=False,
            command=self.on_toggle_clipboard_monitor,
            bg=self.PANEL,
            fg=self.TEXT,
            activebackground=self.PANEL,
            activeforeground=self.TEXT,
            selectcolor=self.PANEL,
            font=("Microsoft YaHei UI", 9),
            padx=8,
            pady=4,
        )
        self.settings_clipboard_check.pack(side="right")

        minimize_row = add_row("填充完成最小化", "自动填充成功后将本软件最小化到任务栏")
        self.settings_minimize_fill_check = tk.Checkbutton(
            minimize_row,
            text="启用",
            variable=self.minimize_after_fill_enabled,
            onvalue=True,
            offvalue=False,
            command=self.on_toggle_minimize_after_fill,
            bg=self.PANEL,
            fg=self.TEXT,
            activebackground=self.PANEL,
            activeforeground=self.TEXT,
            selectcolor=self.PANEL,
            font=("Microsoft YaHei UI", 9),
            padx=8,
            pady=4,
        )
        self.settings_minimize_fill_check.pack(side="right")

        footer = tk.Frame(panel, bg=self.PANEL)
        footer.pack(fill="x", pady=(6, 0))
        self._make_action_button(
            footer,
            "关闭",
            self._close_settings_window,
            self.PANEL,
            self.MUTED,
            outline=self.BORDER,
            hover_bg=self.SUBTLE,
            padx=12,
            pady=6,
        ).pack(side="right")

        self._refresh_settings_window()
        try:
            self.root.update_idletasks()
            x = self.root.winfo_rootx() + 80
            y = self.root.winfo_rooty() + 60
            window.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass
        window.focus_force()

    def _close_settings_window(self):
        if self.settings_window is not None:
            try:
                self.settings_window.destroy()
            except tk.TclError:
                pass
        self._clear_settings_window_refs()

    def _refresh_action_buttons(self):
        active_items = []
        for item in self.action_buttons:
            if isinstance(item, tuple):
                button, bg_role, fg_role = item
                outline_role = None
                hover_role = None
            else:
                button = item["button"]
                bg_role = item["bg_role"]
                fg_role = item["fg_role"]
                outline_role = item.get("outline_role")
                hover_role = item.get("hover_role")
            try:
                if not button.winfo_exists():
                    continue
            except tk.TclError:
                continue
            bg = self._color_from_role(bg_role)
            fg = self._color_from_role(fg_role)
            outline = self._color_from_role(outline_role) if outline_role else bg
            hover = self._color_from_role(hover_role) if hover_role else self._hover_color(bg)
            try:
                button.config(
                    bg=bg,
                    fg=fg,
                    activebackground=hover,
                    activeforeground=fg,
                    highlightbackground=outline,
                    highlightcolor=outline,
                )
                active_items.append(item)
            except tk.TclError:
                continue
        self.action_buttons = active_items

    def _build_theme_color_map(self, old_palette):
        color_map = {}
        for name, old_value in old_palette.items():
            new_value = self._theme_palette.get(name)
            if old_value and new_value:
                color_map[old_value] = new_value
        color_map.update(
            {
                old_palette.get("LOG_BG", "#fbfcfe"): self.LOG_BG,
                old_palette.get("SOLUTION_BG", "#f3f5f9"): self.SOLUTION_BG,
                old_palette.get("CONFLICT_RING", "#b63535"): self.CONFLICT_RING,
                self._hover_color(old_palette.get("PRIMARY", self.PRIMARY)): self.PRIMARY_HOVER,
            }
        )
        return color_map

    def _recolor_widget_tree(self, widget, color_map):
        for option in (
            "bg",
            "background",
            "fg",
            "foreground",
            "activebackground",
            "activeforeground",
            "highlightbackground",
            "highlightcolor",
            "selectbackground",
            "selectforeground",
            "insertbackground",
        ):
            try:
                current = widget.cget(option)
            except tk.TclError:
                continue
            current_key = str(current)
            if current_key in color_map:
                try:
                    widget.config(**{option: color_map[current_key]})
                except tk.TclError:
                    pass
        for child in widget.winfo_children():
            self._recolor_widget_tree(child, color_map)

    def _apply_theme(self, theme_name=None, custom_accent=None):
        old_palette = dict(self._theme_palette)
        target_theme = theme_name or self.theme_name.get()
        self._apply_theme_values(target_theme, custom_accent if custom_accent is not None else self.custom_accent)
        color_map = self._build_theme_color_map(old_palette)
        self.root.configure(bg=self.BG)
        self._recolor_widget_tree(self.root, color_map)
        self._refresh_rounded_surfaces()
        self._refresh_action_buttons()
        self._refresh_pin_visual()
        self._refresh_settings_window()
        if hasattr(self, "generate_menu"):
            self.generate_menu.config(bg=self.PANEL, fg=self.TEXT, activebackground=self.SOFT_BLUE, highlightbackground=self.BORDER)
            try:
                self.generate_menu["menu"].config(bg=self.PANEL, fg=self.TEXT, activebackground=self.SOFT_BLUE, activeforeground=self.TEXT)
            except tk.TclError:
                pass
        if hasattr(self, "teaching_speed_menu"):
            self.teaching_speed_menu.config(bg=self.PANEL, fg=self.TEXT, activebackground=self.SOFT_BLUE, highlightbackground=self.BORDER)
            try:
                self.teaching_speed_menu["menu"].config(bg=self.PANEL, fg=self.TEXT, activebackground=self.SOFT_BLUE, activeforeground=self.TEXT)
            except tk.TclError:
                pass
        self._configure_log_tags()
        self._refresh_all_cell_styles()
        self._update_metrics()
        self._schedule_board_resize()

    def on_toggle_theme(self):
        next_theme = "light" if self.theme_name.get() == "dark" else "dark"
        self._apply_theme(next_theme)
        self._schedule_ui_state_save()
        self._set_status(f"已切换为{'深色' if next_theme == 'dark' else '浅色'}模式")

    def on_window_opacity_change(self, value):
        opacity = self._normalize_window_opacity(float(value) / 100)
        self._apply_window_opacity(opacity)
        self._schedule_ui_state_save()

    def on_pick_accent_color(self):
        _rgb, selected = colorchooser.askcolor(color=self.PRIMARY, title="选择主色")
        if not selected:
            return
        self.custom_accent = selected
        self._apply_theme(self.theme_name.get(), self.custom_accent)
        self._schedule_ui_state_save()
        self._set_status("已更新自定义主色")

    def _normalize_pane_ratio(self, ratio, fallback=None):
        fallback = self.DEFAULT_PANE_RATIO if fallback is None else fallback
        try:
            ratio = float(ratio)
        except (TypeError, ValueError):
            return fallback
        return min(0.82, max(0.18, ratio))

    def _load_ui_state(self):
        if not self.ui_state_path.exists():
            return {}
        try:
            with self.ui_state_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _load_saved_theme_name(self):
        theme = self._ui_state.get("theme", "light")
        return theme if theme in self.THEMES else "light"

    def _load_saved_pane_ratio(self):
        data = self._ui_state
        ratio = self._normalize_pane_ratio(data.get("pane_ratio"), self.DEFAULT_PANE_RATIO)
        if data.get("pane_layout") != self.PANE_LAYOUT_KEY:
            return self._normalize_pane_ratio(1 - ratio, self.DEFAULT_PANE_RATIO)
        return ratio

    def _load_saved_button_mode_position(self):
        position = self._ui_state.get("button_mode_position")
        if not isinstance(position, dict):
            return None
        try:
            x = int(position["x"])
            y = int(position["y"])
        except (KeyError, TypeError, ValueError):
            return None
        return {"x": x, "y": y}

    def _get_current_pane_ratio(self):
        if not hasattr(self, "main_pane") or len(self.main_pane.panes()) < 2:
            return None
        try:
            pane_width = self.main_pane.winfo_width()
            if pane_width <= 1:
                return None
            sash_x = self.main_pane.sash_coord(0)[0]
        except tk.TclError:
            return None
        return self._normalize_pane_ratio(sash_x / pane_width, self.saved_pane_ratio)

    def _remember_pane_ratio(self):
        ratio = self._get_current_pane_ratio()
        if ratio is not None:
            self.saved_pane_ratio = ratio

    def _save_ui_state(self):
        self._remember_pane_ratio()
        payload = {
            "pane_ratio": self.saved_pane_ratio,
            "pane_layout": self.PANE_LAYOUT_KEY,
            "theme": self.theme_name.get(),
            "custom_accent": self.custom_accent,
            "auto_fill_enabled": bool(self.auto_fill_enabled.get()),
            "minimize_after_fill": bool(self.minimize_after_fill_enabled.get()),
            "generate_difficulty": self.generate_difficulty.get(),
            "clipboard_monitor": bool(self.clipboard_monitor_enabled.get()),
            "window_opacity": round(self._normalize_window_opacity(self.window_opacity_var.get() / 100), 2),
        }
        if self.button_mode_position:
            payload["button_mode_position"] = self.button_mode_position
        try:
            with self.ui_state_path.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except OSError:
            return

    def _schedule_ui_state_save(self):
        if self._pane_save_job is not None:
            self.root.after_cancel(self._pane_save_job)
        self._pane_save_job = self.root.after(120, self._flush_ui_state_save)

    def _flush_ui_state_save(self):
        self._pane_save_job = None
        self._save_ui_state()

    def _restore_pane_ratio(self):
        if not hasattr(self, "main_pane") or len(self.main_pane.panes()) < 2:
            return
        pane_width = self.main_pane.winfo_width()
        if pane_width <= 1:
            self.root.after(50, self._restore_pane_ratio)
            return
        target_x = int(round(pane_width * self.saved_pane_ratio))
        try:
            sash_y = self.main_pane.sash_coord(0)[1]
            self.main_pane.sash_place(0, target_x, sash_y)
        except tk.TclError:
            self.root.after(50, self._restore_pane_ratio)
            return
        self._remember_pane_ratio()
        self._update_sidebar_wraplength()
        self._schedule_board_resize()

    def _on_pane_drag_end(self, _event=None):
        self._remember_pane_ratio()
        self._schedule_ui_state_save()
        self._schedule_board_resize()

    def _update_sidebar_wraplength(self, _event=None):
        if not hasattr(self, "status_label") or not hasattr(self, "topbar_tools"):
            return
        try:
            total_width = self.root.winfo_width()
            tools_width = self.topbar_tools.winfo_width()
        except tk.TclError:
            return
        wraplength = max(160, min(360, total_width - tools_width - 60))
        if wraplength == self._last_sidebar_wraplength:
            return
        self._last_sidebar_wraplength = wraplength
        self.status_label.config(wraplength=wraplength)

    def _setup_shortcuts(self):
        shortcuts = {
            "<F2>": self.on_ocr,
            "<Escape>": self.on_cancel_recognition,
            "<Control-o>": self.on_import_image,
            "<Control-O>": self.on_import_image,
            "<Control-Return>": self.on_solve,
            "<Control-BackSpace>": self.on_clear,
            "<Control-g>": self.on_generate_puzzle,
            "<Control-G>": self.on_generate_puzzle,
            "<Control-h>": self.on_show_history,
            "<Control-H>": self.on_show_history,
            "<Control-Shift-C>": self.on_copy_board,
            "<Control-Shift-c>": self.on_copy_board,
            "<Control-i>": self.on_hint_step,
            "<Control-I>": self.on_hint_step,
            "<Control-t>": self.on_start_teaching,
            "<Control-T>": self.on_start_teaching,
            "<Control-Right>": self.on_teaching_next,
            "<Control-Left>": self.on_teaching_prev,
            "<Control-space>": self.on_teaching_autoplay,
        }
        for sequence, handler in shortcuts.items():
            self._bind_shortcut(sequence, handler)

    def _bind_shortcut(self, sequence, handler):
        callback = lambda event, command=handler: self._handle_shortcut(command)
        self.root.bind(sequence, callback, add="+")
        self.root.bind_all(sequence, callback, add="+")
        for row in getattr(self, "cells", []):
            for cell in row:
                if cell is not None:
                    cell.bind(sequence, callback, add="+")

    def _handle_shortcut(self, callback):
        result = callback()
        return "break" if result is not False else None

    def _setup_global_hotkeys(self):
        self._ensure_global_hotkeys()

    def _ensure_global_hotkeys(self):
        if sys.platform != "win32":
            return False
        thread = getattr(self, "_global_hotkey_thread", None)
        if thread is not None and thread.is_alive():
            return True
        retry_job = getattr(self, "_global_hotkey_retry_job", None)
        if retry_job is not None:
            try:
                self.root.after_cancel(retry_job)
            except (tk.TclError, RuntimeError, AttributeError):
                pass
            self._global_hotkey_retry_job = None
        self._global_hotkey_thread_id = None
        self._global_hotkeys_registered = False
        self._global_hotkey_thread = threading.Thread(target=self._global_hotkey_loop, daemon=True)
        self._global_hotkey_thread.start()
        return True

    def _schedule_global_hotkey_retry(self, delay_ms=1500):
        if sys.platform != "win32" or self._closing:
            return
        if self._global_hotkey_retry_job is not None:
            return

        def retry():
            self._global_hotkey_retry_job = None
            self._ensure_global_hotkeys()

        try:
            self._global_hotkey_retry_job = self.root.after(delay_ms, retry)
        except (tk.TclError, RuntimeError):
            self._global_hotkey_retry_job = None

    def _on_root_unmap(self, _event=None):
        if sys.platform != "win32":
            return
        try:
            if self.root.state() in {"iconic", "withdrawn"}:
                self._ensure_global_hotkeys()
        except tk.TclError:
            return

    def _global_hotkey_loop(self):
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            wm_hotkey = 0x0312
            vk_f2 = 0x71

            self._global_hotkey_thread_id = kernel32.GetCurrentThreadId()
            self._global_hotkeys_registered = False
            if not user32.RegisterHotKey(None, self._global_hotkey_id, 0, vk_f2):
                self._run_on_ui_thread(lambda: self._schedule_global_hotkey_retry())
                return
            self._global_hotkeys_registered = True

            msg = wintypes.MSG()
            try:
                while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                    if msg.message == wm_hotkey and msg.wParam == self._global_hotkey_id:
                        self._run_on_ui_thread(self.on_ocr)
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
            finally:
                if self._global_hotkeys_registered:
                    user32.UnregisterHotKey(None, self._global_hotkey_id)
        except Exception:
            self._run_on_ui_thread(lambda: self._schedule_global_hotkey_retry())
            return
        finally:
            self._global_hotkeys_registered = False
            self._global_hotkey_thread_id = None

    def _teardown_global_hotkeys(self):
        if sys.platform != "win32" or self._global_hotkey_thread_id is None:
            return
        try:
            import ctypes

            ctypes.windll.user32.PostThreadMessageW(self._global_hotkey_thread_id, 0x0012, 0, 0)
        except Exception:
            pass

    def _setup_file_drop(self):
        if DND_FILES is None:
            self._drop_enabled = False
            return
        targets = [self.root]
        for name in ("board_panel", "board_holder", "board_stage", "grid_frame"):
            widget = getattr(self, name, None)
            if widget is not None:
                targets.append(widget)
        for widget in targets:
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_file_drop)
                self._drop_enabled = True
            except (AttributeError, tk.TclError):
                continue
        if self._drop_enabled:
            self._set_status("可拖入图片识别，也可按 Ctrl+O 导入，方向键可移动盘面")
        else:
            self._set_status("按 Ctrl+O 导入图片，方向键可移动盘面")

    def _on_file_drop(self, event):
        paths = self._parse_dropped_files(getattr(event, "data", ""))
        for path in paths:
            if self._is_supported_image(path):
                self._start_image_recognition(path, f"拖拽图片: {Path(path).name}")
                return "break"
        self._show_warning("无法导入", "请拖入 PNG、JPG、BMP、GIF、WEBP 或 TIFF 图片文件。")
        return "break"

    def _parse_dropped_files(self, data):
        if not data:
            return []
        try:
            return list(self.root.tk.splitlist(data))
        except tk.TclError:
            return [data.strip("{}")]

    def _is_supported_image(self, path):
        return Path(path).suffix.lower() in self.IMAGE_EXTENSIONS

    def _setup_clipboard_monitor(self):
        if self.clipboard_monitor_enabled.get():
            self._schedule_clipboard_poll()

    def _schedule_clipboard_poll(self, delay_ms=1200):
        if self._clipboard_poll_job is not None:
            try:
                self.root.after_cancel(self._clipboard_poll_job)
            except tk.TclError:
                pass
            self._clipboard_poll_job = None
        if self.clipboard_monitor_enabled.get():
            self._clipboard_poll_job = self.root.after(delay_ms, self._poll_clipboard_image)

    def _clipboard_signature(self, image):
        try:
            preview = image.convert("L").resize((48, 48))
            return hash(preview.tobytes())
        except Exception:
            return None

    def _poll_clipboard_image(self):
        self._clipboard_poll_job = None
        if not self.clipboard_monitor_enabled.get():
            return

        clipboard = None
        try:
            clipboard = ImageGrab.grabclipboard()
        except Exception:
            self._schedule_clipboard_poll(1800)
            return

        if isinstance(clipboard, Image.Image):
            signature = self._clipboard_signature(clipboard)
            if signature is not None and signature != self._last_clipboard_signature:
                self._last_clipboard_signature = signature
                if not self._recognizing and not self._ocr_trigger_active:
                    self.grid_coords = None
                    self._clear_fill_target_window()
                    self._start_image_recognition(
                        clipboard.copy(),
                        "剪贴板图片",
                        detect_grid_bounds=True,
                    )
                    self._schedule_clipboard_poll(2200)
                    return
            elif signature is not None:
                self._last_clipboard_signature = signature

        self._schedule_clipboard_poll()

    def _update_metrics(self):
        if not hasattr(self, "metrics_var"):
            return
        board = self._get_board_from_ui() if hasattr(self, "cells") else self.original_board
        filled = sum(1 for row in board for value in row if value)
        conflicts = len(self._find_conflicts(board)) if filled else 0
        low_confidence = len(self.low_confidence_cells) if getattr(self, "low_confidence_cells", None) else 0
        ocr = "-" if self.performance["last_ocr_ms"] is None else f"{self.performance['last_ocr_ms'] / 1000:.2f}s"
        solve = "-" if self.performance["last_solve_ms"] is None else f"{self.performance['last_solve_ms']:.0f}ms"
        difficulty = self.performance["last_difficulty"] or "-"
        pieces = [f"已填 {filled}/81"]
        if conflicts:
            pieces.append(f"冲突 {conflicts}")
        if low_confidence:
            pieces.append(f"低置信 {low_confidence}")
        pieces.extend([f"识别 {ocr}", f"求解 {solve}", f"难度 {difficulty}"])
        self.metrics_var.set(" · ".join(pieces))

    def _record_perf(self, kind, elapsed_ms):
        if kind == "ocr":
            self.performance["last_ocr_ms"] = elapsed_ms
            self.performance["ocr_runs"] += 1
            self.performance["ocr_total_ms"] += elapsed_ms
        elif kind == "solve":
            self.performance["last_solve_ms"] = elapsed_ms
            self.performance["solve_runs"] += 1
            self.performance["solve_total_ms"] += elapsed_ms
        self._update_metrics()

    def _load_history(self):
        if not self.history_path.exists():
            return []
        try:
            with self.history_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def _save_history(self):
        try:
            with self.history_path.open("w", encoding="utf-8") as fh:
                json.dump(self.history[: self.HISTORY_LIMIT], fh, ensure_ascii=False, indent=2)
        except OSError:
            return

    def _board_has_values(self, board):
        return any(value for row in board for value in row)

    def _estimate_difficulty(self, board):
        clues = sum(1 for row in board for value in row if value)
        if clues >= 40:
            return "简单"
        if clues >= 32:
            return "中等"
        if clues >= 28:
            return "困难"
        return "专家"

    def _add_history_entry(self, source, puzzle, solution, difficulty):
        if not self._board_has_values(puzzle) or not solution:
            return
        entry = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": source,
            "difficulty": difficulty,
            "puzzle": [row[:] for row in puzzle],
            "solution": [row[:] for row in solution],
            "ocr_ms": self.performance["last_ocr_ms"],
            "solve_ms": self.performance["last_solve_ms"],
        }
        self.history = [
            old
            for old in self.history
            if old.get("puzzle") != entry["puzzle"] or old.get("solution") != entry["solution"]
        ]
        self.history.insert(0, entry)
        del self.history[self.HISTORY_LIMIT :]
        self._save_history()

    def _history_entry_title(self, entry):
        source = entry.get("source", "未知")
        difficulty = entry.get("difficulty", "-")
        return f"{entry.get('time', '')} · {source} · {difficulty}"

    def _history_entry_text(self, entry):
        lines = [
            self._history_entry_title(entry),
            "",
            "题目:",
            self._format_board(entry.get("puzzle", [[0 for _ in range(9)] for _ in range(9)])),
        ]
        solution = entry.get("solution")
        if solution:
            lines.extend(["", "答案:", self._format_board(solution)])
        ocr_ms = entry.get("ocr_ms")
        solve_ms = entry.get("solve_ms")
        if ocr_ms is not None or solve_ms is not None:
            ocr_text = "-" if ocr_ms is None else f"{ocr_ms / 1000:.2f}s"
            solve_text = "-" if solve_ms is None else f"{solve_ms:.0f}ms"
            lines.extend(["", f"性能: 识别 {ocr_text} · 求解 {solve_text}"])
        return "\n".join(lines)

    def _copy_text_to_clipboard(self, text, status):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()
        self._set_status(status)

    def _share_text(self):
        current_board = self._get_board_from_ui()
        puzzle = self.original_board if self._board_has_values(self.original_board) else current_board
        lines = ["数独盘面", "", "题目:", self._format_board(puzzle)]
        if self.solution:
            lines.extend(["", "答案:", self._format_board(self.solution)])
        difficulty = self.performance["last_difficulty"]
        if difficulty:
            lines.extend(["", f"难度: {difficulty}"])
        return "\n".join(lines)

    def on_copy_board(self):
        self._copy_text_to_clipboard(self._share_text(), "盘面文本已复制到剪贴板")

    def _load_history_entry(self, entry, window=None):
        puzzle = entry.get("puzzle")
        solution = entry.get("solution")
        if not puzzle:
            return
        self._cancel_solution_animation()
        self.grid_coords = None
        self._clear_fill_target_window()
        self.last_fill_payload = None
        self.recognized_board = [row[:] for row in puzzle]
        self.original_board = [row[:] for row in puzzle]
        self.solution = [row[:] for row in solution] if solution else None
        self._set_board(puzzle, "manual")
        if self.solution:
            self._apply_solution_to_ui(self.solution, puzzle, animate=False)
        self.performance["last_difficulty"] = entry.get("difficulty")
        self._update_metrics()
        self._set_status("已载入历史记录")
        if window is not None:
            window.destroy()

    def on_show_history(self):
        if not self.history:
            self._show_info("历史记录", "还没有已解记录。识别或求解成功后会自动保存。")
            return

        window = tk.Toplevel(self.root)
        window.title("历史记录")
        window.geometry("680x460")
        window.configure(bg=self.BG)
        window.transient(self.root)

        body = tk.Frame(window, bg=self.BG)
        body.pack(fill="both", expand=True, padx=12, pady=12)
        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        listbox = tk.Listbox(
            body,
            width=30,
            bg=self.PANEL,
            fg=self.TEXT,
            selectbackground=self.PRIMARY,
            selectforeground="white",
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.BORDER,
            font=("Microsoft YaHei UI", 9),
        )
        listbox.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        for entry in self.history:
            listbox.insert(tk.END, self._history_entry_title(entry))

        detail = tk.Text(
            body,
            bg=self.LOG_BG,
            fg=self.TEXT,
            relief="flat",
            bd=0,
            padx=10,
            pady=10,
            wrap="word",
            font=("Consolas", 10),
        )
        detail.grid(row=0, column=1, sticky="nsew")

        footer = tk.Frame(window, bg=self.BG)
        footer.pack(fill="x", padx=12, pady=(0, 12))

        def selected_entry():
            selection = listbox.curselection()
            if not selection:
                return None
            return self.history[selection[0]]

        def refresh_detail(_event=None):
            entry = selected_entry()
            if entry is None:
                return
            detail.config(state="normal")
            detail.delete("1.0", tk.END)
            detail.insert("1.0", self._history_entry_text(entry))
            detail.config(state="disabled")

        def load_selected():
            entry = selected_entry()
            if entry is not None:
                self._load_history_entry(entry, window)

        def copy_selected():
            entry = selected_entry()
            if entry is not None:
                self._copy_text_to_clipboard(self._history_entry_text(entry), "历史记录已复制到剪贴板")

        self._make_action_button(footer, "载入", load_selected, self.PRIMARY, "white").pack(side="right", padx=(8, 0))
        self._make_action_button(footer, "复制", copy_selected, self.SOFT_BLUE, self.TEXT).pack(side="right", padx=(8, 0))
        self._make_action_button(footer, "关闭", window.destroy, self.SUBTLE, self.TEXT).pack(side="right")

        listbox.bind("<<ListboxSelect>>", refresh_detail)
        listbox.selection_set(0)
        refresh_detail()

    def on_import_image(self):
        path = filedialog.askopenfilename(
            title="导入数独图片",
            filetypes=[
                ("图片文件", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return
        if not self._is_supported_image(path):
            self._show_warning("无法导入", "请选择 PNG、JPG、BMP、GIF、WEBP 或 TIFF 图片文件。")
            return
        self.grid_coords = None
        self._clear_fill_target_window()
        self._start_image_recognition(path, f"导入图片: {Path(path).name}")

    def _start_image_recognition(
        self,
        image_source,
        source_label,
        auto_solve=True,
        detect_grid_bounds=False,
        grid_offset=(0, 0),
        fallback_to_manual=False,
        fill_target_window=None,
        recognition_generation=None,
    ):
        if recognition_generation is None:
            recognition_generation = self._next_recognition_generation()
        self._cancel_solution_animation()
        self.solution = None
        if detect_grid_bounds:
            self._clear_fill_target_window()
        self._recognition_started_at = time.perf_counter()
        self._log("INFO", f"{source_label}，开始识别")
        self._set_status("正在识别数独")
        self._start_recognition_animation(recognition_generation)

        def task():
            started = time.perf_counter()
            try:
                if not self._is_recognition_generation_current(recognition_generation):
                    return
                source = image_source() if callable(image_source) else image_source
                if not self._is_recognition_generation_current(recognition_generation):
                    return
                if detect_grid_bounds:
                    board, grid_bounds, confidence_map = self.ocr.process_with_grid_bounds_and_confidence(source)
                else:
                    board, confidence_map = self.ocr.process_with_confidence(source)
                    grid_bounds = None
                if not self._is_recognition_generation_current(recognition_generation):
                    return
                elapsed_ms = (time.perf_counter() - started) * 1000
                self._run_on_ui_thread(
                    lambda: self._record_perf("ocr", elapsed_ms)
                    if self._is_recognition_generation_current(recognition_generation)
                    else None
                )
                if board is None:
                    if not self._is_recognition_generation_current(recognition_generation):
                        return
                    self._log("WARNING", "未找到有效九宫格")
                    self._recognition_started_at = None
                    self._set_status("未找到九宫格，请重新识别")
                    if fallback_to_manual:
                        self.root.after(0, self._ask_manual_screenshot_after_auto_fail)
                    else:
                        self._show_warning("未找到九宫格", "未找到九宫格，请重新识别。")
                    return

                if grid_bounds is not None:
                    if not self._is_recognition_generation_current(recognition_generation):
                        return
                    offset_x, offset_y = grid_offset
                    grid_x, grid_y, grid_w, grid_h = grid_bounds
                    self.grid_coords = (offset_x + grid_x, offset_y + grid_y, grid_w, grid_h)
                    self._log("INFO", f"自动定位九宫格坐标: {self.grid_coords}")
                    self._set_fill_target_window(fill_target_window, self.grid_coords, source_label)

                if not self._is_recognition_generation_current(recognition_generation):
                    return
                self.recognized_board = [row[:] for row in board]
                self.original_board = [row[:] for row in board]
                self.ocr_confidence_map = confidence_map
                self.low_confidence_cells = self._find_low_confidence_cells(board, confidence_map)
                self.performance["last_difficulty"] = self._estimate_difficulty(board)
                self.root.after(
                    0,
                    lambda: self._set_board(board, "ocr")
                    if self._is_recognition_generation_current(recognition_generation)
                    else None,
                )
                self.root.after(
                    0,
                    lambda: self._update_metrics()
                    if self._is_recognition_generation_current(recognition_generation)
                    else None,
                )
                if not self._is_recognition_generation_current(recognition_generation):
                    return
                self._log("INFO", f"识别完成，耗时 {elapsed_ms / 1000:.2f}s")
                self._log("INFO", f"本次识别完成时间: {time.strftime('%H:%M:%S')}，耗时: {elapsed_ms / 1000:.2f} 秒")
                self._log("INFO", "识别结果如下:\n" + self._format_board(board))
                if self.low_confidence_cells:
                    self._log("WARNING", f"OCR 低置信格子已用黄色标记: {self._format_cells(self.low_confidence_cells)}")

                conflicts = self._find_conflicts(board)
                if conflicts:
                    if not self._is_recognition_generation_current(recognition_generation):
                        return
                    self.root.after(
                        0,
                        lambda: self._mark_conflicts(conflicts)
                        if self._is_recognition_generation_current(recognition_generation)
                        else None,
                    )
                    self._log("WARNING", "识别结果存在冲突: " + self._format_conflicts(conflicts, board))
                    detail = self._describe_conflicts(board)
                    self._set_status("识别完成，但盘面有重复数字")
                    self._show_warning(
                        "盘面冲突",
                        "识别结果中存在重复数字，红色格子需要手动修正后再求解。\n\n"
                        + (detail or self._format_conflicts(conflicts, board)),
                    )
                    return

                if not self._is_recognition_generation_current(recognition_generation):
                    return
                if auto_solve:
                    self._set_status("识别完成，开始自动求解")
                    self.root.after(
                        0,
                        lambda: self._solve_current_board(auto_fill_after=True)
                        if self._is_recognition_generation_current(recognition_generation)
                        else None,
                    )
                else:
                    self._set_status("识别完成")
            except Exception as exc:
                if not self._is_recognition_generation_current(recognition_generation):
                    return
                self._recognition_started_at = None
                self._log("ERROR", f"OCR 识别失败: {exc}\n{traceback.format_exc()}")
                self._set_status("识别失败")
                self._show_error(
                    "OCR 识别失败",
                    f"{exc}\n\n请确认 Tesseract 可用，图片清晰且包含完整数独边框。",
                )
            finally:
                self._stop_recognition_animation(recognition_generation)

        self._run_background(task)

    def _generate_complete_board(self):
        base = 3
        side = base * base

        def pattern(row, col):
            return (base * (row % base) + row // base + col) % side

        row_groups = random.sample(range(base), base)
        rows = [group * base + row for group in row_groups for row in random.sample(range(base), base)]
        col_groups = random.sample(range(base), base)
        cols = [group * base + col for group in col_groups for col in random.sample(range(base), base)]
        numbers = random.sample(range(1, side + 1), side)
        return [[numbers[pattern(row, col)] for col in cols] for row in rows]

    def _generate_puzzle(self, difficulty):
        clue_targets = {"简单": 42, "中等": 34, "困难": 30, "专家": 26}
        target_clues = clue_targets.get(difficulty, 34)
        solution = self._generate_complete_board()
        puzzle = [row[:] for row in solution]
        cells = [(row, col) for row in range(9) for col in range(9)]
        random.shuffle(cells)
        clues = 81

        for row, col in cells:
            if clues <= target_clues:
                break
            backup = puzzle[row][col]
            puzzle[row][col] = 0
            result = SudokuSolver(puzzle).solve_with_uniqueness_check(max_solutions=2)
            if result["is_unique"]:
                clues -= 1
            else:
                puzzle[row][col] = backup
        return puzzle, solution

    def on_generate_puzzle(self):
        if self._generation_running:
            self._set_status("正在生成题目，请稍候")
            return
        difficulty = self.generate_difficulty.get()
        self._generation_running = True
        self._cancel_solution_animation()
        self._exit_teaching_mode(silent=True)
        self._set_status(f"正在生成{difficulty}题目")
        self._log("INFO", f"开始生成{difficulty}数独题目")

        def task():
            started = time.perf_counter()
            try:
                puzzle, _solution = self._generate_puzzle(difficulty)
                elapsed_ms = (time.perf_counter() - started) * 1000

                def apply_generated():
                    self._generation_running = False
                    self.recognized_board = None
                    self.original_board = [row[:] for row in puzzle]
                    self.solution = None
                    self.grid_coords = None
                    self._clear_fill_target_window()
                    self.last_fill_payload = None
                    self.performance["last_difficulty"] = difficulty
                    self._set_board(puzzle, "manual")
                    self._update_metrics()
                    self._log("INFO", f"生成完成，耗时 {elapsed_ms:.0f}ms")
                    self._set_status(f"已生成{difficulty}题目，可直接求解")

                self.root.after(0, apply_generated)
            except Exception as exc:
                self._generation_running = False
                self._log("ERROR", f"生成题目失败: {exc}\n{traceback.format_exc()}")
                self._set_status("生成题目失败")
                self._show_error("生成题目失败", str(exc))

        self._run_background(task)

    def _append_log_to_ui(self, messages):
        if not messages:
            return
        self.log_text.config(state="normal")
        for raw_message in messages:
            lines = str(raw_message).splitlines() or [str(raw_message)]
            for index, message in enumerate(lines):
                match = re.match(r"^\[(?P<timestamp>[^\]]+)\]\s+(?P<level>[A-Z]+):\s*(?P<detail>.*)$", message)
                if not match:
                    self.log_text.insert(tk.END, message + "\n", ("detail",))
                    continue

                timestamp = f"[{match.group('timestamp')}] "
                level = match.group("level")
                detail = match.group("detail")
                self.log_text.insert(tk.END, timestamp, ("timestamp",))

                level_tag = "detail"
                if level == "ERROR":
                    level_tag = "error"
                elif level == "WARNING":
                    level_tag = "warning"
                elif level == "INFO":
                    level_tag = "info"
                self.log_text.insert(tk.END, f"{level}: ", (level_tag,))

                detail_tags = ["detail"]
                if "耗时" in detail or "完成时间" in detail or "结束时间" in detail or "总耗时" in detail:
                    detail_tags.append("timing")
                if "唯余法" in detail or "隐藏唯一数" in detail or "求解器提示" in detail:
                    detail_tags.append("logic")
                if level_tag not in detail_tags:
                    detail_tags.append(level_tag)
                self.log_text.insert(tk.END, detail, tuple(detail_tags))
                self.log_text.insert(tk.END, "\n")
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        overflow = line_count - self.MAX_LOG_LINES
        if overflow > 0:
            self.log_text.delete("1.0", f"{overflow + 1}.0")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

    def _run_on_ui_thread(self, callback):
        try:
            if not self.root.winfo_exists():
                return
            if threading.current_thread() is threading.main_thread():
                callback()
            else:
                self.root.after(0, callback)
        except (tk.TclError, RuntimeError):
            return

    def _queue_log_message(self, message):
        self._pending_log_messages.append(message)
        if self._log_flush_job is None:
            self._log_flush_job = self.root.after(self.LOG_FLUSH_DELAY_MS, self._flush_log_messages)

    def _flush_log_messages(self):
        self._log_flush_job = None
        if not self._pending_log_messages:
            return
        messages = list(self._pending_log_messages)
        self._pending_log_messages.clear()
        self._append_log_to_ui(messages)

    def _reset_logger_file(self):
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self.log_path.write_text("", encoding="utf-8")
        except OSError:
            pass
        handler = logging.FileHandler(self.log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        self.logger.addHandler(handler)

    def on_clear_log(self):
        if self._log_flush_job is not None:
            self.root.after_cancel(self._log_flush_job)
            self._log_flush_job = None
        self._pending_log_messages.clear()
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state="disabled")
        self._reset_logger_file()
        self._log("INFO", "日志已清空")
        self._set_status("日志已清空")

    def _log(self, level, message):
        getattr(self.logger, level.lower())(message)
        timestamp = time.strftime("%H:%M:%S")
        self._run_on_ui_thread(lambda: self._queue_log_message(f"[{timestamp}] {level}: {message}"))

    def _set_status(self, message):
        self._run_on_ui_thread(lambda: self.status_var.set(message))

    def _show_info(self, title, message):
        self._run_on_ui_thread(lambda: messagebox.showinfo(title, message))

    def _show_warning(self, title, message):
        self._run_on_ui_thread(lambda: messagebox.showwarning(title, message))

    def _show_error(self, title, message):
        self._run_on_ui_thread(lambda: messagebox.showerror(title, message))

    def _root_window_handle(self):
        if sys.platform != "win32":
            return None
        try:
            hwnd = int(self.root.winfo_id())
            try:
                root_hwnd = ctypes.windll.user32.GetAncestor(hwnd, 2)
                if root_hwnd:
                    hwnd = int(root_hwnd)
            except Exception:
                pass
            return hwnd
        except (tk.TclError, ValueError, TypeError):
            return None

    def _window_info_from_handle(self, hwnd, allow_self=False):
        if sys.platform != "win32" or not hwnd:
            return None
        try:
            user32 = ctypes.windll.user32
            hwnd = int(hwnd)
            if not user32.IsWindow(hwnd):
                return None
            root_hwnd = user32.GetAncestor(hwnd, 2)
            if root_hwnd:
                hwnd = int(root_hwnd)
            if not allow_self and hwnd == self._root_window_handle():
                return None
            title_buffer = ctypes.create_unicode_buffer(512)
            class_buffer = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
            user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
            return {
                "hwnd": hwnd,
                "title": title_buffer.value.strip(),
                "class_name": class_buffer.value.strip(),
            }
        except Exception:
            return None

    def _capture_foreground_window_info(self, allow_self=False):
        if sys.platform != "win32":
            return None
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            return None
        return self._window_info_from_handle(hwnd, allow_self=allow_self)

    def _capture_window_at_point(self, x, y, allow_self=False):
        if sys.platform != "win32":
            return None
        try:
            point = wintypes.POINT(int(round(x)), int(round(y)))
            hwnd = ctypes.windll.user32.WindowFromPoint(point)
        except Exception:
            return None
        return self._window_info_from_handle(hwnd, allow_self=allow_self)

    def _capture_window_for_grid(self, grid_coords, allow_self=False):
        if not grid_coords:
            return None
        x, y, w, h = grid_coords
        return self._capture_window_at_point(x + w / 2, y + h / 2, allow_self=allow_self)

    def _describe_window(self, window_info):
        if not window_info:
            return "未知窗口"
        if window_info.get("title"):
            return window_info["title"]
        if window_info.get("class_name"):
            return window_info["class_name"]
        hwnd = window_info.get("hwnd")
        return f"HWND {hwnd}" if hwnd else "未知窗口"

    def _clear_fill_target_window(self):
        self.fill_target_window = None

    def _set_fill_target_window(self, window_info, grid_coords=None, source_label=None):
        resolved = None
        if window_info:
            resolved = self._window_info_from_handle(window_info.get("hwnd"), allow_self=False)
        if resolved is None and grid_coords:
            resolved = self._capture_window_for_grid(grid_coords, allow_self=False)
        if resolved and resolved.get("hwnd") == self._root_window_handle():
            resolved = None
        self.fill_target_window = resolved
        if source_label:
            if resolved:
                self._log("INFO", f"{source_label}，已记录目标窗口: {self._describe_window(resolved)}")
            else:
                self._log("WARNING", f"{source_label}，未能记录目标窗口，填充时将依赖当前前台窗口")
        return resolved

    def _resolve_fill_target_window(self, grid_coords=None):
        if self.fill_target_window:
            resolved = self._window_info_from_handle(self.fill_target_window.get("hwnd"), allow_self=False)
            if resolved:
                if not resolved.get("title") and self.fill_target_window.get("title"):
                    resolved["title"] = self.fill_target_window["title"]
                if not resolved.get("class_name") and self.fill_target_window.get("class_name"):
                    resolved["class_name"] = self.fill_target_window["class_name"]
                if resolved.get("hwnd") != self._root_window_handle():
                    return resolved
            else:
                resolved = None
        if grid_coords:
            resolved = self._capture_window_for_grid(grid_coords, allow_self=False)
            if resolved and resolved.get("hwnd") != self._root_window_handle():
                return resolved
        return None

    def _activate_window(self, window_info, allow_self=False):
        if sys.platform != "win32":
            return False, None, "当前系统不支持窗口切换"
        resolved = self._window_info_from_handle(window_info.get("hwnd") if window_info else None, allow_self=allow_self)
        if resolved is None:
            return False, None, "窗口句柄无效或窗口已关闭"
        hwnd = resolved["hwnd"]
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            current_thread = kernel32.GetCurrentThreadId()
            fg_hwnd = user32.GetForegroundWindow()
            fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
            target_thread = user32.GetWindowThreadProcessId(hwnd, None)
            attached_threads = []
            try:
                if fg_thread and fg_thread != current_thread:
                    user32.AttachThreadInput(current_thread, fg_thread, True)
                    attached_threads.append(fg_thread)
                if target_thread and target_thread not in {0, current_thread, fg_thread}:
                    user32.AttachThreadInput(current_thread, target_thread, True)
                    attached_threads.append(target_thread)
                if user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, 9)
                else:
                    user32.ShowWindow(hwnd, 5)
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                user32.SetActiveWindow(hwnd)
                user32.SetFocus(hwnd)
                time.sleep(0.05)
                active = self._window_info_from_handle(user32.GetForegroundWindow(), allow_self=True)
                if active and active.get("hwnd") == hwnd:
                    return True, resolved, None
                user32.keybd_event(0x12, 0, 0, 0)
                user32.keybd_event(0x12, 0, 0x0002, 0)
                user32.SetForegroundWindow(hwnd)
                time.sleep(0.05)
                active = self._window_info_from_handle(user32.GetForegroundWindow(), allow_self=True)
                if active and active.get("hwnd") == hwnd:
                    return True, resolved, None
                return False, resolved, "系统拒绝切换到目标窗口"
            finally:
                for thread_id in reversed(attached_threads):
                    try:
                        user32.AttachThreadInput(current_thread, thread_id, False)
                    except Exception:
                        pass
        except Exception as exc:
            return False, resolved, str(exc)

    def _restore_window(self, focus=True):
        self.root.deiconify()
        self.root.update_idletasks()
        if self.button_mode_active:
            try:
                self._apply_button_mode_window_state()
            except tk.TclError:
                pass
        desired_topmost = self._button_mode_topmost_enabled()
        if not focus:
            self.root.after(100, lambda: self.root.attributes("-topmost", desired_topmost))
            return
        self.root.lift()
        self.root.focus_force()
        self.root.after(100, lambda: self.root.attributes("-topmost", True))
        self.root.after(250, lambda: self.root.attributes("-topmost", desired_topmost))

    def _minimize_window(self):
        try:
            self._ensure_global_hotkeys()
            self.root.iconify()
        except tk.TclError:
            return

    def _normalize_cell_text(self, row, col):
        cell = self.cells[row][col]
        value = cell.get().strip()
        digits = "".join(ch for ch in value if ch in "123456789")
        normalized = digits[:1]
        if value != normalized:
            self.updating_ui = True
            cell.delete(0, tk.END)
            if normalized:
                cell.insert(0, normalized)
            self.updating_ui = False
        return int(normalized) if normalized else 0

    def _committed_cell_value(self, row, col):
        if self.cell_sources[row][col] == "solution" and self.solution is not None:
            return self.solution[row][col]
        board = getattr(self, "original_board", None)
        if board is not None:
            return board[row][col]
        return 0

    def _invalidate_cached_solution(self):
        self.solution = None
        self.last_fill_payload = None

    def _refresh_cell_style(self, row, col):
        cell = self.cells[row][col]
        source = self.cell_sources[row][col]
        frame = self.cell_frames[row][col] if hasattr(self, "cell_frames") else None
        base_bg = self._cell_base_bg(row, col)
        frame_color = self.CELL_RING
        font_size = getattr(self, "current_cell_font_size", self.CELL_FONT_LIGHT[1])
        font = self._cell_font_for_source("empty", font_size)
        color = self.TEXT

        if source == "ocr":
            color = self.TEXT
            frame_color = self._blend_color(self.CELL_RING, self.TEXT, 0.12)
            font = self._cell_font_for_source(source, font_size)
        elif source == "manual":
            color = self.MANUAL_COLOR
            frame_color = self._blend_color(self.CELL_RING_ACTIVE, self.MANUAL_COLOR, 0.18)
            font = self._cell_font_for_source(source, font_size)
        elif source == "solution":
            color = self.FILL_COLOR
            base_bg = self._cell_base_bg(row, col, self.SOLUTION_BG)
            frame_color = self._blend_color(self.CELL_RING_ACTIVE, self.FILL_COLOR, 0.24)
            font = self._cell_font_for_source(source, font_size)

        value = cell.get().strip()[:1]
        if self.selected_cell is not None:
            selected_row, selected_col = self.selected_cell
            if row == selected_row or col == selected_col or self._cell_in_same_box(row, col, selected_row, selected_col):
                base_bg = self._blend_color(base_bg, self.PRIMARY, 0.08)
                frame_color = self._blend_color(frame_color, self.PRIMARY, 0.10)
        if self.selected_digit and value == str(self.selected_digit):
            base_bg = self._blend_color(base_bg, self.PRIMARY, 0.19)
            frame_color = self.CELL_FOCUS
        if self.selected_candidate_cell == (row, col) or self.selected_cell == (row, col):
            base_bg = self._blend_color(base_bg, self.SOFT_BLUE, 0.22)
            frame_color = self.CELL_FOCUS
        if (row, col) in self.hint_context_cells:
            base_bg = self._blend_color(base_bg, self.PRIMARY, 0.10)
            frame_color = self._blend_color(frame_color, self.PRIMARY, 0.18)
        if (row, col) in self.hint_focus_cells:
            base_bg = self._blend_color(self.SOFT_BLUE, self.PRIMARY, 0.16)
            frame_color = self.PRIMARY
        if (row, col) in self.teaching_context_cells:
            base_bg = self._blend_color(base_bg, self.PRIMARY, 0.10)
            frame_color = self._blend_color(frame_color, self.PRIMARY, 0.16)
        if (row, col) in self.teaching_elimination_cells:
            base_bg = self._blend_color(base_bg, self.MUTED, 0.10)
            frame_color = self._blend_color(frame_color, self.MUTED, 0.22)
            color = self.MUTED
        if (row, col) in self.teaching_focus_cells:
            base_bg = self.CELL_WARNING
            frame_color = self.PRIMARY
            color = self.TEXT
        if (row, col) in self.low_confidence_cells:
            frame_color = self.CELL_WARNING

        if frame is not None:
            frame.config(bg=frame_color)
        cell.config(bg=base_bg, fg=color, font=font, insertbackground=color if source != "solution" else self.TEXT)

    def _refresh_all_cell_styles(self):
        for row in range(9):
            for col in range(9):
                self._refresh_cell_style(row, col)

    def _set_board(self, board, source):
        if hasattr(self, "_solution_anim_job") and self._solution_anim_job is not None:
            self._cancel_solution_animation()
        self._exit_teaching_mode(silent=True)
        self._clear_hint_feedback(refresh=False)
        self._hide_candidate_popup()
        self.selected_cell = None
        self.selected_digit = None
        self.selected_candidate_cell = None
        if source != "ocr":
            self.ocr_confidence_map = None
            self.low_confidence_cells = set[tuple[int, int]]()
        self.updating_ui = True
        for row in range(9):
            for col in range(9):
                value = board[row][col]
                cell = self.cells[row][col]
                cell.delete(0, tk.END)
                if value:
                    cell.insert(0, str(value))
                    self.cell_sources[row][col] = source
                else:
                    self.cell_sources[row][col] = "empty"
        self.updating_ui = False
        self._refresh_all_cell_styles()
        self._update_metrics()

    def _on_cell_edit(self, row, col):
        if self.updating_ui:
            return
        if self.teaching_active:
            self._exit_teaching_mode(silent=True)
        self.low_confidence_cells.discard((row, col))
        previous_value = self._committed_cell_value(row, col)
        self.selected_cell = (row, col)
        value = self._normalize_cell_text(row, col)
        self.selected_digit = value or None
        self.selected_candidate_cell = (row, col) if value == 0 else None
        recognized = self.recognized_board[row][col] if self.recognized_board else 0
        if value == 0:
            self.cell_sources[row][col] = "empty"
        elif recognized != 0 and value == recognized:
            self.cell_sources[row][col] = "ocr"
        else:
            self.cell_sources[row][col] = "manual"
        if value != previous_value:
            self._invalidate_cached_solution()
        self._refresh_all_cell_styles()
        self._update_metrics()

    def _on_cell_click(self, row, col, _event=None):
        self._clear_hint_feedback(refresh=False)
        self._select_cell(row, col, open_popup=True)

    def _select_cell(self, row, col, open_popup=False, focus=True):
        row = max(0, min(8, row))
        col = max(0, min(8, col))
        self._hide_candidate_popup()
        self.selected_cell = (row, col)
        value = self._normalize_cell_text(row, col)
        self.selected_digit = value or None
        self.selected_candidate_cell = (row, col) if value == 0 else None
        if focus:
            try:
                self.cells[row][col].focus_set()
            except tk.TclError:
                pass
        self._refresh_all_cell_styles()
        if open_popup:
            candidates = self._candidates_for_cell(self._get_board_from_ui(), row, col)
            self._show_candidate_popup(row, col, candidates, value)
        return value

    def _on_cell_keypress(self, row, col, event):
        if self.updating_ui:
            return None
        key = getattr(event, "keysym", "")
        if key in {"Up", "Down", "Left", "Right"}:
            deltas = {
                "Up": (-1, 0),
                "Down": (1, 0),
                "Left": (0, -1),
                "Right": (0, 1),
            }
            delta_row, delta_col = deltas[key]
            self._select_cell(row + delta_row, col + delta_col, open_popup=False, focus=True)
            return "break"
        if key == "Tab":
            shift_pressed = bool(getattr(event, "state", 0) & 0x0001)
            index = row * 9 + col + (-1 if shift_pressed else 1)
            index = max(0, min(80, index))
            self._select_cell(index // 9, index % 9, open_popup=False, focus=True)
            return "break"
        if key in {"Return", "KP_Enter"}:
            shift_pressed = bool(getattr(event, "state", 0) & 0x0001)
            self._select_cell(row - 1 if shift_pressed else row + 1, col, open_popup=False, focus=True)
            return "break"
        return None

    def _candidates_for_cell(self, board, row, col):
        if board[row][col]:
            return []
        used = set(board[row])
        used.update(board[r][col] for r in range(9))
        box_row = (row // 3) * 3
        box_col = (col // 3) * 3
        for r in range(box_row, box_row + 3):
            for c in range(box_col, box_col + 3):
                used.add(board[r][c])
        return [value for value in range(1, 10) if value not in used]

    def _cell_in_same_box(self, row, col, target_row, target_col):
        return row // 3 == target_row // 3 and col // 3 == target_col // 3

    def _solver_scan_summary(self, board):
        candidates_map = {}
        empty_cells = []
        naked_single_count = 0

        for row in range(9):
            for col in range(9):
                if board[row][col]:
                    continue
                candidates = self._candidates_for_cell(board, row, col)
                candidates_map[(row, col)] = candidates
                empty_cells.append((row, col))
                if len(candidates) == 1:
                    naked_single_count += 1

        hidden_single_cells = set()

        def scan_unit(unit_cells):
            by_digit = {digit: [] for digit in range(1, 10)}
            for row, col in unit_cells:
                for candidate in candidates_map.get((row, col), ()):
                    by_digit[candidate].append((row, col))
            for positions in by_digit.values():
                if len(positions) == 1:
                    hidden_single_cells.add(positions[0])

        for index in range(9):
            scan_unit([(index, col) for col in range(9)])
            scan_unit([(row, index) for row in range(9)])
        for box_row in range(0, 9, 3):
            for box_col in range(0, 9, 3):
                scan_unit([(box_row + r, box_col + c) for r in range(3) for c in range(3)])

        return {
            "empty_count": len(empty_cells),
            "naked_singles": naked_single_count,
            "hidden_singles": len(hidden_single_cells),
        }

    def _apply_cell_value(self, row, col, value):
        previous_value = self._committed_cell_value(row, col)
        self.updating_ui = True
        self.cells[row][col].delete(0, tk.END)
        if value:
            self.cells[row][col].insert(0, str(value))
        self.updating_ui = False

        self.low_confidence_cells.discard((row, col))
        recognized = self.recognized_board[row][col] if self.recognized_board else 0
        if value == 0:
            self.cell_sources[row][col] = "empty"
        elif recognized != 0 and value == recognized:
            self.cell_sources[row][col] = "ocr"
        else:
            self.cell_sources[row][col] = "manual"

        if value != previous_value:
            self._invalidate_cached_solution()
        self.selected_cell = (row, col)
        self.selected_digit = value or None
        self.selected_candidate_cell = (row, col) if value == 0 else None
        self._refresh_all_cell_styles()
        self._update_metrics()

    def _hide_candidate_popup(self):
        if self.candidate_popup is None:
            return
        try:
            self.candidate_popup.destroy()
        except tk.TclError:
            pass
        self.candidate_popup = None

    def _pick_digit_from_popup(self, row, col, value):
        self._hide_candidate_popup()
        self._apply_cell_value(row, col, value)
        if value:
            self._set_status(f"已将 R{row + 1}C{col + 1} 改为 {value}")
        else:
            self._set_status(f"已清空 R{row + 1}C{col + 1}")

    def _show_candidate_popup(self, row, col, candidates, current_value=0):
        cell = self.cells[row][col]
        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.transient(self.root)
        popup.configure(bg=self.BG)

        shell = tk.Frame(popup, bg=self.BOARD_RING, highlightthickness=1, highlightbackground=self.BORDER)
        shell.pack()
        canvas = tk.Canvas(shell, width=176, height=194, bg=self.PANEL, bd=0, highlightthickness=0, relief="flat")
        canvas.pack()

        center_x = 88
        center_y = 82
        orbit_radius = 56
        node_radius = 18
        allowed_digits = set(range(1, 10)) if current_value else set(candidates)

        canvas.create_oval(10, 10, 166, 166, fill=self.PANEL, outline=self.BORDER, width=1)
        canvas.create_text(
            center_x,
            20,
            text=f"R{row + 1}C{col + 1}",
            fill=self.MUTED,
            font=("Microsoft YaHei UI", 8, "bold"),
        )

        def bind_digit(tag_name, value):
            canvas.tag_bind(tag_name, "<Button-1>", lambda _event, v=value: self._pick_digit_from_popup(row, col, v))

        for index, digit in enumerate(range(1, 10)):
            angle = math.radians(-90 + index * 40)
            node_x = center_x + math.cos(angle) * orbit_radius
            node_y = center_y + math.sin(angle) * orbit_radius
            enabled = digit in allowed_digits or digit == current_value
            fill = self.PRIMARY if digit == current_value else (self.SOFT_BLUE if enabled else self.SUBTLE)
            text_color = "white" if digit == current_value else (self.TEXT if enabled else self.MUTED)
            outline = self.PRIMARY if digit == current_value else self.BORDER
            tag = f"dial_digit_{digit}"
            canvas.create_oval(
                node_x - node_radius,
                node_y - node_radius,
                node_x + node_radius,
                node_y + node_radius,
                fill=fill,
                outline=outline,
                width=2 if digit == current_value else 1,
                tags=(tag,),
            )
            canvas.create_text(
                node_x,
                node_y,
                text=str(digit),
                fill=text_color,
                font=("Segoe UI", 11, "bold"),
                tags=(tag,),
            )
            if enabled:
                bind_digit(tag, digit)

        clear_enabled = current_value != 0
        clear_fill = self.PANEL if clear_enabled else self.SUBTLE
        clear_text = self.MUTED if clear_enabled else self._blend_color(self.MUTED, self.PANEL, 0.35)
        canvas.create_oval(
            center_x - 24,
            center_y - 24,
            center_x + 24,
            center_y + 24,
            fill=clear_fill,
            outline=self.BORDER,
            width=1,
            tags=("dial_clear",),
        )
        canvas.create_text(
            center_x,
            center_y,
            text="清空",
            fill=clear_text,
            font=("Microsoft YaHei UI", 8, "bold"),
            tags=("dial_clear",),
        )
        if clear_enabled:
            bind_digit("dial_clear", 0)

        detail = "候选 " + (" ".join(str(value) for value in candidates) if candidates else "无")
        if current_value:
            detail = f"当前 {current_value}  ·  点击直接修正"
        canvas.create_text(
            center_x,
            178,
            text=detail,
            fill=self.MUTED,
            font=("Microsoft YaHei UI", 8),
        )

        popup.bind("<Escape>", lambda _event: self._hide_candidate_popup())
        popup.bind("<Button-3>", lambda _event: self._hide_candidate_popup())

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        popup_w = 178
        popup_h = 196
        x = cell.winfo_rootx() + cell.winfo_width() + 10
        y = cell.winfo_rooty() - 12
        if x + popup_w > screen_w - 8:
            x = max(8, cell.winfo_rootx() - popup_w - 10)
        if y + popup_h > screen_h - 8:
            y = max(8, screen_h - popup_h - 8)
        if y < 8:
            y = 8
        popup.geometry(f"{popup_w}x{popup_h}+{x}+{y}")
        self.candidate_popup = popup
        self.root.after(4500, lambda: self._hide_candidate_popup() if self.candidate_popup is popup else None)

    def _hide_hint_popup(self):
        if self.hint_popup is None:
            return
        try:
            self.hint_popup.destroy()
        except tk.TclError:
            pass
        self.hint_popup = None

    def _show_hint_popup(self, row, col, message):
        self._hide_hint_popup()
        cell = self.cells[row][col]
        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.transient(self.root)
        popup.configure(bg=self.PRIMARY)
        label = tk.Label(
            popup,
            text=message,
            bg=self.PANEL,
            fg=self.TEXT,
            justify="left",
            wraplength=240,
            padx=10,
            pady=6,
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        label.pack(padx=1, pady=1)
        popup.update_idletasks()
        popup_w = max(1, popup.winfo_reqwidth())
        popup_h = max(1, popup.winfo_reqheight())
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = cell.winfo_rootx() + cell.winfo_width() + 10
        y = max(0, cell.winfo_rooty() - 6)
        if x + popup_w > screen_w - 8:
            x = max(8, cell.winfo_rootx() - popup_w - 10)
        if y + popup_h > screen_h - 8:
            y = max(8, screen_h - popup_h - 8)
        if y < 8:
            y = 8
        popup.geometry(f"+{x}+{y}")
        self.hint_popup = popup

    def _clear_hint_feedback(self, refresh=True):
        if self._hint_clear_job is not None:
            try:
                self.root.after_cancel(self._hint_clear_job)
            except tk.TclError:
                pass
            self._hint_clear_job = None
        self.hint_focus_cells.clear()
        self.hint_context_cells.clear()
        self._hide_hint_popup()
        if refresh:
            self._refresh_all_cell_styles()

    def _activate_hint_feedback(
        self,
        target_cell: tuple[int, int],
        context_cells: set[tuple[int, int]] | None,
        message: str,
    ):
        self._clear_hint_feedback(refresh=False)
        self.hint_focus_cells = {target_cell}
        resolved_context: set[tuple[int, int]] = set(context_cells or ())
        self.hint_context_cells = resolved_context
        self._refresh_all_cell_styles()
        self._show_hint_popup(target_cell[0], target_cell[1], message)
        self._hint_clear_job = self.root.after(3600, self._clear_hint_feedback)

    def _track_teaching_event(self, event, **payload):
        details = {"event": event}
        details.update(payload)
        self.logger.info("TEACHING_EVENT " + json.dumps(details, ensure_ascii=False))

    def _is_teaching_panel_visible(self):
        if not hasattr(self, "main_pane") or not hasattr(self, "teaching_panel"):
            return False
        try:
            return str(self.teaching_panel) in {str(pane) for pane in self.main_pane.panes()}
        except tk.TclError:
            return False

    def _show_teaching_panel(self):
        if self._is_teaching_panel_visible():
            return
        try:
            self.main_pane.add(self.teaching_panel, minsize=self.MIN_TEACHING_PANEL_WIDTH)
        except tk.TclError:
            return
        self._schedule_board_resize()

    def _hide_teaching_panel(self):
        if not self._is_teaching_panel_visible():
            return
        try:
            self.main_pane.forget(self.teaching_panel)
        except tk.TclError:
            return
        self._schedule_board_resize()

    def _refresh_teaching_buttons(self):
        if not hasattr(self, "teaching_prev_button"):
            return
        active = self.teaching_active and bool(self.teaching_steps)
        last_index = len(self.teaching_steps) - 1
        prev_state = "normal" if active and self.teaching_current_step >= 0 else "disabled"
        next_state = "normal" if active and self.teaching_current_step < last_index else "disabled"
        auto_state = "normal" if active and self.teaching_current_step < last_index else "disabled"
        exit_state = "normal" if self.teaching_active else "disabled"
        start_state = "disabled" if self.teaching_active else "normal"
        start_text = "教学中" if self.teaching_active else "开始"
        self.teaching_start_button.config(state=start_state, text=start_text)
        self.teaching_prev_button.config(state=prev_state)
        self.teaching_next_button.config(state=next_state)
        self.teaching_autoplay_button.config(
            state=auto_state,
            text="停止播放 ❚❚" if self.teaching_auto_play else "自动播放 ▶",
        )
        self.teaching_exit_button.config(state=exit_state)
        self.teaching_header_exit_button.config(state=exit_state)

    def _teaching_speed_value(self):
        value = self.teaching_speed_var.get()
        return {"0.5x": 0.5, "1x": 1.0, "2x": 2.0}.get(value, 1.0)

    def _teaching_delay_ms(self):
        speed = self._teaching_speed_value()
        return int({0.5: 2000, 1.0: 1500, 2.0: 1000}.get(speed, 1500))

    def _cancel_teaching_autoplay(self):
        if self._teaching_autoplay_job is not None:
            try:
                self.root.after_cancel(self._teaching_autoplay_job)
            except tk.TclError:
                pass
            self._teaching_autoplay_job = None
        self.teaching_auto_play = False

    def _reset_teaching_panel(self, message=None):
        self.teaching_step_var.set("步骤 0 / 0")
        self.teaching_strategy_var.set("当前策略：未开始")
        self.teaching_explanation_var.set("点击“开始教学”，系统会按人类可理解策略生成分步讲解。")
        self.teaching_candidate_var.set("候选数：-")
        self.teaching_message_var.set(message or "优先使用唯一候选数和唯一位置。")
        self._refresh_teaching_buttons()

    def _exit_teaching_mode(self, silent=False):
        was_active = self.teaching_active
        self._cancel_teaching_autoplay()
        self.teaching_active = False
        self.teaching_steps = []
        self.teaching_current_step = -1
        self.teaching_base_board = None
        self.teaching_base_sources = None
        self.teaching_focus_cells.clear()
        self.teaching_context_cells.clear()
        self.teaching_elimination_cells.clear()
        self._reset_teaching_panel()
        self._hide_teaching_panel()
        if hasattr(self, "cells"):
            self._refresh_all_cell_styles()
        if was_active and not silent:
            self._track_teaching_event("teaching_exit")
            self._set_status("已退出教学模式")

    def _board_for_teaching_start(self):
        current_board = self._get_board_from_ui()
        board = [[0 for _ in range(9)] for _ in range(9)]
        sources = [["empty" for _ in range(9)] for _ in range(9)]
        for row in range(9):
            for col in range(9):
                source = self.cell_sources[row][col]
                value = current_board[row][col]
                board[row][col] = value
                sources[row][col] = source if value else "empty"
        return board, sources

    def _cells_from_teaching_payload(self, cells):
        resolved = set()
        for cell in cells or ():
            try:
                row = int(cell["row"]) - 1
                col = int(cell["col"]) - 1
            except (KeyError, TypeError, ValueError):
                continue
            if 0 <= row < 9 and 0 <= col < 9:
                resolved.add((row, col))
        return resolved

    def _set_teaching_highlight(self, step):
        self.teaching_focus_cells.clear()
        self.teaching_context_cells.clear()
        self.teaching_elimination_cells.clear()
        if not step:
            return
        row = step["position"]["row"] - 1
        col = step["position"]["col"] - 1
        self.teaching_focus_cells.add((row, col))
        highlight = step.get("highlight", {})
        self.teaching_context_cells = self._cells_from_teaching_payload(highlight.get("context_cells"))
        self.teaching_elimination_cells = self._cells_from_teaching_payload(highlight.get("eliminated_cells"))

    def _render_teaching_board(self, step_index):
        if self.teaching_base_board is None or self.teaching_base_sources is None:
            return
        self.updating_ui = True
        try:
            for row in range(9):
                for col in range(9):
                    value = self.teaching_base_board[row][col]
                    self.cells[row][col].delete(0, tk.END)
                    if value:
                        self.cells[row][col].insert(0, str(value))
                    self.cell_sources[row][col] = self.teaching_base_sources[row][col] if value else "empty"
            for index in range(step_index + 1):
                step = self.teaching_steps[index]
                row = step["position"]["row"] - 1
                col = step["position"]["col"] - 1
                self.cells[row][col].delete(0, tk.END)
                self.cells[row][col].insert(0, str(step["value"]))
                self.cell_sources[row][col] = "solution"
                self.low_confidence_cells.discard((row, col))
        finally:
            self.updating_ui = False

        if step_index >= 0:
            step = self.teaching_steps[step_index]
            row = step["position"]["row"] - 1
            col = step["position"]["col"] - 1
            self.selected_cell = (row, col)
            self.selected_digit = step["value"]
            self.selected_candidate_cell = None
            self._set_teaching_highlight(step)
        else:
            self.selected_cell = None
            self.selected_digit = None
            self.selected_candidate_cell = None
            self._set_teaching_highlight(None)
        self._refresh_all_cell_styles()
        self._update_metrics()

    def _show_teaching_step(self, index):
        if not self.teaching_steps:
            self._reset_teaching_panel()
            return
        index = max(-1, min(len(self.teaching_steps) - 1, index))
        self.teaching_current_step = index
        self._render_teaching_board(index)

        total = len(self.teaching_steps)
        if index < 0:
            self.teaching_step_var.set(f"步骤 0 / {total}")
            self.teaching_strategy_var.set("当前策略：准备开始")
            self.teaching_explanation_var.set("点击“下一步”查看第 1 步推理。")
            self.teaching_candidate_var.set("候选数：-")
            self.teaching_message_var.set("盘面已回到教学起点。")
        else:
            step = self.teaching_steps[index]
            self.teaching_step_var.set(f"步骤 {step['step']} / {step['total_steps']}")
            self.teaching_strategy_var.set(f"当前策略：{step['strategy_label']}")
            self.teaching_explanation_var.set(step["explanation"])
            self.teaching_candidate_var.set(
                "候选数："
                + "、".join(str(value) for value in step["candidates_before"])
                + " → "
                + "、".join(str(value) for value in step["candidates_after"])
            )
            highlight = step.get("highlight", {})
            self.teaching_message_var.set(
                f"高亮：第{highlight.get('row')}行、第{highlight.get('col')}列、"
                f"第{highlight.get('block')}宫；灰色为排除依据。"
            )
        self._refresh_teaching_buttons()

    def _schedule_teaching_autoplay(self):
        if not self.teaching_auto_play or not self.teaching_active:
            return
        self._teaching_autoplay_job = self.root.after(self._teaching_delay_ms(), self._teaching_autoplay_tick)

    def _teaching_autoplay_tick(self):
        self._teaching_autoplay_job = None
        if not self.teaching_auto_play or not self.teaching_active:
            return
        if self.teaching_current_step >= len(self.teaching_steps) - 1:
            self._cancel_teaching_autoplay()
            self._refresh_teaching_buttons()
            self._set_status("教学自动播放已完成")
            return
        self._show_teaching_step(self.teaching_current_step + 1)
        self._track_teaching_event("auto_play_step", step=self.teaching_current_step + 1)
        self._schedule_teaching_autoplay()

    def _peer_cells(self, row, col) -> set[tuple[int, int]]:
        peers: set[tuple[int, int]] = {(row, index) for index in range(9)}
        peers.update((index, col) for index in range(9))
        box_row = (row // 3) * 3
        box_col = (col // 3) * 3
        peers.update((box_row + r, box_col + c) for r in range(3) for c in range(3))
        peers.discard((row, col))
        return peers

    def _format_board(self, board):
        return "\n".join(" ".join(str(value) if value else "." for value in row) for row in board)

    def _format_cells(self, cells: set[tuple[int, int]]) -> str:
        return ", ".join(f"R{row + 1}C{col + 1}" for row, col in sorted(cells))

    def _find_low_confidence_cells(self, board, confidence_map) -> set[tuple[int, int]]:
        if not confidence_map:
            return set[tuple[int, int]]()
        cells: set[tuple[int, int]] = set()
        for row in range(9):
            for col in range(9):
                confidence = confidence_map[row][col]
                if board[row][col] and confidence < 65:
                    cells.add((row, col))
                elif board[row][col] == 0 and confidence >= 35:
                    cells.add((row, col))
        return cells

    def _format_solutions(self, solutions):
        if not solutions:
            return "无可显示结果"
        parts = []
        for index, solution in enumerate(solutions, start=1):
            parts.append(f"解 {index}:\n{self._format_board(solution)}")
        return "\n\n".join(parts)

    def _get_board_from_ui(self):
        board = []
        for row in range(9):
            current_row = []
            for col in range(9):
                current_row.append(self._normalize_cell_text(row, col))
            board.append(current_row)
        return board

    def _cancel_solution_animation(self):
        if self._solution_anim_job is not None:
            try:
                self.root.after_cancel(self._solution_anim_job)
            except tk.TclError:
                pass
            self._solution_anim_job = None
        if self._solution_anim_prev_cell is not None and hasattr(self, "cells"):
            row, col = self._solution_anim_prev_cell
            self._refresh_cell_style(row, col)
            self._solution_anim_prev_cell = None

    def _apply_solution_to_ui(self, solution, base_board, animate=True):
        self._cancel_solution_animation()
        if animate:
            self._animate_solution_to_ui(solution, base_board)
            return
        self.updating_ui = True
        for row in range(9):
            for col in range(9):
                if base_board[row][col] == 0 and solution[row][col] != 0:
                    self.cells[row][col].delete(0, tk.END)
                    self.cells[row][col].insert(0, str(solution[row][col]))
                    self.cell_sources[row][col] = "solution"
        self.updating_ui = False
        self._refresh_all_cell_styles()
        self._update_metrics()

    def _animate_solution_to_ui(self, solution, base_board):
        cells_to_fill = [
            (row, col)
            for row in range(9)
            for col in range(9)
            if base_board[row][col] == 0 and solution[row][col] != 0
        ]
        if not cells_to_fill:
            self._refresh_all_cell_styles()
            return

        self.updating_ui = True
        self._solution_anim_prev_cell = None

        def step(index=0):
            if self._solution_anim_prev_cell is not None:
                prev_row, prev_col = self._solution_anim_prev_cell
                self._refresh_cell_style(prev_row, prev_col)
                self._solution_anim_prev_cell = None

            if index >= len(cells_to_fill):
                self.updating_ui = False
                self._solution_anim_job = None
                self._refresh_all_cell_styles()
                self._update_metrics()
                return

            row, col = cells_to_fill[index]
            self.cells[row][col].delete(0, tk.END)
            self.cells[row][col].insert(0, str(solution[row][col]))
            self.cell_sources[row][col] = "solution"
            if hasattr(self, "cell_frames"):
                self.cell_frames[row][col].config(bg=self.PRIMARY)
            self.cells[row][col].config(bg=self.SOFT_BLUE, fg=self.FILL_COLOR, insertbackground=self.TEXT)
            self._solution_anim_prev_cell = (row, col)
            self._solution_anim_job = self.root.after(18, lambda: step(index + 1))

        step()

    def _find_conflicts(self, board):
        conflicts = set()
        for row in range(9):
            seen = {}
            for col in range(9):
                value = board[row][col]
                if value == 0:
                    continue
                if value in seen:
                    conflicts.add((row, col))
                    conflicts.add((row, seen[value]))
                else:
                    seen[value] = col
        for col in range(9):
            seen = {}
            for row in range(9):
                value = board[row][col]
                if value == 0:
                    continue
                if value in seen:
                    conflicts.add((row, col))
                    conflicts.add((seen[value], col))
                else:
                    seen[value] = row
        for box_row in range(0, 9, 3):
            for box_col in range(0, 9, 3):
                seen = {}
                for row in range(box_row, box_row + 3):
                    for col in range(box_col, box_col + 3):
                        value = board[row][col]
                        if value == 0:
                            continue
                        if value in seen:
                            conflicts.add((row, col))
                            conflicts.add(seen[value])
                        else:
                            seen[value] = (row, col)
        return sorted(conflicts)

    def _mark_conflicts(self, conflicts):
        self._refresh_all_cell_styles()
        for row, col in conflicts:
            if hasattr(self, "cell_frames"):
                self.cell_frames[row][col].config(bg=self.CONFLICT_RING)
            self.cells[row][col].config(fg="white", bg=self.DANGER, insertbackground="white")

    def _format_conflicts(self, conflicts, board):
        return ", ".join(f"R{row + 1}C{col + 1}={board[row][col]}" for row, col in conflicts)

    def _describe_conflicts(self, board):
        details = []

        def add_duplicates(label, values):
            seen = {}
            for index, value in values:
                if value == 0:
                    continue
                if value in seen:
                    details.append(f"{label} 有重复数字 {value}")
                else:
                    seen[value] = index

        for row in range(9):
            add_duplicates(f"第 {row + 1} 行", [(col, board[row][col]) for col in range(9)])
        for col in range(9):
            add_duplicates(f"第 {col + 1} 列", [(row, board[row][col]) for row in range(9)])
        for box_row in range(3):
            for box_col in range(3):
                values = []
                for row in range(box_row * 3, box_row * 3 + 3):
                    for col in range(box_col * 3, box_col * 3 + 3):
                        values.append(((row, col), board[row][col]))
                add_duplicates(f"第 {box_row * 3 + box_col + 1} 宫", values)
        return "\n".join(dict.fromkeys(details))

    def _cell_label_text(self, row, col, include_compact=True):
        human = f"第{row + 1}行第{col + 1}列"
        if include_compact:
            return f"{human}（R{row + 1}C{col + 1}）"
        return human

    def _unit_label_text(self, label):
        return str(label).replace(" ", "")

    def _reason_naked_single(self, row, col, value):
        return f"提示：{self._cell_label_text(row, col, include_compact=False)} 这一格只能填 {value}，所以这里填 {value}。"

    def _reason_hidden_single(self, label, row, col, value):
        unit_text = self._unit_label_text(label)
        if unit_text.endswith("行"):
            return (
                f"提示：在{unit_text}里，数字 {value} 只有第{col + 1}列可以放，"
                f"所以 {self._cell_label_text(row, col, include_compact=False)} 填 {value}。"
            )
        elif unit_text.endswith("列"):
            return (
                f"提示：在{unit_text}里，数字 {value} 只有第{row + 1}行可以放，"
                f"所以 {self._cell_label_text(row, col, include_compact=False)} 填 {value}。"
            )
        return (
            f"提示：在{unit_text}里，数字 {value} 只有 "
            f"{self._cell_label_text(row, col, include_compact=False)} 这一个位置合适，所以这里填 {value}。"
        )

    def _reason_solver_suggestion(self, row, col, value):
        return f"提示：如果先走下一步，建议从 {self._cell_label_text(row, col, include_compact=False)} 填 {value} 开始。"

    def _run_background(self, target):
        threading.Thread(target=target, daemon=True).start()

    def _candidate_map_for_board(self, board):
        candidates = {}
        for row in range(9):
            for col in range(9):
                if board[row][col] == 0:
                    candidates[(row, col)] = self._candidates_for_cell(board, row, col)
        return candidates

    def _find_hint_step(self, board):
        candidates = self._candidate_map_for_board(board)
        for (row, col), values in candidates.items():
            if len(values) == 1:
                value = values[0]
                return {
                    "row": row,
                    "col": col,
                    "value": value,
                    "reason": self._reason_naked_single(row, col, value),
                    "context_cells": self._peer_cells(row, col),
                }

        units = []
        units.extend((f"第 {row + 1} 行", [(row, col) for col in range(9)]) for row in range(9))
        units.extend((f"第 {col + 1} 列", [(row, col) for row in range(9)]) for col in range(9))
        for box_row in range(3):
            for box_col in range(3):
                cells = [
                    (row, col)
                    for row in range(box_row * 3, box_row * 3 + 3)
                    for col in range(box_col * 3, box_col * 3 + 3)
                ]
                units.append((f"第 {box_row * 3 + box_col + 1} 宫", cells))

        for label, cells in units:
            for value in range(1, 10):
                places = [cell for cell in cells if value in candidates.get(cell, [])]
                if len(places) == 1:
                    row, col = places[0]
                    return {
                        "row": row,
                        "col": col,
                        "value": value,
                        "reason": self._reason_hidden_single(label, row, col, value),
                        "context_cells": set(cells),
                    }

        result = SudokuSolver(board).solve_with_uniqueness_check(max_solutions=2)
        if result["solved"]:
            for row in range(9):
                for col in range(9):
                    if board[row][col] == 0:
                        value = result["solution"][row][col]
                        return {
                            "row": row,
                            "col": col,
                            "value": value,
                            "reason": self._reason_solver_suggestion(row, col, value),
                            "context_cells": self._peer_cells(row, col),
                        }
        return None

    def _run_hidden_fill_task(self, target, on_done, restore_focus=True):
        worker = threading.Thread(target=target, daemon=True)
        worker.start()
        self.root.after(80, lambda: self._watch_fill_worker(worker, on_done, restore_focus))

    def _watch_fill_worker(self, worker, on_done, restore_focus):
        if worker.is_alive():
            self.root.after(80, lambda: self._watch_fill_worker(worker, on_done, restore_focus))
            return
        self._restore_window(focus=restore_focus)
        on_done()

    def _hide_window_for_fill(self):
        try:
            self.root.withdraw()
            self.root.update_idletasks()
            return True
        except tk.TclError:
            return False

    def _start_fill(self, auto_started=False):
        if not self.solution:
            self._log("WARNING", "自动填充被拒绝: 尚未求解")
            self._set_status("请先求解后再自动填充")
            if not auto_started:
                self._show_warning("无法自动填充", "当前还没有可填充的答案，请先截图识别、导入图片或手动输入后求解。")
            return False
        if not self.grid_coords:
            self._log("WARNING", "自动填充被拒绝: 未校准坐标")
            self._set_status("请先校准坐标后再自动填充")
            if not auto_started:
                self._show_warning(
                    "需要校准坐标",
                    "自动填充需要知道屏幕上数独九宫格的位置。\n\n点击“校准坐标”后，先把鼠标停在九宫格左上角，3 秒后再停到右下角。",
                )
            return False

        if auto_started:
            self._log("INFO", f"求解完成，准备自动填充，坐标: {self.grid_coords}")
        else:
            self._log("INFO", f"准备自动填充，坐标: {self.grid_coords}")
        turbo_enabled = self.turbo_fill_enabled.get()
        if turbo_enabled:
            fill_pause = self.TURBO_STEP_DELAY
            click_settle_delay = self.TURBO_CLICK_SETTLE_DELAY
            mode_suffix = "（安全极速模式）"
        else:
            fill_pause = self.filler.delay
            click_settle_delay = self.filler.delay
            mode_suffix = ""
        self._log("INFO", f"当前填充延迟: {fill_pause:.3f} 秒/步{mode_suffix}")
        self._log("INFO", f"点击聚焦等待: {click_settle_delay:.3f} 秒/格")
        button_mode_fill = bool(self.button_mode_active)
        minimize_after_fill = bool(self.minimize_after_fill_enabled.get()) and not button_mode_fill
        if button_mode_fill:
            self._log("INFO", "按钮模式下开始填充，保留浮窗，不隐藏主窗口")
        else:
            self._log("INFO", "开始填充，隐藏主窗口以避免遮挡目标界面")

        solution = [row[:] for row in self.solution]
        grid_coords = tuple(self.grid_coords)
        fill_base = [row[:] for row in self.original_board]
        recognition_started_at = self._recognition_started_at if self.recognized_board is not None else None
        recognition_elapsed_ms = self.performance["last_ocr_ms"] if self.recognized_board is not None else None
        target_window = self._resolve_fill_target_window(grid_coords)
        if target_window:
            self._log("INFO", f"本次填充目标窗口: {self._describe_window(target_window)}")
        else:
            self._log("WARNING", "未记录目标窗口，填充时将依赖当前前台窗口")
        foreground_window = self._capture_foreground_window_info(allow_self=True)
        root_hwnd = self._root_window_handle()
        if foreground_window and foreground_window.get("hwnd") == root_hwnd:
            restore_window = None
            restore_gui_focus = True
        elif foreground_window and target_window and foreground_window.get("hwnd") == target_window.get("hwnd"):
            restore_window = None
            restore_gui_focus = False
        else:
            restore_window = foreground_window
            restore_gui_focus = False
        try:
            position = pyautogui.position()
            if hasattr(position, "x") and hasattr(position, "y"):
                mouse_start = (position.x, position.y)
            else:
                mouse_start = (position[0], position[1])
        except Exception:
            mouse_start = None
        self.last_fill_payload = {
            "solution": [row[:] for row in solution],
            "original_board": [row[:] for row in fill_base],
            "grid_coords": grid_coords,
            "mouse_start": mouse_start,
            "target_window": dict(target_window) if target_window else None,
        }
        if button_mode_fill:
            self._set_status("正在自动填充，可按 Esc 取消")
        else:
            self._set_status("正在自动填充，窗口已隐藏，可按 Esc 取消")
            self._hide_window_for_fill()
        outcome = {
            "status": "ok",
            "message": None,
            "traceback": None,
            "elapsed_ms": 0.0,
            "total_elapsed_ms": None,
            "recognition_elapsed_ms": recognition_elapsed_ms,
            "mouse_restored": False,
            "mouse_restore_error": None,
            "target_window": target_window,
            "target_switch_error": None,
            "window_restored": False,
            "window_restore_error": None,
            "restored_window": restore_window,
        }

        def task():
            fill_started = None
            try:
                if target_window:
                    active_window = self._capture_foreground_window_info(allow_self=True)
                    if not active_window or active_window.get("hwnd") != target_window.get("hwnd"):
                        switched, resolved_target, switch_error = self._activate_window(target_window)
                        if resolved_target:
                            outcome["target_window"] = resolved_target
                            self.fill_target_window = resolved_target
                        if not switched:
                            outcome["status"] = "error"
                            outcome["target_switch_error"] = switch_error
                            detail = f"未能切回目标窗口 {self._describe_window(target_window)}，已停止自动填充以避免误输入"
                            if switch_error:
                                detail = f"{detail}：{switch_error}"
                            outcome["message"] = detail
                            return
                    time.sleep(0.18)
                elif not restore_gui_focus:
                    outcome["status"] = "error"
                    outcome["message"] = "未记录目标窗口，且当前已切换到其他应用，已停止自动填充以避免误输入"
                    return
                else:
                    time.sleep(0.25)
                fill_started = time.perf_counter()
                self.filler.fill_board(
                    solution,
                    fill_base,
                    grid_coords,
                    step_delay=fill_pause,
                    click_settle_delay=click_settle_delay,
                )
            except FillCancelledError as exc:
                outcome["status"] = "cancelled"
                outcome["message"] = str(exc)
            except Exception as exc:
                outcome["status"] = "error"
                outcome["message"] = str(exc)
                outcome["traceback"] = traceback.format_exc()
            finally:
                finished_at = time.perf_counter()
                if fill_started is not None:
                    outcome["elapsed_ms"] = (finished_at - fill_started) * 1000
                if recognition_started_at is not None:
                    outcome["total_elapsed_ms"] = max(0.0, (finished_at - recognition_started_at) * 1000)
                if restore_window and (
                    outcome["target_window"] is None
                    or restore_window.get("hwnd") != outcome["target_window"].get("hwnd")
                ):
                    restored, resolved_restore, restore_error = self._activate_window(restore_window, allow_self=True)
                    if restored:
                        outcome["window_restored"] = True
                        if resolved_restore:
                            outcome["restored_window"] = resolved_restore
                    else:
                        outcome["window_restore_error"] = restore_error
                if mouse_start is not None:
                    try:
                        pyautogui.moveTo(mouse_start[0], mouse_start[1], duration=0)
                        outcome["mouse_restored"] = True
                    except Exception as exc:
                        outcome["mouse_restore_error"] = str(exc)

        def log_timing(label, total_suffix):
            if outcome["recognition_elapsed_ms"] is not None:
                self._log("INFO", f"本次识别耗时: {outcome['recognition_elapsed_ms'] / 1000:.2f} 秒")
            fill_elapsed_ms = outcome["elapsed_ms"]
            self._log("INFO", f"本次填充耗时: {fill_elapsed_ms / 1000:.2f} 秒")
            if outcome["total_elapsed_ms"] is not None:
                self._log(
                    "INFO",
                    f"{label}: {time.strftime('%H:%M:%S')}，总耗时: {outcome['total_elapsed_ms'] / 1000:.2f} 秒（{total_suffix}）",
                )
            else:
                self._log(
                    "INFO",
                    f"{label}: {time.strftime('%H:%M:%S')}，耗时: {fill_elapsed_ms / 1000:.2f} 秒（仅填充阶段）",
                )

        def on_done():
            if outcome["window_restored"] and outcome["restored_window"]:
                self._log("INFO", f"已恢复此前窗口: {self._describe_window(outcome['restored_window'])}")
            elif outcome["window_restore_error"]:
                self._log("WARNING", f"恢复此前窗口失败: {outcome['window_restore_error']}")
            if outcome["mouse_restored"]:
                self._log("INFO", f"鼠标已回到填充前位置: {mouse_start}")
            elif outcome["mouse_restore_error"]:
                self._log("WARNING", f"鼠标回归失败: {outcome['mouse_restore_error']}")
            if outcome["status"] == "ok":
                self._log("INFO", "自动填充完成")
                log_timing("本次填充完成时间", "从开始识别到填充完成")
                self._log("INFO", "等待下一次识别开始")
                if minimize_after_fill:
                    self._log("INFO", "填充完成后已最小化主窗口")
                    self._set_status("填充完成，已最小化")
                    self.root.after(80, self._minimize_window)
                else:
                    if button_mode_fill and self.minimize_after_fill_enabled.get():
                        self._log("INFO", "按钮模式下跳过填充完成后的最小化")
                    self._set_status("填充完成")
            elif outcome["status"] == "cancelled":
                self._log("WARNING", f"自动填充已取消: {outcome['message']}")
                log_timing("本次填充结束时间", "从开始识别到填充结束")
                self._set_status("自动填充已取消")
            else:
                trace_detail = f"\n{outcome['traceback']}" if outcome["traceback"] else ""
                self._log("ERROR", f"自动填充失败: {outcome['message']}{trace_detail}")
                log_timing("本次填充失败时间", "从开始识别到填充失败")
                self._set_status("填充失败")
                self._show_error("错误", f"填充失败: {outcome['message']}")

        self._run_hidden_fill_task(task, on_done, restore_focus=restore_gui_focus)
        return True

    def _solve_current_board(self, auto_fill_after=False):
        self._cancel_solution_animation()
        board = self._get_board_from_ui()
        self.original_board = [row[:] for row in board]
        self._log("INFO", "开始求解当前盘面")
        self._log("INFO", "待求解盘面:\n" + self._format_board(board))
        self._set_log_stage("校验盘面", "检查重复与空格", 0.08)
        self._set_status("正在求解当前盘面")
        self.root.update_idletasks()

        if not self._board_has_values(board):
            self._set_log_stage("盘面为空", "请先录入题目", 0.0, reset_after_ms=1400)
            self._show_warning("无法求解", "当前盘面为空。请先截图识别、导入图片，或手动输入题目数字。")
            self._set_status("盘面为空，无法求解")
            return False

        conflicts = self._find_conflicts(board)
        if conflicts:
            self._set_log_stage("盘面冲突", "存在重复数字", 0.0, reset_after_ms=1800)
            self._mark_conflicts(conflicts)
            self._log("WARNING", "盘面存在冲突，停止求解: " + self._format_conflicts(conflicts, board))
            detail = self._describe_conflicts(board)
            self._show_warning(
                "盘面冲突",
                "当前盘面有重复数字，红色格子需要先修正。\n\n" + (detail or self._format_conflicts(conflicts, board)),
            )
            self._set_status("盘面冲突，无法求解")
            return False

        scan_summary = self._solver_scan_summary(board)
        scan_detail = (
            f"唯余格 {scan_summary['naked_singles']} · 隐藏唯一数 {scan_summary['hidden_singles']} · 空格 {scan_summary['empty_count']}"
        )
        self._set_log_stage("预扫描候选", scan_detail, 0.24)
        self._log("INFO", f"求解阶段: 预扫描候选 · {scan_detail}")
        self.root.update_idletasks()

        self._set_log_stage("约束搜索", f"准备搜索 {scan_summary['empty_count']} 个空格", 0.56)
        started = time.perf_counter()
        solver = SudokuSolver(board)
        result = solver.solve_with_uniqueness_check(max_solutions=2)
        elapsed_ms = (time.perf_counter() - started) * 1000
        self._set_log_stage("整理结果", f"搜索耗时 {elapsed_ms / 1000:.2f} 秒", 0.82)
        self._record_perf("solve", elapsed_ms)
        difficulty = self._estimate_difficulty(board)
        self.performance["last_difficulty"] = difficulty
        self._update_metrics()
        if not result["solved"]:
            self.solution = None
            self._log("WARNING", "求解失败: 当前盘面无解")
            self._set_log_stage("无可行解", "当前盘面无法完成", 0.0, reset_after_ms=1800)
            self._show_error(
                "无解",
                "当前盘面没有可行解。\n\n请检查是否有 OCR 误识别、手动输入错误，或题目本身不合法。",
            )
            self._set_status("无解")
            return False

        if not result["is_unique"]:
            count_text = f"至少 {result['solution_count']} 个解" if result["truncated"] else f"{result['solution_count']} 个解"
            self._log("WARNING", f"检测到多个解，当前按第一个解继续: {count_text}")

        self.solution = result["solution"]
        self._set_log_stage("应用结果", f"难度 {difficulty}", 0.92)
        self._apply_solution_to_ui(self.solution, board, animate=True)
        source = "识别" if self.recognized_board else "手动"
        self._add_history_entry(source, board, self.solution, difficulty)
        self._log("INFO", f"求解成功，耗时 {elapsed_ms:.0f}ms，难度 {difficulty}:\n" + self._format_board(self.solution))
        self._set_log_stage("求解完成", f"耗时 {elapsed_ms / 1000:.2f} 秒 · 难度 {difficulty}", 1.0, reset_after_ms=1800)
        if auto_fill_after and self.auto_fill_enabled.get() and self.grid_coords:
            self._set_status("求解成功，准备自动填充")
            self._start_fill(auto_started=True)
        elif auto_fill_after and self.auto_fill_enabled.get():
            self._set_status("求解成功，导入图片需先校准坐标才能自动填充")
        else:
            self._set_status(f"求解成功 · 难度 {difficulty}")
        return True

    def on_ocr(self):
        if self._ocr_trigger_active or self._recognizing:
            self._cancel_active_recognition("检测到新的 F2，已中断当前识别并重新截图", silent=True)
            self._log("WARNING", "检测到新的 F2，已中断当前识别并重新截图")
        recognition_generation = self._next_recognition_generation()
        self._ocr_trigger_active = True
        fill_target_window = self._capture_foreground_window_info()
        self._log("INFO", "开始自动截图识别流程")
        self._set_status("正在自动截图识别")
        try:
            self.root.withdraw()
            self.root.update_idletasks()
            time.sleep(0.2)
            screenshot = pyautogui.screenshot()
            if not self._is_recognition_generation_current(recognition_generation):
                return
        except Exception as exc:
            if not self._is_recognition_generation_current(recognition_generation):
                return
            self._log("ERROR", f"自动截图失败: {exc}\n{traceback.format_exc()}")
            self._set_status("自动截图失败")
            self._show_error("自动截图失败", f"{exc}\n\n请确认系统允许当前程序截屏。")
            return
        finally:
            self._restore_window()
            if self._is_recognition_generation_current(recognition_generation):
                self._ocr_trigger_active = False

        if not self._is_recognition_generation_current(recognition_generation):
            return
        self.grid_coords = None
        self._start_image_recognition(
            screenshot,
            "自动全屏截图",
            detect_grid_bounds=True,
            fallback_to_manual=False,
            fill_target_window=fill_target_window,
            recognition_generation=recognition_generation,
        )

    def on_cancel_recognition(self):
        if self._cancel_active_recognition("已取消当前识别"):
            return True
        return False

    def _ask_manual_screenshot_after_auto_fail(self):
        use_manual = messagebox.askyesno(
            "自动识别失败",
            "没有在当前屏幕中自动找到完整数独九宫格。\n\n是否改为手动框选数独区域？",
        )
        if use_manual:
            self.on_manual_ocr()
        else:
            self._set_status("自动识别失败")

    def on_manual_ocr(self):
        self._log("INFO", "开始手动框选截图识别流程")
        self._set_status("请选择数独区域")
        area = None
        screenshot = None
        fill_target_window = None
        try:
            self.root.withdraw()
            self.root.update_idletasks()
            time.sleep(0.2)
            selector = ScreenshotSelector(self.root)
            area = selector.get_selection()
            if area:
                time.sleep(0.05)
                try:
                    screenshot = pyautogui.screenshot(region=area)
                    fill_target_window = self._capture_window_for_grid(area)
                except Exception as exc:
                    self._log("ERROR", f"手动截图失败: {exc}\n{traceback.format_exc()}")
                    screenshot = None
        finally:
            self._restore_window()

        if not area:
            self._log("INFO", "截图识别已取消")
            self._set_status("截图已取消")
            return
        if screenshot is None:
            self._set_status("截图失败")
            self._show_error("截图失败", "未能截取所选区域，请确认目标窗口没有最小化，并允许当前程序截屏。")
            return

        self.grid_coords = area
        self._log("INFO", f"截图区域: {area}")
        self._start_image_recognition(
            screenshot,
            f"手动截图区域: {area}",
            detect_grid_bounds=True,
            grid_offset=(area[0], area[1]),
            fill_target_window=fill_target_window,
        )

    def on_start_teaching(self):
        self._cancel_solution_animation()
        self._clear_hint_feedback(refresh=False)
        self._hide_candidate_popup()

        if self.teaching_active:
            self._show_teaching_panel()
            self._refresh_teaching_buttons()
            self._set_status("已在教学模式中，可继续上一步/下一步；如需重来请先退出教学。")
            return

        board, sources = self._board_for_teaching_start()

        if not self._board_has_values(board):
            self._show_warning("无法进入教学", "当前盘面为空。请先导入、识别、生成或手动输入题目。")
            self._set_status("盘面为空，无法进入教学模式")
            return

        conflicts = self._find_conflicts(board)
        if conflicts:
            self._mark_conflicts(conflicts)
            detail = self._describe_conflicts(board)
            self._show_warning("盘面冲突", "当前盘面有重复数字，请先修正。\n\n" + (detail or self._format_conflicts(conflicts, board)))
            self._set_status("盘面冲突，无法进入教学模式")
            return

        started = time.perf_counter()
        plan = build_teaching_plan(board)
        elapsed_ms = (time.perf_counter() - started) * 1000
        steps = plan["steps"]
        self._track_teaching_event(
            "enter_teaching_mode",
            total_steps=len(steps),
            solved=bool(plan["solved"]),
            elapsed_ms=round(elapsed_ms, 1),
        )

        if not steps:
            self._exit_teaching_mode(silent=True)
            self.teaching_explanation_var.set(plan["message"])
            self.teaching_message_var.set("没有可展示的教学步骤。")
            self._set_status(plan["message"])
            return

        self._cancel_teaching_autoplay()
        self.teaching_active = True
        self.teaching_steps = steps
        self.teaching_current_step = -1
        self.teaching_base_board = [row[:] for row in board]
        self.teaching_base_sources = [row[:] for row in sources]
        self._show_teaching_panel()
        self._show_teaching_step(0)
        self._log("INFO", f"教学模式生成 {len(steps)} 步，耗时 {elapsed_ms:.0f}ms")
        if plan["solved"]:
            self._set_status(f"教学模式已生成 {len(steps)} 步")
        else:
            self._set_status(plan["message"])
            self.teaching_message_var.set(plan["message"])

    def on_teaching_prev(self):
        if not self.teaching_active:
            return
        if self.teaching_current_step < 0:
            return
        self._cancel_teaching_autoplay()
        self._show_teaching_step(self.teaching_current_step - 1)
        self._track_teaching_event("prev_step_click", step=self.teaching_current_step + 1)

    def on_teaching_next(self):
        if not self.teaching_active:
            self.on_start_teaching()
            return
        if self.teaching_current_step >= len(self.teaching_steps) - 1:
            self._set_status("已到最后一步")
            return
        self._show_teaching_step(self.teaching_current_step + 1)
        self._track_teaching_event("next_step_click", step=self.teaching_current_step + 1)

    def on_teaching_autoplay(self):
        if not self.teaching_active:
            self.on_start_teaching()
            if not self.teaching_active:
                return
        if self.teaching_current_step >= len(self.teaching_steps) - 1:
            self._set_status("已到最后一步，无法自动播放")
            return
        if self.teaching_auto_play:
            self._cancel_teaching_autoplay()
            self._track_teaching_event("auto_play_stop", step=self.teaching_current_step + 1)
            self._set_status("教学自动播放已暂停")
        else:
            self.teaching_auto_play = True
            self._track_teaching_event(
                "auto_play_start",
                step=self.teaching_current_step + 1,
                speed=self.teaching_speed_var.get(),
            )
            self._schedule_teaching_autoplay()
            self._set_status(f"教学自动播放中 · {self.teaching_speed_var.get()}")
        self._refresh_teaching_buttons()

    def on_teaching_exit(self):
        self._exit_teaching_mode(silent=False)

    def on_solve(self):
        self._exit_teaching_mode(silent=True)
        self._solve_current_board(auto_fill_after=False)

    def on_calibrate(self):
        self._log("INFO", "开始校准坐标")
        self._log("INFO", "请在 3 秒内将鼠标移动到数独左上角，再在 3 秒内移动到右下角")
        self._show_info(
            "校准坐标",
            "点击确定后开始校准。\n\n1. 先把鼠标停在屏幕上数独九宫格左上角。\n2. 等 3 秒。\n3. 再把鼠标停在九宫格右下角。\n4. 再等 3 秒完成。",
        )

        def task():
            try:
                coords = self.filler.calibrate()
                self.grid_coords = coords
                self._set_fill_target_window(None, coords, "校准坐标")
                self._log("INFO", f"校准成功: {coords}")
                self._set_status(f"校准成功: {coords}")
            except Exception as exc:
                self._log("ERROR", f"校准失败: {exc}\n{traceback.format_exc()}")
                self._set_status("校准失败")
                self._show_error("错误", f"校准失败: {exc}")

        self._run_background(task)

    def on_fill(self):
        self._log("INFO", "手动触发自动填充")
        self._start_fill(auto_started=False)

    def on_hint_step(self):
        self._exit_teaching_mode(silent=True)
        board = self._get_board_from_ui()
        conflicts = self._find_conflicts(board)
        if conflicts:
            self._mark_conflicts(conflicts)
            detail = self._describe_conflicts(board)
            self._show_warning("盘面冲突", "当前盘面有重复数字，请先修正。\n\n" + (detail or self._format_conflicts(conflicts, board)))
            return
        hint = self._find_hint_step(board)
        if hint is None:
            self._show_info("提示一步", "当前盘面没有可提示的空格。")
            return
        row = hint["row"]
        col = hint["col"]
        value = hint["value"]
        reason = hint["reason"]
        self._invalidate_cached_solution()
        self.updating_ui = True
        self.cells[row][col].delete(0, tk.END)
        self.cells[row][col].insert(0, str(value))
        self.cell_sources[row][col] = "solution"
        self.updating_ui = False
        self.low_confidence_cells.discard((row, col))
        self.selected_cell = (row, col)
        self.selected_digit = value
        self.selected_candidate_cell = None
        self._activate_hint_feedback((row, col), hint.get("context_cells"), reason)
        self._log("INFO", reason)
        self._set_status(reason)

    def on_clear_solution(self):
        self._cancel_solution_animation()
        self._exit_teaching_mode(silent=True)
        self._clear_hint_feedback(refresh=False)
        self._hide_candidate_popup()
        self.selected_cell = None
        self.selected_digit = None
        self.selected_candidate_cell = None
        cleared = False
        self.updating_ui = True
        for row in range(9):
            for col in range(9):
                if self.cell_sources[row][col] == "solution":
                    self.cells[row][col].delete(0, tk.END)
                    self.cell_sources[row][col] = "empty"
                    cleared = True
        self.updating_ui = False
        self.solution = None
        self._refresh_all_cell_styles()
        self._update_metrics()
        if cleared:
            self._log("INFO", "已清除求解填入的数字，保留手动输入内容")
            self._set_status("已清除求解结果")
        else:
            self._log("INFO", "当前没有可清除的求解结果")
            self._set_status("没有可清除的求解结果")

    def on_clear(self):
        self._cancel_solution_animation()
        self._exit_teaching_mode(silent=True)
        self._clear_hint_feedback(refresh=False)
        self._hide_candidate_popup()
        self.selected_cell = None
        self.selected_digit = None
        self.selected_candidate_cell = None
        self.low_confidence_cells = set[tuple[int, int]]()
        self.ocr_confidence_map = None
        self.updating_ui = True
        for row in range(9):
            for col in range(9):
                self.cells[row][col].delete(0, tk.END)
                self.cell_sources[row][col] = "empty"
        self.updating_ui = False
        self._refresh_all_cell_styles()
        self.original_board = [[0 for _ in range(9)] for _ in range(9)]
        self.recognized_board = None
        self.solution = None
        self.grid_coords = None
        self._clear_fill_target_window()
        self.last_fill_payload = None
        self._recognition_started_at = None
        self._log("INFO", "已清空界面和缓存状态")
        self._set_status("已重置")
        self._update_metrics()

    def on_toggle_fast_auto_fill(self):
        enabled = bool(self.auto_fill_enabled.get())
        self.turbo_fill_enabled.set(enabled)
        state_text = "开启" if enabled else "关闭"
        self._log("INFO", f"极速自动填充已{state_text}")
        self._set_status(f"极速自动填充已{state_text}")
        self._schedule_ui_state_save()

    def on_toggle_clipboard_monitor(self):
        enabled = bool(self.clipboard_monitor_enabled.get())
        if enabled:
            self._last_clipboard_signature = None
            self._schedule_clipboard_poll(400)
        else:
            if self._clipboard_poll_job is not None:
                try:
                    self.root.after_cancel(self._clipboard_poll_job)
                except tk.TclError:
                    pass
                self._clipboard_poll_job = None
        state_text = "开启" if enabled else "关闭"
        self._log("INFO", f"剪贴板识别已{state_text}")
        self._set_status(f"剪贴板识别已{state_text}")
        self._schedule_ui_state_save()

    def on_toggle_minimize_after_fill(self):
        enabled = bool(self.minimize_after_fill_enabled.get())
        state_text = "开启" if enabled else "关闭"
        self._log("INFO", f"填充完成最小化已{state_text}")
        self._set_status(f"填充完成最小化已{state_text}")
        self._schedule_ui_state_save()

    def on_toggle_log_panel(self):
        if not hasattr(self, "log_body"):
            return
        self.log_collapsed = not self.log_collapsed
        if self.log_collapsed:
            self.log_body.pack_forget()
            self.log_toggle_button.config(text="展开")
            self._set_status("日志面板已收起")
        else:
            self.log_body.pack(fill="both", expand=True, padx=12, pady=(0, 10))
            self.log_toggle_button.config(text="收起")
            self._set_status("日志面板已展开")

    def on_toggle_pin(self):
        self.pinned = not self.pinned
        self.root.attributes("-topmost", self.pinned)
        self._refresh_pin_visual()
        self._log("INFO", f"窗口置顶已{'开启' if self.pinned else '关闭'}")
        self._set_status(f"窗口置顶已{'开启' if self.pinned else '关闭'}")

    def on_close(self):
        if self._closing:
            return
        self._closing = True
        self._cancel_teaching_autoplay()
        self._teardown_global_hotkeys()
        self._cancel_solution_animation()
        self._clear_hint_feedback(refresh=False)
        self._hide_candidate_popup()
        if self._board_resize_job is not None:
            try:
                self.root.after_cancel(self._board_resize_job)
            except tk.TclError:
                pass
            self._board_resize_job = None
        if self._log_stage_reset_job is not None:
            try:
                self.root.after_cancel(self._log_stage_reset_job)
            except tk.TclError:
                pass
            self._log_stage_reset_job = None
        if self._clipboard_poll_job is not None:
            self.root.after_cancel(self._clipboard_poll_job)
            self._clipboard_poll_job = None
        if self._recognition_anim_job is not None:
            self.root.after_cancel(self._recognition_anim_job)
            self._recognition_anim_job = None
        if self._pane_save_job is not None:
            self.root.after_cancel(self._pane_save_job)
            self._pane_save_job = None
        if self._log_flush_job is not None:
            self.root.after_cancel(self._log_flush_job)
            self._log_flush_job = None
        if self._global_hotkey_retry_job is not None:
            try:
                self.root.after_cancel(self._global_hotkey_retry_job)
            except tk.TclError:
                pass
            self._global_hotkey_retry_job = None
        if self._enter_button_mode_job is not None:
            try:
                self.root.after_cancel(self._enter_button_mode_job)
            except tk.TclError:
                pass
            self._enter_button_mode_job = None
        self._save_ui_state()
        self._release_tk_images()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def main():
    root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
    app = None
    try:
        app = SudokuApp(root)
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if app is not None:
                app.on_close()
            else:
                root.destroy()
        except tk.TclError:
            pass


if __name__ == "__main__":
    main()
