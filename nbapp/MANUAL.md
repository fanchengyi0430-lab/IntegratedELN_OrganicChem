# Integrated Notebook for Organic Chemistry user manual

## Start the app

1. Open the project folder and double-click **Start Notebook.bat**. The Windows ZIP includes the chemistry tools. In a source download, the first launch installs them into the app folder.
2. Keep the app window open while you work. If the browser does not open automatically, go to `http://127.0.0.1:8765/`.
3. Select the notebook title in the top bar to open **Switch notebook**. Choose a title, **Start a notebook**, or **Open a demo notebook**. The browser remembers the selected notebook. Open **Menu** and choose **Today** for upcoming work or **Experiments** to find a record.

Press **Ctrl+K** or use the search button in the top bar to find a page, experiment, or **Switch to** another notebook by title. Use the arrow keys to select a result and **Enter** to open it. The last result searches the full text of the records. Press **Esc** to close the menu or search.

On the **Record** tab, choose **Review** to open **Reference and review**. A reference experiment or saved review response opens the drawer automatically. Otherwise the drawer follows your last choice. Below the reference are the review response, checks, closed flags and sources. The blocking count in the heading opens **Edit**, where you can read flags and record a closing note. The other experiment tabs open the bench card, NMR yields or SI draft when available for that record.

## Arrange experiments

In **Experiments**, **Arrange by** starts at **Number**. Choose **Created** or **Last modified** to see the newest first. Press **Newest first** to reverse the order. Creation time comes from the original create entry in the change log, or from the file for older records. Type, **Planned**, text search and **Search full text** work in every arrangement. This browser remembers the arrangement and **Schemes** setting for each notebook.

Choose **Reaction** to see repeats under a parent heading. The app matches the main reactant and product structures across experiment types. Choose **Screening** in the type filter to narrow the list. Expand or collapse a parent with its title. It shows the member count, date range, scheme and highest result for each comparable primary metric. A parent you create takes precedence over automatic grouping.

Choose **Sequence** to follow a synthesis. Your sequences come first in the order you gave their steps. Automatic sequences connect a product material in one experiment to a reactant material with the same InChIKey in another. The connecting compound appears at the receiving step. Branches share a stage, and mutually dependent steps in a loop appear together. The Record page links up to three sequences and the experiment’s parent below the heading.

- Press **Select** and tick experiments. Choose **New parent experiment** and enter a title, or choose **Add to parent…** and select an existing parent. For a new sequence, tick two or more experiments in step order, check the numbered selection, then choose **New sequence**.
- Use **Move out of parent** on a sub-experiment to remove its manual membership or to detach it from automatic grouping. **Move to…** offers the other parents. Renaming an automatic parent keeps its current members as a manual group. **Remove parent** releases the records for grouping again.
- On your sequence, use the arrow buttons to reorder steps. You can rename it, remove a step or remove the sequence. Removing one of the last two steps removes the sequence.
- Each edit saves immediately. Use **Undo** in the message or the named **Undo** button in the toolbar. Repeated undo walks back parents, sequences, moves and reference choices. Record saves use separate history. If someone changes the arrangement elsewhere, the page reloads that version so you can repeat your edit.

**Schemes** shows linked thumbnails as rows come into view. A saved scheme image takes priority. The packaged runtime can also draw a preview from the reaction or material structures. Open the thumbnail to visit the experiment. In Reaction view the parent carries the preview. In Sequence view each experiment can show its own. Computational experiments have no preview.

### Reference experiment

The top of **Reference and review** shows the best earlier result for the current primary metric among experiments with the same main reactant and product, or in the same parent. An earlier start date comes first. When either date is missing or the dates tie, the lower experiment number comes first. A tie in result goes to the later experiment.

The comparison uses each run’s result, or the isolated result when there are no runs. A missing metric kind means yield. Higher yield, conversion or ee wins. For dr, er and regioselectivity the first number is divided by the second. An approximate value uses its stated number, a range uses its lower limit, and any number outranks an upper bound. Text, nd, nr, targets and literature values are excluded, and so is a percentage above 100. Slide results retain their hatched bar and source. The metric **other** has no automatic winner.

Follow the linked experiment to inspect the run and its conditions. To override the reference, select **Choose an experiment**, filter by number or title, and select a record from this notebook. A manual choice can be later or from another reaction. Its card shows the best comparable result when available. **Use the automatic choice** clears the override. Both changes can be undone. Computational records have no reference card.

The packaged Windows runtime includes Python, numpy, RDKit and Pillow. With your own Python 3.9 or newer, the notebook shows which optional features need a packaged dependency.

## Start a notebook

1. Choose **Start a notebook**. In a new project with no notebooks, this form opens automatically.
2. Enter a folder name. A title and researcher name are optional.
3. Choose **Create notebook**. Open **Plan an experiment** when you are ready to add the first record.

The project folder holds rules for AI agents that the researcher can edit. To try the app with teaching records, choose **Open a demo notebook** here or under **Menu → Tools**. [Demo walk-through](DEMO.md)

To keep a notebook in a separate project, create an empty folder and launch the app with that folder as its root.

```powershell
py -3 nbapp\run.py --root 'C:\path\to\my notebook project'
```

## Plan an experiment

1. Open **Plan an experiment**. Enter a title, an experiment type and the question you want to answer.
2. Enter your scale and materials. Check units, bottle information and any calculated charges. If your project has inventory exports, you can search them in the planner.
3. Record the planned conditions and procedure. For screening, choose one **Primary metric** and describe how you will determine it in the metric detail, including the signal and standard if applicable. Set up the runs and the conditions you will vary.
4. Review the hazard prompts, add your own safety note as needed, and choose **Save planned experiment**. The experiment appears on **Today** and in **Experiments**.

In **Find bottle**, type at least two characters of a name, abbreviation, product number, barcode, CAS number or formula. Use the arrow keys and Enter to pick a bottle. Esc clears the search.

For older screening records, you can fill in the metric in **Edit**. If you change the primary metric after recording a run result, the app warns you and records the change in the change log. Review earlier run values against the new metric before comparing them.

The boiling-point prompt names the source and review status of the shipped reference value. If a solvent is heated above this value, state the vessel or reflux setup in the conditions or procedure.

## Find a bottle in Inventory

Choose **Upload inventory workbook** on the welcome screen, Today page or Inventory page and select an `.xlsx` file. The first worksheet must start with a **Name**, **Chemical Name** or **ChemName** column heading and contain at least one named bottle. Optional columns include **CAS**, **SMILES**, **Formula**, **Location** and **Barcode**. The app copies the workbook into the project's configured inventory folder. To update an existing export, replace its file in that folder. Additional workbooks can be uploaded through Inventory.

The demo notebook includes a small fictional inventory when the project has no exports. Try searching for **acetone** or drawing its structure. Your own notebooks show only the inventory you supply.

Search by name, CAS number, abbreviation, formula, supplier product number or barcode. For example, **DBU** finds bottles registered under its CAS number. Alternate spellings such as **CH2Cl2** work too. The editable abbreviation table in `nbapp/data/aliases.yaml` lists the CAS number, bottle names and alternate spellings for each abbreviation.

Under **Search by structure**, enter SMILES or choose **Draw**. An exact search compares stored structures and also finds bottles by CAS numbers associated with the same InChIKey in the compound library, record materials or local look-up cache. When the notebook has no match, **Look up in PubChem** checks that single structure. Enabling PubChem look-up allows that check automatically. The result is cached.

The page counts bottles with a readable exported SMILES or a structure cached by CAS number. Substructure and similarity searches cover those bottles. Set the Tanimoto threshold for similarity. With RDKit unavailable, use the text search.

## Open flags

Choose **Open flags** in the menu, or **Flags** in the top bar outside the Record page. Blocking flags appear in full. Expand an experiment under **Needed** to read its flags. The status line counts blocking and needed flags and the experiments they affect. Choose **Show nice-to-have flags** to read the remaining flags. **Resolve** opens the experiment editor.

## Draw inside the notebook

Choose **Draw** in the planner, experiment editor, compound picker or Structures query line. **Ctrl+K → Draw a structure** opens the search canvas. The Windows ZIP includes the editor. In a source checkout, **Start Notebook.bat** installs it on first use. Ketcher standalone 3.18.0 uses Apache-2.0 and runs locally. Use the packaged Python for RDKit.

Draw a molecule or place a reaction arrow between species. The line below the canvas gives RDKit’s species and the notebook formula weights. **Add to drawing** first reads SMILES or InChI locally. For a name, compound label or CAS number it checks this notebook’s library, experiment materials and inventory bottles with known structures. Pick a match if several are offered. When look-up is enabled, **Search PubChem** sends that one identifier and uses the normal look-up cache. Canvas changes and local searches stay on this PC.

On **Structures**, the first arrow selects **reactions**. You can select another scope. **As drawn** compares complete structures, including stereo, isotope labels, fragments and formal charges. The four **Also match** switches start off. They also broaden substructure and similarity searches on complete drawings. A SMARTS query uses its explicit predicates. **Stereoisomers** ignores stereochemistry. **Salts and mixtures** allows extra components and compares neutralisable ions in salts to their parents. **Isotope-labelled forms** ignores isotope labels. **Other charge states** compares forms that RDKit can neutralise. **As substructure** accepts SMARTS, including query atoms and bonds. **Similar** uses the displayed Tanimoto threshold. **Edit** reloads the small picture and **Remove** clears it.

In an experiment, **Use structure** opens the same species preview as ChemDraw paste. Assign roles, tick materials and check the first reactant and product. Query features can be searched. A material needs a complete structure. The library picker offers the same preview and can save a compound to the library.

Double-click a scheme or material picture or use its edit button. A sketch opens in Draw and a ChemDraw source opens as a working copy. The Record page first takes you to the experiment editor. **Edit in Draw** lays out a ChemDraw source from its SMILES. **Edit in ChemDraw** checks the exported CDXML’s identities and roles before opening the copy. When you change a material, the app looks for its old InChIKey on its reaction side. The change list tells you when the scheme follows the material. Save writes a new reaction drawing and image. If the old species is missing or the image was supplied separately, the change list and the saved Record page name the material whose scheme needs review. Review the old and new formulas and weights and any warnings about recorded results. Accept or discard the changes. Check the name on a changed material. **Save changes** installs new checksummed source files and updates the record. Existing source files remain available under Attachments.

## Bring structures in from ChemDraw

In **Plan an experiment** or **Edit**, focus **Structure from ChemDraw**. In ChemDraw choose **Edit → Copy As → CDXML Text** (or **SMILES**) and paste. You can also drop or choose a `.cdxml`, `.mol`, `.sdf`, `.rxn` or `.smi` file. The packaged runtime supplies RDKit. Each import accepts up to 2 MB and 200 molecules. Fragment messages identify unreadable entries by position.

Check the preview. If ChemDraw stored reaction steps, choose the step you want. If the drawing has several arrows and no stored steps, each species starts with role **none** and its material box clear. Set each role yourself, or review the species numbers and choose **Confirm proposed roles** when a single isolated arrow supports a proposal.

You can change any role and use the up and down buttons to order the species. The reaction SMILES and scheme update when both sides have a structure. Reactants and products start ticked when assigned. Tick an agent if you want a charge row for it. **Add to draft** uses the first ticked reactant at one equivalent and the first ticked product as the main product. You can give an unlabelled structure a name later. The planner uses its formula and the notebook's atomic weights to calculate charges. The exact mass column gives RDKit's neutral monoisotopic mass and calculation basis.

**Save planned experiment** or **Save changes** keeps a new source file and its checksum with the experiment. The app supplies a PNG for the record, bench card and Word notebook when the experiment has no scheme. Choose **Use this drawing as the experiment scheme** to replace the displayed scheme on an edit. **Colour the change** highlights lost and gained groups with heavier lines. Your browser remembers that choice. A plain drawing includes an explanation when there is too little shared structure, the mapping is ambiguous or the comparison times out.

The **Known as** column checks exact InChIKeys in this notebook's compound library, experiment materials and structured bottles. If names differ, choose a source. Names used in more material rows appear first. A bottle selection links its stock details to the row. A **Close match** shows the structural difference. Its name stays with the other structure.

With look-up on, the preview checks up to ten distinct unknown species in PubChem. With look-up off, **Look up in PubChem** checks only the selected species. Only the InChIKey goes to PubChem at the U.S. National Institutes of Health. The key is a fingerprint of the structure. PubChem can identify only a compound it already holds. The structure cannot be read back from the key, though someone who guessed the structure could confirm the guess. A formula conflict leaves the name empty. **Check again** refreshes a dated result.

For **New compound** and **Not looked up**, openclatura proposes a systematic name on this PC. **Use generated name** accepts a proposal marked **generated, not checked**. You can edit the name or leave it empty and calculate charges from the formula. Isotope labels, radical electrons and metals preclude a proposal. Naming also has limits of 100 atoms, 4,096 SMILES characters and two seconds. The row explains when generation is unavailable.

To check a generated name, choose **Name it in ChemDraw**, use **Convert Structure to Name**, then save and close the working copy. Review the label and choose **Use ChemDraw name**. The Record page shows the name's basis. The SI draft lists generated names under **Names to check**, including generated names reused from this notebook.

In the planner and editor, **Save to library** starts ticked for new and unsearched compounds. **Add to draft** stages the selection. Saving the experiment writes the selected structures and their final names to `compounds.yaml`. On the Structures search page, **Save compound** and **Save all to library** save directly. In the planner choose **From library**, filter by label or paste a substructure, and pick its drawing to fill the material row.

## Find structures and transformations

Open **Menu → Records → Structures**, or find **Structures** with **Ctrl+K**. Paste a drawing and choose a species, or type a query. Use **exact** for the same InChIKey, **substructure** for a SMILES or SMARTS pattern, or **similarity** for Morgan fingerprints with your chosen Tanimoto threshold. Set the role to reactant, product or any. With any role, the page includes matching inventory bottles whose CAS numbers already have structures in the local look-up cache.

Use **transformation** with two fragments such as `CO>>CN`. A match needs fewer occurrences of the left fragment and more occurrences of the right fragment on the product side. The Record page also lists **Same step** experiments with the same limiting reactant and main product, ordered by reported percentage and date.

## Edit a scheme in ChemDraw

Double-click a scheme or choose **Edit in ChemDraw**. The Record page opens its edit form. ChemDraw opens a working copy of the experiment's CDXML, or a blank drawing for a new source. For another supported text format the app converts it to CDXML and checks that each structure and reaction role survives the conversion. Save in ChemDraw, then close the document yourself. The notebook checks the file about every 1.5 seconds and shows the saved changes. Saving in ChemDraw triggers the preview. The app has no COM connection to ChemDraw and cannot watch or close its window.

Review the species and formula changes. **Accept ChemDraw changes** places the edited source and selected materials in your draft. Save the plan or edit to register a new permanent source. **Discard working copy** removes the temporary file. If Windows has no application associated with CDXML, use paste or drop.

## PubChem look-up

Automatic look-up is off until you start the app with `--lookup pubchem` or set `reference_lookup: pubchem` in the default project's `nbapp/config.yaml` and restart. The preview also allows one explicit key lookup while automatic look-up is off. With look-up enabled, choose **Look up** on a material to review reference properties. A structured row searches by InChIKey. For a material entered by hand, check the compound name or CAS number before pressing **Search PubChem**.

Review the identity and each candidate's text and source. **Use formula** calculates molecular weight using the notebook's atomic weights. The app flags a difference from PubChem above 0.05 g/mol. **Use density** copies the selected value in g/mL and its literature basis. You can also accept the CID, SMILES or the CAS number used for the search. These choices update the draft. Save to record them.

A repeat search uses the project's dated copy, including when offline. **Refresh from PubChem** fetches fresh candidates. If several compounds match, try a more specific name or CAS number. Include `reference_cache/` when you copy your project.

## Choose bench card contents

1. Open **Bench card** from a planned experiment or its experiment page. Read the **Before you start** flags and the safety note before proceeding.
2. Open **Card contents**. Tick the sections to include. Under **Charges**, choose MW, mmol, equiv, Note and **Kept in** individually. Choose individual hazard prompts or use the control for all prompts. Blocking flags and your own safety note always appear.
3. Use the arrows to reorder the included sections. The card prints with the normal page margin. Turn on **Clip band** to leave space for a binder clip between sections.
4. Select **Print on one page** and review the preview. If the card is too long, the app displays a message. You can also fill in the card on screen and select **Save entries**.

For a material without a picked bottle, **Kept in** shows up to two bottles on the card or three in a planned experiment’s Materials table. The app tries the material or abbreviation CAS first, then a strict bottle name. A shared CAS can identify other bottles with different labels. Check the label on a name match. Your group comes first among available bottles. Empty bottles come last. Select **+… more** to open the Inventory search. A bottle you picked in the planner takes precedence.

The browser remembers the layout for each notebook and the hidden hazard prompts for each experiment. Procedure tick marks also stay in this browser. Use **Reset layout** to restore the default card layout.

## Record results and their basis

Open the experiment and choose **Edit**. Enter screening results in the run table and add the basis for each result. For a synthesis, enter the isolated result and its basis. Keep the short key result current so you can find it in the index. Use the bench entries for actual charges, observations and deviations.

| Basis | What to record |
| --- | --- |
| Measured | The measurement and how you obtained the value. |
| Recalculated | The source values and the calculation. |
| Slides or literature | The slide or reference that supplied the value. |
| Target | The intended value, identified as a target. |

Keep qualifiers as written, such as `<4%`, `~44%`, `0%`, `nd` or `nr`. **Screening results** shows the run results, their bases and the metric for each experiment. Use its CSV link to work with the results in a spreadsheet.

## Measure NMR yields

1. In a new notebook, choose **Open the experiment folder**. Place the sample under `NMR/` inside that folder. For EXP-001, both `NMR/crude/10/` and `NMR/EXP-001-crude/10/` identify acquisition 10 of sample `crude`. In a classic notebook, put the acquisition at `NMR/EXP-001-crude/10/` under the **case** folder. Keep the numbered acquisition folders and their `pdata/1/` files together.
2. Open the experiment and choose the **NMR yields** tab when it is available. Check the product and internal-standard integration regions, their proton counts and the amounts in mmol.
3. Select a run to see its spectrum. **Spectrum source** starts at **TopSpin's spectrum** for a new measurement. With numpy available, **Raw FID, processed here** transforms the acquisition using the displayed line broadening, point count and phase. A blank number field uses the acquisition default shown in the field.
4. **TopSpin's values** uses the stored phase, or zero without processing parameters. **Manual** accepts PHC0 and PHC1 in TopSpin degrees. The step buttons redraw the spectrum as you adjust phase. **Automatic zero-order** keeps the stored first-order phase (zero without processing parameters) and searches within 10° of TopSpin's PHC0, or around the full circle when processing parameters are absent.
5. Processing controls apply to the selected run. Choose **Use these processing settings for all runs** to share them. Choose **Integrate all runs** and review each value alongside its source and applied settings. Integrate again after changing a setting.
6. Select the runs to save. Each saved measurement keeps its processing settings when reopened. The screening results table and CSV identify the source. Saving NMR yields to screening runs is available for the yield metric and for older screens without a metric kind.

Hover over the spectrum or focus it with Tab and press **F** for the full spectrum. Scroll up over the plot for taller peaks and down for shorter peaks. Left-drag across the plot to zoom. Double-click to reset.

Under **Regions for this run**, type the edges in ppm or left-drag a region edge on the plot. Both regions then belong to this run. Its standard stays at the bounds you set. **Use the shared regions** restores the common settings. Integrate again before saving. The measurement and its settings tag identify manual bounds.

## Prepare a supporting information entry

Open **SI draft** to see the entry and working notes. **Copy entry** copies the formatted compound name, preparation, reviewed characterization and source IDs. Missing information or a blocking flag adds **Draft, not reviewed** to the entry. Review the working notes for missing facts and NMR reporting details.

For a proton acquisition, choose the sample and spectrum source under **Proposal from the spectrum, not reviewed**. The table shows first-order pattern estimates and baseline-corrected relative integrals. To scale proton counts, choose a reference group and enter its known count. **Copy to characterization editor** opens an unsaved draft. Check and correct the line, record who reviewed it and save the experiment.

## Attach files

On the experiment page, open **Attach file**, choose a file and its kind, and add a sample, run or note if useful. The browser accepts individual files up to 200 MB. To register a whole instrument folder, use `attach` on the command line. The experiment page lists the attachments and marks missing or changed files.

In a new notebook, uploads of kind **scheme** or **chemdraw** go in the experiment’s `scheme/` folder. Other uploads go in its `attachments/` folder. To display a scheme, enter its case-relative image path in **Edit**, such as `experiments/EXP-001/scheme/reaction.png`. The command line links files already inside the experiment in place and copies files from elsewhere. In a classic notebook, uploads go in `attachments/EXP-001/` and the command line links files already inside the case in place.

## Rebuild the Word notebook

1. Save your record changes and close the notebook in Word.
2. Choose **Rebuild Word notebook** under **Menu** → **Tools**, or use **Rebuild** in the top bar when records have changed. The app updates the Word notebook and the case index from the records.
3. If the app finds pending Word fields, use **Review and import them** to review them before rebuilding. This applies to notebooks with Word field import. New notebooks use the built-in static Word export. Record new observations in the app for those notebooks.

## Use the schedule, supplies and waste log

This page is off by default. Set `schedule_and_supplies: "on"` in the app settings and restart to enable it.

- Add tasks in **Schedule and supplies**. Set a time and duration, and choose equipment or a prerequisite task as needed. The schedule marks overlaps when tasks need the same equipment or both need you at the bench.
- Add supplies with their on-hand count and the count at which you want to follow up. Change the count as supplies are used or replaced. Low and ordered supplies appear on **Today**.
- Under **Waste bottles**, add a bottle with its label, waste stream, location and opening date. You can enter a capacity and type your own stream label.
- Add an entry under the bottle, or select **Log waste** on a bench card. On the bench card, check the filled experiment ID, choose an open bottle, edit the suggested contents and enter the volume in mL.
- Check the logged total against the capacity when one was entered. **Nearly full** is a reminder set by the researcher. The app sums the logged entries and uses the reminder fraction in the case settings, which defaults to 75%. **Today** shows full and nearly full bottles.
- Mark a bottle full or picked up as appropriate. Download its CSV when you need the dated entries for a pickup form.

## Work with an AI agent through the command line

Ask the agent to read the project folder's `AGENTS.md` first. Starting a notebook fills this file from `data/AGENTS.template.md` with the command for that folder. Claude reads the same rules through `CLAUDE.md`. Run `rules` to install missing files in an older project, or `rules --print` to read the filled template.

Ask the agent to read and save records through `run.py`. Give it the project folder, case, experiment ID and author to put in the change log. In an independent project, include `--root '<project folder>'` in every command. Run these examples in the project folder after replacing the example values.

```powershell
py -3 nbapp\run.py cases
py -3 nbapp\run.py ids 'My Case'
py -3 nbapp\run.py show 'My Case' EXP-001
py -3 nbapp\run.py save 'My Case' EXP-001 --file edit.yaml --by 'Agent' --expect '<hash>' --dry-run
py -3 nbapp\run.py save 'My Case' EXP-001 --file edit.yaml --by 'Agent' --expect '<hash>'
py -3 nbapp\run.py validate 'My Case'
```

Start a draft with the full record from `show`, keep fields you do not edit and use the hash shown there. If a newer save changes the hash, read the record again and review the differences before retrying. To create a record from a draft, use `new '<case>' --file <path> --by '<name>'`. To register a file or folder, use `attach '<case>' EXP-001 <path> --kind <kind> --by '<name>'`.

Review the dry run's old and new values, added and removed rows, validation notes and the basis beside each changed result. Once the researcher accepts the changes, repeat the save with the same file and hash, then validate and build. The [demo walk-through](DEMO.md) includes a refused edit and a review response.

See the [record format](SCHEMA.md) for field names and the [app reference](README.md) for the full command list.

## Back up by copying the folder

To archive one experiment from a new notebook, choose **Open the experiment folder** and copy the entire ID folder. Keep its ID when placing the copy under another per-experiment notebook’s `experiments/` directory. The journal and save history belong to the original case.

For a full backup, save open edits and close the app and Word. Copy the whole project folder to your backup location. Include the case folders, records, linked files, follow-ups and build settings. If you use an independent project root, copy that folder. Card layout and tick marks stay in browser storage.

## What the app does not do

- The app runs locally for one researcher. It does not sync with other computers or replace your lab's ELN.
- Supply counts are manual. A waste reminder reflects logged volume and is not a safety limit or a compatibility check.
- Review the phase, baseline, integration regions and assignments for each NMR yield you use.
- Follow your lab's procedures for safety, waste and pickup. The app records information and supplies prompts for review.
