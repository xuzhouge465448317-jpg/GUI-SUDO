import sys
import types
import unittest
from unittest import mock
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))


def _install_import_stubs():
    if "pyautogui" not in sys.modules:
        sys.modules["pyautogui"] = types.SimpleNamespace(
            PAUSE=0,
            FAILSAFE=True,
            screenshot=lambda *args, **kwargs: None,
            position=lambda: (0, 0),
            moveTo=lambda *args, **kwargs: None,
            click=lambda *args, **kwargs: None,
            press=lambda *args, **kwargs: None,
        )

    if "cv2" not in sys.modules:
        sys.modules["cv2"] = types.SimpleNamespace(createCLAHE=lambda *args, **kwargs: None)

    if "numpy" not in sys.modules:
        sys.modules["numpy"] = types.SimpleNamespace()

    if "pytesseract" not in sys.modules:
        sys.modules["pytesseract"] = types.SimpleNamespace(
            Output=types.SimpleNamespace(),
            pytesseract=types.SimpleNamespace(tesseract_cmd=""),
        )

    if "PIL" not in sys.modules:
        pil_module = types.ModuleType("PIL")
        image_module = types.SimpleNamespace(Image=type("Image", (), {}))
        image_grab_module = types.SimpleNamespace(grabclipboard=lambda: None)
        pil_module.Image = image_module
        pil_module.ImageGrab = image_grab_module
        sys.modules["PIL"] = pil_module
        sys.modules["PIL.Image"] = image_module
        sys.modules["PIL.ImageGrab"] = image_grab_module


_install_import_stubs()

import sudoku_gui
from sudoku_gui import SudokuApp


class Cell:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def delete(self, _start, _end=None):
        self.value = ""

    def insert(self, _index, value):
        self.value = str(value)


class PopupCell:
    def __init__(self, x_root, y_root, width):
        self._x_root = x_root
        self._y_root = y_root
        self._width = width

    def winfo_rootx(self):
        return self._x_root

    def winfo_rooty(self):
        return self._y_root

    def winfo_width(self):
        return self._width


class FakePopup:
    def __init__(self, _root):
        self.geometry_value = None

    def overrideredirect(self, _value):
        pass

    def transient(self, _root):
        pass

    def configure(self, **_kwargs):
        pass

    def update_idletasks(self):
        pass

    def winfo_reqwidth(self):
        return 250

    def winfo_reqheight(self):
        return 48

    def geometry(self, value):
        self.geometry_value = value

    def destroy(self):
        pass


class FakeLabel:
    def __init__(self, *_args, **_kwargs):
        pass

    def pack(self, **_kwargs):
        pass


class FakeThread:
    def __init__(self, alive=False):
        self.alive = alive
        self.start_calls = 0

    def is_alive(self):
        return self.alive

    def start(self):
        self.start_calls += 1
        self.alive = True


def _build_stub_app():
    app = SudokuApp.__new__(SudokuApp)
    app.cells = [[Cell() for _ in range(9)] for _ in range(9)]
    app.cell_sources = [["empty" for _ in range(9)] for _ in range(9)]
    app.low_confidence_cells = set()
    app.recognized_board = None
    app.solution = [[((row * 3 + row // 3 + col) % 9) + 1 for col in range(9)] for row in range(9)]
    app.last_fill_payload = {"grid_coords": (10, 20, 300, 300)}
    app.updating_ui = False
    app.teaching_active = False
    app.selected_cell = None
    app.selected_digit = None
    app.selected_candidate_cell = None
    app._exit_teaching_mode = lambda silent=True: None
    app._normalize_cell_text = lambda row, col: int(app.cells[row][col].get() or "0")
    app._update_metrics = lambda: None
    app._log = lambda level, message: None
    app._set_status = lambda message: None
    return app


class SudokuGuiStateRegressionTests(unittest.TestCase):
    def test_ensure_global_hotkeys_restarts_dead_worker_thread(self):
        app = SudokuApp.__new__(SudokuApp)
        app._global_hotkey_thread = FakeThread(alive=False)
        app._global_hotkey_thread_id = 321

        created_threads = []

        def make_thread(target, daemon):
            thread = FakeThread(alive=False)
            created_threads.append((target, daemon, thread))
            return thread

        with mock.patch.object(sudoku_gui.threading, "Thread", side_effect=make_thread):
            result = SudokuApp._ensure_global_hotkeys(app)

        self.assertTrue(result)
        self.assertIsNone(app._global_hotkey_thread_id)
        self.assertEqual(len(created_threads), 1)
        self.assertIs(app._global_hotkey_thread, created_threads[0][2])
        self.assertEqual(created_threads[0][2].start_calls, 1)

    def test_enter_button_mode_ensures_global_hotkeys(self):
        app = SudokuApp.__new__(SudokuApp)
        app.button_mode_active = False
        app.button_mode_position = None
        app.BUTTON_MODE_GEOMETRY = "96x42"
        app.BG = "#111111"
        app.PRIMARY = "#222222"
        app.PRIMARY_HOVER = "#333333"
        app.pinned = False
        app._normal_window_geometry = None
        app._normal_window_minsize = None
        app._close_settings_window = lambda: None
        app._hide_candidate_popup = lambda: None
        app._build_button_mode_frame = lambda: None
        app._set_status = lambda message: None

        calls = {"ensure": 0}
        app._ensure_global_hotkeys = lambda: calls.__setitem__("ensure", calls["ensure"] + 1)

        app.shell = type("Shell", (), {"pack_forget": lambda self: None})()
        app.button_mode_frame = type("Frame", (), {"pack": lambda self, **kwargs: None})()
        app.root = type(
            "Root",
            (),
            {
                "geometry": lambda self, *args: "900x600+10+10",
                "minsize": lambda self, *args: (860, 500),
                "resizable": lambda self, *args: None,
                "overrideredirect": lambda self, *args: None,
                "attributes": lambda self, *args: None,
            },
        )()

        SudokuApp.on_enter_button_mode(app)

        self.assertEqual(calls["ensure"], 1)
        self.assertTrue(app.button_mode_active)

    def test_root_unmap_ensures_global_hotkeys_when_window_is_minimized(self):
        app = SudokuApp.__new__(SudokuApp)
        calls = {"ensure": 0}
        app._ensure_global_hotkeys = lambda: calls.__setitem__("ensure", calls["ensure"] + 1)
        app.root = type("Root", (), {"state": lambda self: "iconic"})()

        SudokuApp._on_root_unmap(app)

        self.assertEqual(calls["ensure"], 1)

    def test_on_cell_edit_invalidates_cached_solution_and_refreshes_global_highlight(self):
        app = _build_stub_app()
        app.cells[2][3].insert(0, "7")

        calls = {"cell": 0, "all": 0}
        app._refresh_cell_style = lambda row, col: calls.__setitem__("cell", calls["cell"] + 1)
        app._refresh_all_cell_styles = lambda: calls.__setitem__("all", calls["all"] + 1)

        SudokuApp._on_cell_edit(app, 2, 3)

        self.assertIsNone(app.solution)
        self.assertIsNone(app.last_fill_payload)
        self.assertEqual(app.selected_cell, (2, 3))
        self.assertEqual(app.selected_digit, 7)
        self.assertIsNone(app.selected_candidate_cell)
        self.assertEqual(app.cell_sources[2][3], "manual")
        self.assertEqual(calls["all"], 1)
        self.assertEqual(calls["cell"], 0)

    def test_apply_cell_value_invalidates_cached_solution(self):
        app = _build_stub_app()

        calls = {"all": 0}
        app._refresh_all_cell_styles = lambda: calls.__setitem__("all", calls["all"] + 1)

        SudokuApp._apply_cell_value(app, 4, 5, 9)

        self.assertEqual(app.cells[4][5].get(), "9")
        self.assertIsNone(app.solution)
        self.assertIsNone(app.last_fill_payload)
        self.assertEqual(app.selected_cell, (4, 5))
        self.assertEqual(app.selected_digit, 9)
        self.assertIsNone(app.selected_candidate_cell)
        self.assertEqual(app.cell_sources[4][5], "manual")
        self.assertEqual(calls["all"], 1)

    def test_hint_step_invalidates_cached_solution_after_filling_value(self):
        app = _build_stub_app()
        app._find_conflicts = lambda board: []
        app._mark_conflicts = lambda conflicts: None
        app._describe_conflicts = lambda board: ""
        app._format_conflicts = lambda conflicts, board: ""
        app._show_warning = lambda title, message: None
        app._show_info = lambda title, message: None
        app._activate_hint_feedback = lambda focus, context, reason: None
        app._get_board_from_ui = lambda: [[0 for _ in range(9)] for _ in range(9)]
        app._find_hint_step = lambda board: {
            "row": 1,
            "col": 2,
            "value": 4,
            "reason": "提示：这里填 4。",
            "context_cells": {(1, 0), (1, 1)},
        }

        SudokuApp.on_hint_step(app)

        self.assertEqual(app.cells[1][2].get(), "4")
        self.assertIsNone(app.solution)
        self.assertIsNone(app.last_fill_payload)
        self.assertEqual(app.selected_cell, (1, 2))
        self.assertEqual(app.selected_digit, 4)
        self.assertIsNone(app.selected_candidate_cell)
        self.assertEqual(app.cell_sources[1][2], "solution")

    def test_load_history_entry_clears_stale_fill_coordinates(self):
        app = SudokuApp.__new__(SudokuApp)
        app.grid_coords = (11, 22, 333, 444)
        app.fill_target_window = {"hwnd": 123}
        app.performance = {"last_difficulty": None}
        app._cancel_solution_animation = lambda: None
        app._set_board = lambda board, source: None
        app._apply_solution_to_ui = lambda solution, puzzle, animate=False: None
        app._update_metrics = lambda: None
        app._set_status = lambda message: None

        def clear_fill_target_window():
            app.fill_target_window = None

        app._clear_fill_target_window = clear_fill_target_window

        entry = {
            "puzzle": [[0 for _ in range(9)] for _ in range(9)],
            "solution": [[1 for _ in range(9)] for _ in range(9)],
            "difficulty": "中等",
        }

        SudokuApp._load_history_entry(app, entry)

        self.assertIsNone(app.grid_coords)
        self.assertIsNone(app.fill_target_window)

    def test_hint_popup_uses_left_side_when_target_cell_is_in_last_column(self):
        app = SudokuApp.__new__(SudokuApp)
        app.PRIMARY = "#1"
        app.PANEL = "#2"
        app.TEXT = "#3"
        app.hint_popup = None
        app.root = type(
            "Root",
            (),
            {
                "winfo_screenwidth": lambda self: 1280,
                "winfo_screenheight": lambda self: 720,
            },
        )()
        app.cells = [[PopupCell(100, 100, 40) for _ in range(9)] for _ in range(9)]
        app.cells[0][8] = PopupCell(1180, 200, 40)

        with mock.patch.object(sudoku_gui.tk, "Toplevel", FakePopup), mock.patch.object(sudoku_gui.tk, "Label", FakeLabel):
            SudokuApp._show_hint_popup(app, 0, 8, "提示文本")

        self.assertIsNotNone(app.hint_popup)
        self.assertEqual(app.hint_popup.geometry_value, "+920+194")


if __name__ == "__main__":
    unittest.main()
