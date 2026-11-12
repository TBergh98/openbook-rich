# SPDX-FileCopyrightText: 2026 TBergh98
# SPDX-License-Identifier: MIT
"""Check that two .obr files are identical apart from the metadata fields
"generator" and "created" (and the header field meta_len that follows them).

Used to check ctg2obr.cpp against the Python pipeline.
Usage: python compare_obr.py a.obr b.obr      (exit code 0 = identical)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from obr import HEADER, POS, MOVE, ALIAS  # noqa: E402

CHUNK = 64 << 20
VOLATILE = ("generator", "created")


def main():
    pa, pb = sys.argv[1:3]
    with open(pa, "rb") as fa, open(pb, "rb") as fb:
        ha, hb = HEADER.unpack(fa.read(HEADER.size)), HEADER.unpack(fb.read(HEADER.size))
        names = ("magic", "version", "header_size", "n_pos", "n_moves", "n_alias", "pos_size",
                 "move_size", "pos_off", "move_off", "alias_off", "meta_off", "meta_len")
        bad = [f"{k}: {x} != {y}" for k, x, y in zip(names[:-1], ha, hb) if x != y]
        if bad:
            print("header differs:\n  " + "\n  ".join(bad))
            return 1
        meta_off = ha[11]
        tables = [("positions", ha[8], POS.size), ("moves", ha[9], MOVE.size), ("aliases", ha[10], ALIAS.size)]
        off = HEADER.size
        while off < meta_off:
            n = min(CHUNK, meta_off - off)
            a, b = fa.read(n), fb.read(n)
            if a != b:
                i = next(k for k in range(n) if a[k] != b[k]) + off
                name, start, size = [t for t in tables if t[1] <= i][-1]
                rec = (i - start) // size
                o = start + rec * size
                fa.seek(o)
                fb.seek(o)
                print(f"{name} record {rec} differs (byte {i}):\n  a {fa.read(size).hex()}\n  b {fb.read(size).hex()}")
                return 1
            off += n
        ma, mb = json.loads(fa.read(ha[12])), json.loads(fb.read(hb[12]))
    for k in VOLATILE:
        ma.pop(k, None)
        mb.pop(k, None)
    if ma != mb:
        for k in sorted(set(ma) | set(mb)):
            if ma.get(k) != mb.get(k):
                print(f"metadata '{k}' differs:\n  a {json.dumps(ma.get(k))[:500]}\n  b {json.dumps(mb.get(k))[:500]}")
        return 1
    print(f"identical: {ha[3]} positions, {ha[4]} moves, {ha[5]} aliases, metadata equal "
          f"(ignoring {', '.join(VOLATILE)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
