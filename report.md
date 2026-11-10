# Hiarcs15vBook.ctg: estrazione completa, confronto con jja, formato OpenBook Rich

Analisi del 10/11/2026 su `Hiarcs15vBook.ctg` (2,3 GB) con i file `.cto` e `.ctb`. Gli strumenti sono in `tools/`, i risultati in `out/`.

## Risposte in breve

1. **jja perde informazioni?** Sì, e in modo più grave di quanto si pensasse. Oltre ai dati che un `.bin` non può contenere, jja 0.9.1 ha due bug, verificati sull'eseguibile:
   - **perde il 12,75% delle posizioni del libro** (3.936.374 posizioni con mosse). Sono tutte quelle senza arrocco con il re di chi muove sulle colonne a–d, più i loro discendenti. Tra queste ci sono posizioni con fino a 15.037 partite;
   - **inverte vittorie e sconfitte**: per 1.e4 riporta "win 88.374 / loss 164.271", ma in realtà il Bianco vince 164.271 partite e il Nero 88.374.
2. **Tutto in un `.bin`?** No. Una voce Polyglot ha 16 bit di peso e 32 di "learn". Una voce CTG contiene vinte, patte, perse, rating medio, performance, colore e annotazioni.
3. **Un formato che conservi tutto?** Sì: è **OpenBook Rich (`.obr`)**, aperto e documentato in `tools/SPEC.md`. Il lettore di riferimento (`tools/obr.py`) è di circa 80 righe di Python, senza dipendenze.

## Cosa contiene una voce CTG (decodificato e verificato)

| Campo | Contenuto | Nel `.bin` di jja | Nel `.obr` |
|---|---|---|---|
| posizione (Huffman, arrocco, en passant) | | chiave | chiave + alias |
| mosse: codice + annotazione | NAG nei bit 0–4 | solo `!` `?` `!!` `??` `!?` `?!` □, nel campo learn | sì |
| | bit 5–7: livello di preferenza (8 combinazioni) | **perso** | sì |
| totale, vinte, perse, patte | | fuse in un peso (e invertite) | sì, in colori assoluti |
| 4 byte "sconosciuti" | = 5×(2·vinte+patte), il punteggio in decimi | perso | ricavabile: verificato su 32,3M voci, 0 eccezioni |
| rating medio (partite + somma) | | perso | sì |
| performance (partite + somma) | | perso | sì |
| raccomandazione | `0x80` verde, `0x40` rossa | fusa nel peso; le rosse restano | sì |
| byte extra e byte commento | sempre 0 in questo libro | — | ricavabile (0 eccezioni) |

Una scoperta sul formato: il CTG **salva nella stessa voce posizioni diverse**. Ogni posizione viene normalizzata come se muovesse il Bianco, e quelle senza arrocco vengono specchiate. Per esempio 1.d4 g6 e 1.g3 d5 (colori invertiti) hanno una sola voce con le stesse statistiche. È un limite del CTG, non un errore di conversione. Il `.obr` lo rappresenta con 85,5 milioni di alias, ciascuno con la trasformazione da applicare.

## Numeri

| | Valore |
|---|---|
| Voci CTG (header e scansione coincidono) | 32.330.172 |
| Voci raggiunte dalla posizione iniziale | 32.330.141 |
| Voci non raggiungibili (salvate byte per byte nel `.obr`) | 31 |
| Mosse | 32.808.816 |
| Mosse non decodificabili | 0 |
| Mosse illegali | 1 |
| Mosse con posizione figlia assente | 3 |
| Posizioni nel `.bin` di jja | 51.972.722 |
| di cui assenti nel `.obr` | 6 |
| Posizioni reali (con mosse) **perse da jja** | **3.936.374 (12,75%)** |
| Mosse rosse "da evitare" mantenute da jja | 787.958 su 918.848 |

Correlazione tra il peso di jja e i risultati: circa 0. Il peso dipende quasi solo da colore e NAG, e i conteggi pesano pochissimo.

## Verifiche fatte
- **Struttura:** tutte le 561.556 pagine sono interamente spiegate (byte usati = fine dell'ultima voce), 0 errori.
- **Codec posizioni:** per tutte le 32,3M voci la scacchiera ricostruita dai byte CTG riproduce esattamente la chiave Polyglot della posizione raggiunta giocando le mosse (0 discrepanze). Su un campione di 17.621 voci la ricodifica è identica byte per byte.
- **Indice `.cto`:** tutte le posizioni sono state cercate attraverso la tabella hash originale.
- **Regola dello specchio:** su 7.107 posizioni campione senza arrocco, la regola della specifica le trova tutte, quella di jja ne manca 649. Su 12 posizioni reali, l'eseguibile di jja ne trova 0 e il `.obr` 12.
- **Alias:** 3.002 posizioni gemelle cercate su 3.002 trovate, 0 mosse illegali dopo la trasformazione, statistiche coerenti al 100%.

## Cosa NON è stato conservato, e perché
- **Byte residui in fondo alle pagine** (384.331 pagine su 561.556): sono avanzi dell'allocazione del file, non fanno parte di nessuna voce e ChessBase non li legge. Non ho verificato se contengano voci cancellate.
- **Posizione esatta di ogni voce nel file** (pagina e slot): è un dettaglio di impaginazione. Di conseguenza dal `.obr` si possono rigenerare tutti i dati del CTG, ma non un file identico byte per byte.

## Ancora aperto
- Il significato preciso dei bit 5–7 dell'annotazione dentro ChessBase. Sono conservati; l'interpretazione "livello di preferenza" è dedotta dai dati.
- Le 6 posizioni e le 16 mosse presenti solo nel `.bin` di jja non sono state analizzate. Sono trascurabili, probabilmente casi limite di en passant.

## Controllo visivo in ChessBase (fatto dall'utente)
Ho confrontato sei posizioni, una per ogni caso da verificare:
- la posizione iniziale;
- dopo 1.e4;
- la Najdorf;
- il Gambetto di Donna;
- l'Inglese, che passa da un alias;
- il Dragone dopo 9.O-O-O d5, posizione specchiata che jja non trova.

In tutte e sei mosse, partite, percentuali, simboli e colori coincidono con il `.obr`. Le sole differenze sono nell'ordine delle mosse: ChessBase le ordina per numero di partite, mentre il `.obr` conserva l'ordine salvato nel libro.

## File
- `out/Hiarcs15vBook.obr` (2,84 GB): il libro completo.
- `out/Hiarcs15vBook_from_obr.bin` (1,9 GB): Polyglot derivato con statistiche corrette. Il peso è il punteggio di chi muove, alias inclusi.
- `out/hiarcs_jja.bin`: l'output di jja, per confronto.
- `out/compare_jja.json`, `out/compare_canonical.json`, `out/scan_full.json`, `out/walk_stats.json`: i numeri di questo report.
- File intermedi cancellabili (circa 2,7 GB): `out/nodes.bin`, `out/moves.bin`, `out/aliases.bin`, `out/aliases_full.bin`.
- `tools/`:
  - `ctgscan.py`: scansione delle pagine;
  - `ctglib.py`: codec, indice, mosse;
  - `ctgwalk.py`: visita dell'albero;
  - `gen_aliases.py`: generazione degli alias;
  - `build_obr.py`: costruzione del `.obr`;
  - `obr.py`: lettore;
  - `obr_tobin.py`: esportazione `.bin`;
  - `compare_jja.py`: confronto con jja;
  - `SPEC.md`: specifica del formato.

Nota sulla licenza: `tools/ctg_movetable.py` è estratto da jja (GPL-3.0); la tabella deriva dalla specifica CTG di Steinar H. Gunderson. Prima di pubblicare gli strumenti con licenza MIT conviene rigenerarla dalla specifica originale, oppure distribuire gli strumenti CTG come GPL. La specifica `.obr` e il lettore `obr.py` non contengono codice di jja.
