# 国际象棋 Chess

基于 PyQt6 的桌面国际象棋程序，中文界面，支持本地对战、Stockfish 人机/引擎互弈、局域网联机、PGN 棋谱、局面分析与 DeepSeek 教练。

## 功能

- 完整棋规：王车易位、吃过路兵、升变、将军/将死、逼和、子力不足、50/75 回合规则、三次/五次重复局面
- 双人对战、人机对战、引擎互弈
- Stockfish 提示、局面评估、自动分析与走子标注
- 局域网联机：房间发现、WebSocket 连接、聊天、棋钟、提和、认输、悔棋
- PGN 导入/导出、棋谱回放、吃子统计
- DeepSeek 教练：结合 Stockfish 评估生成复盘报告
- 主题、坐标、音效、拖拽走子、走子动画

## 运行

需要 Python 3.10+。

```powershell
pip install -r requirements.txt
python main.py
```

Stockfish 默认从 `stockfish/` 目录查找，也可以通过环境变量 `STOCKFISH_PATH` 指定：

```powershell
$env:STOCKFISH_PATH = "C:\path\to\stockfish.exe"
```

DeepSeek 教练可通过界面配置 API Key，或设置环境变量：

```powershell
$env:DEEPSEEK_API_KEY = "your-api-key"
```

## 项目结构

| 文件 | 说明 |
| --- | --- |
| `main.py` | PyQt6 主窗口、棋盘绘制与交互 |
| `chess_engine.py` | 棋规引擎、FEN/SAN/UCI |
| `stockfish_ai.py` | Stockfish 常驻引擎与分析 |
| `lan.py` / `lan_ui.py` | 局域网 WebSocket 联机 |
| `chess_clock.py` | 棋钟 |
| `coach_ai.py` / `coach_ui.py` | DeepSeek 教练 |
| `pgn_import.py` / `pgn_export.py` | PGN 导入导出 |
| `sound_player.py` | 音效 |

## 许可证

本项目代码采用 MIT License，见 `LICENSE`。

`stockfish/` 目录包含第三方 Stockfish 引擎及其源码，遵循 GPLv3，详见 `stockfish/Copying.txt`。
