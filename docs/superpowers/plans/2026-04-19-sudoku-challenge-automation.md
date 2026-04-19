# Sudoku Daily Challenge Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GUI-started automation runner that completes Sudoku.com daily challenges from `2025-02` down through `2022-01` by controlling the browser and reusing the existing OCR, solver, and fill workflow.

**Architecture:** Add `sudoku_challenge_runner.py` for month generation, browser-page orchestration, retries, stop handling, and Selenium Edge control. Keep `sudoku_gui.py` responsible for UI state and existing OCR/solve/fill behavior, with one callback bridge that lets the runner request "solve the current visible browser puzzle".

**Tech Stack:** Python 3, tkinter, pytest, Selenium WebDriver for Edge, existing `SudokuApp`, existing `SudokuFiller`, existing OCR/solver modules.

---

## File Structure

- Create: `GUI/sudoku_challenge_runner.py`
  - Month range generation.
  - Calendar entry normalization.
  - Runner orchestration and retry logic.
  - Selenium page adapter and Edge driver factory.
- Create: `GUI/test_sudoku_challenge_runner.py`
  - Pure unit tests for range generation, completed filtering, retry, and stop behavior.
- Modify: `GUI/sudoku_gui.py`
  - Import runner.
  - Add runner state fields.
  - Add a compact action button.
  - Add start/stop methods.
  - Add a blocking solve callback that waits for the existing OCR/solve/fill flow.
  - Add optional fill completion callback support to `_start_fill`.
- Create: `GUI/test_sudoku_gui_challenge.py`
  - GUI-level tests for button presence and fill callback behavior.

## Task 1: Runner Pure Data Model

**Files:**
- Create: `GUI/test_sudoku_challenge_runner.py`
- Create: `GUI/sudoku_challenge_runner.py`

- [ ] **Step 1: Write the failing tests**

Create `GUI/test_sudoku_challenge_runner.py`:

```python
from sudoku_challenge_runner import CalendarDay, iter_months_desc, unfinished_days


def test_iter_months_desc_includes_start_and_end():
    assert list(iter_months_desc("2025-02", "2025-01")) == [(2025, 2), (2025, 1)]


def test_iter_months_desc_crosses_years():
    months = list(iter_months_desc("2025-02", "2022-01"))

    assert months[0] == (2025, 2)
    assert months[1] == (2025, 1)
    assert months[-1] == (2022, 1)
    assert (2024, 12) in months
    assert (2023, 1) in months
    assert len(months) == 38


def test_unfinished_days_skips_completed_and_disabled_entries():
    days = [
        CalendarDay(day=24, completed=True, enabled=True),
        CalendarDay(day=25, completed=False, enabled=True),
        CalendarDay(day=26, completed=False, enabled=False),
        CalendarDay(day=27, completed=True, enabled=False),
    ]

    assert unfinished_days(days) == [25]
```

- [ ] **Step 2: Verify the tests fail**

Run:

```bash
python -m pytest GUI/test_sudoku_challenge_runner.py -q
```

Expected: FAIL because `sudoku_challenge_runner` does not exist.

- [ ] **Step 3: Implement the minimal data model**

Create `GUI/sudoku_challenge_runner.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CalendarDay:
    day: int
    completed: bool = False
    enabled: bool = True


def parse_month(value: str) -> tuple[int, int]:
    year_text, month_text = value.split("-", 1)
    year = int(year_text)
    month = int(month_text)
    if month < 1 or month > 12:
        raise ValueError(f"month must be in 1..12: {value}")
    return year, month


def iter_months_desc(start_month: str, end_month: str):
    start_year, start = parse_month(start_month)
    end_year, end = parse_month(end_month)
    current_year = start_year
    current_month = start
    while (current_year, current_month) >= (end_year, end):
        yield current_year, current_month
        current_month -= 1
        if current_month == 0:
            current_year -= 1
            current_month = 12


def unfinished_days(days: list[CalendarDay]) -> list[int]:
    return [entry.day for entry in days if entry.enabled and not entry.completed]
```

- [ ] **Step 4: Verify the tests pass**

Run:

```bash
python -m pytest GUI/test_sudoku_challenge_runner.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add GUI/sudoku_challenge_runner.py GUI/test_sudoku_challenge_runner.py
git commit -m "feat: add sudoku challenge range helpers"
```

## Task 2: Runner Retry And Stop Orchestration

**Files:**
- Modify: `GUI/test_sudoku_challenge_runner.py`
- Modify: `GUI/sudoku_challenge_runner.py`

- [ ] **Step 1: Add failing tests for retry and stop behavior**

Append to `GUI/test_sudoku_challenge_runner.py`:

```python
from sudoku_challenge_runner import ChallengeRunner


class FakePage:
    def __init__(self, days_by_month, completion_results=None):
        self.days_by_month = days_by_month
        self.completion_results = list(completion_results or [])
        self.visited_months = []
        self.started_days = []
        self.continued_days = []
        self.opened = False

    def open_challenges(self):
        self.opened = True

    def goto_month(self, year, month):
        self.visited_months.append((year, month))

    def read_calendar_days(self):
        return self.days_by_month[self.visited_months[-1]]

    def start_day(self, day):
        self.started_days.append(day)

    def wait_for_puzzle(self):
        return True

    def wait_for_completion(self):
        if self.completion_results:
            return self.completion_results.pop(0)
        return True

    def continue_after_completion(self):
        self.continued_days.append(self.started_days[-1])

    def close(self):
        pass


def test_runner_retries_failed_day_once_then_continues():
    page = FakePage(
        {(2025, 2): [CalendarDay(24, completed=False), CalendarDay(25, completed=True)]},
        completion_results=[False, True],
    )
    solve_calls = []
    logs = []
    runner = ChallengeRunner(
        page_factory=lambda: page,
        solve_current_puzzle=lambda: solve_calls.append("solve") or True,
        log=lambda message: logs.append(message),
        start_month="2025-02",
        end_month="2025-02",
        max_attempts=2,
    )

    runner.run()

    assert page.opened is True
    assert page.started_days == [24, 24]
    assert page.continued_days == [24]
    assert solve_calls == ["solve", "solve"]
    assert any("retry" in message.lower() for message in logs)


def test_runner_stops_before_next_day_when_stop_requested():
    page = FakePage(
        {(2025, 2): [CalendarDay(24, completed=False), CalendarDay(25, completed=False)]}
    )
    runner = None

    def solve_once():
        runner.stop()
        return True

    runner = ChallengeRunner(
        page_factory=lambda: page,
        solve_current_puzzle=solve_once,
        log=lambda message: None,
        start_month="2025-02",
        end_month="2025-02",
    )

    runner.run()

    assert page.started_days == [24]
    assert page.continued_days == [24]
```

- [ ] **Step 2: Verify the tests fail**

Run:

```bash
python -m pytest GUI/test_sudoku_challenge_runner.py -q
```

Expected: FAIL because `ChallengeRunner` does not exist.

- [ ] **Step 3: Implement runner orchestration**

Append to `GUI/sudoku_challenge_runner.py`:

```python
class ChallengeRunner:
    def __init__(
        self,
        page_factory,
        solve_current_puzzle,
        log,
        start_month="2025-02",
        end_month="2022-01",
        max_attempts=2,
    ):
        self.page_factory = page_factory
        self.solve_current_puzzle = solve_current_puzzle
        self.log = log
        self.start_month = start_month
        self.end_month = end_month
        self.max_attempts = max(1, int(max_attempts))
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def run(self):
        page = self.page_factory()
        try:
            self.log("Opening Sudoku.com daily challenges")
            page.open_challenges()
            for year, month in iter_months_desc(self.start_month, self.end_month):
                if self._stop_requested:
                    self.log("Challenge run stopped before next month")
                    return
                self._run_month(page, year, month)
        finally:
            close = getattr(page, "close", None)
            if callable(close):
                close()

    def _run_month(self, page, year, month):
        self.log(f"Processing {year:04d}-{month:02d}")
        page.goto_month(year, month)
        days = unfinished_days(page.read_calendar_days())
        if not days:
            self.log(f"No unfinished days in {year:04d}-{month:02d}")
            return
        for day in days:
            if self._stop_requested:
                self.log("Challenge run stopped before next day")
                return
            self._run_day(page, year, month, day)

    def _run_day(self, page, year, month, day):
        for attempt in range(1, self.max_attempts + 1):
            if self._stop_requested:
                return
            label = f"{year:04d}-{month:02d}-{day:02d}"
            self.log(f"Starting {label}, attempt {attempt}/{self.max_attempts}")
            page.start_day(day)
            if not page.wait_for_puzzle():
                self.log(f"Puzzle did not appear for {label}")
                continue
            if not self.solve_current_puzzle():
                self.log(f"Solve callback failed for {label}")
                continue
            if page.wait_for_completion():
                page.continue_after_completion()
                self.log(f"Completed {label}")
                return
            if attempt < self.max_attempts:
                self.log(f"Completion not detected for {label}; retrying")
        self.log(f"Failed {year:04d}-{month:02d}-{day:02d} after {self.max_attempts} attempts")
```

- [ ] **Step 4: Verify the tests pass**

Run:

```bash
python -m pytest GUI/test_sudoku_challenge_runner.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add GUI/sudoku_challenge_runner.py GUI/test_sudoku_challenge_runner.py
git commit -m "feat: orchestrate sudoku challenge retries"
```

## Task 3: Selenium Page Adapter

**Files:**
- Modify: `GUI/test_sudoku_challenge_runner.py`
- Modify: `GUI/sudoku_challenge_runner.py`

- [ ] **Step 1: Add failing tests for Selenium import failure and driver path selection**

Append to `GUI/test_sudoku_challenge_runner.py`:

```python
import pytest

from sudoku_challenge_runner import SeleniumUnavailableError, default_edge_driver_path, require_selenium


def test_default_edge_driver_path_points_to_project_driver():
    path = default_edge_driver_path()

    assert path.name == "msedgedriver.exe"
    assert path.parent.name == "edgedriver_win64"


def test_require_selenium_reports_missing_dependency(monkeypatch):
    real_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("selenium"):
            raise ModuleNotFoundError("No module named selenium")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(SeleniumUnavailableError):
        require_selenium()
```

- [ ] **Step 2: Verify the tests fail**

Run:

```bash
python -m pytest GUI/test_sudoku_challenge_runner.py -q
```

Expected: FAIL because the Selenium helpers do not exist.

- [ ] **Step 3: Add Selenium adapter code**

Replace `GUI/sudoku_challenge_runner.py` with the current content plus these imports and classes. Keep Chinese labels as escaped Unicode so the source stays ASCII.

```python
import re
import time
from pathlib import Path


CHALLENGE_URL = "https://sudoku.com/zh/challenges"
TEXT_DAILY_1 = "\u6bcf\u65e5"
TEXT_DAILY_2 = "\u6311\u6218"
TEXT_MONTH = "\u6708"
TEXT_START_GAME = "\u5f00\u59cb\u6e38\u620f"
TEXT_CONTINUE = "\u7ee7\u7eed"
TEXT_ERROR = "\u9519\u8bef"
TEXT_TIME = "\u65f6\u95f4"
TEXT_COMPLETE = "\u5b8c\u6210"


class SeleniumUnavailableError(RuntimeError):
    pass


def default_edge_driver_path() -> Path:
    return Path(__file__).resolve().parents[1] / "edgedriver_win64" / "msedgedriver.exe"


def require_selenium():
    try:
        from selenium import webdriver
        from selenium.common.exceptions import TimeoutException
        from selenium.webdriver.common.by import By
        from selenium.webdriver.edge.service import Service
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
    except ModuleNotFoundError as exc:
        raise SeleniumUnavailableError(
            "selenium is required for daily challenge automation. Install it with: python -m pip install selenium"
        ) from exc
    return {
        "webdriver": webdriver,
        "TimeoutException": TimeoutException,
        "By": By,
        "Service": Service,
        "EC": EC,
        "WebDriverWait": WebDriverWait,
    }


class SeleniumChallengePage:
    def __init__(self, driver_path=None, timeout=20):
        self.selenium = require_selenium()
        webdriver = self.selenium["webdriver"]
        service_cls = self.selenium["Service"]
        options = webdriver.EdgeOptions()
        options.add_argument("--start-maximized")
        service = service_cls(str(driver_path or default_edge_driver_path()))
        self.driver = webdriver.Edge(service=service, options=options)
        self.wait = self.selenium["WebDriverWait"](self.driver, timeout)
        self.By = self.selenium["By"]
        self.EC = self.selenium["EC"]
        self.TimeoutException = self.selenium["TimeoutException"]

    def open_challenges(self):
        self.driver.get(CHALLENGE_URL)
        self._wait_for_text(["Daily Challenge", TEXT_DAILY_1, TEXT_DAILY_2])

    def goto_month(self, year, month):
        for _ in range(60):
            text = self.driver.find_element(self.By.TAG_NAME, "body").text
            if str(year) in text and (f"{month} {TEXT_MONTH}" in text or f"{month}{TEXT_MONTH}" in text):
                return
            self._find_month_nav(previous=True).click()
            time.sleep(0.35)
        raise RuntimeError(f"Could not navigate to {year:04d}-{month:02d}")

    def read_calendar_days(self):
        entries = []
        elements = self.driver.find_elements(
            self.By.XPATH,
            "//button[normalize-space()!=''] | //*[@role='button'][normalize-space()!='']",
        )
        for element in elements:
            text = (element.text or "").strip()
            if not re.fullmatch(r"\d{1,2}", text):
                continue
            day = int(text)
            if day < 1 or day > 31:
                continue
            classes = (element.get_attribute("class") or "").lower()
            aria = (element.get_attribute("aria-label") or "").lower()
            enabled = element.is_enabled() and "disabled" not in classes and "disabled" not in aria
            completed = any(token in classes or token in aria for token in ["complete", "completed", "star", "done"])
            entries.append(CalendarDay(day=day, completed=completed, enabled=enabled))
        unique = {}
        for entry in entries:
            unique[entry.day] = entry
        return [unique[day] for day in sorted(unique)]

    def start_day(self, day):
        self._click_text(str(day))
        self._click_any_text([TEXT_START_GAME, TEXT_CONTINUE, "Start", "Continue"])

    def wait_for_puzzle(self):
        try:
            self._wait_for_text([TEXT_ERROR, TEXT_TIME, "0/3", "1", "2", "3"])
            return True
        except self.TimeoutException:
            return False

    def wait_for_completion(self):
        try:
            self._wait_for_text(["Congratulations", TEXT_COMPLETE, TEXT_CONTINUE])
            return True
        except self.TimeoutException:
            return False

    def continue_after_completion(self):
        self._click_any_text([TEXT_CONTINUE, "Continue"])

    def close(self):
        self.driver.quit()

    def _find_month_nav(self, previous):
        direction_tokens = ["prev", "previous", "left"] if previous else ["next", "right"]
        candidates = self.driver.find_elements(
            self.By.XPATH,
            "//*[self::button or @role='button' or self::a]",
        )
        for element in candidates:
            label = " ".join(
                filter(
                    None,
                    [
                        element.text,
                        element.get_attribute("aria-label"),
                        element.get_attribute("class"),
                    ],
                )
            ).lower()
            if any(token in label for token in direction_tokens) and element.is_displayed() and element.is_enabled():
                return element
        raise RuntimeError("Month navigation control not found")

    def _wait_for_text(self, texts):
        def has_text(driver):
            body = driver.find_element(self.By.TAG_NAME, "body").text
            return any(text in body for text in texts)

        return self.wait.until(has_text)

    def _click_any_text(self, texts):
        last_error = None
        for text in texts:
            try:
                return self._click_text(text)
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"Could not click any of: {texts}") from last_error

    def _click_text(self, text):
        xpath = (
            "//*[self::button or @role='button' or self::a]"
            f"[contains(normalize-space(), {text!r})]"
        )
        element = self.wait.until(self.EC.element_to_be_clickable((self.By.XPATH, xpath)))
        element.click()
        return element
```

- [ ] **Step 4: Verify the tests pass**

Run:

```bash
python -m pytest GUI/test_sudoku_challenge_runner.py -q
```

Expected: PASS. These tests do not require Selenium to be installed because they only verify the missing-dependency error.

- [ ] **Step 5: Commit**

```bash
git add GUI/sudoku_challenge_runner.py GUI/test_sudoku_challenge_runner.py
git commit -m "feat: add selenium sudoku challenge page adapter"
```

## Task 4: GUI Solve Callback And Fill Completion Hook

**Files:**
- Create: `GUI/test_sudoku_gui_challenge.py`
- Modify: `GUI/sudoku_gui.py`

- [ ] **Step 1: Add failing GUI tests**

Create `GUI/test_sudoku_gui_challenge.py`:

```python
import sys
import tkinter as tk
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

from sudoku_gui import SudokuApp


TEXT_DAILY_CHALLENGE = "\u6bcf\u65e5\u6311\u6218"


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


def test_daily_challenge_button_exists():
    root = tk.Tk()
    root.withdraw()
    app = SudokuApp(root)
    try:
        assert any(TEXT_DAILY_CHALLENGE in text for text in _widget_texts(root))
    finally:
        app.on_close()


def test_fill_completion_callback_is_called(monkeypatch):
    root = tk.Tk()
    root.withdraw()
    app = SudokuApp(root)
    called = []
    try:
        app.solution = [[1 for _ in range(9)] for _ in range(9)]
        app.original_board = [[0 for _ in range(9)] for _ in range(9)]
        app.grid_coords = (0, 0, 90, 90)
        app._resolve_fill_target_window = lambda grid_coords=None: None
        app._capture_foreground_window_info = lambda allow_self=False: None
        app._hide_window_for_fill = lambda: True
        app._run_hidden_fill_task = lambda target, on_done, restore_focus=True: (target(), on_done())
        app.filler.fill_board = lambda *args, **kwargs: None

        assert app._start_fill(auto_started=True, on_complete=lambda ok: called.append(ok)) is True

        assert called == [True]
    finally:
        app.on_close()
```

- [ ] **Step 2: Verify the tests fail**

Run:

```bash
python -m pytest GUI/test_sudoku_gui_challenge.py -q
```

Expected: FAIL because the button does not exist and `_start_fill` has no `on_complete` parameter.

- [ ] **Step 3: Add imports and state fields**

Add near the other imports in `GUI/sudoku_gui.py`:

```python
from sudoku_challenge_runner import ChallengeRunner, SeleniumChallengePage, SeleniumUnavailableError
```

In `SudokuApp.__init__`, after `self.action_buttons = []`, add:

```python
        self.challenge_runner = None
        self.challenge_thread = None
        self.challenge_running = False
        self.challenge_button = None
        self._pending_challenge_fill_callback = None
```

- [ ] **Step 4: Add the daily challenge button**

In `_build_sidebar`, add this entry to `compact_actions` after the auto-fill entry:

```python
            ("\u2605 \u6bcf\u65e5\u6311\u6218", self.on_toggle_daily_challenges, self.SOFT_BLUE, self.TEXT, self.PRIMARY),
```

After `button.grid(...)` in the loop, add:

```python
            if command == self.on_toggle_daily_challenges:
                self.challenge_button = button
```

- [ ] **Step 5: Add fill completion callback support**

Change:

```python
    def _start_fill(self, auto_started=False):
```

to:

```python
    def _start_fill(self, auto_started=False, on_complete=None):
```

Inside `on_done()`, add `on_complete` calls in each terminal branch without rewriting the existing log text:

```python
            if outcome["status"] == "ok":
                # Keep the existing success logging here.
                if callable(on_complete):
                    on_complete(True)
                if self.minimize_after_fill_enabled.get():
```

Add this in the cancelled branch after the existing cancelled status update:

```python
                if callable(on_complete):
                    on_complete(False)
```

Add this in the error branch after the existing failure status update and before `_show_error(...)`:

```python
                if callable(on_complete):
                    on_complete(False)
```

- [ ] **Step 6: Add GUI start/stop methods**

Add near `on_fill`:

```python
    def on_toggle_daily_challenges(self):
        if self.challenge_running:
            self.on_stop_daily_challenges()
        else:
            self.on_start_daily_challenges()

    def on_start_daily_challenges(self):
        if self.challenge_running:
            return
        self.challenge_running = True
        self._refresh_challenge_button()
        self._log("INFO", "Daily challenge automation started: 2025-02 to 2022-01")
        self._set_status("\u6bcf\u65e5\u6311\u6218\u81ea\u52a8\u5237\u9898\u8fd0\u884c\u4e2d")

        def log_runner(message):
            self._log("INFO", f"Daily challenge: {message}")

        def task():
            try:
                runner = ChallengeRunner(
                    page_factory=SeleniumChallengePage,
                    solve_current_puzzle=self._solve_visible_challenge_puzzle,
                    log=log_runner,
                    start_month="2025-02",
                    end_month="2022-01",
                )
                self.challenge_runner = runner
                runner.run()
            except SeleniumUnavailableError as exc:
                self._log("ERROR", str(exc))
                self._show_error("\u7f3a\u5c11\u4f9d\u8d56", str(exc))
            except Exception as exc:
                self._log("ERROR", f"Daily challenge automation failed: {exc}\n{traceback.format_exc()}")
                self._show_error("\u6bcf\u65e5\u6311\u6218\u5931\u8d25", str(exc))
            finally:
                self.challenge_runner = None
                self.challenge_running = False
                self._run_on_ui_thread(self._refresh_challenge_button)
                self._set_status("\u6bcf\u65e5\u6311\u6218\u81ea\u52a8\u5237\u9898\u5df2\u505c\u6b62")

        self.challenge_thread = threading.Thread(target=task, daemon=True)
        self.challenge_thread.start()

    def on_stop_daily_challenges(self):
        if self.challenge_runner is not None:
            self.challenge_runner.stop()
        self.challenge_running = False
        self._refresh_challenge_button()
        self._log("INFO", "Daily challenge stop requested")
        self._set_status("\u6b63\u5728\u505c\u6b62\u6bcf\u65e5\u6311\u6218\u81ea\u52a8\u5237\u9898")

    def _refresh_challenge_button(self):
        if self.challenge_button is None:
            return
        text = "\u25a0 \u505c\u6b62\u5237\u9898" if self.challenge_running else "\u2605 \u6bcf\u65e5\u6311\u6218"
        self.challenge_button.config(text=text)
```

- [ ] **Step 7: Add blocking solve callback**

Add near the daily challenge methods:

```python
    def _solve_visible_challenge_puzzle(self):
        done = threading.Event()
        result = {"ok": False}

        def completed(ok):
            result["ok"] = bool(ok)
            done.set()

        def start():
            if not self.auto_fill_enabled.get():
                self.auto_fill_enabled.set(True)
                self.turbo_fill_enabled.set(True)
            self.on_ocr_with_fill_callback(completed)

        self._run_on_ui_thread(start)
        return done.wait(timeout=90) and result["ok"]

    def on_ocr_with_fill_callback(self, on_complete):
        self._pending_challenge_fill_callback = on_complete
        self.on_ocr()
```

In `_solve_current_board`, change:

```python
            self._start_fill(auto_started=True)
```

to:

```python
            callback = self._pending_challenge_fill_callback
            self._pending_challenge_fill_callback = None
            self._start_fill(auto_started=True, on_complete=callback)
```

- [ ] **Step 8: Verify GUI tests pass**

Run:

```bash
python -m pytest GUI/test_sudoku_gui_challenge.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add GUI/sudoku_gui.py GUI/test_sudoku_gui_challenge.py
git commit -m "feat: add daily challenge GUI controls"
```

## Task 5: Calendar Refresh After Completion

**Files:**
- Modify: `GUI/test_sudoku_challenge_runner.py`
- Modify: `GUI/sudoku_challenge_runner.py`

- [ ] **Step 1: Add failing refresh test**

Append to `GUI/test_sudoku_challenge_runner.py`:

```python
def test_runner_refreshes_month_after_completed_day_when_page_supports_it():
    page = FakePage({(2025, 2): [CalendarDay(24, completed=False)]})
    page.refresh_calls = 0
    page.refresh_calendar = lambda year, month: setattr(page, "refresh_calls", page.refresh_calls + 1)
    runner = ChallengeRunner(
        page_factory=lambda: page,
        solve_current_puzzle=lambda: True,
        log=lambda message: None,
        start_month="2025-02",
        end_month="2025-02",
    )

    runner.run()

    assert page.refresh_calls == 1
```

- [ ] **Step 2: Verify the test fails**

Run:

```bash
python -m pytest GUI/test_sudoku_challenge_runner.py::test_runner_refreshes_month_after_completed_day_when_page_supports_it -q
```

Expected: FAIL because refresh is not called.

- [ ] **Step 3: Implement refresh hook**

In `ChallengeRunner._run_day`, after `page.continue_after_completion()`, add:

```python
                refresh = getattr(page, "refresh_calendar", None)
                if callable(refresh):
                    refresh(year, month)
```

Add to `SeleniumChallengePage`:

```python
    def refresh_calendar(self, year, month):
        self.driver.get(CHALLENGE_URL)
        self.goto_month(year, month)
```

- [ ] **Step 4: Verify runner tests pass**

Run:

```bash
python -m pytest GUI/test_sudoku_challenge_runner.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add GUI/sudoku_challenge_runner.py GUI/test_sudoku_challenge_runner.py
git commit -m "feat: refresh sudoku challenge calendar"
```

## Task 6: Full Verification

**Files:**
- Modify only if verification exposes defects directly related to this feature.

- [ ] **Step 1: Run focused tests**

Run:

```bash
python -m pytest GUI/test_sudoku_challenge_runner.py GUI/test_sudoku_gui_challenge.py -q
```

Expected: PASS.

- [ ] **Step 2: Run existing GUI tests**

Run:

```bash
python -m pytest GUI/test_sudoku_gui_settings.py GUI/test_sudoku_teaching.py -q
```

Expected: PASS.

- [ ] **Step 3: Run OCR tests if dependencies are available**

Run:

```bash
python -m pytest GUI/test_sudoku_ocr.py -q
```

Expected: PASS if OpenCV/PIL/Tesseract dependencies are available. If dependency import fails, record the exact missing dependency and do not claim OCR tests passed.

- [ ] **Step 4: Manual Selenium smoke check**

Run:

```bash
python GUI/sudoku_gui.py
```

Manual checks:

- Confirm the daily challenge button is visible.
- Confirm clicking it starts Edge and opens `https://sudoku.com/zh/challenges`.
- Confirm it navigates to February 2025.
- Confirm it starts one unfinished day.
- Confirm OCR, solve, and fill run through the existing app.
- Confirm the completion page continue control is clicked.
- Confirm the calendar reloads and the next day is selected or the stop button halts before the next day.

- [ ] **Step 5: Final status check**

Run:

```bash
git status --short
```

Expected: only intended files changed, with the unrelated pre-existing untracked GUI copy directory left untouched.
