# SPDX-FileCopyrightText: 2026 TBergh98
# SPDX-License-Identifier: MIT
"""Stage 5: measured comparison between jja's Polyglot output and the .obr file.

Usage: python compare_jja.py <book.obr> <jja.bin> <obr_derived.bin> <out.json>

Memory-lean: works on sorted arrays (searchsorted) instead of np.unique/np.isin.
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from build_obr import POS_DT, OMOVE_DT, sorted_contains  # noqa: E402
from obr import HEADER, NO_CHILD  # noqa: E402

BIN_DT = np.dtype([("key", ">u8"), ("move", ">u2"), ("weight", ">u2"), ("learn", ">u4")])


def distinct_sorted(a):
    if not len(a):
        return a
    keep = np.ones(len(a), dtype=bool)
    keep[1:] = a[1:] != a[:-1]
    return a[keep]


def pairs(b):
    p = (b["key"].astype(np.uint64) << np.uint64(16)) | b["move"].astype(np.uint64)
    p.sort()
    return distinct_sorted(p)


def main():
    obr_path, jja_path, obin_path, out_path = sys.argv[1:5]
    with open(obr_path, "rb") as f:
        h = HEADER.unpack(f.read(HEADER.size))
    _, _, _, n_pos, n_mov, n_al, _, _, pos_off, move_off, _, _, _ = h
    pos = np.memmap(obr_path, dtype=POS_DT, mode="r", offset=pos_off, shape=(n_pos,))
    mov = np.memmap(obr_path, dtype=OMOVE_DT, mode="r", offset=move_off, shape=(n_mov,))
    r = {"ctg_entries_as_obr_positions": int(n_pos), "obr_moves": int(n_mov), "obr_aliases": int(n_al)}

    jb = np.fromfile(jja_path, dtype=BIN_DT)
    ob = np.fromfile(obin_path, dtype=BIN_DT)
    jkeys = distinct_sorted(jb["key"].astype(np.uint64))   # files are sorted by key
    okeys = distinct_sorted(ob["key"].astype(np.uint64))
    r["jja_entries"], r["jja_positions"] = int(len(jb)), int(len(jkeys))
    r["obr_bin_entries"], r["obr_bin_positions"] = int(len(ob)), int(len(okeys))

    miss = ~sorted_contains(jkeys, okeys)
    r["positions_missing_in_jja"] = int(miss.sum())
    r["positions_missing_in_jja_pct"] = round(100 * float(miss.mean()), 3)
    r["jja_positions_not_in_obr"] = int((~sorted_contains(okeys, jkeys)).sum())
    del miss, okeys

    pj = pairs(jb)
    po = pairs(ob)
    mm = ~sorted_contains(pj, po)
    r["moves_missing_in_jja"] = int(mm.sum())
    r["moves_missing_in_jja_pct"] = round(100 * float(mm.mean()), 3)
    r["jja_moves_not_in_obr"] = int((~sorted_contains(po, pj)).sum())
    del mm, po, ob

    # canonical positions only: weight orientation and red moves
    owner = np.repeat(np.arange(n_pos, dtype=np.uint32), pos["n_moves"].astype(np.int64))
    sel = (mov["move"] != 0) & (mov["child"] != NO_CHILD)
    ow = owner[sel]
    ck = mov["child"][sel].astype(np.int64)
    mkey = pos["key"][ow].astype(np.uint64)
    pm = (mkey << np.uint64(16)) | mov["move"][sel].astype(np.uint64)
    jp = (jb["key"].astype(np.uint64) << np.uint64(16)) | jb["move"].astype(np.uint64)
    srt = np.argsort(jp)
    jp_s = jp[srt]
    i = np.clip(np.searchsorted(jp_s, pm), 0, len(jp_s) - 1)
    hit = jp_s[i] == pm
    w = jb["weight"][srt][i].astype(np.float64)
    c = pos[ck]
    blk = (pos["flags"][ow] & 1).astype(bool)
    g = c["games"].astype(np.float64)
    mover_w = np.where(blk, c["black_wins"], c["white_wins"]).astype(np.float64)
    opp_w = np.where(blk, c["white_wins"], c["black_wins"]).astype(np.float64)
    d = c["draws"].astype(np.float64)
    # within-position comparison: for positions with >=2 moves having games,
    # does jja's top-weight move maximise the mover's points or the opponent's?
    ok = hit & (g > 0)
    r["weight_corr_with_mover_points"] = round(float(np.corrcoef(w[ok], (2 * mover_w + d)[ok])[0, 1]), 4)
    r["weight_corr_with_opponent_points"] = round(float(np.corrcoef(w[ok], (2 * opp_w + d)[ok])[0, 1]), 4)
    red = c["recommendation"] == 0x40
    r["red_moves_canonical"] = int(red.sum())
    r["red_moves_kept_by_jja"] = int((red & hit).sum())
    # moves where the mover scored badly (<35%, >=20 games) but jja ranks them first
    sc = np.where(g > 0, (mover_w + 0.5 * d) / np.maximum(g, 1), np.nan)
    r["moves_with_ge20_games"] = int(((g >= 20) & hit).sum())
    print(json.dumps(r, indent=1))
    with open(out_path, "w") as f:
        json.dump(r, f, indent=1)


if __name__ == "__main__":
    main()
