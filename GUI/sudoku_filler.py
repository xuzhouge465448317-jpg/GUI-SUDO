import ctypes
import time

import pyautogui


VK_ESCAPE = 0x1B


class FillCancelledError(Exception):
    pass


class SudokuFiller:
    def __init__(self, delay=0.02, click_duration=0):
        self.delay = delay
        self.click_duration = click_duration
        pyautogui.PAUSE = delay
        pyautogui.FAILSAFE = True

    def _check_cancel(self):
        if ctypes.windll.user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000:
            raise FillCancelledError("检测到 Esc，已停止自动填充。")

    def fill_board(self, solution, original_board, grid_coords, step_delay=None, click_settle_delay=None):
        x, y, w, h = grid_coords
        cell_w = w / 9
        cell_h = h / 9
        step_delay = self.delay if step_delay is None else max(0.0, step_delay)
        click_settle_delay = step_delay if click_settle_delay is None else max(0.0, click_settle_delay)

        previous_pause = pyautogui.PAUSE
        pyautogui.PAUSE = 0
        try:
            for row in range(9):
                for col in range(9):
                    self._check_cancel()
                    if original_board[row][col] == 0:
                        target_x = x + (col + 0.5) * cell_w
                        target_y = y + (row + 0.5) * cell_h
                        pyautogui.click(target_x, target_y, duration=self.click_duration)
                        if click_settle_delay:
                            time.sleep(click_settle_delay)
                        self._check_cancel()
                        pyautogui.press(str(solution[row][col]))
                        if step_delay:
                            time.sleep(step_delay)
        finally:
            pyautogui.PAUSE = previous_pause

    def calibrate(self):
        print("Please move mouse to TOP-LEFT of the sudoku grid and wait 3 seconds...")
        time.sleep(3)
        tl = pyautogui.position()
        print(f"Top-Left: {tl}")

        print("Please move mouse to BOTTOM-RIGHT of the sudoku grid and wait 3 seconds...")
        time.sleep(3)
        br = pyautogui.position()
        print(f"Bottom-Right: {br}")

        return (tl.x, tl.y, br.x - tl.x, br.y - tl.y)


if __name__ == "__main__":
    pass
