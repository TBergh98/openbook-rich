# OpenBook Rich

OpenBook Rich (`.obr`) is an open, documented file format for chess opening books. It stores game statistics, ratings, annotations and recommendations for each position and move. This repository contains the format specification, a reference reader, an exporter to Polyglot `.bin`, and tools that convert ChessBase CTG books to `.obr`: a fast C++ converter and a Python reference implementation.

## Why it exists

CTG is a proprietary, undocumented format. Existing tools such as [jja](https://git.sr.ht/~alip/jja) can read CTG books and export them to open formats. These formats have no fields for some of the data in a CTG entry:

| CTG data | Polyglot `.bin` | Arena `.abk` (as written by jja 0.9.1) | `.obr` |
|---|---|---|---|
| Book moves | yes | yes | yes |
| Games, wins, draws, losses | one 16-bit weight | `ngames`, `nwon`, `nlost` (draws derivable) | yes, in absolute colours |
| Average rating (games and sum) | no | no | yes |
| Performance (games and sum) | no | no | yes |
| NAG (annotation bits 0–4) | no field¹ | combined with the colour into one `priority` value | yes |
| Recommendation byte (move colour) | no field | combined into `priority` | yes, verbatim |
| Annotation bits 5–7 | no | no | yes, verbatim |

¹ A Polyglot entry is a 64-bit key, a 16-bit move, a 16-bit weight and a 32-bit learn field ([format description](https://hgm.nubati.net/book_format.html)). jja can optionally store the NAG in the learn field.

BrainLearn experience files (`.exp`) store a key, depth, score, move and performance value per entry. These are engine experience data, not game statistics.

## What it provides

- Statistics per position and per move, in absolute colours (White wins, draws, Black wins).
- Average rating and performance rating, stored as game counts and sums.
- The original NAG, recommendation byte and annotation flags of each move.
- Aliases for positions that CTG stores only once (colour-reversed and mirrored twins).
- Metadata that make the conversion lossless: derivation rules for fields not stored as columns, records that break those rules, unreachable entries and undecodable moves, all kept verbatim.
- Polyglot Zobrist keys and Polyglot move encoding.
- A CC0 specification ([`tools/SPEC.md`](tools/SPEC.md)) and a reference reader that uses only the Python standard library ([`tools/obr.py`](tools/obr.py)).
- Export to Polyglot `.bin` ([`tools/obr_tobin.py`](tools/obr_tobin.py)) for programs that read only Polyglot books.

## How the converter was built

The CTG data format was studied by analysing book files, using Claude with the [REA: Reverse Engineer Anything](https://github.com/morluto/rea) skill (`reverse-engineer-anything`, by morluto). The public starting points were Steinar H. Gunderson's [CTG specification](https://web.archive.org/web/20210129162445/https://rybkaforum.net/cgi-bin/rybkaforum/topic_show.pl?tid=2319) and the source code of jja, used as a reference.

The converter was checked on one commercial CTG book (figures in [`results/`](results/)):

| | |
|---|---|
| CTG entries | about 32 million |
| Pages whose used length matches the parsed entries | all (about 560,000) |
| Unreachable entries, stored verbatim | 31 |
| Moves | about 33 million |
| Undecodable moves | 0 |
| Illegal moves (kept in metadata) | 1 |
| Aliases | about 85 million |
| Entries breaking a derivation rule | 0 |

Counts, file size and run times depend on the book and the hardware; the figures here are orders of magnitude for that one book on a laptop.

## Quick start

Converting a book needs only a C++ compiler. Python is needed only to inspect the result, export it to Polyglot, or run the reference pipeline.

Use the C++ converter: on the book above it took a few minutes, against more than an hour for the Python pipeline, with the same output.

### Convert a CTG book (C++, recommended)

[`tools/ctg2obr.cpp`](tools/ctg2obr.cpp) needs only a C++17 compiler (GCC, Clang, or MinGW on Windows).

```
g++ -O2 -std=c++17 -o ctg2obr tools/ctg2obr.cpp
./ctg2obr book.ctg book.obr
```

The `.ctg`, `.cto` and `.ctb` files must be in the same folder. A `.ini` file with the same name is read if present. The output is identical to the Python pipeline except for the metadata fields `generator` and `created`. For a book of about 30 million positions the `.obr` file is a few GB.

### Open the book in Scid Community

[Scid Community](https://github.com/whelanh/scidCommunity), a fork of Scid, reads `.obr` files directly: load the book in the **Book Window** to see games, score, ratings, performance and the coloured moves for every move. No Python is needed. The original Scid does not read `.obr`.

### Inspect and export

For other programs, which read only Polyglot `.bin` books, export the book with Python. These tools need Python 3. `probe` also needs [python-chess](https://github.com/niklasf/python-chess) (`pip install chess`).

```
python tools/obr.py info  book.obr
python tools/obr.py probe book.obr "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
```

To export a Polyglot book:

```
python tools/obr_tobin.py book.obr book.bin [--no-red] [--min-games N]
```

The weight of each move is the score of the side that played it. `--no-red` leaves out moves marked "avoid". `--min-games N` leaves out moves with fewer than N games.

### Python reference pipeline (slow)

The Python tools are the reference implementation the C++ converter was checked against. Use them only to verify a conversion or to study the format: they are many times slower (more than an hour on the book above, mostly in the tree walk).

Requirements: Python 3, python-chess and NumPy (`pip install chess numpy`).

```
mkdir out
python tools/ctgwalk.py book.ctg out                 # walk the book tree: nodes.bin, moves.bin, aliases.bin
python tools/gen_aliases.py book.ctg out [workers]   # alias keys: aliases_full.bin
python tools/build_obr.py book.ctg out out/book.obr  # write the .obr file
python tools/compare_obr.py book.obr out/book.obr    # check the C++ output against it
```

Optional checks: `tools/ctgscan.py book.ctg [max_pages]` parses every page and prints field statistics as JSON. `tools/test_codec.py book.ctg [pages]` checks the position codec round trip.

## Programmatic use

`ObrBook` needs only the standard library. python-chess is used here only to compute the Polyglot key. Run from `tools/` or add it to `sys.path`.

```python
import chess
import chess.polyglot
from obr import ObrBook, move_colour, pg_move_to_uci

key = chess.polyglot.zobrist_hash(chess.Board())
with ObrBook("book.obr") as book:
    for m in book.moves(key):
        c = m["child"]  # statistics of the position after the move, or None
        if c is None:
            continue
        print(pg_move_to_uci(m["move"]), m["nag"],
              move_colour(c["recommendation"], m["nag"]),
              c["games"], c["white_wins"], c["draws"], c["black_wins"],
              c["avg_rating"], c["performance"])
```

Castling moves use the Polyglot king-takes-rook encoding (for example `e1h1`). Aliases are resolved by `find` and `moves`.

## Licensing

The repository is licensed per component. See [`LICENSE`](LICENSE) for the file list and [`LICENSES/`](LICENSES/) for the full texts.

- `tools/SPEC.md` and `results/`: CC0-1.0.
- `tools/obr.py`, `tools/obr_tobin.py`, `tools/build_obr.py`, `tools/ctgscan.py`, `tools/compare_obr.py`: MIT.
- `tools/ctg_movetable.py`, `tools/ctglib.py`, `tools/ctgwalk.py`, `tools/gen_aliases.py`, `tools/test_codec.py`, `tools/test_flip.py`, `tools/ctg2obr.cpp`: GPL-3.0-or-later. The move table in `ctg_movetable.py` is derived from jja, which is GPL-3.0-or-later; the other files import it, and `ctg2obr.cpp` contains it.

The format can be implemented without any GPL code: a reader needs only the specification.

## Disclaimer

- ChessBase, CTG and HIARCS are trademarks of their respective owners. This project is not affiliated with or endorsed by them.
- The CTG tools are provided for interoperability only: reading books you lawfully own with other software.
- This repository contains no ChessBase code and no content from commercial books.
- The CTG format was analysed from the public specification, the source code of jja, and the data files of a book the author lawfully owns. No ChessBase or other proprietary program was decompiled, disassembled or otherwise reverse engineered. ChessBase was used only as an end user, to compare displayed results visually.
- You are responsible for having the rights to any book you convert, and for not distributing converted commercial books.
- The software is provided without warranty, as stated in its licences.

## Acknowledgements

- Steinar H. Gunderson, for the CTG specification and [remoteglot](http://git.sesse.net/?p=remoteglot;a=summary).
- Ali Polatel, for [jja](https://git.sr.ht/~alip/jja).
- Niklas Fiekas and contributors, for [python-chess](https://github.com/niklasf/python-chess).
