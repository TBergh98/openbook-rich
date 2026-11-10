"""OpenBook Rich (.obr) - reference reader and writer.

Specification: SPEC.md (same folder). Licence: MIT.

Reader usage (no dependencies beyond the standard library):
    with ObrBook("book.obr") as book:
        for m in book.moves(key): ...

CLI:
    python obr.py info  book.obr
    python obr.py probe book.obr "<FEN>"          (needs python-chess)
Polyglot export: python obr_tobin.py book.obr out.bin [--no-red]   (needs numpy)
"""
import json
import mmap
import struct
import sys

MAGIC = b"OBR1"
HEADER = struct.Struct("<4sHHIIIHHQQQQI4x")          # 64 bytes
POS = struct.Struct("<QIIIIIIIIIHBB")                # 48 bytes
MOVE = struct.Struct("<HBBI")                        # 8 bytes
ALIAS = struct.Struct("<QI")                         # 12 bytes
NO_CHILD = 0xFFFFFFFF

NAG_NAMES = {0: "", 1: "!", 2: "?", 3: "!!", 4: "??", 5: "!?", 6: "?!", 7: "forced", 8: "only"}
REC_NAMES = {0x00: "none", 0x40: "avoid", 0x80: "normal", 0xA4: "normal+"}


def move_colour(recommendation, nag):
    """Display colour of a move (SPEC section 9): from the child's
    recommendation byte and the move's NAG, as ChessBase shows it."""
    if recommendation == 0x40:
        return "red"
    if recommendation in (0x80, 0xA4):
        return "blue" if nag in (2, 4, 5, 6, 9) else "green"
    return "none"


class Position(tuple):
    __slots__ = ()
    fields = ("key", "games", "white_wins", "draws", "black_wins", "rating_games",
              "rating_sum", "perf_games", "perf_sum", "first_move", "n_moves",
              "recommendation", "flags")

    def __getattr__(self, name):
        return self[self.fields.index(name)]

    def as_dict(self):
        d = dict(zip(self.fields, self))
        d["avg_rating"] = round(self.rating_sum / self.rating_games) if self.rating_games else None
        d["performance"] = round(self.perf_sum / self.perf_games) if self.perf_games else None
        d["black_to_move"] = bool(self.flags & 1)
        return d


class ObrBook:
    def __init__(self, path):
        self.f = open(path, "rb")
        self.m = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_READ)
        (magic, self.version, hsize, self.n_pos, self.n_moves, self.n_alias, psize, msize,
         self.pos_off, self.move_off, self.alias_off, self.meta_off, self.meta_len) = \
            HEADER.unpack_from(self.m, 0)
        if magic != MAGIC or psize != POS.size or msize != MOVE.size:
            raise ValueError("not an OBR v1 file")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.m.close()
        self.f.close()

    @property
    def meta(self):
        return json.loads(self.m[self.meta_off:self.meta_off + self.meta_len])

    def position_at(self, i):
        return Position(POS.unpack_from(self.m, self.pos_off + i * POS.size))

    def _key_at(self, i, off, size):
        return struct.unpack_from("<Q", self.m, off + i * size)[0]

    def _bsearch(self, key, off, size, n):
        lo, hi = 0, n
        while lo < hi:
            mid = (lo + hi) // 2
            if self._key_at(mid, off, size) < key:
                lo = mid + 1
            else:
                hi = mid
        return lo if lo < n and self._key_at(lo, off, size) == key else -1

    def find(self, key):
        """(index, transform) of the record answering this Polyglot key, or (-1, 0).
        transform bit0: colours reversed, bit1: files mirrored (see SPEC 5)."""
        i = self._bsearch(key, self.pos_off, POS.size, self.n_pos)
        if i >= 0:
            return i, 0
        if self.n_alias:
            j = self._bsearch(key, self.alias_off, ALIAS.size, self.n_alias)
            if j >= 0:
                v = ALIAS.unpack_from(self.m, self.alias_off + j * ALIAS.size)[1]
                return v & 0x3FFFFFFF, v >> 30
        return -1, 0

    def position(self, i, t=0):
        """Position stats as seen through transform t."""
        d = self.position_at(i).as_dict()
        if t & 1:
            d["white_wins"], d["black_wins"] = d["black_wins"], d["white_wins"]
            d["black_to_move"] = not d["black_to_move"]
        return d

    def moves(self, key):
        """List of dicts: move (Polyglot 16-bit), nag, annotation_flags, child stats."""
        i, t = self.find(key)
        if i < 0:
            return []
        p = self.position_at(i)
        out = []
        for k in range(p.first_move, p.first_move + p.n_moves):
            mv, annot, status, child = MOVE.unpack_from(self.m, self.move_off + k * MOVE.size)
            d = {"move": transform_move(mv, t), "nag": annot & 0x1F,
                 "annotation_flags": annot & 0xE0, "status": status, "child": None}
            if child != NO_CHILD:
                d["child"] = self.position(child, t)
            out.append(d)
        return out


def transform_move(mv, t):
    """Apply an alias transform to a Polyglot move (bit0: flip ranks, bit1: flip files)."""
    if not t or not mv:
        return mv
    f, to = (mv >> 6) & 63, mv & 63
    if t & 1:
        f, to = f ^ 56, to ^ 56
    if t & 2:
        f, to = f ^ 7, to ^ 7
    return (mv & 0x7000) | (f << 6) | to


# ---------------------------------------------------------------- helpers

def pg_move_to_uci(mv):
    f, t = (mv >> 6) & 63, mv & 63
    promo = (mv >> 12) & 7
    s = "abcdefgh"[f & 7] + str(f // 8 + 1) + "abcdefgh"[t & 7] + str(t // 8 + 1)
    return s + ("", "n", "b", "r", "q")[promo] if promo else s


def pg_move_to_chess(board, mv):
    """Polyglot move -> legal python-chess Move (handles king-takes-rook castling)."""
    import chess
    uci = pg_move_to_uci(mv)
    m = chess.Move.from_uci(uci)
    for lm in board.legal_moves:
        if lm == m:
            return lm
        if board.is_castling(lm) and lm.from_square == m.from_square and \
                board.piece_type_at(m.to_square) == chess.ROOK and \
                (chess.square_file(lm.to_square) > chess.square_file(lm.from_square)) == \
                (chess.square_file(m.to_square) > chess.square_file(m.from_square)):
            return lm
    return None


def mover_score(child, black_moved):
    """Score (0..1) of the side that played the move, from the child position stats."""
    g = child["games"]
    if not g:
        return None
    w = child["black_wins"] if black_moved else child["white_wins"]
    return (w + 0.5 * child["draws"]) / g


def cli():
    cmd, path = sys.argv[1], sys.argv[2]
    with ObrBook(path) as b:
        if cmd == "info":
            meta = b.meta
            for k in ("exceptions", "unreached_raw", "unplayable_moves"):
                if k in meta:
                    meta[k] = f"<{len(meta[k])} items>"
            print(json.dumps({"positions": b.n_pos, "moves": b.n_moves, "aliases": b.n_alias,
                              "meta": meta}, indent=1))
        elif cmd == "probe":
            import chess
            import chess.polyglot
            board = chess.Board(sys.argv[3])
            key = chess.polyglot.zobrist_hash(board)
            i, t = b.find(key)
            if i < 0:
                print("position not in book")
                return
            d = b.position(i, t)
            d["via_alias_transform"] = t
            print(json.dumps(d))
            for m in b.moves(key):
                c = m["child"]
                san = pg_move_to_uci(m["move"])
                lm = pg_move_to_chess(board, m["move"])
                if lm is not None:
                    san = board.san(lm)
                if c:
                    sc = mover_score(c, board.turn == chess.BLACK)
                    print(f"{san:8} {NAG_NAMES.get(m['nag'], m['nag']):3} flags=0x{m['annotation_flags']:02x} "
                          f"{move_colour(c['recommendation'], m['nag']):6} "
                          f"games={c['games']:<8} +{c['white_wins']} ={c['draws']} -{c['black_wins']} "
                          f"score={sc:.3f} elo={c['avg_rating']} perf={c['performance']}")
                else:
                    print(f"{san:8} {NAG_NAMES.get(m['nag'], m['nag']):3} (no stats, status {m['status']})")
        else:
            print("commands: info, probe  (Polyglot export: obr_tobin.py)")


if __name__ == "__main__":
    cli()
