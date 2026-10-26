from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from chess_engine import ChessGame, Move


@dataclass
class GameNode:
    node_id: int = 0
    move: Optional[Move] = None
    san: str = ""
    color: str = ""
    ply: int = 0
    comment: str = ""
    nags: list[int] = field(default_factory=list)
    parent: Optional["GameNode"] = None
    children: list["GameNode"] = field(default_factory=list)

    @property
    def is_root(self) -> bool:
        return self.move is None


class GameTree:
    def __init__(self, start_fen: str = ChessGame.START_FEN) -> None:
        checker = ChessGame()
        if start_fen and start_fen != ChessGame.START_FEN:
            checker.load_fen(start_fen)
            self.start_fen = checker.to_fen()
        else:
            self.start_fen = ChessGame.START_FEN
        self.headers: dict[str, str] = {}
        self.result = ""
        self._next_id = 1
        self.root = self._make_node()
        self.current = self.root
        self._nodes: dict[int, GameNode] = {self.root.node_id: self.root}

    def _make_node(
        self,
        parent: Optional[GameNode] = None,
        move: Optional[Move] = None,
        san: str = "",
        color: str = "",
        ply: int = 0,
        comment: str = "",
        nags: Optional[list[int]] = None,
    ) -> GameNode:
        node = GameNode(
            node_id=self._next_id,
            move=move,
            san=san,
            color=color,
            ply=ply,
            comment=comment,
            nags=list(nags or []),
            parent=parent,
        )
        self._next_id += 1
        if not hasattr(self, "_nodes"):
            return node
        self._nodes[node.node_id] = node
        return node

    def _append(
        self,
        parent: GameNode,
        move: Move,
        san: str,
        color: str,
        make_mainline: bool,
        comment: str = "",
        nags: Optional[list[int]] = None,
    ) -> GameNode:
        node = self._make_node(
            parent=parent,
            move=move,
            san=san,
            color=color,
            ply=parent.ply + 1,
            comment=comment,
            nags=nags,
        )
        if make_mainline and parent.children:
            parent.children.insert(0, node)
        else:
            parent.children.append(node)
        return node

    def add_move(
        self,
        move: Move,
        san: str,
        color: str,
        make_mainline: bool = True,
        comment: str = "",
        nags: Optional[list[int]] = None,
    ) -> GameNode:
        node = self._append(
            self.current,
            move,
            san,
            color,
            make_mainline,
            comment,
            nags,
        )
        self.current = node
        return node

    def append_move(
        self,
        parent: GameNode,
        move: Move,
        san: str,
        color: str,
        comment: str = "",
        nags: Optional[list[int]] = None,
    ) -> GameNode:
        return self._append(
            parent, move, san, color, False, comment, nags
        )

    def path_to(self, node: Optional[GameNode] = None) -> list[GameNode]:
        node = node or self.current
        path: list[GameNode] = []
        while node is not None and node.parent is not None:
            path.append(node)
            node = node.parent
        path.reverse()
        return path

    def path_indices(self, node: Optional[GameNode] = None) -> list[int]:
        node = node or self.current
        indices: list[int] = []
        while node is not None and node.parent is not None:
            parent = node.parent
            try:
                indices.append(parent.children.index(node))
            except ValueError:
                break
            node = parent
        indices.reverse()
        return indices

    def build_game(self, node: Optional[GameNode] = None) -> ChessGame:
        node = node or self.current
        game = ChessGame()
        if self.start_fen != ChessGame.START_FEN:
            game.load_fen(self.start_fen)
        for item in self.path_to(node):
            if item.move is not None:
                game.make_move(item.move)
        return game

    def mainline(self) -> list[GameNode]:
        nodes: list[GameNode] = []
        node = self.root
        while node.children:
            node = node.children[0]
            nodes.append(node)
        return nodes

    def latest_node(self) -> GameNode:
        node = self.root
        while node.children:
            node = node.children[0]
        return node

    def tip_from(self, node: Optional[GameNode] = None) -> GameNode:
        node = node or self.current
        while node.children:
            node = node.children[0]
        return node

    def is_reviewing(self) -> bool:
        return bool(self.current.children)

    def node_by_id(self, node_id: int) -> Optional[GameNode]:
        return self._nodes.get(node_id)

    def truncate_after(self, node: GameNode) -> None:
        node.children.clear()
        self.current = node

    def move_number(self, node: GameNode) -> int:
        fields = self.start_fen.split()
        start_turn = fields[1] if len(fields) > 1 else "w"
        try:
            start_full = int(fields[5]) if len(fields) > 5 else 1
        except ValueError:
            start_full = 1
        before = max(0, node.ply - 1)
        return start_full + (
            before + (1 if start_turn == "b" else 0)
        ) // 2

    def to_dict(self) -> dict:
        def encode(node: GameNode) -> dict:
            return {
                "move": (
                    ChessGame.move_to_uci(node.move)
                    if node.move is not None
                    else ""
                ),
                "comment": node.comment,
                "nags": list(node.nags),
                "children": [encode(child) for child in node.children],
            }

        return {
            "start_fen": self.start_fen,
            "headers": dict(self.headers),
            "result": self.result,
            "root": encode(self.root),
            "current": self.path_indices(self.current),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GameTree":
        if not isinstance(data, dict):
            raise ValueError("棋谱树数据无效")
        start_fen = data.get("start_fen")
        if not isinstance(start_fen, str) or not start_fen.strip():
            start_fen = ChessGame.START_FEN
        tree = cls(start_fen)
        root_data = data.get("root")
        if not isinstance(root_data, dict):
            raise ValueError("棋谱树根节点无效")

        def decode(parent: GameNode, payload: dict) -> None:
            children = payload.get("children", [])
            if not isinstance(children, list):
                raise ValueError("棋谱树子节点无效")
            for child in children:
                if not isinstance(child, dict):
                    raise ValueError("棋谱树节点无效")
                uci = str(child.get("move") or "")
                game = tree.build_game(parent)
                move = game.find_move_by_uci(uci) if uci else None
                if move is None:
                    raise ValueError(f"无法恢复着法：{uci}")
                nags: list[int] = []
                raw_nags = child.get("nags", [])
                if isinstance(raw_nags, list):
                    for value in raw_nags:
                        if isinstance(value, int) and not isinstance(value, bool):
                            nags.append(value)
                node = tree.append_move(
                    parent,
                    move,
                    game.san_for_move(move),
                    game.turn,
                    comment=str(child.get("comment") or ""),
                    nags=nags,
                )
                decode(node, child)

        decode(tree.root, root_data)

        headers = data.get("headers")
        if isinstance(headers, dict):
            tree.headers = {
                str(key): str(value) for key, value in headers.items()
            }
        tree.result = str(data.get("result") or "")

        indices = data.get("current")
        node = tree.root
        if isinstance(indices, list):
            for index in indices:
                if not isinstance(index, int) or not (0 <= index < len(node.children)):
                    node = tree.root
                    break
                node = node.children[index]
        tree.current = node
        return tree
