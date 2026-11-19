# Agent rules for this notebook

The notebook app wrote this file when the project folder was set up. Edit it to suit your group. Claude Code reads it through `CLAUDE.md`. Codex and other agents read it directly.

**Your role.** The researcher sets the question and reviews your work. You do the routine work around the experiments. Say plainly what you checked, what you assumed and what you could not resolve.

**Goal:** keep every session small. Read the least that answers the task. When a command or a script can answer a question about a file, do not read that file into context.

## Read order

1. This file.
2. `<case>/index.md`: one line per experiment. Find the experiment there first. If the file is missing or out of date, run `build`.
3. The record of each experiment the task names, printed with `show`. Records are the source of truth.
4. Anything else only if the task needs it, following the rules below.

## The command line

Read and change records through the notebook's command line. It applies the same checks as the app and logs each change.

```
{{RUN}} <command>
```

If the app or this folder has moved, correct the line above.

| Command | Use |
|---|---|
| `cases`, `ids "<case>"` | List the notebooks in this folder, or the experiments in one |
| `show "<case>" EXP-###` | Print a record and its hash |
| `save "<case>" EXP-### --file <yaml> --by "<name>" --expect <hash> --dry-run` | Check an edit and print what it would change |
| `save` without `--dry-run` | Save the edit |
| `new "<case>" --file <yaml> --by "<name>"` | Create a record |
| `attach "<case>" EXP-### <path> --kind <kind> --by "<name>"` | Register a file or an instrument folder |
| `validate "<case>"` | Check the records and attachments |
| `build "<case>"` | Rebuild the index and the Word notebook |

`nbapp/SCHEMA.md` lists every field and who may write it. `nbapp/MANUAL.md` has a section on working with an agent.

## Do not read into context unless the researcher names the file

- **Raw instrument data:** `**/NMR/**`. Query it with a script and quote only the fields you need.
- **Logs and backups:** `**/_logs/**` and `**/Notebook backups/**`. To review one change, read that change's entry only.
- **Generated files:** the Word notebook. It is built from the records, so rebuild it and do not read it.
- **Bulky formats:** `*.cdx`, `*.cdxml`, `*.mnova`, `*.pptx` and `*.pdf` bodies. Take structures as SMILES from the records.
- **The app itself:** `nbapp/**`, except `MANUAL.md` and `SCHEMA.md`. Never read `nbapp/runtime/**` or `reference_cache/**`.

Never list folders recursively from this folder or from any `NMR/` folder. List one level at a time.

## Soft budgets for file reads

| Task | Budget |
|---|---|
| Question about one experiment | 5k tokens or less |
| Writing or revising one entry | 20k tokens or less |
| Anything larger | Say why before reading |

## Changing records

- **Facts go in the record, through the command line.** Do not edit a record's YAML file directly.
- **Start from the full record that `show` prints.** Keep every field you do not edit, including the ones `SCHEMA.md` marks as written by the app.
- **Sign your work.** Give `--by` a name that identifies you as an agent, such as `Claude (agent)`, and add a `--summary`.
- **Dry run first**, with `--expect` set to the hash from `show`. Before you save anything that alters a result, a quantity, a structure or a flag, show the researcher the changes the dry run prints.
- **A refused save states its reason.** Fix the record. Do not go around the check.
- **After a save,** run `validate`, then `build`. Never edit the index or the Word notebook by hand.
- **Each fact appears once.** Do not describe your own steps in the record. The change log holds that.

## Results

- **Every result states its basis**, and the basis starts with one of these words: measured, recalculated, slides, literature or target.
- **Keep results as written.** `<4%`, `~44%`, `0%`, `nd` and `nr` mean different things.
- **A slide, literature or target value is never a measurement of this experiment.** Do not enter it as one.
- **When you recalculate,** record the inputs and keep the original value in the basis.
- **Do not smooth over a problem.** A yield above 100%, a mass that does not balance or two sources that disagree each get a flag.

## Flags

- Give each flag a tier: `blocking`, `needed` (for publication or reproducibility) or `nice`.
- Keep three or fewer open per experiment.
- Before asking the researcher, try to resolve a flag from the sources you were given.
- Move a closed flag to `history` with one line saying how it was closed and by whom. Only the researcher's word closes a `blocking` flag.
- After the researcher accepts a checked change, add one dated line to `checks` naming the evidence.

## Second reader

NMR assignments and stoichiometry get a second check, by another agent or by the researcher, before the researcher signs off.

## Never

- Delete or alter raw data, backups or `_logs/`.
- Rename instrument folders or files without the researcher's approval.
- Send unpublished structures or results to an outside service, such as a look-up or a web search, unless the researcher has said you may.
