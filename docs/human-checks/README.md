# The two checks a person does

The research plan has two steps that no script can do: checking the parsed metrics
against hand-annotated games (gate G2) and coding the wrongful ejections (qualitative
sub-study). Everything both need is in this folder, taken from the main run
`runs/20261015-145843-main`. Neither check calls a model.

| File | For |
|---|---|
| `g2_annotations.csv` | G2: ten games chosen at random (`govlab annotate`, seed 0), to fill in by hand |
| `wrongful_ejections.md` | Qualitative: the ten meetings that ejected a Crewmate (`govlab sample`) |
| `codebook.md` | Qualitative: the codes and how to apply them (draft, to review first) |
| `coding_sheet_hieu.csv`, `coding_sheet_rong.csv` | Qualitative: one sheet per author |

## Gate G2: hand-annotate ten games (one author, about an hour)

1. Run `.venv/bin/govlab serve`, open http://localhost:8765, go to Watch, pick the main
   run, then each game listed in `g2_annotations.csv`.
2. Replay the game and fill in its row from what you see, without opening
   `tables/games.csv`:

   | Column | What to write |
   |---|---|
   | `winner` | `crew` or `impostor` |
   | `kills` | how many Crewmates the insider killed in the whole game |
   | `wrongful_count` | how many votes ejected a Crewmate |
   | `meetings` | how many meetings reached a vote. A meeting cut short because the game ended does not count (3 of the run's 79 meetings ended that way) |
   | `insider_ejected` | `1` if the insider was voted out, else `0` |
   | `detection_meeting` | which of the counted meetings ejected the insider (1 = the first meeting that reached a vote); leave empty if none did |

3. Compare:

   ```bash
   .venv/bin/govlab validate runs/20261015-145843-main docs/human-checks/g2_annotations.csv
   ```

   The gate passes at 95% field agreement (57 of 60 fields). For each mismatch, check
   whether you or the parser is wrong. A parser error is a bug, and it would change
   the results. A misreading is not, but report it.

## Qualitative coding (both authors, separately, about an hour each)

Follow `codebook.md`. The codebook is a draft and has to be agreed before either of
you starts. κ only means something if the two sheets are coded independently.

## What goes into the report

- §3.2, Data quality: the G2 rate and the number of mismatches.
- §3.3, Wrongful ejections: κ per dimension, raw agreement, and the agreed codes.
- Appendix A.3: the codebook as finally used.
