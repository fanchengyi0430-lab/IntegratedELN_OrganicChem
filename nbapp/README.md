# Integrated Notebook for Organic Chemistry

A local web app for an experimental notebook. It reads and writes experiment records and regenerates the Word notebook from them.
Records, spectra and inventory stay in this folder. PubChem look-up is off by default.
For step-by-step instructions, open **Help** in the app or read the [user manual](MANUAL.md).

## Start

On 64-bit Windows, extract the portable ZIP and double-click **Start Notebook.bat**.
The app opens in the browser at http://127.0.0.1:8765/. Keep the black window open while you work. Close it to stop.
The portable ZIP includes Python and the chemistry tools. The same launcher in a source checkout installs the tools on first use and needs an internet connection for that step.

To start an independent notebook, run `& ".\Start Notebook.bat" --root "<project folder>"` with an empty folder
and choose **Start a notebook**. In an existing project, open **Menu** and choose **Start a notebook** under **Tools**.
The app creates a case folder with `experiments/` and sets `layout: per-experiment` in `_build/case.yaml`. Use **Plan an experiment**
to save a first record.

Choose **Open a demo notebook** on the first screen or under **Menu → Tools** for a teaching notebook with three experiments. Follow one yield correction from the agent's preview through the researcher's review. [Demo walk-through](DEMO.md)

## Pages

Select the notebook title in the top bar to switch notebooks. Open **Menu** to browse pages or press **Ctrl+K** to find a notebook, page or experiment. Use the arrow keys to select a result, **Enter** to open it, and **Esc** to close the search.

| Page | Use |
|---|---|
| Today | Planned experiments, blocking flags and recent changes. Enabling Schedule and supplies also shows due tasks, low supplies and waste reminders. |
| Experiments | Browse by number, reaction, synthetic sequence, creation time or modification time. Filter by type, planned status or text, preview schemes, arrange selected experiments and undo changes. |
| Experiment page | Scheme, materials, procedure, runs, NMR and attachments, sequence and parent links, and a blocking count linked to Edit. Open Review for the reference experiment, review response, checks and sources. |
| Edit | Form and "Record file" views of one draft; closing a flag moves it to `history` |
| Bench card | Planned charges, steps and actual values. Choose sections, charge columns, inventory locations, hazard prompts and a clip band for printing. Waste logging is available when Schedule and supplies is on. |
| Plan an experiment | Stoichiometry from a scale, inventory lookup, hazard prompts and a primary metric for screening. |
| Schedule and supplies | Off by default. Tracks tasks, supplies and waste bottles with entry logs, capacity reminders and CSV export. |
| Structures | Local exact, substructure, similarity and transformation searches, with CAS-matched cached inventory structures. |
| Screening results | Screening runs, primary metrics and their details, and CSV. Yield bars distinguish measurements, slide results and target or literature values. |
| NMR yields | Integrates product and standard regions in TopSpin's spectrum or a raw Bruker 1D FID processed with numpy. Each saved value identifies its source. |
| SI drafts | Reviewed characterization, unassigned peak lists and missing items |
| Inventory | Search .xlsx exports by name, abbreviation, CAS or structure. Exact structure searches also use CAS identities known to the notebook. |
| Change log | Record saves from the browser and CLI, with their author and origin |

## Where your data goes

Nothing goes to us. We distribute code and reference tables and never receive notebook data: there is no server of ours, and records, spectra and the inventory stay in your folder. The app listens on this computer only (127.0.0.1). The only requests it can send out go to PubChem, in four cases. With look-up switched on, a structure preview sends the InChIKey of each species this notebook does not already know, up to ten per preview. With look-up off, a row sends its InChIKey only when you press its look-up button. An exact structure search in Inventory sends the InChIKey of the drawn structure when the notebook has no match for it: when you press **Look up in PubChem** with look-up off, and without a press with look-up on. A search for a typed name or CAS number sends what you typed. Drawings, structures and generated names stay on this PC.

## Safeguards

- **Reference experiment.** The automatic reference shows the best earlier result of the same primary metric in the same reaction or parent. Dates establish order, with experiment number deciding when a date is missing or tied. The comparison excludes targets, literature, nonnumeric results and percentages above 100, ranks upper bounds below numbers and keeps the basis with the result. A manual choice and its undo belong to the notebook arrangement.
- **Saving.** The browser and command line use the same record checks. If a record changed while you edited, the browser merges changes made to different fields and shows any conflicting edits for review. The CLI can check the hash from `show`.
- **Unsaved work.** Leaving a page with unsaved changes asks first. The draft is kept in this browser and offered when you return.
- **Rebuild.** Close the notebook in Word before rebuilding. Cases with their own `_build/build.py` use that script. The app offers to import pending Word fields, or keeps a copy in `Notebook backups/` if you force the rebuild. The built-in export produces a static Word notebook and index.
- **NMR yields.** Changing a region or amount after integrating blocks saving until you integrate again. Each calculation's settings are written once under the run table as `[m1]`, `[m2]`…, and each run's basis names its tag.
- **Results as written.** `<4%`, `~44%`, `0%`, `nd` and `nr` stay distinct on screen and in exports. A new numeric run result needs a basis. Target and literature values have outlined bars, slide values have hatched bars and other numeric results have solid bars. An upper bound adds an end mark. A range keeps its printed limits and the bar ends at the lower limit.
- **Screening metrics.** Format v1 screens require `metric_kind` and `metric`. Missing values on v0 screens give a warning. Changing the kind after a run has a result returns a warning and adds a note to the change log. Screening metrics appear in results, CSV and the built-in Word export.
- **Automatic checks.** A yield above 100% and a calculated solution charge missing its assay give warnings. With both formula and CAS columns in the export, hits with the same formula and different CAS numbers get an isomer prompt.
- **Attachments.** Each attachment stores a case-relative path, timestamp, author, size and SHA-256. The app checks for missing files or changes in size and verifies checksums up to 20 MB. Use `validate --deep` to verify larger attachments too.

## What the app ships

- `data/aliases.yaml` maps reagent and solvent abbreviations and alternate spellings to CAS numbers and bottle names.
- `data/AGENTS.template.md` holds the editable agent rules that the app installs in a project folder.
- `data/demo/` contains the teaching case settings, three records, scheme image, follow-ups and three full-record edits for EXP-001.

## What it writes

New notebooks use one folder per experiment. Existing notebooks with the classic layout keep their original paths.

| Case-relative path | Per-experiment | Classic |
|---|---|---|
| Record | `experiments/EXP-001/record.yaml` | `records/EXP-001.yaml` |
| Instrument acquisition | `experiments/EXP-001/NMR/<sample>/<acquisition>/` | `NMR/EXP-001-<sample>/<acquisition>/` |
| Uploaded scheme images and ChemDraw files | `experiments/EXP-001/scheme/` | `attachments/EXP-001/` |
| Other uploaded files | `experiments/EXP-001/attachments/` | `attachments/EXP-001/` |

The per-experiment layout also accepts instrument folder names starting with the experiment ID, such as `NMR/EXP-001-crude/10/` inside `experiments/EXP-001/`. The CLI links files already inside the experiment in place and copies other inputs into the experiment. In classic cases it links files already inside the case in place. Both layouts store attachment and scheme paths relative to the case.

- Each save writes a change log entry in `<case>/_logs/changes.jsonl`. Updates keep the previous record in `<case>/_logs/history/EXP-###/<time>.yaml`. The shared lock is `<case>/_logs/records.lock`.
- The first arrangement change writes `<case>/arrangement.yaml` for parents, sequences, detached experiments and chosen references. Changes and undos use the case lock, check the file hash and appear in the change log. Undo consumes a version from `<case>/_logs/history/arrangement/`.
- `<case>/followups.yaml` for tasks, supplies and waste bottles. Both follow-up save routes check the same file hash and preserve keys handled by the other route.
- `<case>/_logs/word_export.json` on custom builds for cases with Word import.
- `<case>/index.md` and the notebook `.docx` on rebuild. The built-in export gives the case a front page, one entry per experiment, embedded PNG or JPEG schemes, and a list of attachments.
- An enabled look-up writes `<root>/reference_cache/pubchem/<CID>.json` and a query-to-CID index in `index.sqlite3`. Each JSON file keeps the identity, original candidate texts, parsed values and units, sources, retrieval date and request URLs.
- The same SQLite index stores dated InChIKey results, including PubChem's title and systematic name on a hit and a dated miss on no match.

Keep acquisition number folders and their `pdata/1/` files together. Use `attach` on the command line to register a whole folder or **Attach file** on the experiment page for individual files up to 200 MB.

New records use format v1. Older records keep their version and identifiers on ordinary saves. [Record format](SCHEMA.md)

The `waste` list in `followups.yaml` holds bottles with `id`, `label`, `stream`, `location`, `opened`, optional `capacity_mL`, `state` and `entries`. The bottle state is `open`, `full` or `picked-up`. Each entry records `date`, `exp`, `contents`, `volume_mL` and `by`. Totals and reminders are calculated on read.

## Settings

- `nbapp/config.yaml` holds the default project's local settings. See `nbapp/config.example.yaml` for neutral defaults. A blank user uses the operating-system login for the change log. With a separate `--root`, put .xlsx exports in `<project folder>/inventory/`.
- `<case>/_build/case.yaml` holds the notebook title, researcher, project question, shared caveats and references.
- `schedule_and_supplies: "off"` is the default in the app settings. Set it to `"on"` and restart to enable the schedule, supplies and waste log.
- Optional `waste_streams` in `case.yaml` is a list of suggested stream labels. A researcher can also type a label. `waste_reminder_fraction` sets the nearly-full reminder, with `0.75` as the default. The reminder is based on logged volume for bottles with a capacity.
- `<case>/_build/nmr.yaml` supplies optional integration presets. When absent, enter regions on the NMR yields page.
- `nbapp/data/hazards.yaml` contains the rule list behind the hazard prompts.
- `nbapp/data/solvents.yaml` lists the reference boiling points and their sources. The validator warns when a solvent row is above its reference boiling point and the conditions and procedure omit the vessel or reflux.

## In-page structure editor

From `nbapp`, run `py -3 packaging/build_sketcher.py` to install Ketcher standalone 3.18.0. Keep the supplied Apache-2.0 licence and NOTICE beside the `ketcher` directory. The explicit builder checks the cached release or downloads the pinned zip. Use `--offline` for a cached installation and `--force` to replace one. The notebook serves the editor, worker and chemistry engine locally.

**Draw** and **ChemDraw paste** share a species preview. Conversion reads SMILES/InChI on this PC and checks names, labels and CAS numbers in the library, record materials and structured bottles. When enabled, a separate PubChem click sends one identifier using the existing cache. Draw searches can include stereoisomers, salts/mixtures, isotope labels and neutralisable charge states. All four options start off. Double-click a scheme or material to edit its source, review the species changes, confirm changed names, then save. Saving a changed material updates its matching species in an app-generated scheme and keeps the previous files. The record identifies materials that need a separate scheme correction. Help describes the match options and editor hand-over. [User manual](MANUAL.md)

## Structure files

The planner and editor share a ChemDraw paste and file-drop preview. The packaged RDKit parses CDXML, MOL, SDF, RXN and SMILES in a time-limited local process. The validated record save installs the source attachment and, when selected, the generated PNG scheme. The notebook keeps reusable labelled structures in `compounds.yaml`. Native editing opens a disposable CDXML working copy through the Windows file association. See **Bring structures in from ChemDraw** in Help.

## PubChem look-up

Set `reference_lookup: pubchem` in the default project's `nbapp/config.yaml` and restart, or pass `--lookup pubchem` for one launch or command. Independent project roots use neutral defaults. `--lookup off` disables a configured look-up for the run. In the planner or experiment editor choose **Look up** on one material. Structured materials use their InChIKey. For a material entered by hand, review its name or CAS number before pressing **Search PubChem**. Keep unpublished compounds private.

The client resolves the identity with PUG REST and reads boiling point, melting point and density from PUG View over HTTPS. It spaces requests by at least 0.2 seconds and sets a 10-second timeout. Repeat queries use the local project cache. **Refresh from PubChem** requests a new copy. The editor shows each source's wording and the notebook's formula-derived molecular weight beside PubChem's value. Choose each value to copy to your draft, then save the experiment normally. Accepting density keeps its literature basis and original text.

## Command line

Run `py -3 nbapp\run.py` followed by any command below. Put `--root "<project folder>"` before or after the command. Launch options include `--no-browser` and `--port <port>`.

| Command | Use |
|---|---|
| `init "<case>" [--title "..."] [--researcher "..."]` | Start a notebook in the project folder. |
| `demo` | Create the teaching notebook, install the agent rules, and build the index and Word notebook. |
| `rules` | Install any missing AGENTS.md and CLAUDE.md in the project folder. |
| `rules --print` | Print the agent rules with this folder's command line. |
| `cases` and `ids "<case>"` | List case names or experiment IDs, one per line. |
| `show "<case>" EXP-### [--json]` | Print the YAML record with a hash comment, or a JSON object with `record` and `hash`. |
| `new "<case>" --file <path> --by "<name>"` | Create a record from YAML or JSON. Prints the new ID and hash. |
| `save "<case>" EXP-### --file <path> --by "<name>" [--expect <hash>] [--summary "..."] [--dry-run]` | Print validation notes, old and new values, and the basis of a changed result. A dry run previews the same changes before saving. |
| `attach "<case>" EXP-### <path> --kind <kind> --by "<name>" [--sample S] [--run N] [--note "..."]` | Attach a file or instrument folder. See the record format for allowed kinds. |
| `validate ["<case>"] [--deep]` | Check records and attachments. |
| `build "<case>"` | Rebuild the notebook and index. |
| `lookup "<name or CAS>" [--json] [--refresh]` | Fetch or read one compound using the same opt-in and cache as the browser. |

Exit codes are 0 for success or unchanged, 1 for validation, usage, disabled look-up, network or ambiguous-name errors, 2 for a stale hash, and 3 for a missing case, record, file or compound. Use the CLI to save agent edits.

## Packaged runtime

To build the portable download from the distribution Git checkout, run `py -3 -B nbapp/packaging/build_windows_zip.py`. The builder stages the app with neutral settings, installs the verified dependencies, extracts the finished ZIP and tests it. Use `--downloads <folder> --offline` to reuse a complete archive cache.

The Windows x64 builder runs on Python 3.9 or newer and checks the byte count and SHA-256 digest of each pinned archive before extraction.

| Archive | Source | Bytes | SHA-256 |
|---|---|---:|---|
| `python-3.14.10-embed-amd64.zip` | python.org, CPython 3.14.10 embeddable distribution | 12,619,664 | `90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159` |
| `numpy-2.5.4-cp314-cp314-win_amd64.whl` | files.pythonhosted.org, PyPI numpy 2.5.4 wheel | 12,703,552 | `2ca144f15135b6212a5c47b1e2aeca6e412f102f95a2d5d88d8aec77eb255de3` |
| `rdkit-2026.9.1-cp314-cp314-win_amd64.whl` | files.pythonhosted.org, PyPI RDKit wheel | 25,888,564 | `655cf6c4df7711254bb925b612af3d00f24f372e6461251f7db579fe9e1476ad` |
| `pillow-12.3.0-cp314-cp314-win_amd64.whl` | files.pythonhosted.org, PyPI Pillow wheel | 7,237,707 | `fdafc9cce40277e0f7a0feabce0ee50dd2fa1800f3b38015e51296b5e814048d` |
| `openclatura-0.4.4-py3-none-any.whl` | files.pythonhosted.org, PyPI openclatura wheel | 690,529 | `98cc62fa67a5099ec4c2e921f72795ecd16c2f1e79b4c0bc9cd8c60991e4f57b` |

Run these commands from the project folder on 64-bit Windows.

```powershell
py -3 -B nbapp/packaging/build_runtime.py
py -3 -B nbapp/packaging/build_runtime.py --check
nbapp\runtime\python.exe nbapp/run.py
```

Archives are reused from `nbapp/packaging/_downloads/`. Use `--offline` when all archives are cached or `--out <folder>` for another destination. For a runtime made with the previous pins, run `py -3 -B nbapp/packaging/build_runtime.py --force`. The builder stages the runtime, imports numpy, PIL, RDKit and openclatura, checks their versions and names ethanol before replacing the installed runtime. Set `SOURCE_DATE_EPOCH` to a fixed Unix timestamp to reproduce the manifest's build date across days.

Distribute the whole `nbapp/runtime/` directory. The builder retains each wheel's distribution metadata and licence texts. See the [third-party notices](THIRD_PARTY_NOTICES.md). `RUNTIME.json` records the pins, build date and installed file hashes. `--check` verifies the files offline. Help shows the running Python, numpy and RDKit versions. Feature code obtains optional modules and their availability messages from `runtime_info.numpy_support()` and `runtime_info.rdkit_support()`.

## Limits

- NMR yields default to TopSpin's spectrum. Raw FID processing uses numpy and needs a recorded group delay. Unassigned SI peak lists use TopSpin's spectrum. Proton multiplet proposals can use either spectrum source and reach characterization through the editor. The app links to existing Mnova files.
- The schedule marks time and equipment clashes.
- Bench-card contents and order are stored per notebook in this browser. Automatic location hints show up to two bottles on the card and three on a planned record. Hidden hazard prompts are tracked by experiment and prompt ID. Blocking flags and the record's safety line always print. Procedure tick marks also stay in this browser.
- Computational entries are edited in the "Record file" view.
- Each project folder serves one researcher on one computer.
