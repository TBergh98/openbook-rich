# SPDX-FileCopyrightText: 2026 TBergh98
# SPDX-License-Identifier: MIT
"""Derive a standard Polyglot .bin from an .obr file.

Weight of a move = points scored by the side that played it in the book games
(wins + draws/2, from the child position's statistics), scaled per position
so the best move gets at most 65535. Moves with no games get weight 1.
Alias positions (colour-reversed / mirrored twins) are included, as CTG lookups
answer them too. Learn field = 0.

Usage: python obr_tobin.py book.obr out.bin [--no-red] [--min-games N]
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from build_obr import POS_DT, OMOVE_DT  # noqa: E402
from obr import HEADER, NO_CHILD  # noqa: E402

BIN_DT = np.dtype([("key", ">u8"), ("move", ">u2"), ("weight", ">u2"), ("learn", ">u4")])
ALIAS_DT = np.dtype([("key", "<u8"), ("val", "<u4")])


def transform_moves(mv, t):
    mv = mv.astype(np.uint16)
    f = (mv >> 6) & 63
    to = mv & 63
    flip_r = (t & 1).astype(bool)
    flip_f = (t & 2).astype(bool)
    f = np.where(flip_r, f ^ 56, f)
    to = np.where(flip_r, to ^ 56, to)
    f = np.where(flip_f, f ^ 7, f)
    to = np.where(flip_f, to ^ 7, to)
    return ((mv & 0x7000) | (f << 6) | to).astype(np.uint16)


def main():
    src, out = sys.argv[1:3]
    no_red = "--no-red" in sys.argv
    min_games = int(sys.argv[sys.argv.index("--min-games") + 1]) if "--min-games" in sys.argv else 0
    with open(src, "rb") as f:
        h = HEADER.unpack(f.read(HEADER.size))
    _, _, _, n_pos, n_mov, n_al, _, _, pos_off, move_off, alias_off, _, _ = h
    pos = np.memmap(src, dtype=POS_DT, mode="r", offset=pos_off, shape=(n_pos,))
    mov = np.memmap(src, dtype=OMOVE_DT, mode="r", offset=move_off, shape=(n_mov,))
    al = np.memmap(src, dtype=ALIAS_DT, mode="r", offset=alias_off, shape=(n_al,)) if n_al else None

    owner = np.repeat(np.arange(n_pos, dtype=np.uint32), pos["n_moves"].astype(np.int64))
    child = mov["child"]
    ok = (mov["move"] != 0) & (child != NO_CHILD)
    c = pos[np.where(ok, child, 0).astype(np.int64)]
    black = (pos["flags"][owner] & 1).astype(bool)
    mover_w = np.where(black, c["black_wins"], c["white_wins"]).astype(np.float64)
    pts = mover_w + 0.5 * c["draws"].astype(np.float64)
    if no_red:
        ok &= c["recommendation"] != 0x40
    if min_games:
        ok &= c["games"] >= min_games
    pts[~ok] = -1
    # per-position scaling
    top = np.zeros(n_pos)
    np.maximum.at(top, owner, pts)
    scale = np.where(top > 65535, 65535 / np.maximum(top, 1), 1.0)
    w = np.clip(np.round(pts * scale[owner]), 1, 65535).astype(np.uint16)

    sel = np.nonzero(ok)[0]
    keys = [pos["key"][owner[sel]]]
    moves = [mov["move"][sel]]
    weights = [w[sel]]
    if al is not None:
        idx = (al["val"] & 0x3FFFFFFF).astype(np.int64)
        t = (al["val"] >> 30).astype(np.uint8)
        first = pos["first_move"][idx].astype(np.int64)
        cnt = pos["n_moves"][idx].astype(np.int64)
        rep = np.repeat(np.arange(len(idx)), cnt)
        mi = np.repeat(first, cnt) + (np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt))
        keep = ok[mi]
        rep, mi = rep[keep], mi[keep]
        keys.append(al["key"][rep])
        moves.append(transform_moves(mov["move"][mi], t[rep]))
        weights.append(w[mi])
    K = np.concatenate(keys)
    M = np.concatenate(moves)
    W = np.concatenate(weights)
    order = np.lexsort((-W.astype(np.int64), K))
    res = np.zeros(len(K), dtype=BIN_DT)
    res["key"] = K[order]
    res["move"] = M[order]
    res["weight"] = W[order]
    res.tofile(out)
    k = res["key"]
    npos = int((k[1:] != k[:-1]).sum()) + 1 if len(k) else 0
    print(f"wrote {len(res)} entries, {npos} positions to {out}")


if __name__ == "__main__":
    main()
