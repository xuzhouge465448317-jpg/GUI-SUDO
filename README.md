# 数独助手 GUI

`sudoku_gui.py` 是一个基于 Tkinter 的 Windows 桌面数独助手，支持截图/OCR 识别、自动求解、教学模式、坐标校准和自动填充。

## 功能概览

- 截图识别：按 `F2` 自动隐藏窗口、截屏并识别屏幕中的数独九宫格。
- 图片导入：支持 `PNG`、`JPG`、`BMP`、`GIF`、`WEBP`、`TIFF` 等图片格式。
- 自动求解：识别或手动录入盘面后调用 `SudokuSolver` 求解，并检测无解或多解。
- 自动填充：基于校准坐标使用 `pyautogui` 点击空格并输入答案，按 `Esc` 可中止填充。
- 教学模式：按唯一候选数、唯一位置等策略生成可解释步骤，支持上一步、下一步和自动播放。
- 提示一步：对当前盘面给出一个可填数字及理由。
- 题目生成：可生成简单、中等、困难、专家难度的数独题目。
- 历史与分享：保存历史题目、载入历史记录、复制盘面和答案。
- 外观设置：支持浅色/深色主题、主配色、窗口透明度、按钮模式、置顶窗口。

## 目录结构

```text
GUI/
├── sudoku_gui.py              # 主界面和业务编排入口
├── sudoku_solver.py           # 数独求解器和唯一解检测
├── sudoku_ocr.py              # OpenCV + Tesseract OCR 识别
├── sudoku_filler.py           # 坐标校准和自动填充
├── screenshot_selector.py     # 手动框选截图区域
├── assets/                    # 程序图标
├── logs/                      # 运行日志目录
├── test_sudoku_gui_settings.py
├── test_sudoku_ocr.py
└── test_sudoku_teaching.py
```

## 环境要求

- Python 3.9+
- Windows 推荐使用：全局 `F2` 热键、窗口激活和自动填充依赖 Windows API。
- Tesseract OCR：需要安装 `tesseract.exe` 并加入 `PATH`，或放在程序可发现的位置。

Python 依赖：

```powershell
pip install pyautogui pillow opencv-python numpy pytesseract pytest
```

可选依赖：

```powershell
pip install tkinterdnd2
```

`tkinterdnd2` 仅用于增强拖拽导入；未安装时程序仍可通过按钮导入图片。

## 运行

在项目目录执行：

```powershell
cd F:\datacode\GUI
python .\sudoku_gui.py
```

如果 Tesseract 不在 `PATH` 中，程序还会尝试查找以下位置：

- `GUI\tesseract\tesseract.exe`
- `D:\software\Tools\tesseract\tesseract.exe`
- `C:\Program Files\Tesseract-OCR\tesseract.exe`
- `C:\Program Files (x86)\Tesseract-OCR\tesseract.exe`

## 使用流程

1. 识别盘面：按 `F2` 截图识别，或点击“导入图片”选择本地图片。
2. 校对盘面：黄色格表示 OCR 低置信度，红色格表示行、列或宫内存在冲突。
3. 求解：点击“一键求解”或按 `Ctrl+Enter`。
4. 自动填充：使用“校准坐标”记录目标网页/程序中的九宫格位置，然后点击“自动填充”。
5. 教学：点击“教学模式”查看分步讲解，或点击“提示一步”获得当前盘面的一步提示。

## 快捷键

| 快捷键 | 功能 |
| --- | --- |
| `F2` | 自动截图识别 |
| `Esc` | 取消识别或中止自动填充 |
| `Ctrl+O` | 导入图片 |
| `Ctrl+Enter` | 一键求解 |
| `Ctrl+Backspace` | 清空重置 |
| `Ctrl+G` | 生成题目 |
| `Ctrl+H` | 打开历史记录 |
| `Ctrl+Shift+C` | 复制/分享当前盘面 |
| `Ctrl+I` | 提示一步 |
| `Ctrl+T` | 开始教学模式 |
| `Ctrl+Right` | 教学下一步 |
| `Ctrl+Left` | 教学上一步 |
| `Ctrl+Space` | 教学自动播放/暂停 |

## 测试

```powershell
cd F:\datacode\GUI
python -m pytest test_sudoku_teaching.py test_sudoku_ocr.py test_sudoku_gui_settings.py
```

部分 OCR 回归测试依赖本机临时截图文件；文件不存在时对应用例会自动跳过。

## 运行时文件

程序运行时会读写以下本地状态文件：

- `sudoku_gui_state.json`：界面布局、主题、透明度、设置状态。
- `sudoku_history.json`：历史题目和解题结果。
- `logs/sudoku_gui.log`：运行日志。

这些文件用于本机使用状态，不是程序核心源码。
