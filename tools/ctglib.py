"""Core CTG primitives: position codec, index lookup, move decoding.

Board representation ("byteboard"): a list of 64 one-char strings, index
row*8+file with row 0 = rank 8 (same layout as jja's ByteBoard), ' ' empty,
uppercase = side to move after normalisation.
"""
import mmap
import struct

import chess

from ctg_movetable import MOVETABLE

PAGE = 4096

# Huffman codes for squares (bit strings), from the CTG spec.
CODES = {
    ' ': '0', 'P': '110', 'p': '111',
    'R': '10110', 'r': '10111', 'B': '10100', 'b': '10101',
    'N': '10010', 'n': '10011', 'Q': '100010', 'q': '100011',
    'K': '100000', 'k': '100001',
}
DECODE = {v: k for k, v in CODES.items()}

TBL2 = [
    0x3100d2bf, 0x3118e3de, 0x34ab1372, 0x2807a847, 0x1633f566, 0x2143b359, 0x26d56488, 0x3b9e6f59,
    0x37755656, 0x3089ca7b, 0x18e92d85, 0x0cd0e9d8, 0x1a9e3b54, 0x3eaa902f, 0x0d9bfaae, 0x2f32b45b,
    0x31ed6102, 0x3d3c8398, 0x146660e3, 0x0f8d4b76, 0x02c77a5f, 0x146c8799, 0x1c47f51f, 0x249f8f36,
    0x24772043, 0x1fbc1e4d, 0x1e86b3fa, 0x37df36a6, 0x16ed30e4, 0x02c3148e, 0x216e5929, 0x0636b34e,
    0x317f9f56, 0x15f09d70, 0x131026fb, 0x38c784b1, 0x29ac3305, 0x2b485dc5, 0x3c049ddc, 0x35a9fbcd,
    0x31d5373b, 0x2b246799, 0x0a2923d3, 0x08a96e9d, 0x30031a9f, 0x08f525b5, 0x33611c06, 0x2409db98,
    0x0ca4feb2, 0x1000b71e, 0x30566e32, 0x39447d31, 0x194e3752, 0x08233a95, 0x0f38fe36, 0x29c7cd57,
    0x0f7b3a39, 0x328e8a16, 0x1e7d1388, 0x0fba78f5, 0x274c7e7c, 0x1e8be65c, 0x2fa0b0bb, 0x1eb6c371,
]


# ---------------------------------------------------------------- codec

def encode_position(bb, castle_bits, ep_file):
    """Encode a normalised byteboard. castle_bits: None or 4-tuple of bools
    (opponent K, opponent Q, mover K, mover Q). ep_file: None or 0..7
    (only when an adjacent mover pawn exists)."""
    bits = []
    for x in range(8):
        for y in range(8):
            bits.append(CODES[bb[(7 - y) * 8 + x]])
    bits = ''.join(bits)
    bits_left = 8 - (len(bits) % 8)  # bits free in the current byte (8 = byte boundary)
    ep_any = ep_file is not None
    right = 3 if ep_any else 8
    if castle_bits is not None:
        right += 4
        if right > 8:
            right %= 8
    if bits_left > right:
        nb = bits_left - right
    elif bits_left < right:
        nb = bits_left + 8 - right
    else:
        nb = 0
    if bits_left == 8 and castle_bits is None and not ep_any:
        nb = 8
    bits += '0' * nb
    if ep_any:
        bits += format(ep_file, '03b')
    if castle_bits is not None:
        bits += ''.join('1' if b else '0' for b in castle_bits)
    if len(bits) % 8:
        bits += '0' * (8 - len(bits) % 8)
    body = int(bits, 2).to_bytes(len(bits) // 8, 'big') if bits else b''
    hdr = (len(body) + 1)
    if castle_bits is not None:
        hdr |= 0x40
    if ep_any:
        hdr |= 0x20
    return bytes([hdr]) + body


def decode_position(pos):
    """Inverse of encode_position. Returns (bb, castle_bits, ep_file)."""
    hdr = pos[0]
    body = pos[1:]
    bits = ''.join(format(b, '08b') for b in body)
    bb = [' '] * 64
    i = 0
    for x in range(8):
        for y in range(8):
            j = i + 1
            while bits[i:j] not in DECODE:
                j += 1
                if j - i > 6:
                    raise ValueError("bad huffman code")
            bb[(7 - y) * 8 + x] = DECODE[bits[i:j]]
            i = j
    castle_bits = None
    ep_file = None
    # Flags are right-aligned at the end of the encoding.
    end = len(bits)
    if hdr & 0x40:
        c = bits[end - 4:end]
        castle_bits = tuple(ch == '1' for ch in c)
        end -= 4
    if hdr & 0x20:
        ep_file = int(bits[end - 3:end], 2)
    return bb, castle_bits, ep_file


def gen_hash(pos):
    h = 0
    tmp = 0
    for ch in pos:
        ch = ch - 256 if ch > 127 else ch  # i8
        tmp = (tmp + ((0x0f - (ch & 0x0f)) << 2) + 1) & 0xFFFF
        h = (h + TBL2[tmp & 0x3f]) & 0xFFFFFFFF
        tmp = (tmp + ((0xf0 - (ch & 0xf0)) >> 2) + 1) & 0xFFFF
        h = (h + TBL2[tmp & 0x3f]) & 0xFFFFFFFF
    return h


# ---------------------------------------------------------------- normalisation

def byteboard_from_chess(board):
    bb = [' '] * 64
    for sq, pc in board.piece_map().items():
        bb[(7 - chess.square_rank(sq)) * 8 + chess.square_file(sq)] = pc.symbol()
    return bb


def invert_bb(bb):
    out = [' '] * 64
    for r in range(8):
        for f in range(8):
            c = bb[r * 8 + f]
            out[(7 - r) * 8 + f] = c.swapcase()
    return out


def mirror_bb(bb):
    """Horizontal mirror (a<->h)."""
    return [bb[r * 8 + (7 - f)] for r in range(8) for f in range(8)]


def king_on_left(bb):
    idx = bb.index('K')
    return idx % 8 < 4


def normalise(board, flip_mode="mirror"):
    """Return (pos_bytes, invert, flip) for a python-chess board.

    flip_mode "mirror": spec/remoteglot rule - mirror horizontally when no
    castling rights and the mover's king is on files a-d.
    flip_mode "jja": jja 0.9.1 rule - reverse the whole array when no castling
    rights and the mover's king is in rows 0..3 (ranks 8..5)."""
    bb = byteboard_from_chess(board)
    invert = board.turn == chess.BLACK
    if invert:
        bb = invert_bb(bb)
    cr = board.castling_rights
    if cr:
        if invert:
            castle = (bool(cr & chess.BB_H1), bool(cr & chess.BB_A1),
                      bool(cr & chess.BB_H8), bool(cr & chess.BB_A8))
        else:
            castle = (bool(cr & chess.BB_H8), bool(cr & chess.BB_A8),
                      bool(cr & chess.BB_H1), bool(cr & chess.BB_A1))
    else:
        castle = None
    ep_file = None
    if board.ep_square is not None:
        f = chess.square_file(board.ep_square)
        # normalised row 3 = mover's 5th rank
        if (f > 0 and bb[3 * 8 + f - 1] == 'P') or (f < 7 and bb[3 * 8 + f + 1] == 'P'):
            ep_file = f
    flip = False
    if castle is None:
        if flip_mode == "mirror":
            if king_on_left(bb):
                flip = True
                bb = mirror_bb(bb)
                if ep_file is not None:
                    ep_file = 7 - ep_file
        else:  # jja
            if 'K' in bb[0:32]:
                flip = True
                bb = bb[::-1]
                if ep_file is not None:
                    ep_file = 7 - ep_file
                    # jja recomputes ep_any before flip; keep identical behaviour
    return encode_position(bb, castle, ep_file), invert, flip, bb


def real_board(pos, flags):
    """Rebuild the real python-chess board of a CTG entry, given the walk flags
    (bit0 black to move, bit1 mirrored). Move counters are not stored by CTG."""
    bb, castle, ep = decode_position(pos)
    if flags & 2:
        bb = mirror_bb(bb)
        if ep is not None:
            ep = 7 - ep
    black = bool(flags & 1)
    if black:
        bb = invert_bb(bb)
    b = chess.Board(None)
    for i, c in enumerate(bb):
        if c != ' ':
            b.set_piece_at(chess.square(i % 8, 7 - i // 8), chess.Piece.from_symbol(c))
    b.turn = chess.BLACK if black else chess.WHITE
    cr = 0
    if castle is not None:
        opp_k, opp_q, me_k, me_q = castle
        if black:  # opponent = white
            cr |= (chess.BB_H1 if opp_k else 0) | (chess.BB_A1 if opp_q else 0) | \
                  (chess.BB_H8 if me_k else 0) | (chess.BB_A8 if me_q else 0)
        else:
            cr |= (chess.BB_H8 if opp_k else 0) | (chess.BB_A8 if opp_q else 0) | \
                  (chess.BB_H1 if me_k else 0) | (chess.BB_A1 if me_q else 0)
    b.castling_rights = cr
    if ep is not None:
        b.ep_square = chess.square(ep, 5 if not black else 2)
    return b


# ---------------------------------------------------------------- book access

class CtgBook:
    def __init__(self, path):
        base = path[:-4]
        self.f = open(path, 'rb')
        self.ctg = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_READ)
        self.fo = open(base + '.cto', 'rb')
        self.cto = mmap.mmap(self.fo.fileno(), 0, access=mmap.ACCESS_READ)
        with open(base + '.ctb', 'rb') as fb:
            hdr = fb.read(12)
        self.low, self.high = struct.unpack('>ii', hdr[4:12])
        self.npages = struct.unpack_from('>I', self.ctg, 16)[0]

    def page(self, n):
        o = PAGE * (n + 1)
        return self.ctg[o:o + PAGE]

    def find_in_page(self, pg, pos):
        """Return (offset_of_moves, slot_index) of pos in page pg, or None."""
        page = self.page(pg)
        n = struct.unpack_from('>H', page, 0)[0]
        p = 4
        for slot in range(n):
            plen = page[p] & 0x1F
            if page[p:p + plen] == pos:
                return p + plen, slot
            p += plen
            p += page[p] + 33
        return None

    def lookup(self, pos):
        """Index lookup via the .cto hash table. Returns (page, moves_off, slot)."""
        h = gen_hash(pos)
        mask = 0
        while mask != 0x7fffffff:
            key = (h & mask) + mask
            if key >= self.low:
                o = key * 4 + 16
                if o + 4 <= len(self.cto):
                    pg = struct.unpack_from('>i', self.cto, o)[0]
                    if pg >= 0:
                        r = self.find_in_page(pg, pos)
                        if r:
                            return pg, r[0], r[1]
            if key >= self.high:
                break
            mask = 2 * mask + 1
        return None


def decode_move(bb_norm, invert, flip, code, flip_mode="mirror"):
    """Translate a CTG move code into a python-chess Move in real coordinates."""
    if code not in MOVETABLE:
        return None
    piece, num, fwd, right = MOVETABLE[code]
    occ = num
    frm = None
    for x in range(8):
        for y in range(8):
            if bb_norm[(7 - y) * 8 + x] == piece:
                if occ == 1:
                    frm = (y, x)
                    break
                occ -= 1
        if frm:
            break
    if frm is None:
        return None
    fr, fc = frm
    tr, tc = (fr + 8 + fwd) % 8, (fc + 8 + right) % 8
    if flip:
        if flip_mode == "mirror":
            fc, tc = 7 - fc, 7 - tc
        else:  # undo 180-degree reversal
            fr, fc, tr, tc = 7 - fr, 7 - fc, 7 - tr, 7 - tc
    if invert:
        fr, tr = 7 - fr, 7 - tr
    promo = chess.QUEEN if piece == 'P' and tr in (0, 7) else None
    return chess.Move(chess.square(fc, fr), chess.square(tc, tr), promotion=promo)
