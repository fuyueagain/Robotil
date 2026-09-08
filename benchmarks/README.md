# B84 Baselines

`B84-reported` records only the tracked official-submission artifacts under
`大师赛第一期赛题1—跑得快-王莹莹—18540293911`. It is an evidence record, not a
reconstruction of the historical command, model, weights, or parameters: those
unknown values remain JSON `null` and are named in `unknown_fields`.

`B84-reproduced` is a separately named current-code rerun contract. Its output
paths are under `output/b84-reproduced/`, and its parameters are current-code
defaults rather than claims about the reported submission.

Run the report generator from the repository root:

```powershell
D:/Miniconda/Scripts/conda.exe run --no-capture-output -n wham_gmr python scripts/build_baseline_report.py benchmarks/baselines/B84-reported.json output/baseline-reports
D:/Miniconda/Scripts/conda.exe run --no-capture-output -n wham_gmr python scripts/build_baseline_report.py benchmarks/baselines/B84-reproduced.json output/baseline-reports
```

Each command writes identity-specific JSON and Markdown reports. Missing local
generated artifacts are recorded as missing evidence; present CSV and metadata
artifacts are checked against the declared 37-value linglong2 qpos contract.
