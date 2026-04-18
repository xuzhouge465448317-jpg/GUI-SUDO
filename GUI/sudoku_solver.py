class SudokuSolver:
    ALL_DIGITS_MASK = 0x1FF

    def __init__(self, board):
        self.board = [row[:] for row in board]
        self.rows = [0] * 9
        self.cols = [0] * 9
        self.boxes = [0] * 9
        self.empty_cells = []
        self.solved = False
        self._init_constraints()

    def _init_constraints(self):
        for row in range(9):
            for col in range(9):
                value = self.board[row][col]
                if value != 0:
                    self._set_constraint(row, col, value)
                else:
                    self.empty_cells.append((row, col))

    def _set_constraint(self, row, col, value):
        mask = 1 << (value - 1)
        self.rows[row] |= mask
        self.cols[col] |= mask
        self.boxes[(row // 3) * 3 + (col // 3)] |= mask

    def _clear_constraint(self, row, col, value):
        mask = ~(1 << (value - 1))
        self.rows[row] &= mask
        self.cols[col] &= mask
        self.boxes[(row // 3) * 3 + (col // 3)] &= mask

    def _get_possible_mask(self, row, col):
        return ~(self.rows[row] | self.cols[col] | self.boxes[(row // 3) * 3 + (col // 3)]) & self.ALL_DIGITS_MASK

    def _prepare_search(self):
        self.empty_cells.sort(key=lambda item: self._get_possible_mask(item[0], item[1]).bit_count())

    def _select_next_cell(self, index):
        best_index = index
        best_mask = 0
        best_count = 10

        for candidate_index in range(index, len(self.empty_cells)):
            row, col = self.empty_cells[candidate_index]
            mask = self._get_possible_mask(row, col)
            count = mask.bit_count()
            if count < best_count:
                best_index = candidate_index
                best_mask = mask
                best_count = count
                if count <= 1:
                    break

        if best_index != index:
            self.empty_cells[index], self.empty_cells[best_index] = self.empty_cells[best_index], self.empty_cells[index]
        return best_index, best_mask

    def solve(self):
        if not self.empty_cells:
            return True
        self._prepare_search()
        self.solved = self._backtrack(0)
        return self.solved

    def _backtrack(self, index):
        if index == len(self.empty_cells):
            return True

        swapped_index, mask = self._select_next_cell(index)
        row, col = self.empty_cells[index]

        if mask == 0:
            if swapped_index != index:
                self.empty_cells[index], self.empty_cells[swapped_index] = self.empty_cells[swapped_index], self.empty_cells[index]
            return False

        while mask > 0:
            lowbit = mask & -mask
            value = lowbit.bit_length()
            self.board[row][col] = value
            self._set_constraint(row, col, value)

            if self._backtrack(index + 1):
                return True

            self.board[row][col] = 0
            self._clear_constraint(row, col, value)
            mask ^= lowbit

        if swapped_index != index:
            self.empty_cells[index], self.empty_cells[swapped_index] = self.empty_cells[swapped_index], self.empty_cells[index]
        return False

    def solve_with_uniqueness_check(self, max_solutions=20):
        self._prepare_search()
        solutions = []
        self._collect_solutions(0, solutions, max_solutions)
        if solutions:
            self.board = [row[:] for row in solutions[0]]
            self.solved = True
        else:
            self.solved = False
        return {
            "solved": bool(solutions),
            "solution_count": len(solutions),
            "is_unique": len(solutions) == 1,
            "solution": [row[:] for row in solutions[0]] if solutions else None,
            "solutions": [[row[:] for row in solution] for solution in solutions],
            "truncated": len(solutions) >= max_solutions,
        }

    def _collect_solutions(self, index, solutions, max_solutions):
        if len(solutions) >= max_solutions:
            return

        if index == len(self.empty_cells):
            solutions.append([row[:] for row in self.board])
            return

        swapped_index, mask = self._select_next_cell(index)
        row, col = self.empty_cells[index]

        if mask == 0:
            if swapped_index != index:
                self.empty_cells[index], self.empty_cells[swapped_index] = self.empty_cells[swapped_index], self.empty_cells[index]
            return

        while mask > 0 and len(solutions) < max_solutions:
            lowbit = mask & -mask
            value = lowbit.bit_length()
            self.board[row][col] = value
            self._set_constraint(row, col, value)
            self._collect_solutions(index + 1, solutions, max_solutions)
            self.board[row][col] = 0
            self._clear_constraint(row, col, value)
            mask ^= lowbit

        if swapped_index != index:
            self.empty_cells[index], self.empty_cells[swapped_index] = self.empty_cells[swapped_index], self.empty_cells[index]

    def get_board(self):
        return [row[:] for row in self.board]
