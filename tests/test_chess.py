from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chess_engine import ChessGame
from game_tree import GameTree
from pgn_export import build_pgn_tree
from pgn_import import PGNImportError, parse_pgn


class PerftMixin:
    def perft(self, game: ChessGame, depth: int) -> int:
        if depth == 0:
            return 1
        total = 0
        for move in game.all_legal_moves():
            game.make_move(move)
            total += self.perft(game, depth - 1)
            game.undo_move()
        return total


class EngineRulesTest(PerftMixin, unittest.TestCase):
    def test_perft_start_position(self) -> None:
        game = ChessGame()
        self.assertEqual(self.perft(game, 3), 8902)
        self.assertEqual(game.to_fen(), ChessGame.START_FEN)

    def test_perft_kiwipete(self) -> None:
        fen = (
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/"
            "PPPBBPPP/R3K2R w KQkq - 0 1"
        )
        game = ChessGame()
        game.load_fen(fen)
        self.assertEqual(self.perft(game, 2), 2039)
        self.assertEqual(game.to_fen(), fen)

    def test_make_and_undo_restores_position(self) -> None:
        game = ChessGame()
        for uci in ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6"):
            move = game.find_move_by_uci(uci)
            self.assertIsNotNone(move)
            game.make_move(move)
        fen = game.to_fen()
        san_history = list(game.san_history)
        self.assertEqual(
            san_history,
            ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"],
        )
        while game.history:
            game.undo_move()
        self.assertEqual(game.to_fen(), ChessGame.START_FEN)
        self.assertEqual(game.san_history, [])
        game.load_fen(fen)
        self.assertEqual(game.to_fen(), fen)

    def test_en_passant(self) -> None:
        fen = "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"
        game = ChessGame()
        game.load_fen(fen)
        move = game.find_move_by_uci("e5d6")
        self.assertIsNotNone(move)
        self.assertTrue(move.is_en_passant)
        game.make_move(move)
        self.assertIsNone(game.piece_at(3, 3))
        self.assertEqual(game.piece_at(2, 3), "P")
        self.assertEqual(game.captured_pieces(), (["p"], []))
        game.undo_move()
        self.assertEqual(game.to_fen(), fen)

    def test_promotion(self) -> None:
        game = ChessGame()
        game.load_fen("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
        move = game.find_move_by_uci("a7a8q")
        self.assertIsNotNone(move)
        game.make_move(move)
        self.assertEqual(game.piece_at(0, 0), "Q")
        self.assertEqual(game.san_history[-1], "a8=Q+")

    def test_castling(self) -> None:
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        game = ChessGame()
        game.load_fen(fen)
        move = game.find_move_by_uci("e1g1")
        self.assertIsNotNone(move)
        self.assertTrue(move.is_castle)
        game.make_move(move)
        self.assertEqual(game.piece_at(7, 6), "K")
        self.assertEqual(game.piece_at(7, 5), "R")
        self.assertNotIn("K", game.castling)
        self.assertNotIn("Q", game.castling)
        game.undo_move()
        self.assertEqual(game.to_fen(), fen)

    def test_san_disambiguation(self) -> None:
        game = ChessGame()
        game.load_fen("4k3/8/8/8/4K3/8/8/R6R w - - 0 1")
        move = game.find_move_by_uci("a1d1")
        self.assertIsNotNone(move)
        self.assertEqual(game.san_for_move(move), "Rad1")
        move = game.find_move_by_uci("h1d1")
        self.assertIsNotNone(move)
        self.assertEqual(game.san_for_move(move), "Rhd1")


class PgnAndTreeTest(unittest.TestCase):
    def test_pgn_round_trip(self) -> None:
        tree = GameTree()
        game = ChessGame()
        for uci in ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5"):
            move = game.find_move_by_uci(uci)
            self.assertIsNotNone(move)
            turn = game.turn
            game.make_move(move)
            tree.add_move(move, game.san_history[-1], turn)
        pgn = build_pgn_tree(tree, result="*")
        parsed = parse_pgn(pgn)
        self.assertEqual(
            [node.san for node in parsed.mainline()],
            ["e4", "e5", "Nf3", "Nc6", "Bb5"],
        )
        self.assertEqual(parsed.result, "*")

    def test_pgn_variation_tree_shape(self) -> None:
        pgn = "1. e4 e5 (1... c5 2. Nf3 {Sicilian} $1) 2. Nf3 Nc6 *"
        tree = parse_pgn(pgn)
        e4 = tree.root.children[0]
        self.assertEqual([child.san for child in e4.children], ["e5", "c5"])
        c5 = e4.children[1]
        variation_move = c5.children[0]
        self.assertEqual(variation_move.san, "Nf3")
        self.assertEqual(variation_move.comment, "Sicilian")
        self.assertEqual(variation_move.nags, [1])
        self.assertEqual(
            [node.san for node in tree.mainline()],
            ["e4", "e5", "Nf3", "Nc6"],
        )

    def test_tree_serialization_round_trip(self) -> None:
        pgn = "1. e4 e5 (1... c5 2. Nf3) 2. Nf3 Nc6 3. Bb5 *"
        tree = parse_pgn(pgn)
        tree.current = tree.mainline()[3]
        data = tree.to_dict()
        restored = GameTree.from_dict(data)
        self.assertEqual(
            [node.san for node in restored.mainline()],
            [node.san for node in tree.mainline()],
        )
        self.assertEqual(
            [node.san for node in restored.root.children[0].children],
            [node.san for node in tree.root.children[0].children],
        )
        self.assertEqual(
            restored.current.san,
            tree.current.san,
        )

    def test_long_game_serialization(self) -> None:
        tree = GameTree()
        game = ChessGame()
        cycle = ("g1f3", "g8f6", "f3g1", "f6g8")
        for _ in range(275):
            for uci in cycle:
                move = game.find_move_by_uci(uci)
                self.assertIsNotNone(move)
                turn = game.turn
                game.make_move(move)
                tree.add_move(move, game.san_history[-1], turn)
        self.assertGreater(len(tree.mainline()), 1000)
        restored = GameTree.from_dict(tree.to_dict())
        self.assertEqual(
            len(restored.mainline()),
            len(tree.mainline()),
        )

    def test_truncate_removes_orphan_nodes(self) -> None:
        pgn = "1. e4 e5 (1... c5 2. Nf3) 2. Nf3 *"
        tree = parse_pgn(pgn)
        first = tree.root.children[0]
        mainline = first.children[0]
        variation = first.children[1]
        removed = {mainline.node_id, variation.node_id, variation.children[0].node_id}
        self.assertIsNotNone(tree.node_by_id(variation.node_id))
        tree.truncate_after(first)
        for node_id in removed:
            self.assertIsNone(tree.node_by_id(node_id))
        self.assertEqual(first.children, [])

    def test_invalid_pgn_is_rejected(self) -> None:
        with self.assertRaises(PGNImportError):
            parse_pgn("1. e4 e5 ( 2. Nf3 *")


if __name__ == "__main__":
    unittest.main()
