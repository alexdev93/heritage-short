# GPU stages on Kaggle

Wan 2.2 (moving shots) and ACE-Step 1.5 (score) need a GPU. Kaggle gives about 30 GPU hours a week after phone
verification. The repo stays the source of truth: jobs go out as JSON, results come back by file name.

## Moving shots (Wan 2.2 TI2V-5B)
1. `make keyframes` then `make shots-export` → `outputs/shots/export/` (jobs.json + keyframes).
2. Copy `kaggle/wan22_shots.py` into that folder. On kaggle.com: Datasets → New dataset → upload the folder.
3. New notebook → Settings: Accelerator **GPU T4 x2**, Internet **on** → Add input → your dataset.
4. Cell: `!python /kaggle/input/<dataset>/wan22_shots.py`. Draft first with `WAN_STEPS=20` and short shots.
5. Download `/kaggle/working/out` (Output panel) and run `make shots-import DIR=~/Downloads/out`, then `make film`.

Sessions time out; the script skips clips that already exist, so rerun it to resume (use "Save Version" so
`/kaggle/working` survives). Log GPU minutes — they land in runs.jsonl via `runs_kaggle.jsonl`.

## Score (ACE-Step 1.5)
1. Fill in `setup()` and `generate_one()` in `kaggle/acestep_music.py` from the ACE-Step 1.5 README.
2. `make music-export N=3` → `outputs/music/export/jobs.json`; upload it with the script as above.
3. Run, download `music_out`, `make music-import DIR=...`, listen under the narration, set `music.chosen` and
   `music.chosen_reason` in storyboard.json, and log the comparison in EXPERIMENTS.md.

If the GPU fails you: Ken Burns shots and the placeholder pad keep the film complete. Write down what failed.
