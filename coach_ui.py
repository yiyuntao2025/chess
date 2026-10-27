from __future__ import annotations

import hashlib
import threading
from typing import Optional

from PyQt6.QtCore import QSettings, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from coach_ai import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    env_api_key,
    stream_deepseek_coach,
)


KEYRING_SERVICE = "chess-pyqt-deepseek"
KEYRING_USER = "api_key"


def _keyring_get() -> str:
    try:
        import keyring
    except ImportError:
        return ""
    try:
        return (keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or "").strip()
    except Exception:
        return ""


def _keyring_set(value: str) -> bool:
    try:
        import keyring
    except ImportError:
        return False
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, value)
        return True
    except Exception:
        return False


def _keyring_delete() -> None:
    try:
        import keyring
    except ImportError:
        return
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:
        pass


def _format_eval(cp: Optional[int]) -> str:
    if cp is None:
        return "未知"
    return f"{cp / 100:+.2f}"


def _move_label(ply: int, san: str) -> str:
    number = (ply + 1) // 2
    side = "白" if ply % 2 == 1 else "黑"
    return f"{number}.{side} {san}"


class CoachConfigDialog(QDialog):
    def __init__(
        self,
        settings: QSettings,
        initial_key: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.api_key = ""
        self.base_url = str(
            settings.value("coach_base_url", DEFAULT_BASE_URL)
        )
        self.model = str(settings.value("coach_model", DEFAULT_MODEL))

        self.setWindowTitle("配置 DeepSeek")
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.key_edit = QLineEdit(initial_key)
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("留空则使用 DEEPSEEK_API_KEY 环境变量")
        form.addRow("API Key", self.key_edit)

        self.base_edit = QLineEdit(self.base_url)
        form.addRow("Base URL", self.base_edit)

        self.model_edit = QLineEdit(self.model)
        form.addRow("模型", self.model_edit)
        layout.addLayout(form)

        self.remember_check = QCheckBox("记住 API Key")
        self.remember_check.setChecked(
            bool(settings.value("coach_remember_key", 0))
            and bool(initial_key)
        )
        layout.addWidget(self.remember_check)

        warning = QLabel(
            "勾选后优先保存到系统凭据管理器（Windows Credential Manager）。"
            "如果系统凭据管理器不可用，会退回到本地 QSettings 明文保存。"
            "不希望保存时保持未勾选，仅本次运行使用。"
        )
        warning.setWordWrap(True)
        warning.setObjectName("HintLabel")
        layout.addWidget(warning)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        cancel_button = buttons.button(
            QDialogButtonBox.StandardButton.Cancel
        )
        if save_button is not None:
            save_button.setText("保存")
        if cancel_button is not None:
            cancel_button.setText("取消")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setStyleSheet(
            """
            QDialog { background-color: #262421; }
            QLabel { color: #e8ddc7; font-size: 13px; }
            QLabel#HintLabel { color: #8d877d; font-size: 12px; }
            QLineEdit {
                background-color: #1d1b19;
                color: #e8ddc7;
                border: 1px solid #3d3933;
                border-radius: 4px;
                padding: 5px;
            }
            QCheckBox { color: #e8ddc7; font-size: 13px; }
            QPushButton {
                background-color: #3b3834;
                color: #f0e6d2;
                border: 1px solid #555049;
                border-radius: 5px;
                padding: 6px 14px;
            }
            """
        )

    def _save(self) -> None:
        self.api_key = self.key_edit.text().strip()
        self.base_url = (
            self.base_edit.text().strip() or DEFAULT_BASE_URL
        )
        self.model = self.model_edit.text().strip() or DEFAULT_MODEL
        remember = self.remember_check.isChecked()

        self.settings.setValue("coach_base_url", self.base_url)
        self.settings.setValue("coach_model", self.model)
        self.settings.setValue("coach_remember_key", int(remember))
        if remember and self.api_key:
            if _keyring_set(self.api_key):
                self.settings.remove("coach_api_key")
            else:
                self.settings.setValue("coach_api_key", self.api_key)
        else:
            _keyring_delete()
            self.settings.remove("coach_api_key")
        self.settings.sync()
        self.accept()


class CoachDialog(QDialog):
    resultReady = pyqtSignal(int, str, str)
    streamChunk = pyqtSignal(int, str)

    def __init__(
        self,
        settings: QSettings,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._session_key = ""
        self._token = 0
        self._busy = False
        self._pending_local = ""
        self._pending_cache_key = ""
        self._stream_text = ""
        self._cache: dict[str, str] = {}

        self.setWindowTitle("教练模式")
        self.setModal(False)
        self.setMinimumSize(620, 580)
        self.resize(680, 660)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        top_row = QHBoxLayout()
        self.config_button = QPushButton("配置 DeepSeek")
        self.config_button.clicked.connect(self._open_config)
        top_row.addWidget(self.config_button)
        self.status_label = QLabel("")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)
        top_row.addWidget(self.status_label, 1)
        root.addLayout(top_row)

        hint = QLabel(
            "教练会结合 Stockfish 的评估/标注和 DeepSeek 的文本分析，"
            "提供逐着点评、漏着解释和练习建议。"
            "生成 DeepSeek 报告时会发送棋谱、FEN、评估和标注，"
            "不包含本机文件或个人信息。"
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("复盘范围"))
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("全部对局", "all")
        self.scope_combo.addItem("开局（前 10 回合）", "opening")
        self.scope_combo.addItem("中局（11-40 回合）", "middlegame")
        self.scope_combo.addItem("残局（40 回合后）", "endgame")
        scope_row.addWidget(self.scope_combo, 1)
        root.addLayout(scope_row)

        action_row = QHBoxLayout()
        self.last_button = QPushButton("点评最后一手")
        self.full_button = QPushButton("复盘整局")
        self.copy_button = QPushButton("复制报告")
        self.clear_button = QPushButton("清空")
        self.last_button.clicked.connect(self._review_last_move)
        self.full_button.clicked.connect(self._review_full_game)
        self.copy_button.clicked.connect(self._copy_report)
        self.clear_button.clicked.connect(self._clear_report)
        for button in (
            self.last_button,
            self.full_button,
            self.copy_button,
            self.clear_button,
        ):
            action_row.addWidget(button)
        root.addLayout(action_row)

        self.report = QTextBrowser()
        self.report.setObjectName("CoachReport")
        self.report.setReadOnly(True)
        self.report.setOpenExternalLinks(False)
        self.report.setPlaceholderText(
            "点击“点评最后一手”或“复盘整局”开始。"
        )
        root.addWidget(self.report, 1)

        note = QLabel(
            "报告仅用于学习参考；深色/浅色标注来自本地 Stockfish 快速评估。"
        )
        note.setObjectName("HintLabel")
        note.setWordWrap(True)
        root.addWidget(note)

        self.resultReady.connect(self._on_result)
        self.streamChunk.connect(self._on_stream_chunk)
        self._update_status()
        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QDialog { background-color: #262421; }
            QLabel { color: #e8ddc7; font-size: 13px; }
            QLabel#HintLabel { color: #8d877d; font-size: 12px; }
            QLabel#StatusLabel { color: #d8b26a; font-size: 13px; }
            QTextBrowser#CoachReport {
                background-color: #1d1b19;
                color: #e8ddc7;
                border: 1px solid #3d3933;
                border-radius: 6px;
                padding: 10px;
                font-size: 13px;
            }
            QPushButton {
                background-color: #3b3834;
                color: #f0e6d2;
                border: 1px solid #555049;
                border-radius: 5px;
                padding: 6px 12px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #4a463f; }
            QPushButton:disabled { color: #77716a; border-color: #3a3732; }
            """
        )

    def _saved_key(self) -> str:
        stored = _keyring_get()
        if stored:
            return stored
        return str(self.settings.value("coach_api_key", "")).strip()

    def _base_url(self) -> str:
        return str(
            self.settings.value("coach_base_url", DEFAULT_BASE_URL)
        ).strip() or DEFAULT_BASE_URL

    def _model(self) -> str:
        return str(
            self.settings.value("coach_model", DEFAULT_MODEL)
        ).strip() or DEFAULT_MODEL

    def _effective_key(self) -> str:
        return self._session_key or self._saved_key() or env_api_key()

    def _update_status(self) -> None:
        saved_key = self._saved_key()
        key = self._session_key or saved_key or env_api_key()
        if key:
            if self._session_key:
                source = "本次会话"
            elif saved_key:
                source = "本地设置"
            else:
                source = "环境变量"
            self.status_label.setText(
                f"DeepSeek：已配置（{self._model()}，密钥来自{source}）"
            )
        else:
            self.status_label.setText(
                "DeepSeek：未配置。可只使用本地 Stockfish 摘要，"
                "或点击“配置 DeepSeek”。"
            )

    def _open_config(self) -> None:
        initial = self._session_key or self._saved_key()
        dialog = CoachConfigDialog(self.settings, initial, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._session_key = dialog.api_key
            self._update_status()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for button in (
            self.config_button,
            self.last_button,
            self.full_button,
            self.clear_button,
        ):
            button.setEnabled(not busy)
        if busy:
            self.status_label.setText("正在生成教练报告…")

    def _clear_report(self) -> None:
        self.report.clear()

    def _copy_report(self) -> None:
        text = self.report.toPlainText()
        if text:
            QApplication.clipboard().setText(text)

    def _coach_context(self) -> dict:
        parent = self.parent()
        if parent is not None and hasattr(parent, "coach_context"):
            return parent.coach_context()
        return {}

    def _review_last_move(self) -> None:
        if self._busy:
            return
        context = self._coach_context()
        history = context.get("history_sans", [])
        if not history:
            self.report.setMarkdown("还没有可点评的着法。")
            return
        local = self._local_last_move_report(context)
        prompt = self._last_move_prompt(context)
        self._start_request(prompt, local)

    def _review_full_game(self) -> None:
        if self._busy:
            return
        context = self._coach_context()
        if not context.get("sans"):
            self.report.setMarkdown("还没有可复盘的棋谱。")
            return
        local = self._local_full_report(context)
        prompt = self._full_game_prompt(context)
        self._start_request(prompt, local)

    def _start_request(self, prompt: str, local_report: str) -> None:
        key = self._effective_key()
        if not key:
            self._pending_local = ""
            self.report.setMarkdown(local_report)
            self.status_label.setText(
                "DeepSeek 未配置，已生成本地 Stockfish 摘要。"
            )
            return

        model = self._model()
        cache_key = hashlib.sha256(
            f"{model}|{prompt}".encode("utf-8")
        ).hexdigest()
        cached = self._cache.get(cache_key)
        if cached:
            self.report.setMarkdown(cached)
            self.status_label.setText("已使用缓存的教练报告。")
            return

        self._pending_local = local_report
        self._pending_cache_key = cache_key
        self._stream_text = ""
        self._token += 1
        token = self._token
        self._set_busy(True)
        self.report.setMarkdown("正在生成教练报告…")
        base_url = self._base_url()

        def worker() -> None:
            pieces: list[str] = []
            try:
                for chunk in stream_deepseek_coach(
                    prompt, key, base_url=base_url, model=model
                ):
                    if not chunk:
                        continue
                    pieces.append(chunk)
                    self.streamChunk.emit(token, chunk)
            except Exception as exc:
                self.resultReady.emit(
                    token,
                    "".join(pieces),
                    f"{type(exc).__name__}: {exc}",
                )
                return
            self.resultReady.emit(token, "".join(pieces), "")

        threading.Thread(target=worker, daemon=True).start()

    def _on_stream_chunk(self, token: int, chunk: str) -> None:
        if token != self._token or not self._busy:
            return
        self._stream_text += chunk
        self.report.setMarkdown(self._stream_text)
        scrollbar = self.report.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_result(self, token: int, text: str, error: str) -> None:
        if token != self._token:
            return
        self._set_busy(False)
        self._stream_text = ""
        if error:
            partial = text.strip()
            if partial:
                body = (
                    f"### DeepSeek 请求中断\n\n`{error}`\n\n"
                    f"{partial}\n\n---\n\n{self._pending_local}"
                )
            else:
                body = (
                    f"### DeepSeek 请求失败\n\n`{error}`\n\n"
                    f"---\n\n{self._pending_local}"
                )
            self.report.setMarkdown(body)
            self.status_label.setText("DeepSeek 请求失败，已显示本地摘要。")
        else:
            self.report.setMarkdown(text)
            if self._pending_cache_key and text:
                self._cache[self._pending_cache_key] = text
            self.status_label.setText("教练报告已生成。")
        self._pending_local = ""
        self._pending_cache_key = ""

    @staticmethod
    def _annotation_lines(
        context: dict,
        min_ply: int = 1,
        max_ply: int = 10**9,
    ) -> list[str]:
        sans = context.get("sans", [])
        annotations = context.get("annotations", {})
        evals = context.get("evals", {})
        lines: list[str] = []
        for ply in sorted(annotations):
            if not min_ply <= ply <= max_ply:
                continue
            if not 1 <= ply <= len(sans):
                continue
            san = sans[ply - 1]
            symbol = annotations[ply]
            value = _format_eval(evals.get(ply))
            lines.append(
                f"- {_move_label(ply, san)} {symbol}（评估 {value}）"
            )
        return lines

    def _scope_range(self) -> tuple[int, int, str]:
        key = self.scope_combo.currentData()
        if key == "opening":
            return 1, 20, "开局（前 10 回合）"
        if key == "middlegame":
            return 21, 80, "中局（11-40 回合）"
        if key == "endgame":
            return 81, 10**9, "残局（40 回合后）"
        return 1, 10**9, "全部对局"

    def _full_game_prompt(self, context: dict) -> str:
        min_ply, max_ply, scope_label = self._scope_range()
        annotations = self._annotation_lines(context, min_ply, max_ply)
        annotation_text = "\n".join(annotations) or "无"
        scope_rule = (
            ""
            if scope_label == "全部对局"
            else f"只重点点评“{scope_label}”范围内的着法，其他阶段可以略过。\n"
        )
        return (
            "请复盘下面这局国际象棋。\n\n"
            f"结果：{context.get('result') or '进行中'}\n"
            f"分析范围：{scope_label}\n\n"
            f"PGN：\n{context.get('pgn', '')}\n\n"
            "已有的 Stockfish 标注（评估为白方视角，单位兵）：\n"
            f"{annotation_text}\n\n"
            "要求：\n"
            "1. 按回合做简要逐着点评，优先解释被标注的失误/精彩着法；"
            "没有被标注的普通着法可以合并概括。\n"
            "2. 指出关键漏着、转折点和更好的候选着法。\n"
            "3. 给出 3 条具体、可执行的训练建议。\n"
            "4. 不要编造未提供的引擎评估；控制篇幅，条理清晰。\n"
            f"{scope_rule}"
        )

    def _last_move_prompt(self, context: dict) -> str:
        return (
            "请点评下面这局棋的最后一手。\n\n"
            f"最后一手：{context.get('last_san')}\n"
            f"Stockfish 标注：{context.get('last_annotation') or '无'}\n"
            f"走前评估（白方视角）：{_format_eval(context.get('eval_before'))}\n"
            f"走后评估（白方视角）：{_format_eval(context.get('eval_after'))}\n"
            f"当前 FEN：{context.get('current_fen')}\n\n"
            f"棋谱：{context.get('pgn', '')}\n\n"
            "要求：解释这步棋的意图、优点/问题；如果评估下降或标注为失误，"
            "说明漏着原因并给出更好的候选着法；最后给一条练习建议。"
            "不要编造未提供的评估。"
        )

    def _local_full_report(self, context: dict) -> str:
        annotations = self._annotation_lines(context)
        result = context.get("result") or "进行中"
        if annotations:
            annotation_text = "\n".join(annotations)
            advice = (
                "### 推荐练习\n"
                "- 逐着复盘上面列出的标注着法，先用自己计算候选着法，"
                "再用 Stockfish 验证。\n"
                "- 重点练习战术识别和计算深度，尤其是评估下降超过 "
                "0.5 兵的回合。\n"
                "- 下一局打开提示/评估，在关键分岔口停一下再落子。"
            )
        else:
            annotation_text = "本局暂无可用的 Stockfish 标注。"
            advice = (
                "### 推荐练习\n"
                "- 打开提示/评估走完一局，让软件记录关键失误。\n"
                "- 练习战术题和残局基本功。\n"
                "- 配置 DeepSeek API 后可获得逐着文字讲解。"
            )
        return (
            f"## 本地教练摘要\n\n结果：**{result}**\n\n"
            f"### Stockfish 标注\n{annotation_text}\n\n{advice}\n\n"
            "> 这是本地摘要。配置 DeepSeek API 后可生成更详细的逐着点评。"
        )

    def _local_last_move_report(self, context: dict) -> str:
        eval_before = context.get("eval_before")
        eval_after = context.get("eval_after")
        symbol = context.get("last_annotation") or "无"
        return (
            "## 本地教练摘要\n\n"
            f"最后一手：**{context.get('last_san')}**\n\n"
            f"Stockfish 标注：**{symbol}**\n\n"
            f"走前评估（白方视角）：{_format_eval(eval_before)}\n\n"
            f"走后评估（白方视角）：{_format_eval(eval_after)}\n\n"
            "建议：把这步棋和更好的候选着法放在一起对比，"
            "先独立计算一遍再用引擎验证。\n\n"
            "> 配置 DeepSeek API 后可获得针对这步棋的详细解释和练习建议。"
        )

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
