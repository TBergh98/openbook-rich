# SPDX-FileCopyrightText: 2026 TBergh98
# SPDX-License-Identifier: GPL-3.0-or-later
"""Quick checks: position codec round-trip on the first pages, and index
lookups from the initial position with both flip rules."""
import sys
import chess
from ctgscan import parse_page
from ctglib import CtgBook, decode_position, encode_position, normalise, decode_move

book = CtgBook(sys.argv[1])
npg = int(sys.argv[2]) if len(sys.argv) > 2 else 200
ok = bad = 0
examples = []
for pg in range(npg):
    _, _, entries, _ = parse_page(book.page(pg))
    for pos, moves, st in entries:
        bb, cb, ep = decode_position(pos)
        if encode_position(bb, cb, ep) == pos:
            ok += 1
        else:
            bad += 1
            if len(examples) < 3:
                examples.append((pos.hex(), encode_position(bb, cb, ep).hex()))
print(f"codec round-trip: ok={ok} bad={bad} {examples}")

b = chess.Board()
for mode in ("mirror", "jja"):
    pos, inv, flip, bb = normalise(b, mode)
    r = book.lookup(pos)
    print(mode, "start found:", r)
    if r:
        pg, off, slot = r
        page = book.page(pg)
        mlen = page[off]
        for i in range((mlen - 1) // 2):
            code, an = page[off + 1 + 2 * i], page[off + 2 + 2 * i]
            mv = decode_move(bb, inv, flip, code, mode)
            print("  ", mv, b.san(mv) if mv and b.is_legal(mv) else "ILLEGAL", hex(an))
