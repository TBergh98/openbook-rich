# SPDX-FileCopyrightText: 2026 TBergh98
# SPDX-License-Identifier: GPL-3.0-or-later
"""Walk the book tree from the start position (bounded) and measure, for
child positions WITHOUT castling rights, how many are found in the book with
each flip rule. The rule that matches the book finds them; the wrong one doesn't."""
import sys
import random
import chess
from ctglib import CtgBook, normalise, decode_move

book = CtgBook(sys.argv[1])
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
random.seed(1)

stats = {m: {"nocastle_found": 0, "nocastle_missing": 0, "castle_found": 0, "castle_missing": 0}
         for m in ("mirror", "jja")}


def moves_of(board, mode):
    pos, inv, flip, bb = normalise(board, mode)
    r = book.lookup(pos)
    if not r:
        return None
    pg, off, _ = r
    page = book.page(pg)
    out = []
    for i in range((page[off] - 1) // 2):
        mv = decode_move(bb, inv, flip, page[off + 1 + 2 * i], mode)
        if mv and board.is_legal(mv):
            out.append(mv)
    return out


for mode in ("mirror", "jja"):
    nodes = 0
    # random deep walks, so that castling rights get lost
    while nodes < limit:
        b = chess.Board()
        for ply in range(60):
            mv = moves_of(b, mode)
            if not mv:
                break
            b.push(random.choice(mv))
            nodes += 1
            key = "castle" if b.castling_rights else "nocastle"
            found = book.lookup(normalise(b, mode)[0]) is not None
            stats[mode][key + ("_found" if found else "_missing")] += 1
print(stats)
