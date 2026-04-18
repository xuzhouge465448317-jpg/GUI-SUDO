import tkinter as tk

import pyautogui


class ScreenshotSelector:
    def __init__(self, parent):
        self.parent = parent
        self.selection = None
        self.start_x = None
        self.start_y = None
        self.rect = None
        self.dragging = False

        self.window = tk.Toplevel(parent)
        self.window.attributes("-alpha", 0.3)
        self.window.attributes("-fullscreen", True)
        self.window.attributes("-topmost", True)
        self.window.overrideredirect(True)
        self.window.config(cursor="cross")

        self.canvas = tk.Canvas(self.window, cursor="cross", bg="grey", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_move_press)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        self.window.bind("<Escape>", self.on_cancel)
        self.window.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.window.grab_set()
        self.window.update_idletasks()
        self.window.focus_force()

    def on_button_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.dragging = True
        if self.rect is not None:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(
            self.start_x,
            self.start_y,
            self.start_x,
            self.start_y,
            outline="red",
            width=2,
        )

    def on_move_press(self, event):
        if not self.dragging or self.rect is None or self.start_x is None or self.start_y is None:
            return
        self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)

    def on_button_release(self, event):
        if not self.dragging or self.start_x is None or self.start_y is None:
            self.selection = None
            self.close()
            return

        end_x, end_y = event.x, event.y
        x1 = min(self.start_x, end_x)
        y1 = min(self.start_y, end_y)
        x2 = max(self.start_x, end_x)
        y2 = max(self.start_y, end_y)

        width = x2 - x1
        height = y2 - y1
        if width > 5 and height > 5:
            self.selection = (x1, y1, width, height)

        self.close()

    def on_cancel(self, _event=None):
        self.selection = None
        self.close()

    def close(self):
        self.dragging = False
        self.start_x = None
        self.start_y = None
        if self.window.winfo_exists():
            try:
                self.window.grab_release()
            except tk.TclError:
                pass
            self.window.destroy()

    def get_selection(self):
        self.parent.wait_window(self.window)
        return self.selection


def capture_screen_area(parent):
    selector = ScreenshotSelector(parent)
    area = selector.get_selection()
    if area:
        screenshot = pyautogui.screenshot(region=area)
        return screenshot, area
    return None, None
