# Demo walk-through

## 1. Start the demo and look at EXP-001

Open PowerShell in `nbapp`. These commands create an empty temporary project. The `nb` function runs the app against that folder for the rest of this session. The notebook uses invented data. Reference 1 supplies the literature procedure and its 90–94% isolated yield (DOI 10.15227/orgsyn.012.0022).

```powershell
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$demoRoot = Join-Path ([IO.Path]::GetTempPath()) ('notebook-' + [guid]::NewGuid())
[void][IO.Directory]::CreateDirectory($demoRoot)
function nb { py -3 -B .\run.py --root $demoRoot @args }
$case = 'Demo notebook'
$edits = '.\data\demo\edits'
nb demo
```

```text
Started Demo notebook
Walk-through: Help > Demo walk-through (nbapp/DEMO.md)
```

Read the experiment and copy its hash from `show`. The second line displays the fields at issue. The third copies the hash into `$hash`. Your hash can differ from the example.

```powershell
$shown = nb show $case EXP-001
$shown | Where-Object { $_ -match '^(# hash:|title:|key_result:|result:)' }
$hash = $shown[0] -replace '^# hash: ', ''
```

```text
# hash: 9e86170385f5ac0f
title: Dibenzalacetone by double aldol condensation
key_result: 2.41 g, 51% (as entered)
result: {text: '2.41 g, 51%', basis: Recorded mass. Yield as entered at the bench.}
```

Enter `$shown` to read the full record, including the materials and open flag 1.1. In the app, **Open a demo notebook** on the start screen or under **Menu → Tools** opens the same teaching example in the current project.

If you open the fresh demo in the app, choose **Experiments → Arrange by → Reaction**. The heading **dibenzalacetone from acetone** contains Exp 1, 2 and 3. Choose Exp 3 to see the planned repeat. **Reference and review** opens with Exp 2, run 1, at 88% by measured NMR yield. The target and literature entries in Exp 2 are excluded. After the correction below, Exp 1 reads 102.9% of theory. A result above 100% is never offered as a reference, so Exp 3 keeps Exp 2, run 1.

## 2. Give the agent the researcher's request

“Check the yield of EXP-001 against the recorded mass and the stoichiometry, and record what you find.”

Give the agent the project folder and ask it to read `AGENTS.md`. To follow along without an agent, use the three shipped edit files below. They are full records for the unchanged demo at each step. If a save is refused as stale, start again in a fresh project folder.

The 2.41 g mass gives 10.286 mmol. Two benzaldehydes and one acetone give one product, so 10.0 mmol acetone sets the theoretical mass at 2.343 g. The bench calculation used 20.0 mmol benzaldehyde to obtain 51%. The recorded mass is 102.9% of theory.

## 3. Try the edit with the basis missing

```powershell
nb save $case EXP-001 --file "$edits\missing-basis.yaml" --by 'Demo agent' --expect $hash
```

```text
Not saved. 'result' needs both text and basis.
```

This refusal exits with code 1. The original record and hash still apply.

## 4. Review the dry run

```powershell
$edit = @('save', $case, 'EXP-001', '--file', "$edits\recalculate.yaml", '--by', 'Demo agent', '--summary', 'Check recorded yield', '--expect', $hash)
nb @edit --dry-run
```

```text
warn: Isolated result: yield 102.9% is above 100%. Check for residual solvent or water in the weighed product, the limiting reagent, and the purity of the standard.
key_result: '2.41 g, 51% (as entered)' -> '2.41 g = 103% of theory; check'
result.text: '2.41 g, 51%' -> '2.41 g, 10.286 mmol = 102.9% of theory'
result.basis: 'Recorded mass. Yield as entered at the bench.' -> 'Recalculated from the recorded mass against 10.0 mmol acetone (2 PhCHO + 1 acetone → 1 product). The bench entry of 51% divided by 20.0 mmol benzaldehyde. Purity not assessed.'
flags[1.2]: added {tier: blocking, text: '2.41 g exceeds the theoretical 2.343 g. Check the dry mass, residual solvent and purity.'}
flags[1.3]: added {tier: needed, text: 'Confirm whether the 2.41 g was weighed before or after drying. Ref 1 dries the solid to constant weight.'}
Would save
```

Read the old and new results, the recalculation basis and both flags before accepting the edit.

## 5. Save and read the change log

```powershell
nb @edit
```

```text
warn: Isolated result: yield 102.9% is above 100%. Check for residual solvent or water in the weighed product, the limiting reagent, and the purity of the standard.
key_result: '2.41 g, 51% (as entered)' -> '2.41 g = 103% of theory; check'
result.text: '2.41 g, 51%' -> '2.41 g, 10.286 mmol = 102.9% of theory'
result.basis: 'Recorded mass. Yield as entered at the bench.' -> 'Recalculated from the recorded mass against 10.0 mmol acetone (2 PhCHO + 1 acetone → 1 product). The bench entry of 51% divided by 20.0 mmol benzaldehyde. Purity not assessed.'
flags[1.2]: added {tier: blocking, text: '2.41 g exceeds the theoretical 2.343 g. Check the dry mass, residual solvent and purity.'}
flags[1.3]: added {tier: needed, text: 'Confirm whether the 2.41 g was weighed before or after drying. Ref 1 dries the solid to constant weight.'}
Saved
```

In **Menu → Reference → Change log**, the row gives the author, origin, experiment, summary and field names. Read those columns from this save's entry in PowerShell.

```powershell
$journal = Join-Path $demoRoot "$case\_logs\changes.jsonl"
$change = Get-Content -LiteralPath $journal -Encoding utf8 -Tail 1 | ConvertFrom-Json
'{0} | {1} | {2} | {3} | {4}' -f $change.by,$change.via,$change.exp,$change.summary,($change.fields -join ', ')
```

```text
Demo agent | cli | EXP-001 | Check recorded yield | flags, key_result, result
```

## 6. Record the researcher's review and close flag 1.3

Start the app in this project and open the address it prints.

```powershell
nb serve --no-browser --port 8875 | Where-Object { $_ -like 'Open http*' }
```

```text
Open http://127.0.0.1:8875/  (Ctrl+C here to stop)
```

Open **Experiments → Exp 1**. Select the blocking count in the heading to open **Edit** and read flags 1.2 and 1.3. Return to the Record page and open **Review** in the top bar. Under **Review response**, enter the following text and choose **Save response**.

```text
Weighed damp from the filter, before drying. Dry to constant weight and reweigh. Demo researcher, 3 Nov 2026.
```

Press **Ctrl+C** in PowerShell to stop the app. Copy the new hash from `show` and check the saved response.

```powershell
$shown = nb show $case EXP-001
$shown | Where-Object { $_ -match '^(# hash:|entries:)' }
$hash = $shown[0] -replace '^# hash: ', ''
```

```text
# hash: 1c9133710506fa40
entries: {review_exp01: 'Weighed damp from the filter, before drying. Dry to constant weight and reweigh. Demo researcher, 3 Nov 2026.'}
```

Preview the follow-up edit. The response settles when the solid was weighed. Flag 1.2 stays open until a dry mass is recorded.

```powershell
$close = @('save', $case, 'EXP-001', '--file', "$edits\after-review.yaml", '--by', 'Demo agent', '--summary', 'Close flag 1.3 after review', '--expect', $hash)
nb @close --dry-run
```

```text
warn: Isolated result: yield 102.9% is above 100%. Check for residual solvent or water in the weighed product, the limiting reagent, and the purity of the standard.
flags[1.3]: removed {tier: needed, text: 'Confirm whether the 2.41 g was weighed before or after drying. Ref 1 dries the solid to constant weight.'}
history[0]: added '1.3 (when the solid was weighed) closed 3 Nov 2026: the researcher confirmed it was weighed damp from the filter, before drying.'
Would save
```

Accept the move to history and save it.

```powershell
nb @close
```

```text
warn: Isolated result: yield 102.9% is above 100%. Check for residual solvent or water in the weighed product, the limiting reagent, and the purity of the standard.
flags[1.3]: removed {tier: needed, text: 'Confirm whether the 2.41 g was weighed before or after drying. Ref 1 dries the solid to constant weight.'}
history[0]: added '1.3 (when the solid was weighed) closed 3 Nov 2026: the researcher confirmed it was weighed damp from the filter, before drying.'
Saved
```

## 7. Validate and build the notebook

```powershell
nb validate $case
"validate exit $LASTEXITCODE"
nb build $case
Get-Content -Encoding utf8 -LiteralPath (Join-Path $demoRoot "$case\index.md") | Where-Object { $_ -like '- EXP-001 *' }
```

```text
Demo notebook  EXP-001  warn  Isolated result: yield 102.9% is above 100%. Check for residual solvent or water in the weighed product, the limiting reagent, and the purity of the standard.
validate exit 0
Demo notebook: Wrote index.md and Demo notebook.docx.
- EXP-001 · open · synthesis · Dibenzalacetone by double aldol condensation · 2.41 g = 103% of theory; check
```

The point of the example: the agent did the arithmetic and raised the problem, and the researcher settled one question and left the other open.
