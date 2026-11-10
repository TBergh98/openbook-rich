"""Stage 4: build an OpenBook Rich (.obr) file from a CTG book + walk output.

Usage: python build_obr.py <book.ctg> <walkdir> <out.obr>

Every CTG entry field is either stored, or verified to be derivable (the
derivation rule goes in the metadata; any entry that breaks a rule is stored
verbatim in metadata "exceptions"). CTG entries not reachable from the
initial position are stored verbatim in the metadata ("unreached_raw").
"""
import configparser
import datetime
import json
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from obr import HEADER, MAGIC, POS, MOVE, NO_CHILD  # noqa: E402
from ctgscan import parse_page  # noqa: E402

PAGE = 4096
NODE_DT = np.dtype([("key", "<u8"), ("page", "<u4"), ("slot", "<u2"), ("off", "<u2"),
                    ("flags", "u1"), ("pad", "V7")])
MOVE_DT = np.dtype([("parent", "<u4"), ("pgmove", "<u2"), ("code", "u1"), ("annot", "u1"),
                    ("child", "<i4"), ("status", "u1"), ("pad", "V3")])
POS_DT = np.dtype([("key", "<u8"), ("games", "<u4"), ("white_wins", "<u4"), ("draws", "<u4"),
                   ("black_wins", "<u4"), ("rating_games", "<u4"), ("rating_sum", "<u4"),
                   ("perf_games", "<u4"), ("perf_sum", "<u4"), ("first_move", "<u4"),
                   ("n_moves", "<u2"), ("recommendation", "u1"), ("flags", "u1")])
OMOVE_DT = np.dtype([("move", "<u2"), ("annot", "u1"), ("status", "u1"), ("child", "<u4")])
assert POS_DT.itemsize == POS.size and OMOVE_DT.itemsize == MOVE.size


def sorted_contains(sorted_arr, values, chunk=5_000_000):
    """Boolean mask: values[i] in sorted_arr (sorted ascending). Low memory."""
    out = np.zeros(len(values), dtype=bool)
    if not len(sorted_arr):
        return out
    for s in range(0, len(values), chunk):
        v = values[s:s + chunk]
        i = np.searchsorted(sorted_arr, v)
        i[i >= len(sorted_arr)] = len(sorted_arr) - 1
        out[s:s + chunk] = sorted_arr[i] == v
    return out


def be(a, n):
    """Big-endian unsigned from an (N, n) uint8 array."""
    v = np.zeros(a.shape[0], dtype=np.uint64)
    for i in range(n):
        v = (v << np.uint64(8)) | a[:, i].astype(np.uint64)
    return v


def main():
    ctg_path, wd, out = sys.argv[1:4]
    ctg = np.memmap(ctg_path, dtype=np.uint8, mode="r")
    nodes = np.fromfile(f"{wd}/nodes.bin", dtype=NODE_DT)
    moves = np.fromfile(f"{wd}/moves.bin", dtype=MOVE_DT)
    aliases = np.fromfile(f"{wd}/aliases.bin", dtype=np.dtype([("key", "<u8"), ("node", "<u4")]))
    n = len(nodes)
    print(f"nodes {n} moves {len(moves)} aliases {len(aliases)}", flush=True)

    pos = np.zeros(n, dtype=POS_DT)
    pos["key"] = nodes["key"]
    exceptions = []
    CH = 2_000_000
    for s in range(0, n, CH):
        nd = nodes[s:s + CH]
        mo = (nd["page"].astype(np.int64) + 1) * PAGE + nd["off"]
        so = mo + ctg[mo].astype(np.int64)
        st = ctg[so[:, None] + np.arange(33)]
        total, a, b, d = be(st[:, 0:3], 3), be(st[:, 3:6], 3), be(st[:, 6:9], 3), be(st[:, 9:12], 3)
        score10 = be(st[:, 12:16], 4)
        blk = (nd["flags"] & 1).astype(bool)
        p = pos[s:s + CH]
        p["games"] = total
        p["white_wins"] = np.where(blk, b, a)
        p["black_wins"] = np.where(blk, a, b)
        p["draws"] = d
        p["rating_games"] = be(st[:, 16:19], 3)
        p["rating_sum"] = be(st[:, 19:23], 4)
        p["perf_games"] = be(st[:, 23:26], 3)
        p["perf_sum"] = be(st[:, 26:30], 4)
        p["recommendation"] = st[:, 30]
        p["flags"] = nd["flags"]
        # Derivation rules; anything breaking them is kept verbatim.
        bad = (total != a + b + d) | (score10 != 5 * (2 * a + d)) | (st[:, 31] != 0) | (st[:, 32] != 0)
        for i in np.nonzero(bad)[0]:
            exceptions.append({"key": int(nd["key"][i]), "stats_hex": bytes(st[i]).hex()})
        print(f"stats {s + len(nd)}/{n}, exceptions {len(exceptions)}", flush=True)

    # sort positions by key
    perm = np.argsort(pos["key"], kind="stable")
    inv = np.empty(n, dtype=np.uint32)
    inv[perm] = np.arange(n, dtype=np.uint32)
    pos = pos[perm]

    # moves grouped by (new) parent index, CTG order preserved inside a group
    mparent = inv[moves["parent"]]
    morder = np.argsort(mparent, kind="stable")
    moves = moves[morder]
    mparent = mparent[morder]
    om = np.zeros(len(moves), dtype=OMOVE_DT)
    om["move"] = moves["pgmove"]
    om["annot"] = moves["annot"]
    om["status"] = moves["status"]
    has = moves["child"] >= 0
    om["child"] = NO_CHILD
    om["child"][has] = inv[moves["child"][has]]
    first = np.searchsorted(mparent, np.arange(n, dtype=np.uint32), side="left")
    last = np.searchsorted(mparent, np.arange(n, dtype=np.uint32), side="right")
    pos["first_move"] = first
    pos["n_moves"] = last - first
    # raw CTG move codes of undecodable/illegal moves are kept in metadata
    raw_bad_moves = [{"parent_key": int(pos["key"][mparent[i]]), "ctg_code": int(moves["code"][i]),
                      "annot": int(moves["annot"][i]), "status": int(moves["status"][i])}
                     for i in np.nonzero(np.isin(moves["status"], [1, 2]))[0]]
    del moves, mparent, morder, has, first, last

    # Alias table: every other real position answered by the same CTG entry.
    # value = position_index | transform << 30 (bit0 colours reversed, bit1 files mirrored)
    full = np.fromfile(f"{wd}/aliases_full.bin",
                       dtype=np.dtype([("key", "<u8"), ("node", "<u4"), ("t", "u1"), ("pad", "V3")]))
    assert n < (1 << 30)
    al = np.zeros(len(full), dtype=np.dtype([("key", "<u8"), ("val", "<u4")]))
    al["key"] = full["key"]
    al["val"] = inv[full["node"]] | (full["t"].astype(np.uint32) << np.uint32(30))
    del full
    al = al[np.argsort(al["key"], kind="stable")]
    if len(al):
        keep = np.ones(len(al), dtype=bool)
        keep[1:] = al["key"][1:] != al["key"][:-1]
        al = al[keep]
        del keep
    # an alias key must never collide with a real position key (pos is sorted by key)
    clash = sorted_contains(pos["key"], al["key"])
    al = al[~clash]
    walk_alias_keys = np.unique(aliases["key"])
    walk_alias_covered = int(sorted_contains(al["key"], walk_alias_keys).sum())

    # unreached CTG entries, verbatim
    npages = int.from_bytes(bytes(ctg[16:20]), "big")
    visited = np.zeros(npages * 128, dtype=bool)
    visited[nodes["page"].astype(np.int64) * 128 + nodes["slot"]] = True
    pidx = (np.arange(npages, dtype=np.int64) + 1) * PAGE
    counts = (ctg[pidx].astype(np.int64) << 8) | ctg[pidx + 1]
    total_entries = int(counts.sum())
    nvis = visited.reshape(npages, 128).sum(axis=1)
    unreached = []
    for pg in np.nonzero(nvis != counts)[0].tolist():
        o = (pg + 1) * PAGE
        _, _, entries, _ = parse_page(bytes(ctg[o:o + PAGE]))
        for s, (p_, m_, st_) in enumerate(entries):
            if not visited[pg * 128 + s]:
                unreached.append((p_ + m_ + st_).hex())
        if pg % 100000 == 0:
            print(f"unreached scan page {pg}", flush=True)

    base = ctg_path[:-4]
    ini = {}
    if os.path.exists(base + ".ini"):
        cp = configparser.ConfigParser()
        cp.read(base + ".ini")
        ini = {s: dict(cp[s]) for s in cp.sections()}
    with open(base + ".ctb", "rb") as f:
        ctb_hdr = f.read(12).hex()
    with open(base + ".cto", "rb") as f:
        cto_hdr = f.read(16).hex()
    meta = {
        "format": "OpenBook Rich", "version": 1,
        "generator": "build_obr.py (reference implementation)",
        "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "source": {"type": "ctg", "file": os.path.basename(ctg_path), "ini": ini,
                   "ctg_header_hex": bytes(ctg[:32]).hex(), "ctb_header_hex": ctb_hdr,
                   "cto_header_hex": cto_hdr, "entries": total_entries},
        "derived_fields": {
            "ctg_score10": "5*(2*wins_side_to_move + draws)",
            "ctg_total": "white_wins + draws + black_wins",
            "ctg_byte31": 0, "ctg_byte32": 0},
        "exceptions": exceptions,
        "unreached_raw": unreached,
        "unplayable_moves": raw_bad_moves,
    }
    mb = json.dumps(meta, separators=(",", ":")).encode()

    pos_off = HEADER.size
    move_off = pos_off + pos.nbytes
    alias_off = move_off + om.nbytes
    meta_off = alias_off + al.nbytes
    with open(out, "wb") as f:
        f.write(HEADER.pack(MAGIC, 1, HEADER.size, n, len(om), len(al), POS.size, MOVE.size,
                            pos_off, move_off, alias_off, meta_off, len(mb)))
        pos.tofile(f)
        om.tofile(f)
        al.tofile(f)
        f.write(mb)
    print(json.dumps({"positions": n, "moves": len(om), "aliases": len(al),
                      "alias_key_clashes_dropped": int(clash.sum()),
                      "walk_aliases": len(walk_alias_keys), "walk_aliases_covered": walk_alias_covered,
                      "exceptions": len(exceptions), "unreached": len(unreached),
                      "unplayable_moves": len(raw_bad_moves), "ctg_entries": total_entries,
                      "bytes": os.path.getsize(out)}, indent=1))


if __name__ == "__main__":
    main()
