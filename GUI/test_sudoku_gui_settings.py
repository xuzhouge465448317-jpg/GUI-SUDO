import sys
import tkinter as tk
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

from sudoku_gui import RoundedButton, SudokuApp


class MouseEvent:
    def __init__(self, x_root, y_root):
        self.x_root = x_root
        self.y_root = y_root


def _widget_texts(widget):
    texts = []
    try:
        text = widget.cget("text")
    except tk.TclError:
        text = None
    if text:
        texts.append(text)
    for child in widget.winfo_children():
        texts.extend(_widget_texts(child))
    return texts


def test_rounded_button_initializes_without_shadowing_tk_options():
    root = tk.Tk()
    root.withdraw()
    frame = tk.Frame(root, bg="#ffffff")
    frame.pack()
    try:
        button = RoundedButton(
            frame,
            text="测试",
            command=lambda: None,
            bg="#336699",
            fg="#ffffff",
        )
        assert isinstance(button, tk.Canvas)
    finally:
        root.destroy()


def test_settings_button_mode_and_opacity_behaviors(tmp_path):
    root = tk.Tk()
    root.withdraw()
    app = SudokuApp(root)
    app.ui_state_path = tmp_path / "state.json"
    app._remember_pane_ratio = lambda: None
    try:
        assert "数独助手" not in _widget_texts(root)

        app.on_enter_button_mode()
        root.update_idletasks()

        assert app.button_mode_active is True
        assert app.shell.winfo_manager() == ""
        assert app.button_mode_frame.winfo_manager() == "pack"
        assert app.button_mode_button.cget("text") == "展开"

        root.geometry("96x42+20+30")
        root.update_idletasks()
        start_x = root.winfo_x()
        start_y = root.winfo_y()
        app._on_button_mode_drag_start(MouseEvent(100, 120))
        app._on_button_mode_drag(MouseEvent(145, 165))
        root.update_idletasks()

        assert root.geometry().endswith(f"+{start_x + 45}+{start_y + 45}")
        assert app.button_mode_active is True
        saved_position = dict(app.button_mode_position)

        app._on_button_mode_release()
        root.update_idletasks()
        assert app.button_mode_active is True

        app._on_button_mode_drag_start(MouseEvent(145, 165))
        app._on_button_mode_release()
        root.update_idletasks()

        assert app.button_mode_active is False
        assert app.shell.winfo_manager() == "pack"
        assert app.button_mode_frame.winfo_manager() == ""

        app.on_enter_button_mode()
        root.update_idletasks()

        assert root.geometry().endswith(f"+{saved_position['x']}+{saved_position['y']}")
        app.on_exit_button_mode()
        root.update_idletasks()

        app.on_window_opacity_change("75")
        root.update_idletasks()

        assert app.window_opacity_var.get() == 75
        assert abs(float(root.attributes("-alpha")) - 0.75) < 0.02

        app._save_ui_state()
        state = app._load_ui_state()
        assert state["window_opacity"] == 0.75
        assert state["button_mode_position"] == saved_position
    finally:
        app.on_close()
