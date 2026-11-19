# Experiment record format v1

Write records through the app or its command line. The case layout determines the record path.
New records have `schema_version: 1`. A record with no version is v0 and keeps that
format on save. Paths in records are relative to the case folder. Fields are optional
except where marked required. In the tables, **R** is researcher, **App** is notebook
app, and **A** is agent using the command line.

## Case layout

The `layout` setting in `<case>/_build/case.yaml` selects `classic` or `per-experiment`. An absent key selects `classic`. Case discovery requires that settings file and the matching `records/` or `experiments/` directory. New cases use `per-experiment`. The setting describes the existing tree. Creating or saving records never migrates a notebook.

```text
<case>/
  _build/case.yaml
  experiments/
    EXP-001/
      record.yaml
      scheme/
      NMR/<sample>/<acquisition>/
      attachments/
  _logs/
  index.md
  followups.yaml
  arrangement.yaml
```

The experiment directory name is the full ID. Under its `NMR/` directory, either `crude/10/` or `EXP-001-crude/10/` represents acquisition 10 of sample `crude`. Use one spelling per sample. Scheme, ChemDraw, Mnova and attachment references use case-relative paths inside the experiment, for example `experiments/EXP-001/scheme/reaction.png`.

Classic cases use `records/EXP-001.yaml`, `NMR/EXP-001-<sample>/<acquisition>/`, `attachments/EXP-001/` and the scheme path specified by the record. In either layout `_logs/` holds the case journal, lock, per-save history and custom Word export state. The index, Word notebook and follow-ups belong to the case.

### Notebook arrangement

The optional case file `arrangement.yaml` first appears when the researcher changes an arrangement. For example,

```yaml
groups:
- id: G1
  title: Temperature screen
  members: [EXP-002, EXP-005]
sequences:
- id: Q1
  title: Preparation of the alcohol
  steps: [EXP-001, EXP-003]
detached: [EXP-006]
references:
  EXP-005: EXP-002
```

Each group has a unique G-number, a title and a list of members. An experiment belongs to at most one manual group. Each sequence has a unique Q-number, a title and two or more distinct steps in the chosen order. An experiment can occur in different sequences. The detached list suppresses automatic grouping for those experiments. Each reference maps an experiment to a different record in this case. Missing lists and maps default to empty. The reader skips missing experiment IDs, and the next save drops them. Validation names entries that break these rules.

Parent headings have no experiment ID or record file. Arrangement writes check the file hash under the case lock, replace the file atomically and journal the action as `arrange`. Each save keeps the previous version in `_logs/history/arrangement/<time>.yaml`. An empty first snapshot represents the original absent file. Undo consumes the latest snapshot. Record saves have their own history.

## Identity

| Field | Type | Writer | Basis rule |
|---|---|---|---|
| `id` | text, required | App | Assigned when the record is created. |
| `schema_version` | integer | App | Version of the format used to create the record. |
| `compound_id` | text or integer | R, A | Optional SI compound label, for example `3a`. Used when the product material has no compound label. |
| `legacy_id`, `eln` | text | R, A | Preserve identifiers from the original notebook or ELN. |
| `title`, `type`, `status` | text, required | R, A | Describe the experiment and its current state. |
| `researcher`, `started`, `ended` | name and dates as text | R, App, A | Name and recorded or planned dates. |

## Plan

| Field | Type | Writer | Basis rule |
|---|---|---|---|
| `question` | text, required | R, A | State what the experiment aims to find out. |
| `planned` | boolean | R, App, A | Shows planned and actual charges side by side. |
| `metric_kind` | text, required for v1 screening | R, A | Choose one primary metric from `yield`, `conversion`, `dr`, `ee`, `er`, `regioselectivity` and `other`. A change after results gives a save warning and appears in the change log. |
| `metric` | text, required for v1 screening | R, A | Describe how the primary metric will be measured. |
| `conditions` | text | R, A | Record planned or observed conditions. |
| `procedure`, `procedure_basis` | list of text, text | R, A | Say whether the procedure is planned, recorded or taken from a source. |
| `vessels`, `notes` | list of text | R, A | Use actual labels and distinguish targets from observations. |
| `safety`, `refs` | text, list or map | R, A | Identify the source of any reference data. |
| `bench`, `result_fields` | list of maps with `field`, `hint` | R, App, A | Prompts for recording observations and their basis. |
| `planned_work` | map with `tlc_rows` integer, `tlc_columns` text list, `fields` prompt list | R, A | Prompts for planned TLC and purification. |
| `reaction` | map | App, A | Preserve `smiles` (reactants>agents>products), `source` (origin and date) and `drawing` (case-relative source file in the experiment’s scheme upload folder). A drawn reaction points to its KET file, or to a regenerated RXN after a material edit, and has the source “Drawn in the app, YYYY-MM-DD”. Each import keeps fresh checksummed source attachments. |
| `scheme_image`, `scheme_alt` | path, text | R, App, A | Link the scheme and describe what it shows. |
| `method`, `species` | lists of rows | R, A | Record the computational method and species. The first species row gives column names. |

## Materials

| Field under `materials[]` | Type | Writer | Basis rule |
|---|---|---|---|
| `id`, `name` | text, required per row | R, App, A | Use the row ID and material name. A structured row with a formula may have an empty name until the researcher supplies one. |
| `name_basis` | optional map | App | `kind` is `entered`, `notebook`, `pubchem`, `generated` or `chemdraw`. A notebook basis includes a non-empty `source`. If the source name was generated, `generated` keeps the original generated basis. A PubChem basis includes a positive integer `cid` and ISO retrieval `date` as text. A generated basis includes `package` and `version` as text. Typing or editing a name gives it an entered basis. Older records may omit this field. |
| `drawing`, `check_name` | case-relative path, boolean | App, R | Material-specific attached source. A changed species keeps its ID and equivalents. Confirm or replace its name to clear `check_name`. The optional boolean `scheme_mismatch` marks a material edit whose scheme could not follow. Regenerating the scheme from a reviewed reaction clears that marker. RDKit also checks reactant and product membership independently. |
| `compound_id` | text or integer | R, A | Optional SI compound label on the product. Takes precedence over the record-level label. The material row ID stays separate. |
| `formula`, `mw` | text, number | R, App, A | Formula and molar mass for the composition used in the charge. |
| `equiv`, `mmol`, `amount` | number, number, text | R, App, A | State the units in the amount. Identify theoretical amounts as such. |
| `assay`, `density` | number | R, App, A | Record wt% and g/mL when known. State the formulation basis and source. |
| `density_basis` | non-empty text | R, App, A | Optional basis for a positive numeric `density`. A PubChem selection records the literature source, CID, retrieval date and original candidate text, including measurement conditions when supplied. Keep this field with its density on agent edits. |
| `cas`, `smiles` | non-empty text | R, App, A | Optional material identifiers accepted by the researcher. A look-up can retain the CAS used for the query and the SMILES reported for the resolved identity. |
| `inchikey` | non-empty text | R, App, A | Standard InChIKey of the material. Preserve this field and its SMILES on agent edits. An import supplies canonical isomeric SMILES and uses the notebook formula weights for `mw`. |
| `pubchem_cid` | positive integer | R, App, A | Optional PubChem compound ID accepted for this material. |
| `note`, `bottle` | text, map | R, App, A | Keep charge qualifications and the inventory bottle details when used. |
| `smiles` (record level) | map from material ID to text | R, A | Structure of the material represented by that ID. |

Material IDs starting with R, P and A denote reactants, products and agents. S identifies a solvent. The first R row with one equivalent and the first P row identify the limiting reagent and main product. Material-level SMILES takes precedence over the older record-level map.

A literature density is an app-written value that agents preserve, along with its basis. Using a PubChem formula fills `mw` from the notebook's atomic weights. These optional material fields apply to both v0 and v1.

## Compound library

`<case>/compounds.yaml` is a list of entries with `id`, `name` (the drawing label or empty), `smiles`, `inchikey`, `formula` and `source`. The picker and library use the same identity as the material rows. An entry drawn in the app records that origin with a date. Its optional `sketch` contains KET for a single molecule or the selected species’ coordinate-bearing MOL block for a multi-species drawing. Re-importing the same InChIKey and label keeps the existing entry.

An entry may also contain `cas` and the same optional `name_basis` map as a material. Saving a preview takes the final material name and its basis when the species was added as a material. A library-only selection takes the name accepted in the preview.

## Runs

| Field | Type | Writer | Basis rule |
|---|---|---|---|
| `runs[].run`, `runs[].variable` | text or numeric label, text | R, App, A | Keep labels stable and record the varied conditions. |
| `runs[].result` | text, required per run | R, App, A | Keep the exact result and its qualifiers. Can be blank when planned. |
| `runs[].basis` | text | R, App, A | Required for a new numeric result. The first word selects how a yield is drawn. Measured is solid, slides hatched, target and literature outlined, and recalculated solid. Existing slide citations also select hatching unless the basis starts with measured. |
| `runs[].measured` | map with numeric `value` (percent), or legacy number | App | NMR integral ratio. The run basis identifies its integration regions, amounts and options. |
| `runs[].measured.processing` | optional map | App | New measurements record `source: topspin` (stored real spectrum) or `source: fid`. With `fid`, save `lb_hz`, integer `points`, `phase_mode` (`topspin`, `manual`, `auto0`), the applied `ph0` and `ph1` in TopSpin degrees, and the `numpy` version as text. For `auto0`, `delta_ph0` gives the difference from TopSpin in degrees, or null without processing parameters. A measurement with no processing field uses TopSpin's spectrum. |
| `runs[].measured.regions` | optional map | App | For a manual integration, `product` and `standard` are increasing numeric [low, high] ppm pairs on the displayed axis and `manual: true`. The [m#] basis identifies referencing and these bounds. Without this map the shared settings apply. |
| `results_basis` | text | R, App, A | Shared conditions or source and any app-written `[m#]` NMR settings. |

## Results

| Field | Type | Writer | Basis rule |
|---|---|---|---|
| `key_result`, `summary_basis` | text, `key_result` required | R, App, A | Index summary with its basis, or the planned state. |
| `result.text`, `result.basis` | text, both required when `result` is present | R, A | Isolated result as written and what it was calculated or taken from. The first word of the basis selects the drawing style wherever a yield bar is used, as for `runs[].basis`. The isolated result prints with its basis. |
| `interpretation`, `next` | text | R, A | Separate interpretation and proposed work from observations. |
| `results_table`, `results_note` | list of rows, text | R, A | Table with column names in the first row and a note on how the values were obtained. |
| `status_heading`, `status_items`, `next_items` | text, map of text lists, text list | R, A | Group computational status and record proposed next steps. |
| `sources` | map | R, A | ELN and ChemDraw paths, slide identifiers and reference text keyed by number when applicable. |
| `links` | list of label and path pairs | R, A | Link supporting project files. |

## NMR

| Field under `nmr[]` | Type | Writer | Basis rule |
|---|---|---|---|
| `sample` | text, required per sample | R, App, A | Sample label, for example `crude` for either accepted per-experiment folder spelling. |
| `spectra` | text | R, App, A | Acquisition labels as displayed by the instrument. |
| `date` | text or date | R, App, A | Acquisition date. |
| `mnova`, `mnova_status` | path, text | R, A | Processed Mnova file and its recorded state. The app can also find a matching file in the sample folder or its parent `NMR/` directory. Classic cases also search the case’s `Mnova/` directory. |

## Characterization

| Field | Type | Writer | Basis rule |
|---|---|---|---|
| `characterization` | list of text | R, A | Reviewed characterization lines. |
| `characterization_basis` | text | R, A | State who reviewed the assignments and when. |

## Attachments

| Field under `attachments[]` | Type | Writer | Basis rule |
|---|---|---|---|
| `path`, `kind` | path, text | App, R, A | Stored case-relative path and file kind. |
| `sample`, `run`, `note` | text, run also accepts a number | R, A | Optional sample, run and researcher note. |
| `sha256`, `size` | text, integer | App | Content checksum and size in bytes at attachment. |
| `added`, `by` | timestamp text, text | App | Attachment time and provided name or login. |

A drawing from the in-page editor keeps its KET and the parsed MOL or RXN as separate `sketch` attachments with a shared unique filename stem.

Kinds are `scheme`, `chemdraw`, `sketch`, `nmr-raw`, `nmr-processed`, `mnova`, `ms`,
`chromatogram`, `report`, `image` and `other`. Folder sizes sum the file sizes.
Folder checksums hash the sorted file lines, each made of the file's relative path,
a NUL byte and its hexadecimal SHA-256, joined by line feeds.

## Flags, history and checks

| Field | Type | Writer | Basis rule |
|---|---|---|---|
| `flags` | list of maps, required | R, App, A | Each flag has `id`, `text` and `tier` (blocking, needed or nice). |
| `history` | list of text | R, App, A | Say how a flag was closed. |
| `checks` | list of text | R, A | Date and verdict with the supporting log or source. |

## Entries

| Field | Type | Writer | Basis rule |
|---|---|---|---|
| `entries` | map from field tag to text | R, App, A | Preserve recorded bench, result and review text. Include the basis of results. |
