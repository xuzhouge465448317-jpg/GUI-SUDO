from pathlib import Path
from time import perf_counter

import cv2
import numpy as np
import pytest

from sudoku_ocr import SudokuOCR


def _detector():
    return SudokuOCR.__new__(SudokuOCR)


def _detected_bounds(image):
    ocr = _detector()
    result = ocr._warp_board_with_corners(image)
    assert result is not None
    _warped, corners = result
    return ocr._corners_to_bounds(corners)


def _draw_sudoku_grid(image, left, top, size):
    cv2.rectangle(image, (left, top), (left + size, top + size), (255, 255, 255), -1)
    for index in range(10):
        offset = round(index * size / 9)
        thickness = 3 if index % 3 == 0 else 1
        color = (95, 95, 95) if index % 3 == 0 else (175, 175, 175)
        cv2.line(image, (left + offset, top), (left + offset, top + size), color, thickness)
        cv2.line(image, (left, top + offset), (left + size, top + offset), color, thickness)


def _draw_keypad_panel(image, left, top, size):
    cv2.rectangle(image, (left, top), (left + size, top + size), (218, 230, 246), -1)
    cv2.rectangle(image, (left, top), (left + size, top + size), (70, 108, 170), 3)
    for index in range(1, 3):
        offset = round(index * size / 3)
        cv2.line(image, (left + offset, top), (left + offset, top + size), (70, 108, 170), 3)
        cv2.line(image, (left, top + offset), (left + size, top + offset), (70, 108, 170), 3)


def test_grid_detection_prefers_9x9_board_over_larger_3x3_keypad():
    image = np.full((760, 1280, 3), 255, dtype=np.uint8)
    _draw_sudoku_grid(image, left=120, top=140, size=420)
    _draw_keypad_panel(image, left=710, top=120, size=460)

    left, top, width, height = _detected_bounds(image)

    assert left < 300
    assert top < 260
    assert width >= 380
    assert height >= 380


def test_grid_detection_prefers_main_board_on_reported_thesudoku_screenshot():
    path = Path(r"C:\Users\Spring\AppData\Local\Temp\ai-chat-attachment-9242244042133643574.png")
    if not path.exists():
        pytest.skip("reported screenshot is not available")

    image = cv2.imread(str(path))
    assert image is not None

    left, top, width, height = _detected_bounds(image)

    assert left < 800
    assert top < 380
    assert width >= 520
    assert height >= 520


def test_reported_metool_screenshot_reads_narrow_one_not_four():
    path = Path(r"C:\Users\Spring\AppData\Local\Temp\ai-chat-attachment-9026993304443134493.png")
    if not path.exists():
        pytest.skip("reported screenshot is not available")

    board, _bounds, _confidence = SudokuOCR().process_with_grid_bounds_and_confidence(str(path))

    assert board[0][5] == 1
    assert board[2][5] == 4


def test_reported_metool_screenshot_reads_eight_not_three():
    path = Path(r"C:\Users\Spring\AppData\Local\Temp\ai-chat-attachment-8979554885179233304.png")
    if not path.exists():
        pytest.skip("reported screenshot is not available")

    board, _bounds, _confidence = SudokuOCR().process_with_grid_bounds_and_confidence(str(path))

    assert board[1][3] == 8
    assert board[5][2] == 8
    assert board[8][2] == 3


def test_reported_metool_screenshot_recognizes_under_two_seconds():
    path = Path(r"C:\Users\Spring\AppData\Local\Temp\ai-chat-attachment-8979554885179233304.png")
    if not path.exists():
        pytest.skip("reported screenshot is not available")

    started = perf_counter()
    board, _bounds, _confidence = SudokuOCR().process_with_grid_bounds_and_confidence(str(path))
    elapsed = perf_counter() - started

    assert board[1][3] == 8
    assert elapsed < 2.0
