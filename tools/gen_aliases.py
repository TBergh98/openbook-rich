# SPDX-FileCopyrightText: 2026 TBergh98
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 3b: alias keys.

CTG normalises every position (side to move shown as White; boards without
castling rights mirrored so the mover's king is on files e-h). So one CTG
entry answers for up to 4 real positions: the position, its colour-reversed
twin (python-chess Board.mirror()), and, without castling rights, the
horizontal mirrors of both. ChessBase returns the same entry for all of them.

For every walked node this computes the Polyglot keys of the other variants
and writes <Q key, I node_id, B transform, 3x pad> (16 B) to aliases_full.bin
transform bit0 = colours reversed, bit1 = files mirrored.
It also checks that the rebuilt board reproduces the node key exactly.

Usage: python gen_aliases.py <book.ctg> <walkdir> [workers]
"""
import multiprocessing as mp
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

PAGE = 4096
NODE_DT = np.dtype([("key", "<u8"), ("page", "<u4"), ("slot", "<u2"), ("off", "<u2"),
                    ("flags", "u1"), ("pad", "V7")])
OUT = struct.Struct("<QIB3x")


def work(args):
    import chess
    import chess.polyglot
    from ctglib import real_board
    from ctgscan import parse_page
    ctg_path, wd, pages, node_ids, slots, flags, keys, part = args
    out = bytearray()
    mismatch = 0
    sym = 0
    with open(ctg_path, "rb") as f:
        cur = -1
        entries = None
        for pg, nid, slot, fl, key in zip(pages, node_ids, slots, flags, keys):
            if pg != cur:
                f.seek((pg + 1) * PAGE)
                entries = parse_page(f.read(PAGE))[2]
                cur = pg
            b = real_board(entries[slot][0], fl)
            if chess.polyglot.zobrist_hash(b) != key:
                mismatch += 1
                continue
            variants = [(1, b.mirror())]
            if not b.castling_rights:
                h = b.transform(chess.flip_horizontal)
                variants += [(2, h), (3, h.mirror())]
            seen = {int(key)}
            for t, v in variants:
                k = chess.polyglot.zobrist_hash(v)
                if k in seen:
                    sym += 1
                    continue
                seen.add(k)
                out += OUT.pack(k, nid, t)
    fn = f"{wd}/aliases_part{part:03d}.bin"
    with open(fn, "wb") as g:
        g.write(out)
    return fn, mismatch, sym


def main():
    ctg_path, wd = sys.argv[1:3]
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else max(1, os.cpu_count() - 1)
    nodes = np.fromfile(f"{wd}/nodes.bin", dtype=NODE_DT)
    order = np.lexsort((nodes["slot"], nodes["page"]))
    ids = order.astype(np.uint32)
    chunks = np.array_split(np.arange(len(order)), workers * 8)
    jobs = []
    for i, c in enumerate(chunks):
        o = order[c]
        jobs.append((ctg_path, wd, nodes["page"][o].tolist(), ids[c].tolist(),
                     nodes["slot"][o].tolist(), nodes["flags"][o].tolist(),
                     nodes["key"][o].tolist(), i))
    tot_mis = tot_sym = 0
    parts = []
    with mp.Pool(workers) as pool:
        for k, (fn, mis, sym) in enumerate(pool.imap_unordered(work, jobs)):
            parts.append(fn)
            tot_mis += mis
            tot_sym += sym
            print(f"chunk {k + 1}/{len(jobs)} mismatches {tot_mis}", file=sys.stderr, flush=True)
    with open(f"{wd}/aliases_full.bin", "wb") as g:
        for fn in sorted(parts):
            with open(fn, "rb") as p:
                g.write(p.read())
            os.remove(fn)
    n = os.path.getsize(f"{wd}/aliases_full.bin") // OUT.size
    print(f"aliases {n} key_mismatches {tot_mis} symmetric_skipped {tot_sym}")


if __name__ == "__main__":
    main()
