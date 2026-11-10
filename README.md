# OpenBook Rich

OpenBook Rich (`.obr`) is an open, documented file format for chess opening books. It stores game statistics, ratings, annotations and recommendations for each position and move. This repository contains the format specification, a reference reader, an exporter to Polyglot `.bin`, and tools that convert ChessBase CTG books to `.obr`.

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

The CTG format was studied by reverse engineering, using Claude with the [REA: Reverse Engineer Anything](https://github.com/morluto/rea) skill (`reverse-engineer-anything`, by morluto). The public starting points were Steinar H. Gunderson's [CTG specification](https://web.archive.org/web/20210129162445/https://rybkaforum.net/cgi-bin/rybkaforum/topic_show.pl?tid=2319) and the source code of jja, used as a reference.

The converter was checked on one commercial CTG book (figures in [`results/`](results/)):

| | |
|---|---|
| CTG entries | 32,330,172 |
| Pages whose used length matches the parsed entries | 561,556 of 561,556 |
| Entries reached from the initial position | 32,330,141 |
| Unreachable entries, stored verbatim | 31 |
| Moves | 32,808,816 |
| Undecodable moves | 0 |
| Illegal moves (kept in metadata) | 1 |
| Aliases | 85,531,229 |
| Entries breaking a derivation rule | 0 |

## Quick start

Requirements: Python 3, [python-chess](https://github.com/niklasf/python-chess) and NumPy.

```
pip install chess numpy
```

The `.ctg`, `.cto` and `.ctb` files must be in the same folder. A `.ini` file with the same name is read if present.

```
mkdir out
python tools/ctgwalk.py book.ctg out                 # walk the book tree: nodes.bin, moves.bin, aliases.bin
python tools/gen_aliases.py book.ctg out [workers]   # alias keys: aliases_full.bin
python tools/build_obr.py book.ctg out out/book.obr  # write the .obr file
```

Inspect the result:

```
python tools/obr.py info  out/book.obr
python tools/obr.py probe out/book.obr "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
```

`probe` needs python-chess. To export a Polyglot book:

```
python tools/obr_tobin.py out/book.obr out/book.bin [--no-red] [--min-games N]
```

The weight of each move is the score of the side that played it. `--no-red` leaves out moves marked "avoid". `--min-games N` leaves out moves with fewer than N games.

Optional checks: `tools/ctgscan.py book.ctg [max_pages]` parses every page and prints field statistics as JSON. `tools/test_codec.py book.ctg [pages]` checks the position codec round trip.

On the book above, the tree walk took about 80 minutes and the `.obr` file is 2.8 GB.

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
- `tools/obr.py`, `tools/obr_tobin.py`, `tools/build_obr.py`, `tools/ctgscan.py`: MIT.
- `tools/ctg_movetable.py`, `tools/ctglib.py`, `tools/ctgwalk.py`, `tools/gen_aliases.py`, `tools/test_codec.py`, `tools/test_flip.py`: GPL-3.0-or-later. The move table in `ctg_movetable.py` is derived from jja, which is GPL-3.0-or-later; the other files import it.

The format can be implemented without any GPL code: a reader needs only the specification.

## Disclaimer

- ChessBase, CTG and HIARCS are trademarks of their respective owners. This project is not affiliated with or endorsed by them.
- The CTG tools are provided for interoperability only: reading books you lawfully own with other software.
- This repository contains no ChessBase code and no content from commercial books.
- You are responsible for having the rights to any book you convert, and for not distributing converted commercial books.
- The software is provided without warranty, as stated in its licences.

## Acknowledgements

- Steinar H. Gunderson, for the CTG specification and [remoteglot](http://git.sesse.net/?p=remoteglot;a=summary).
- Ali Polatel, for [jja](https://git.sr.ht/~alip/jja).
- Niklas Fiekas and contributors, for [python-chess](https://github.com/niklasf/python-chess).
