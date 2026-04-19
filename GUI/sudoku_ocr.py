import os
import shutil
import sys
import threading
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from PIL import Image
from pytesseract import Output


BOARD_SIZE = 9
WARP_SIZE = 540
CELL_SIZE = WARP_SIZE // BOARD_SIZE


class SudokuOCR:
    OCR_CACHE_LIMIT = 512

    def __init__(self):
        self.tesseract_cmd = self._configure_tesseract()
        digit_config = "-c tessedit_char_whitelist=123456789 -c load_system_dawg=0 -c load_freq_dawg=0"
        self.primary_config = f"--oem 3 --psm 10 {digit_config}"
        self.fallback_config = f"--oem 3 --psm 13 {digit_config}"
        self.layout_config = f"--oem 3 --psm 6 {digit_config}"
        self.primary_conf_threshold = 60.0
        self.layout_conf_threshold = 78.0
        self.layout_vote_threshold = 60.0
        self.fast_single_conf_threshold = 95.0
        self.fast_primary_conf_threshold = 82.0
        self.fast_confirm_conf_threshold = 55.0
        self.fast_average_conf_threshold = 78.0
        self.blank_rescue_signal_threshold = 0.030
        self.template_score_threshold = 0.80
        self.template_margin_threshold = 0.05
        self.ocr_workers = max(2, min(4, os.cpu_count() or 2))
        self._digit_read_cache = OrderedDict()
        self._cache_lock = threading.Lock()
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    def _configure_tesseract(self):
        command = shutil.which("tesseract")
        if command:
            pytesseract.pytesseract.tesseract_cmd = command
            return command

        # Support PyInstaller bundles by preferring a packaged tesseract folder
        # next to the executable or inside the extraction dir.
        bundled_roots = []
        if getattr(sys, "frozen", False):
            bundled_roots.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)))
            bundled_roots.append(Path(sys.executable).resolve().parent)
        else:
            bundled_roots.append(Path(__file__).resolve().parent)

        for root in bundled_roots:
            candidate = root / "tesseract" / "tesseract.exe"
            if candidate.exists():
                tessdata_dir = candidate.parent / "tessdata"
                if tessdata_dir.exists():
                    os.environ["TESSDATA_PREFIX"] = str(tessdata_dir)
                pytesseract.pytesseract.tesseract_cmd = str(candidate)
                return str(candidate)

        candidates = [
            Path(r"D:\software\Tools\tesseract\tesseract.exe"),
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        ]
        for candidate in candidates:
            if candidate.exists():
                tessdata_dir = candidate.parent / "tessdata"
                if tessdata_dir.exists():
                    os.environ["TESSDATA_PREFIX"] = str(tessdata_dir)
                pytesseract.pytesseract.tesseract_cmd = str(candidate)
                return str(candidate)

        raise FileNotFoundError(
            "未找到 tesseract.exe。请安装 Tesseract，或加入 PATH，"
            "或放到 D:\\software\\Tools\\tesseract\\tesseract.exe。"
        )

    def _load_image(self, image_source):
        if isinstance(image_source, str):
            image = cv2.imread(image_source)
            if image is None:
                raise ValueError(f"无法读取图片: {image_source}")
            return image

        if isinstance(image_source, Image.Image):
            return cv2.cvtColor(np.array(image_source), cv2.COLOR_RGB2BGR)

        if isinstance(image_source, np.ndarray):
            if len(image_source.shape) == 2:
                return cv2.cvtColor(image_source, cv2.COLOR_GRAY2BGR)
            return image_source.copy()

        raise TypeError("不支持的图片输入类型。")

    def _order_points(self, points):
        rect = np.zeros((4, 2), dtype=np.float32)
        sums = points.sum(axis=1)
        rect[0] = points[np.argmin(sums)]
        rect[2] = points[np.argmax(sums)]
        diffs = np.diff(points, axis=1)
        rect[1] = points[np.argmin(diffs)]
        rect[3] = points[np.argmax(diffs)]
        return rect

    def _projection_groups(self, projection, threshold):
        indices = np.where(projection >= threshold)[0]
        if len(indices) == 0:
            return []

        groups = []
        start = previous = int(indices[0])
        for index in indices[1:]:
            index = int(index)
            if index <= previous + 2:
                previous = index
                continue
            groups.append((start + previous) // 2)
            start = previous = index
        groups.append((start + previous) // 2)
        return groups

    def _grid_line_counts(self, horizontal, vertical, bounds):
        x, y, width, height = bounds
        horizontal_roi = horizontal[y:y + height, x:x + width]
        vertical_roi = vertical[y:y + height, x:x + width]
        if horizontal_roi.size == 0 or vertical_roi.size == 0:
            return 0, 0

        vertical_projection = np.count_nonzero(vertical_roi, axis=0)
        horizontal_projection = np.count_nonzero(horizontal_roi, axis=1)
        vertical_threshold = max(8, int(height * 0.35))
        horizontal_threshold = max(8, int(width * 0.35))
        vertical_groups = self._projection_groups(vertical_projection, vertical_threshold)
        horizontal_groups = self._projection_groups(horizontal_projection, horizontal_threshold)
        return len(vertical_groups), len(horizontal_groups)

    def _find_grid_corners_from_lines(self, gray):
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        binary = cv2.adaptiveThreshold(
            blur,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            15,
            3,
        )
        edges = cv2.Canny(blur, 50, 150)
        binary = cv2.bitwise_or(binary, edges)

        kernel_length = max(15, min(gray.shape[:2]) // 24)
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_length, 1))
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kernel_length))
        horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)
        vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)
        lines = cv2.bitwise_or(horizontal, vertical)
        lines = cv2.dilate(lines, np.ones((3, 3), np.uint8), iterations=1)

        contours, _ = cv2.findContours(lines, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        image_area = gray.shape[0] * gray.shape[1]
        min_side = min(gray.shape[:2])
        best_corners = None
        best_score = -1.0

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < image_area * 0.015:
                continue

            x, y, width, height = cv2.boundingRect(contour)
            if min(width, height) < min_side * 0.20:
                continue

            ratio = width / max(height, 1)
            if not 0.65 <= ratio <= 1.45:
                continue

            vertical_count, horizontal_count = self._grid_line_counts(
                horizontal,
                vertical,
                (x, y, width, height),
            )
            if vertical_count < 8 or horizontal_count < 8:
                continue

            square_score = 1.0 - min(abs(1.0 - ratio), 1.0)
            line_score = min(vertical_count, 10) + min(horizontal_count, 10)
            score = line_score + square_score + area / image_area
            if score <= best_score:
                continue

            rect = cv2.minAreaRect(contour)
            box = cv2.boxPoints(rect)
            best_corners = self._order_points(box.astype(np.float32))
            best_score = score

        return best_corners

    def _find_grid_corners(self, gray):
        line_corners = self._find_grid_corners_from_lines(gray)
        if line_corners is not None:
            return line_corners

        blur = cv2.GaussianBlur(gray, (7, 7), 0)
        thresh = cv2.adaptiveThreshold(
            blur,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            11,
            2,
        )
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)

        image_area = gray.shape[0] * gray.shape[1]
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < image_area * 0.08:
                break
            perimeter = cv2.arcLength(contour, True)
            polygon = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
            if len(polygon) == 4:
                return self._order_points(polygon.reshape(4, 2).astype(np.float32))

        if contours:
            rect = cv2.minAreaRect(contours[0])
            box = cv2.boxPoints(rect)
            return self._order_points(box.astype(np.float32))
        return None

    def _warp_board(self, image):
        result = self._warp_board_with_corners(image)
        if result is None:
            return None
        warped, _corners = result
        return warped

    def _warp_board_with_corners(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        height, width = gray.shape[:2]
        max_side = max(height, width)
        scale = 1.0
        search_gray = gray
        if max_side > 1200:
            scale = 1200 / max_side
            search_gray = cv2.resize(
                gray,
                (max(1, int(width * scale)), max(1, int(height * scale))),
                interpolation=cv2.INTER_AREA,
            )

        corners = self._find_grid_corners(search_gray)
        if corners is not None and not self._corners_look_square(corners):
            corners = None
        if corners is None and scale != 1.0:
            corners = self._find_grid_corners(gray)
            scale = 1.0
        if corners is None:
            return None
        if scale != 1.0:
            corners = corners / scale
            corners = self._refine_corners_in_roi(gray, corners)
        target = np.array(
            [[0, 0], [WARP_SIZE - 1, 0], [WARP_SIZE - 1, WARP_SIZE - 1], [0, WARP_SIZE - 1]],
            dtype=np.float32,
        )
        matrix = cv2.getPerspectiveTransform(corners, target)
        warped = cv2.warpPerspective(image, matrix, (WARP_SIZE, WARP_SIZE))
        return warped, corners

    def _corners_to_bounds(self, corners):
        left = max(0, int(np.floor(corners[:, 0].min())))
        top = max(0, int(np.floor(corners[:, 1].min())))
        right = int(np.ceil(corners[:, 0].max()))
        bottom = int(np.ceil(corners[:, 1].max()))
        return left, top, max(1, right - left), max(1, bottom - top)

    def _corners_look_square(self, corners):
        _left, _top, width, height = self._corners_to_bounds(corners)
        ratio = width / max(height, 1)
        return 0.65 <= ratio <= 1.45

    def _refine_corners_in_roi(self, gray, corners):
        if corners is None:
            return None
        left, top, width, height = self._corners_to_bounds(corners)
        pad = max(18, int(max(width, height) * 0.08))
        x1 = max(0, left - pad)
        y1 = max(0, top - pad)
        x2 = min(gray.shape[1], left + width + pad)
        y2 = min(gray.shape[0], top + height + pad)
        roi = gray[y1:y2, x1:x2]
        if roi.size == 0:
            return corners
        refined = self._find_grid_corners(roi)
        if refined is None:
            return corners
        refined[:, 0] += x1
        refined[:, 1] += y1
        if self._corners_look_square(refined):
            return refined
        return corners

    def _remove_grid_lines(self, gray):
        binary = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            11,
            2,
        )

        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (CELL_SIZE // 2, 1))
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, CELL_SIZE // 2))
        horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)
        vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)
        lines = cv2.bitwise_or(horizontal, vertical)
        lines = cv2.dilate(lines, np.ones((3, 3), np.uint8), iterations=1)

        cleaned = cv2.inpaint(gray, lines, 3, cv2.INPAINT_TELEA)
        return cleaned

    def _crop_digit_component(self, binary):
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
        if num_labels <= 1:
            return None

        h, w = binary.shape
        center = np.array([w / 2.0, h / 2.0])
        best_label = None
        best_score = None

        for label in range(1, num_labels):
            x, y, bw, bh, area = stats[label]
            if area < binary.size * 0.015:
                continue
            if bw < 4 or bh < 8:
                continue
            if bw > w * 0.7 or bh > h * 0.85:
                continue

            centroid = centroids[label]
            distance = np.linalg.norm(centroid - center)
            distance_score = distance / max(h, w)
            if distance_score > 0.28:
                continue

            area_score = area / binary.size
            fill_ratio = area / max(bw * bh, 1)
            if fill_ratio < 0.12:
                continue

            score = area_score + fill_ratio * 0.15 - distance_score * 0.25

            if best_score is None or score > best_score:
                best_score = score
                best_label = label

        if best_label is None:
            return None

        x, y, bw, bh, _ = stats[best_label]
        component = np.zeros_like(binary)
        component[labels == best_label] = 255
        digit = component[y:y + bh, x:x + bw]
        if digit.size == 0:
            return None
        return digit

    def _normalize_digit(self, digit):
        canvas = np.zeros((96, 96), dtype=np.uint8)
        h, w = digit.shape
        scale = min(68 / max(w, 1), 68 / max(h, 1))
        resized = cv2.resize(
            digit,
            (max(1, int(w * scale)), max(1, int(h * scale))),
            interpolation=cv2.INTER_CUBIC,
        )
        off_x = (96 - resized.shape[1]) // 2
        off_y = (96 - resized.shape[0]) // 2
        canvas[off_y:off_y + resized.shape[0], off_x:off_x + resized.shape[1]] = resized
        return canvas

    def _quick_nonzero_ratio(self, gray):
        quick_binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        edge = max(2, int(min(quick_binary.shape) * 0.06))
        quick_binary[:edge, :] = 0
        quick_binary[-edge:, :] = 0
        quick_binary[:, :edge] = 0
        quick_binary[:, -edge:] = 0
        return cv2.countNonZero(quick_binary) / quick_binary.size

    def _extract_variants_from_gray(self, gray):
        normalized = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
        equalized = cv2.equalizeHist(normalized)
        local_contrast = self._clahe.apply(normalized)
        blend = cv2.addWeighted(equalized, 0.55, local_contrast, 0.45, 0)
        blur = cv2.GaussianBlur(blend, (3, 3), 0)
        sharpened = cv2.addWeighted(blend, 1.35, blur, -0.35, 0)

        variants = []
        binaries = [
            cv2.adaptiveThreshold(
                blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2
            ),
            cv2.adaptiveThreshold(
                sharpened, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 11, 2
            ),
            cv2.threshold(sharpened, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1],
        ]

        kernel = np.ones((2, 2), np.uint8)
        for binary in binaries:
            edge = max(2, int(min(binary.shape) * 0.05))
            binary[:edge, :] = 0
            binary[-edge:, :] = 0
            binary[:, :edge] = 0
            binary[:, -edge:] = 0
            dense_binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
            cleaned = cv2.morphologyEx(dense_binary, cv2.MORPH_OPEN, kernel)
            sparse_rescue = cv2.dilate(binary, kernel, iterations=1)
            for prepared in (binary, dense_binary, cleaned, sparse_rescue):
                digit = self._crop_digit_component(prepared)
                if digit is None:
                    continue
                if cv2.countNonZero(digit) < digit.size * 0.06:
                    continue
                normalized_digit = self._normalize_digit(digit)
                if not any(np.array_equal(normalized_digit, existing) for existing in variants):
                    variants.append(normalized_digit)
        return variants

    def _build_cell_variants(self, gray_sources, variant_limit=3):
        candidate_margins = [0.12, 0.16, 0.20]
        variants = []
        max_ratio = 0.0
        seen_variants = set()
        variant_limit = max(1, int(variant_limit))

        for gray_source in gray_sources:
            if gray_source is None or gray_source.size == 0:
                continue
            for margin_ratio in candidate_margins:
                margin = max(4, int(gray_source.shape[0] * margin_ratio))
                core = gray_source[margin:-margin, margin:-margin]
                if core.size == 0:
                    continue

                max_ratio = max(max_ratio, self._quick_nonzero_ratio(core))
                for variant in self._extract_variants_from_gray(core):
                    variant_key = variant.tobytes()
                    if variant_key not in seen_variants:
                        seen_variants.add(variant_key)
                        variants.append(variant)
                    if len(variants) >= variant_limit:
                        return variants, False

        if max_ratio < 0.028:
            return [], True
        return variants, False

    def _cell_signal_strength(self, gray_sources):
        signal = 0.0
        for gray_source in gray_sources:
            if gray_source is None or gray_source.size == 0:
                continue
            margin = max(4, int(min(gray_source.shape) * 0.12))
            core = gray_source[margin:-margin, margin:-margin]
            if core.size == 0:
                continue
            signal = max(signal, self._quick_nonzero_ratio(core))
        return signal

    def _has_center_digit_stroke(self, gray_sources):
        for gray_source in gray_sources:
            if gray_source is None or gray_source.size == 0:
                continue

            margin = max(6, int(min(gray_source.shape) * 0.18))
            core = gray_source[margin:-margin, margin:-margin]
            if core.size == 0:
                continue

            normalized = cv2.normalize(core, None, 0, 255, cv2.NORM_MINMAX)
            equalized = cv2.equalizeHist(normalized)
            blur = cv2.GaussianBlur(equalized, (3, 3), 0)
            binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
            binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
            num_labels, _labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
            if num_labels <= 1:
                continue

            core_h, core_w = binary.shape
            center = np.array([core_w / 2.0, core_h / 2.0])
            for label in range(1, num_labels):
                x, y, width, height, area = stats[label]
                if area < binary.size * 0.012:
                    continue
                if height < core_h * 0.28:
                    continue
                if width < core_w * 0.035:
                    continue
                if width > core_w * 0.82 or height > core_h * 0.98:
                    continue
                fill_ratio = area / max(width * height, 1)
                if fill_ratio < 0.10:
                    continue
                distance = np.linalg.norm(centroids[label] - center) / max(core_h, core_w)
                if distance <= 0.34:
                    return True
        return False

    def _read_digit(self, image, config):
        cache_key = (config, image.tobytes())
        with self._cache_lock:
            cached = self._digit_read_cache.get(cache_key)
            if cached is not None:
                self._digit_read_cache.move_to_end(cache_key)
                return cached

        data = pytesseract.image_to_data(
            image,
            config=config,
            output_type=Output.DICT,
        )

        best_digit = None
        best_conf = -1.0
        for text, conf in zip(data["text"], data["conf"]):
            text = text.strip()
            try:
                confidence = float(conf)
            except (TypeError, ValueError):
                continue

            if text in "123456789" and confidence > best_conf:
                best_digit = int(text)
                best_conf = confidence

        result = (best_digit, best_conf)
        with self._cache_lock:
            self._digit_read_cache[cache_key] = result
            if len(self._digit_read_cache) > self.OCR_CACHE_LIMIT:
                self._digit_read_cache.popitem(last=False)
        return result

    def _collect_variant_votes(self, variant, variant_index):
        config_specs = (
            ("primary", self.primary_config, 40.0),
            ("fallback", self.fallback_config, 40.0),
            ("layout", self.layout_config, self.layout_vote_threshold),
        )

        votes = defaultdict(list)
        best_digit = 0
        best_conf = -1.0
        for source, config, min_conf in config_specs:
            digit, confidence = self._read_digit(variant, config)
            if digit is None or confidence < min_conf:
                continue
            votes[digit].append((confidence, variant_index, source))
            if confidence > best_conf:
                best_conf = confidence
                best_digit = digit
        return votes, best_digit, best_conf

    def _rank_votes(self, votes):
        ranked = []
        for digit, records in votes.items():
            confidences = [confidence for confidence, _variant_index, _source in records]
            variant_count = len({variant_index for _confidence, variant_index, _source in records})
            config_count = len({source for _confidence, _variant_index, source in records})
            vote_count = len(records)
            average_conf = sum(confidences) / vote_count
            best_conf = max(confidences)
            ranked.append(
                {
                    "digit": digit,
                    "variant_count": variant_count,
                    "config_count": config_count,
                    "vote_count": vote_count,
                    "average_conf": average_conf,
                    "best_conf": best_conf,
                    "rank": (variant_count, config_count, vote_count, average_conf, best_conf),
                }
            )
        ranked.sort(key=lambda item: item["rank"], reverse=True)
        return ranked

    def _template_similarity(self, candidate, sample):
        candidate_f = candidate.astype(np.float32).reshape(-1) / 255.0
        sample_f = sample.astype(np.float32).reshape(-1) / 255.0

        corr = np.corrcoef(candidate_f, sample_f)[0, 1]
        if np.isnan(corr):
            corr = -1.0

        candidate_blur = cv2.GaussianBlur(candidate, (5, 5), 0)
        sample_blur = cv2.GaussianBlur(sample, (5, 5), 0)
        blur_corr = np.corrcoef(
            candidate_blur.astype(np.float32).reshape(-1) / 255.0,
            sample_blur.astype(np.float32).reshape(-1) / 255.0,
        )[0, 1]
        if np.isnan(blur_corr):
            blur_corr = -1.0

        overlap = np.logical_and(candidate > 0, sample > 0).sum()
        union = np.logical_or(candidate > 0, sample > 0).sum()
        iou = overlap / max(union, 1)

        return 0.60 * corr + 0.25 * blur_corr + 0.15 * iou

    def _shape_hint_six_nine(self, candidate):
        if candidate is None or candidate.size == 0:
            return 0

        contours, hierarchy = cv2.findContours(candidate, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        if hierarchy is None:
            return 0

        height, width = candidate.shape[:2]
        hole_candidates = []
        for contour, info in zip(contours, hierarchy[0]):
            if info[3] == -1:
                continue
            area = cv2.contourArea(contour)
            if area < candidate.size * 0.03:
                continue
            moments = cv2.moments(contour)
            if moments["m00"] == 0:
                continue
            center_x = moments["m10"] / moments["m00"]
            center_y = moments["m01"] / moments["m00"]
            hole_candidates.append((area, center_x / max(width, 1), center_y / max(height, 1)))

        if not hole_candidates:
            return 0

        hole_candidates.sort(reverse=True)
        _area, center_x, center_y = hole_candidates[0]
        if not 0.24 <= center_x <= 0.76:
            return 0
        if center_y <= 0.48:
            return 9
        if center_y >= 0.52:
            return 6
        return 0

    def _shape_looks_like_one(self, candidate):
        if candidate is None or candidate.size == 0:
            return False

        ys, xs = np.where(candidate > 0)
        if len(xs) == 0:
            return False

        left, right = int(xs.min()), int(xs.max())
        top, bottom = int(ys.min()), int(ys.max())
        width = right - left + 1
        height = bottom - top + 1
        if height < candidate.shape[0] * 0.45:
            return False

        ratio = width / max(height, 1)
        if ratio > 0.68:
            return False

        digit_roi = candidate[top:bottom + 1, left:right + 1]
        if digit_roi.size == 0:
            return False

        vertical_projection = np.count_nonzero(digit_roi, axis=0) / max(height, 1)
        strong_columns = np.count_nonzero(vertical_projection >= 0.80)
        return strong_columns >= max(2, int(width * 0.18))

    def _finalize_digit_result(self, digit, variant, confidence):
        if digit in {4, 7} and variant is not None and self._shape_looks_like_one(variant):
            digit = 1
        if digit in {6, 9} and variant is not None:
            shape_hint = self._shape_hint_six_nine(variant)
            if shape_hint in {6, 9}:
                digit = shape_hint
        return digit, variant, confidence

    def _recognize_cell_slow(self, gray_sources):
        variants, is_empty = self._build_cell_variants(gray_sources, variant_limit=6)
        if is_empty or not variants:
            return 0, None, -1.0

        primary_variant = variants[0]
        votes, best_digit, best_conf = self._collect_variant_votes(primary_variant, 0)
        primary_ranked = self._rank_votes(votes)

        # Fast path: only trust the first candidate when every OCR mode agrees,
        # or when a single strong result stands alone.
        if len(primary_ranked) == 1:
            top = primary_ranked[0]
            if top["config_count"] >= 2 and top["average_conf"] >= 70:
                return self._finalize_digit_result(top["digit"], primary_variant, top["best_conf"])
            if top["best_conf"] >= 92 and len(variants) == 1:
                return self._finalize_digit_result(top["digit"], primary_variant, top["best_conf"])

        # Ambiguous cells expand to the remaining variants instead of letting the
        # first OCR result decide on its own.
        for variant_index, variant in enumerate(variants[1:], start=1):
            variant_votes, variant_best_digit, variant_best_conf = self._collect_variant_votes(variant, variant_index)
            for digit, records in variant_votes.items():
                votes[digit].extend(records)
            if variant_best_conf > best_conf:
                best_conf = variant_best_conf
                best_digit = variant_best_digit

        if not votes:
            return 0, primary_variant, best_conf

        ranked = self._rank_votes(votes)
        top = ranked[0]
        for candidate in ranked[1:]:
            if (
                candidate["config_count"] > top["config_count"]
                and candidate["vote_count"] >= top["vote_count"]
                and candidate["average_conf"] >= top["average_conf"] + 10
                and candidate["best_conf"] >= top["best_conf"]
            ):
                top = candidate
                break
        runner_up = next((item for item in ranked if item is not top), None)

        if top["variant_count"] >= 2 and top["average_conf"] >= 60:
            return self._finalize_digit_result(top["digit"], primary_variant, top["best_conf"])

        if top["config_count"] >= 2 and top["average_conf"] >= 72:
            if runner_up is None or top["rank"] > runner_up["rank"]:
                return self._finalize_digit_result(top["digit"], primary_variant, top["best_conf"])

        if top["best_conf"] >= self.layout_conf_threshold:
            if runner_up is None or top["best_conf"] >= runner_up["best_conf"] + 12:
                return self._finalize_digit_result(top["digit"], primary_variant, top["best_conf"])

        if best_conf >= 42:
            return self._finalize_digit_result(best_digit, primary_variant, best_conf)
        return 0, primary_variant, best_conf

    def _recognize_cell(self, gray_sources):
        if not self._has_center_digit_stroke(gray_sources):
            return 0, None, -1.0

        variants, is_empty = self._build_cell_variants(gray_sources, variant_limit=1)
        if is_empty or not variants:
            return 0, None, -1.0

        primary_variant = variants[0]
        primary_digit, primary_conf = self._read_digit(primary_variant, self.primary_config)
        if primary_digit is not None:
            if primary_conf >= self.fast_single_conf_threshold:
                return self._finalize_digit_result(primary_digit, primary_variant, primary_conf)

            if primary_conf >= self.fast_primary_conf_threshold:
                confirm_digit, confirm_conf = self._read_digit(primary_variant, self.fallback_config)
                average_conf = (primary_conf + confirm_conf) / 2
                if (
                    confirm_digit == primary_digit
                    and confirm_conf >= self.fast_confirm_conf_threshold
                    and average_conf >= self.fast_average_conf_threshold
                ):
                    return self._finalize_digit_result(primary_digit, primary_variant, max(primary_conf, confirm_conf))

        return self._recognize_cell_slow(gray_sources)

    def _template_match_digit(self, candidate, templates):
        best_digit = 0
        best_score = -1.0
        runner_up = -1.0

        for digit, samples in templates.items():
            digit_score = -1.0
            for sample in samples:
                similarity = self._template_similarity(candidate, sample)
                if similarity > digit_score:
                    digit_score = similarity

            if digit_score > best_score:
                runner_up = best_score
                best_score = digit_score
                best_digit = digit
            elif digit_score > runner_up:
                runner_up = digit_score

        if best_score >= self.template_score_threshold and best_score - runner_up >= self.template_margin_threshold:
            best_digit, _variant, _confidence = self._finalize_digit_result(best_digit, candidate, 0.0)
            return best_digit
        return 0

    def _find_conflicting_cells(self, board):
        conflicts = set()

        def collect(unit_cells):
            positions_by_digit = defaultdict(list)
            for row, col in unit_cells:
                digit = board[row][col]
                if digit:
                    positions_by_digit[digit].append((row, col))
            for positions in positions_by_digit.values():
                if len(positions) > 1:
                    conflicts.update(positions)

        for index in range(BOARD_SIZE):
            collect((index, col) for col in range(BOARD_SIZE))
            collect((row, index) for row in range(BOARD_SIZE))

        for box_row in range(0, BOARD_SIZE, 3):
            for box_col in range(0, BOARD_SIZE, 3):
                collect(
                    (box_row + inner_row, box_col + inner_col)
                    for inner_row in range(3)
                    for inner_col in range(3)
                )

        return conflicts

    def _build_recognition_sources(self, gray, cleaned):
        variants_map = [[None for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        confidence_map = [[-1.0 for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        cell_sources_map = [[None for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        signal_map = [[0.0 for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        occupied_cells = []

        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                y1 = row * CELL_SIZE
                y2 = (row + 1) * CELL_SIZE
                x1 = col * CELL_SIZE
                x2 = (col + 1) * CELL_SIZE
                original_gray = gray[y1:y2, x1:x2]
                cleaned_cell = cleaned[y1:y2, x1:x2]
                blended_cell = cv2.addWeighted(original_gray, 0.35, cleaned_cell, 0.65, 0)
                gray_sources = (blended_cell, cleaned_cell, original_gray)
                cell_sources_map[row][col] = gray_sources
                signal_map[row][col] = self._cell_signal_strength(gray_sources)

                if not self._has_center_digit_stroke(gray_sources):
                    continue
                variants, is_empty = self._build_cell_variants(gray_sources, variant_limit=1)
                if is_empty or not variants:
                    continue
                variants_map[row][col] = variants[0]
                occupied_cells.append((row, col))

        return variants_map, confidence_map, cell_sources_map, signal_map, occupied_cells

    def _assign_layout_digit(self, board, confidence_map, templates, variants_map, row, col, digit, confidence):
        if not (0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE):
            return False
        variant = variants_map[row][col]
        if variant is None:
            return False
        digit, _variant, _confidence = self._finalize_digit_result(int(digit), variant, confidence)
        board[row][col] = digit
        confidence_map[row][col] = max(float(confidence), 70.0)
        templates[digit].append(variant)
        return True

    def _seed_digits_from_layout(self, cleaned, board, confidence_map, templates, variants_map, occupied_cells):
        try:
            data = pytesseract.image_to_data(
                cleaned,
                config=self.layout_config,
                output_type=Output.DICT,
            )
        except Exception:
            return 0

        occupied_by_row = defaultdict(list)
        for row, col in occupied_cells:
            occupied_by_row[row].append(col)
        for cols in occupied_by_row.values():
            cols.sort()

        seeded = 0
        for text, conf, left, top, width, height in zip(
            data["text"],
            data["conf"],
            data["left"],
            data["top"],
            data["width"],
            data["height"],
        ):
            digits = "".join(ch for ch in str(text).strip() if ch in "123456789")
            if not digits:
                continue
            try:
                confidence = float(conf)
            except (TypeError, ValueError):
                confidence = -1.0

            row = int((top + height / 2) // CELL_SIZE)
            if not 0 <= row < BOARD_SIZE:
                continue

            if len(digits) == 1:
                if confidence < 85:
                    continue
                col = int((left + width / 2) // CELL_SIZE)
                if 0 <= col < BOARD_SIZE and board[row][col] == 0 and self._assign_layout_digit(
                    board,
                    confidence_map,
                    templates,
                    variants_map,
                    row,
                    col,
                    digits,
                    confidence,
                ):
                    seeded += 1
                continue

            candidate_cols = []
            for col in occupied_by_row.get(row, []):
                center_x = col * CELL_SIZE + CELL_SIZE / 2
                if left - 8 <= center_x <= left + width + 8 and board[row][col] == 0:
                    candidate_cols.append(col)
            if len(candidate_cols) != len(digits):
                continue
            for col, digit in zip(candidate_cols, digits):
                if self._assign_layout_digit(
                    board,
                    confidence_map,
                    templates,
                    variants_map,
                    row,
                    col,
                    digit,
                    confidence,
                ):
                    seeded += 1
        return seeded

    def _match_cells_from_templates(self, board, confidence_map, templates, variants_map, occupied_cells):
        if not templates:
            return 0
        matched_count = 0
        for row, col in occupied_cells:
            if board[row][col] != 0:
                continue
            variant = variants_map[row][col]
            if variant is None:
                continue
            matched = self._template_match_digit(variant, templates)
            if not matched:
                continue
            board[row][col] = matched
            confidence_map[row][col] = 82.0
            templates[matched].append(variant)
            matched_count += 1
        return matched_count

    def _recognize_unresolved_cells(self, cell_sources_map, cells):
        def recognize_one(row, col):
            digit, variant, confidence = self._recognize_cell(cell_sources_map[row][col])
            return row, col, digit, variant, confidence

        if not cells:
            return []
        if self.ocr_workers <= 1 or len(cells) == 1:
            return [recognize_one(row, col) for row, col in cells]

        with ThreadPoolExecutor(max_workers=self.ocr_workers) as executor:
            futures = [executor.submit(recognize_one, row, col) for row, col in cells]
            return [future.result() for future in as_completed(futures)]

    def recognize_digits(self, warped_img, return_confidence=False):
        gray = cv2.cvtColor(warped_img, cv2.COLOR_BGR2GRAY)
        cleaned = self._remove_grid_lines(gray)
        board = [[0 for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        variants_map, confidence_map, cell_sources_map, signal_map, occupied_cells = self._build_recognition_sources(
            gray,
            cleaned,
        )

        templates = defaultdict(list)
        self._seed_digits_from_layout(cleaned, board, confidence_map, templates, variants_map, occupied_cells)
        self._match_cells_from_templates(board, confidence_map, templates, variants_map, occupied_cells)

        unresolved_cells = [(row, col) for row, col in occupied_cells if board[row][col] == 0]
        for row, col, digit, variant, confidence in self._recognize_unresolved_cells(cell_sources_map, unresolved_cells):
            if digit == 0:
                continue
            board[row][col] = digit
            variants_map[row][col] = variant
            confidence_map[row][col] = confidence
            if variant is not None:
                templates[digit].append(variant)

        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                if board[row][col] != 0:
                    continue
                if signal_map[row][col] < self.blank_rescue_signal_threshold:
                    continue
                digit, variant, confidence = self._recognize_cell_slow(cell_sources_map[row][col])
                if digit == 0:
                    continue
                board[row][col] = digit
                variants_map[row][col] = variant
                confidence_map[row][col] = confidence

        if templates:
            for row in range(BOARD_SIZE):
                for col in range(BOARD_SIZE):
                    if board[row][col] != 0:
                        continue
                    variant = variants_map[row][col]
                    if variant is None:
                        continue
                    matched = self._template_match_digit(variant, templates)
                    if matched:
                        board[row][col] = matched
                        confidence_map[row][col] = 82.0

        for row, col in self._find_conflicting_cells(board):
            digit, variant, confidence = self._recognize_cell_slow(cell_sources_map[row][col])
            board[row][col] = digit
            variants_map[row][col] = variant
            confidence_map[row][col] = confidence

        if return_confidence:
            return board, confidence_map
        return board

    def process(self, image_source):
        image = self._load_image(image_source)
        warped = self._warp_board(image)
        if warped is None:
            return None
        return self.recognize_digits(warped)

    def process_with_confidence(self, image_source):
        image = self._load_image(image_source)
        warped = self._warp_board(image)
        if warped is None:
            return None, None
        return self.recognize_digits(warped, return_confidence=True)

    def process_with_grid_bounds(self, image_source):
        image = self._load_image(image_source)
        result = self._warp_board_with_corners(image)
        if result is None:
            return None, None
        warped, corners = result
        return self.recognize_digits(warped), self._corners_to_bounds(corners)

    def process_with_grid_bounds_and_confidence(self, image_source):
        image = self._load_image(image_source)
        result = self._warp_board_with_corners(image)
        if result is None:
            return None, None, None
        warped, corners = result
        board, confidence_map = self.recognize_digits(warped, return_confidence=True)
        return board, self._corners_to_bounds(corners), confidence_map
