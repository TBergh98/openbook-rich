# SPDX-FileCopyrightText: 2026 TBergh98
# SPDX-License-Identifier: MIT
"""Stage 1: linear scan of every page of a CTG book.

Parses the page/entry structure without interpreting positions, checks that
each page is fully explained by (header + entries + tail), and gathers
statistics about every field, including the ones not understood yet.

Usage: python -I ctgscan.py <book.ctg> [max_pages]
"""
import collections
import json
import struct
import sys
import time

PAGE = 4096
STATS_LEN = 33


def u24(b, o):
    return (b[o] << 16) | (b[o + 1] << 8) | b[o + 2]


def u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def parse_page(page):
    """Return (n_entries, used, entries, tail) where entries are
    (pos_bytes, moves_bytes, stats_bytes). Raises ValueError on inconsistency."""
    n, used = struct.unpack_from(">HH", page, 0)
    p = 4
    entries = []
    for _ in range(n):
        hdr = page[p]
        plen = hdr & 0x1F
        if plen == 0:
            raise ValueError("zero position length")
        pos = page[p:p + plen]
        p += plen
        mlen = page[p]
        if mlen < 1 or (mlen - 1) % 2:
            raise ValueError(f"bad moves length {mlen}")
        moves = page[p:p + mlen]
        p += mlen
        stats = page[p:p + STATS_LEN]
        p += STATS_LEN
        if p > PAGE:
            raise ValueError("entry overruns page")
        entries.append((pos, moves, stats))
    return n, used, entries, p


def main():
    path = sys.argv[1]
    max_pages = int(sys.argv[2]) if len(sys.argv) > 2 else None
    c = collections.Counter
    cnt = {k: c() for k in [
        "pos_hdr_flags", "pos_len", "n_moves", "annot", "annot_low5", "annot_high3",
        "rec", "extra1", "comment", "unk4_zero", "used_vs_end", "tail_nonzero",
        "wdl_sum_eq_total", "move_code"]}
    unk4_samples = c()
    total_entries = 0
    max_total = 0
    bad_pages = []
    t0 = time.time()
    with open(path, "rb") as f:
        header = f.read(PAGE)
        npages = u32(header, 16)
        if max_pages:
            npages = min(npages, max_pages)
        for pg in range(npages):
            page = f.read(PAGE)
            if len(page) < PAGE:
                bad_pages.append((pg, "short read"))
                break
            try:
                n, used, entries, end = parse_page(page)
            except (ValueError, IndexError) as e:
                bad_pages.append((pg, str(e)))
                continue
            cnt["used_vs_end"][used - end] += 1
            cnt["tail_nonzero"][any(page[end:])] += 1
            total_entries += n
            for pos, moves, st in entries:
                cnt["pos_hdr_flags"][pos[0] & 0xE0] += 1
                cnt["pos_len"][len(pos)] += 1
                nm = (len(moves) - 1) // 2
                cnt["n_moves"][nm] += 1
                for i in range(nm):
                    mv, an = moves[1 + 2 * i], moves[2 + 2 * i]
                    cnt["move_code"][mv] += 1
                    cnt["annot"][an] += 1
                    cnt["annot_low5"][an & 0x1F] += 1
                    cnt["annot_high3"][an & 0xE0] += 1
                total = u24(st, 0)
                w, l, d = u24(st, 3), u24(st, 6), u24(st, 9)
                max_total = max(max_total, total)
                cnt["wdl_sum_eq_total"][w + l + d == total] += 1
                unk = u32(st, 12)
                cnt["unk4_zero"][unk == 0] += 1
                if len(unk4_samples) < 2000 or unk in unk4_samples:
                    unk4_samples[unk] += 1
                cnt["rec"][st[30]] += 1
                cnt["extra1"][st[31]] += 1
                cnt["comment"][st[32]] += 1
            if pg % 50000 == 0:
                print(f"page {pg}/{npages} entries {total_entries} {time.time()-t0:.0f}s",
                      file=sys.stderr, flush=True)
    out = {
        "header_hex": header[:32].hex(" "),
        "pages_scanned": npages,
        "total_entries": total_entries,
        "max_total_games": max_total,
        "bad_pages": bad_pages[:50],
        "n_bad_pages": len(bad_pages),
        "seconds": round(time.time() - t0, 1),
    }
    for k, v in cnt.items():
        out[k] = {str(kk): vv for kk, vv in sorted(v.items(), key=lambda x: -x[1])[:40]}
    out["unk4_top"] = {str(k): v for k, v in unk4_samples.most_common(30)}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
