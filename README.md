# 国际象棋 Chess

基于 PyQt6 的桌面国际象棋程序，中文界面，支持本地对战、Stockfish 人机/引擎互弈、局域网联机、变例复盘、PGN 棋谱、局面分析与 DeepSeek 教练。

## 功能

- 完整棋规：王车易位、吃过路兵、升变、将军/将死、逼和、子力不足、50/75 回合规则、三次/五次重复局面
- 双人对战、人机对战、引擎互弈
- 自动保存并恢复上次对局
- 可开关的全模式棋钟，支持局时与加秒
- FEN 查看、复制、粘贴和加载
- 变例树：回退后走新手会保留原线路，可在棋谱中点击切换
- 完整 PGN：FEN/SetUp、变例、注释、NAG 和常用标签
- Stockfish 常驻引擎、提示、MultiPV 候选着、棋盘箭头、评估曲线与准确率统计
- DeepSeek 教练：流式输出、报告缓存、开局/中局/残局范围选择、系统凭据管理器保存密钥
- 局域网联机：房间发现、WebSocket、聊天、棋钟、提和、认输、悔棋、暂停、再战、房间密码
- 联机对局中自动关闭引擎提示，降低作弊风险
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

勾选“记住 API Key”时，程序优先保存到系统凭据管理器（Windows Credential Manager）；如果不可用，则退回到本地 QSettings。生成 DeepSeek 报告时会发送棋谱、FEN、Stockfish 评估和标注，不包含本机文件或个人信息。

## 项目结构

| 文件 | 说明 |
| --- | --- |
| `main.py` | 程序入口 |
| `main_window.py` | 主窗口、模式/联机/分析/会话控制 |
| `board_widgets.py` | 棋盘、评估条、评估曲线、吃子显示 |
| `app_constants.py` | 主题、评估、颜色等常量 |
| `chess_engine.py` | 棋规引擎、FEN/SAN/UCI |
| `game_tree.py` | 变例树与序列化 |
| `stockfish_ai.py` | Stockfish 常驻引擎、MultiPV 与可取消分析 |
| `lan.py` / `lan_ui.py` | 局域网 WebSocket 联机与协议校验 |
| `chess_clock.py` | 棋钟 |
| `coach_ai.py` / `coach_ui.py` | DeepSeek 教练 |
| `fen_dialog.py` | FEN 局面对话框 |
| `pgn_import.py` / `pgn_export.py` | PGN 导入导出 |
| `session_store.py` | 自动保存/恢复 |
| `sound_player.py` | 音效 |

## 许可证

本项目代码采用 MIT License，见 `LICENSE`。

`stockfish/` 目录包含第三方 Stockfish 引擎及其源码，遵循 GPLv3，详见 `stockfish/Copying.txt`。
