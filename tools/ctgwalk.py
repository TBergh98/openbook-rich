"""Stage 3: walk the whole book tree from the initial position.

For every CTG entry reachable by legal book moves it records the real
position (Polyglot key, side to move, mirroring) and every book move with
its real coordinates. Output (little-endian, fixed size):

  nodes.bin : per visited entry  <Q key, I page, H slot, H moves_off, B flags, 7x pad>  (24 B)
              flags bit0 = black to move, bit1 = board mirrored by the CTG rule
  moves.bin : per book move      <I parent_id, H pg_move, B code, B annot, i child_id, B status, 3x pad> (16 B)
              child_id = id of the child node or -1; status 0 ok, 1 undecodable,
              2 illegal, 3 child not in book
  aliases.bin: <Q key, I node_id> when an entry is reached as a second, different real position
  walk_stats.json

The node id of an entry is assigned at first visit (DFS order).
"""
import array
import json
import struct
import sys
import time

import chess
import chess.polyglot

from ctglib import CtgBook, normalise, decode_move

SLOTS = 128


def pg_move(board, mv):
    """Polyglot 16-bit move encoding (castling as king-takes-rook)."""
    frm, to = mv.from_square, mv.to_square
    if board.is_castling(mv):
        to = chess.square(7 if chess.square_file(to) > chess.square_file(frm) else 0,
                          chess.square_rank(frm))
    promo = {None: 0, chess.KNIGHT: 1, chess.BISHOP: 2, chess.ROOK: 3, chess.QUEEN: 4}[mv.promotion]
    return (promo << 12) | (chess.square_rank(frm) << 9) | (chess.square_file(frm) << 6) | \
        (chess.square_rank(to) << 3) | chess.square_file(to)


def main():
    book = CtgBook(sys.argv[1])
    outdir = sys.argv[2]
    node_of = array.array('i', [-1]) * (book.npages * SLOTS)
    key_of = {}  # node id -> key only for alias detection (stored compactly below)
    node_key = array.array('Q')
    fn = open(f"{outdir}/nodes.bin", "wb")
    fm = open(f"{outdir}/moves.bin", "wb")
    fa = open(f"{outdir}/aliases.bin", "wb")
    st = {"nodes": 0, "moves": 0, "undecodable": 0, "illegal": 0, "child_missing": 0,
          "aliases": 0, "max_depth": 0, "transpositions": 0}
    t0 = time.time()
    NODE = struct.Struct("<QIHHB7x")
    MOVE = struct.Struct("<IHBBiB3x")

    def visit(board):
        """Return node id for board (creating it), or -1 if not in book.
        Second value: True if newly created (needs expansion)."""
        pos, inv, flip, bb = normalise(board)
        r = book.lookup(pos)
        if r is None:
            return -1, False, None
        pg, off, slot = r
        idx = pg * SLOTS + slot
        key = chess.polyglot.zobrist_hash(board)
        nid = node_of[idx]
        if nid >= 0:
            if node_key[nid] != key:
                st["aliases"] += 1
                fa.write(struct.pack("<QI", key, nid))
            else:
                st["transpositions"] += 1
            return nid, False, None
        nid = st["nodes"]
        st["nodes"] += 1
        node_of[idx] = nid
        node_key.append(key)
        fn.write(NODE.pack(key, pg, slot, off, (1 if inv else 0) | (2 if flip else 0)))
        return nid, True, (pg, off, inv, flip, bb)

    root = chess.Board()
    nid, new, info = visit(root)
    stack = [(nid, info, None)]  # (node id, info, move pushed to get here)
    board = root
    # Iterative DFS: each frame expands all moves of a node.
    frames = []

    def expand(nid, info):
        pg, off, inv, flip, bb = info
        page = book.page(pg)
        children = []
        for i in range((page[off] - 1) // 2):
            code, an = page[off + 1 + 2 * i], page[off + 2 + 2 * i]
            st["moves"] += 1
            mv = decode_move(bb, inv, flip, code)
            if mv is None:
                st["undecodable"] += 1
                fm.write(MOVE.pack(nid, 0, code, an, -1, 1))
                continue
            if not board.is_legal(mv):
                st["illegal"] += 1
                fm.write(MOVE.pack(nid, 0, code, an, -1, 2))
                continue
            pm = pg_move(board, mv)
            board.push(mv)
            cid, cnew, cinfo = visit(board)
            board.pop()
            if cid < 0:
                st["child_missing"] += 1
                fm.write(MOVE.pack(nid, pm, code, an, -1, 3))
                continue
            fm.write(MOVE.pack(nid, pm, code, an, cid, 0))
            if cnew:
                children.append((mv, cid, cinfo))
        return children

    frames.append(iter(expand(nid, info)))
    depth = 0
    while frames:
        try:
            mv, cid, cinfo = next(frames[-1])
        except StopIteration:
            frames.pop()
            if frames:
                board.pop()
            continue
        board.push(mv)
        frames.append(iter(expand(cid, cinfo)))
        if len(frames) > st["max_depth"]:
            st["max_depth"] = len(frames)
        if st["nodes"] % 200000 < 1 and st["nodes"]:
            pass
        if st["moves"] % 500000 == 0:
            print(f"nodes {st['nodes']} moves {st['moves']} {time.time()-t0:.0f}s",
                  file=sys.stderr, flush=True)
    st["seconds"] = round(time.time() - t0)
    for f in (fn, fm, fa):
        f.close()
    with open(f"{outdir}/walk_stats.json", "w") as f:
        json.dump(st, f, indent=1)
    print(json.dumps(st, indent=1))


if __name__ == "__main__":
    main()
