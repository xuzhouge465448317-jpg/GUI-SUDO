# Sudoku Daily Challenge Automation Design

## Goal

Automate Sudoku.com daily challenge completion for the remaining days in February 2025, January 2025, and every month in 2024, 2023, and 2022, while reusing the existing Sudoku GUI recognition, solving, and fill workflow.

## Assumptions

- The user is already logged in to Sudoku.com in the browser profile used by automation.
- The target page is `https://sudoku.com/zh/challenges`.
- The existing `SudokuApp` workflow can solve a visible puzzle by taking a screenshot, detecting the board, solving it, and filling the browser board.
- Selenium is acceptable for controlling browser navigation and page buttons.
- The project-local Edge driver at `F:\datacode\edgedriver_win64\msedgedriver.exe` is available.
- Completed dates on the month calendar can be detected from the page state, such as star or completed markers, before deciding whether to play a day.

## Scope

In scope:

- Add a browser automation runner for Sudoku.com daily challenge pages.
- Add a small GUI entry point to start and stop the daily challenge automation.
- Process months in reverse chronological order from `2025-02` through `2022-01`.
- Skip dates that appear completed.
- Start or continue each unfinished daily puzzle.
- Invoke the existing GUI OCR, solver, and auto-fill path for each puzzle.
- Detect the completion screen and click the final continue button.
- Log progress, skipped days, retries, and failures in the existing GUI log.

Out of scope:

- Creating a new Sudoku solver.
- Replacing the existing OCR and fill implementation.
- Bypassing the Sudoku.com UI by reverse-engineering internal game data.
- Automating account login.
- Persisting a separate achievement database outside the existing app state.

## Architecture

The feature is split into a new automation module and a small GUI integration.

`GUI/sudoku_challenge_runner.py` owns Selenium browser automation. It opens the challenge page, navigates months, identifies unfinished dates, starts games, waits for puzzle and completion states, and calls a supplied callback to solve the current visible puzzle.

`GUI/sudoku_gui.py` stays responsible for the existing solving workflow. It adds start and stop controls, creates the runner in a background thread, and passes a callback that triggers the current screenshot recognition, solve, and fill sequence.

This keeps website navigation separate from OCR and solving. The runner can be tested with fake browser/page adapters without launching the GUI or a real browser.

## Workflow

1. User opens the Sudoku helper GUI.
2. User clicks the new daily challenge automation button.
3. The GUI starts the runner in a background thread and logs the selected range.
4. The runner opens `https://sudoku.com/zh/challenges`.
5. For each month from `2025-02` down to `2022-01`:
   - Navigate to that month.
   - Read the visible calendar days.
   - Build a list of days that are not visibly completed.
   - Process days from the current visible remaining day onward.
6. For each unfinished day:
   - Click the date.
   - Click the visible start or continue control for the selected daily challenge.
   - Wait for the puzzle board.
   - Call the GUI solve callback.
   - Wait for the completion page.
   - Click the visible continue control.
   - Return to the calendar page and continue.
7. The user may stop the run from the GUI. The runner finishes the current checkpoint safely and stops before starting another day.

## Browser Automation Details

The first implementation uses Selenium WebDriver with Microsoft Edge:

- Driver path: `F:\datacode\edgedriver_win64\msedgedriver.exe`.
- Browser window should be maximized or set to a stable size before starting.
- The runner uses explicit waits for page states instead of fixed sleeps where possible.
- Text matching supports labels shown in the screenshots:
  - Start-game control.
  - Continue control.
  - Daily-challenge navigation label.
  - `Congratulations!`

Selectors should be centralized in the runner. If a selector fails, the runner logs the failing phase and skips or retries the current day rather than continuing blindly.

## Solve Callback Contract

The runner calls a GUI-provided callback after a puzzle board is visible.

The callback must:

- Trigger screenshot recognition on the current foreground browser window.
- Let the existing app solve and auto-fill the board.
- Return `True` only when the fill task has completed without an app-level error.
- Return `False` if OCR, solving, or filling fails.

The callback should not decide which calendar day to process next. That remains the runner's responsibility.

## Failure Handling

- Each day gets up to two attempts.
- If OCR fails, solving fails, filling fails, or the completion page does not appear, the runner logs the day as failed and retries.
- After retries are exhausted, the runner logs the failure and moves to the next unfinished day.
- If browser startup fails, the run stops immediately with the error in the GUI log.
- If the stop flag is set, the runner stops before opening the next day.
- Escape remains available through the existing filler cancel path while numbers are being entered.

## UI Integration

Add a compact control in the existing action area:

- Button text while idle: the existing app's Chinese equivalent of "Run daily challenges".
- Button text while running: the existing app's Chinese equivalent of "Stop challenge run".
- Default range: `2025-02` through `2022-01`

The existing log panel reports:

- Runner startup and browser selection.
- Current month and day.
- Whether a day was skipped as completed.
- Start, solve, fill, completion, and continue phases.
- Retry counts and final failures.

No new large configuration panel is needed for the first version.

## Testing

Unit tests cover deterministic runner logic:

- Month range generation from `2025-02` down to `2022-01`.
- Current month ordering before earlier months.
- Completed day filtering from normalized calendar entries.
- Retry behavior for a day that fails once then succeeds.
- Stop flag behavior between days.

Selenium end-to-end behavior is verified manually because it depends on the live Sudoku.com page, browser profile, login state, and current page layout.

Manual verification:

1. Start the GUI.
2. Start daily challenge automation.
3. Confirm the browser opens the challenge page.
4. Confirm an unfinished day starts.
5. Confirm the existing OCR/solve/fill path completes the puzzle.
6. Confirm the completion page appears and the continue control is clicked.
7. Confirm the runner returns to the calendar and proceeds to the next unfinished date.
8. Confirm the stop button halts before the next day.
