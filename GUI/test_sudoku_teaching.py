import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

import sudoku_gui
from sudoku_gui import TEACHING_STRATEGIES, SudokuApp, build_teaching_plan


def test_teaching_strategies_are_standardized():
    assert TEACHING_STRATEGIES == [
        "single_candidate",
        "single_position",
        "row_elimination",
        "column_elimination",
        "block_elimination",
        "naked_pair",
        "hidden_pair",
        "x_wing",
    ]


def test_build_teaching_plan_creates_single_candidate_step():
    board = [
        [1, 2, 3, 4, 5, 6, 7, 8, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0],
    ]

    plan = build_teaching_plan(board)

    assert plan["steps"][0]["step"] == 1
    assert plan["steps"][0]["total_steps"] == len(plan["steps"])
    assert plan["steps"][0]["position"] == {"row": 1, "col": 9}
    assert plan["steps"][0]["value"] == 9
    assert plan["steps"][0]["strategy"] == "single_candidate"
    assert plan["steps"][0]["candidates_before"] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert plan["steps"][0]["candidates_after"] == [9]
    assert plan["steps"][0]["highlight"]["block"] == 3
    assert "\u7b2c1\u884c\u7b2c9\u5217\u53ea\u80fd\u586b 9" in plan["steps"][0]["explanation"]


def test_build_teaching_plan_finds_single_position_when_no_single_candidates():
    board = [
        [0, 2, 0, 0, 5, 0, 0, 8, 0],
        [0, 5, 6, 0, 0, 0, 0, 0, 0],
        [0, 0, 9, 1, 0, 0, 0, 0, 0],
        [2, 0, 0, 0, 0, 7, 0, 9, 0],
        [0, 0, 0, 8, 0, 0, 0, 0, 0],
        [0, 9, 1, 0, 0, 4, 0, 0, 0],
        [0, 4, 5, 0, 0, 0, 0, 0, 0],
        [0, 7, 8, 0, 0, 0, 0, 4, 0],
        [9, 0, 0, 0, 0, 0, 0, 0, 0],
    ]

    plan = build_teaching_plan(board)

    assert plan["steps"][0]["position"] == {"row": 9, "col": 2}
    assert plan["steps"][0]["value"] == 1
    assert plan["steps"][0]["strategy"] == "single_position"
    assert plan["steps"][0]["candidates_after"] == [1]
    assert "\u6570\u5b57 1" in plan["steps"][0]["explanation"]


def test_single_position_explanation_includes_elimination_reasons():
    board = [
        [0, 1, 3, 0, 0, 6, 4, 8, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0],
        [6, 0, 0, 9, 8, 0, 2, 0, 0],
        [9, 8, 6, 0, 0, 1, 0, 0, 0],
        [1, 3, 0, 0, 0, 0, 9, 0, 0],
        [0, 0, 0, 8, 0, 0, 1, 4, 0],
        [0, 0, 5, 0, 0, 0, 0, 0, 2],
        [0, 0, 0, 0, 0, 0, 3, 0, 0],
        [0, 0, 0, 2, 1, 7, 0, 0, 6],
    ]

    plan = build_teaching_plan(board)
    explanation = plan["steps"][0]["explanation"]

    assert plan["steps"][0]["strategy"] == "single_position"
    assert plan["steps"][0]["position"] == {"row": 1, "col": 9}
    assert "\u7b2c1\u884c\u7f3a\u5c11" in explanation
    assert "\u7b2c1\u5217\u5df2\u67099" in explanation
    assert "\u7b2c4\u5217\u5df2\u67099" in explanation
    assert "\u7b2c2\u5bab\u5df2\u67099" in explanation
    assert "\u53ea\u5269\u7b2c9\u5217" in explanation


def test_teaching_events_are_not_queued_to_user_log():
    app = SudokuApp.__new__(SudokuApp)
    internal_messages = []
    ui_messages = []

    class Logger:
        def info(self, message):
            internal_messages.append(message)

    app.logger = Logger()
    app._run_on_ui_thread = lambda callback: callback()
    app._queue_log_message = lambda message: ui_messages.append(message)

    SudokuApp._track_teaching_event(app, "next_step_click", step=12)

    assert internal_messages
    assert "TEACHING_EVENT" in internal_messages[0]
    assert ui_messages == []


def test_teaching_panel_is_hidden_until_teaching_starts():
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    app = SudokuApp(root)
    app._save_ui_state = lambda: None
    try:
        board = [
            [1, 2, 3, 4, 5, 6, 7, 8, 0],
            [4, 5, 6, 7, 8, 9, 1, 2, 3],
            [7, 8, 9, 1, 2, 3, 4, 5, 6],
            [2, 3, 4, 5, 6, 7, 8, 9, 1],
            [5, 6, 7, 8, 9, 1, 2, 3, 4],
            [8, 9, 1, 2, 3, 4, 5, 6, 7],
            [3, 4, 5, 6, 7, 8, 9, 1, 2],
            [6, 7, 8, 9, 1, 2, 3, 4, 5],
            [9, 1, 2, 3, 4, 5, 6, 7, 8],
        ]

        assert app.sidebar_pane.cget("orient") == "vertical"
        panes = {str(pane) for pane in app.sidebar_pane.panes()}
        assert str(app.sidebar_actions_pane) in panes
        assert str(app.sidebar_log_pane) in panes
        assert str(app.teaching_panel) not in {str(pane) for pane in app.main_pane.panes()}
        app._set_board(board, "manual")
        app.on_start_teaching()
        root.update_idletasks()
        assert str(app.teaching_panel) in {str(pane) for pane in app.main_pane.panes()}
    finally:
        app.on_close()


def test_teaching_panel_wraps_text_inside_visible_width():
    app = SudokuApp.__new__(SudokuApp)

    assert SudokuApp.MIN_TEACHING_PANEL_WIDTH >= 300
    assert app._teaching_wraplength_for_width(220) <= 180
    assert app._teaching_wraplength_for_width(360) <= 316


def test_teaching_start_keeps_visible_solution_source_values():
    class Cell:
        def __init__(self, value=""):
            self.value = value

        def get(self):
            return self.value

        def delete(self, _start, _end=None):
            self.value = ""

        def insert(self, _index, value):
            self.value = str(value)

    app = SudokuApp.__new__(SudokuApp)
    app.cells = [[Cell() for _ in range(9)] for _ in range(9)]
    app.cell_sources = [["empty" for _ in range(9)] for _ in range(9)]
    app.updating_ui = False
    app.cells[0][0].insert(0, "9")
    app.cell_sources[0][0] = "solution"
    app.cells[0][1].insert(0, "1")
    app.cell_sources[0][1] = "manual"

    board, sources = app._board_for_teaching_start()

    assert board[0][0] == 9
    assert sources[0][0] == "solution"
    assert board[0][1] == 1
    assert sources[0][1] == "manual"


def test_teaching_exit_button_is_visible_in_header_when_active():
    class Button:
        def __init__(self):
            self.options = {}

        def config(self, **kwargs):
            self.options.update(kwargs)

    app = SudokuApp.__new__(SudokuApp)
    app.teaching_active = True
    app.teaching_steps = [{"step": 1}, {"step": 2}]
    app.teaching_current_step = 0
    app.teaching_auto_play = False
    app.teaching_start_button = Button()
    app.teaching_prev_button = Button()
    app.teaching_next_button = Button()
    app.teaching_autoplay_button = Button()
    app.teaching_exit_button = Button()
    app.teaching_header_exit_button = Button()

    SudokuApp._refresh_teaching_buttons(app)

    assert app.teaching_header_exit_button.options["state"] == "normal"
    assert app.teaching_start_button.options["state"] == "disabled"
    assert app.teaching_start_button.options["text"] == "\u6559\u5b66\u4e2d"


def test_advanced_teaching_message_does_not_show_modal_warning(monkeypatch):
    app = SudokuApp.__new__(SudokuApp)
    warnings = []
    statuses = []

    app.teaching_active = False
    app.teaching_steps = []
    app.teaching_current_step = -1
    app._cancel_solution_animation = lambda: None
    app._clear_hint_feedback = lambda refresh=False: None
    app._hide_candidate_popup = lambda: None
    app._board_for_teaching_start = lambda: ([[1] + [0] * 8] + [[0] * 9 for _ in range(8)], [["manual"] + ["empty"] * 8] + [["empty"] * 9 for _ in range(8)])
    app._board_has_values = lambda board: True
    app._find_conflicts = lambda board: []
    app._track_teaching_event = lambda *args, **kwargs: None
    app._cancel_teaching_autoplay = lambda: None
    app._show_teaching_panel = lambda: None
    app._show_teaching_step = lambda index: None
    app._log = lambda level, message: None
    app._set_status = statuses.append
    app._show_warning = lambda title, message: warnings.append((title, message))
    app.teaching_message_var = type("Var", (), {"set": lambda self, value: None})()

    monkeypatch.setattr(
        sudoku_gui,
        "build_teaching_plan",
        lambda board: {
            "steps": [{"step": 1, "total_steps": 1}],
            "solved": False,
            "message": "\u5f53\u524d\u9898\u76ee\u9700\u8981\u9ad8\u7ea7\u63a8\u7406\u6216\u8bd5\u63a2\u6cd5\uff0c\u5df2\u4fdd\u7559\u53ef\u89e3\u91ca\u7684\u6559\u5b66\u6b65\u9aa4\u3002",
        },
    )

    SudokuApp.on_start_teaching(app)

    assert warnings == []
    assert statuses == ["\u5f53\u524d\u9898\u76ee\u9700\u8981\u9ad8\u7ea7\u63a8\u7406\u6216\u8bd5\u63a2\u6cd5\uff0c\u5df2\u4fdd\u7559\u53ef\u89e3\u91ca\u7684\u6559\u5b66\u6b65\u9aa4\u3002"]


def test_start_button_does_not_restart_active_teaching(monkeypatch):
    app = SudokuApp.__new__(SudokuApp)
    statuses = []

    app.teaching_active = True
    app.teaching_current_step = 6
    app.teaching_steps = [{"step": 1}] * 10
    app.teaching_base_board = [[0] * 9 for _ in range(9)]
    app.teaching_base_sources = [["empty"] * 9 for _ in range(9)]
    app._cancel_solution_animation = lambda: None
    app._clear_hint_feedback = lambda refresh=False: None
    app._hide_candidate_popup = lambda: None
    app._show_teaching_panel = lambda: None
    app._refresh_teaching_buttons = lambda: None
    app._set_status = statuses.append
    monkeypatch.setattr(sudoku_gui, "build_teaching_plan", lambda board: (_ for _ in ()).throw(AssertionError("should not rebuild active teaching")))

    SudokuApp.on_start_teaching(app)

    assert app.teaching_current_step == 6
    assert statuses == ["\u5df2\u5728\u6559\u5b66\u6a21\u5f0f\u4e2d\uff0c\u53ef\u7ee7\u7eed\u4e0a\u4e00\u6b65/\u4e0b\u4e00\u6b65\uff1b\u5982\u9700\u91cd\u6765\u8bf7\u5148\u9000\u51fa\u6559\u5b66\u3002"]
