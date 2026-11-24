# Architecture

> First draft written with the skeleton. Rewrite it in your own words as the pipeline changes.

## Stages and contracts

```
story/brief.md ──script──▶ storyboard.json ◀── the contract (schema/storyboard.schema.json)
                                │
         ┌──────────────┬───────┴───────┬──────────────┐
     narration      keyframes         music          (validate runs first, every time)
   Gemini TTS     FLUX/Workers AI   ACE-Step 1.5
         │              │            (Kaggle)
         │            shots
         │      Wan 2.2 (Kaggle) or Ken Burns
         └──────────────┴───────┬───────┘
                            assemble (FFmpeg)
                 film_9x16.mp4 · film_16x9.mp4 · subtitles_en.srt
```

| Stage | Reads from storyboard | Writes | Cache key (hash of) |
|---|---|---|---|
| validate | everything | nothing (exit 1 on error) | — |
| script | `story/brief.md`, current storyboard | `storyboard.draft.json`, narration lines | — (human reviews the draft) |
| narration | `shots[].narration.text`, `voice`, `language` | `outputs/narration/<shot>-<hash>.wav` | text, voice, style instruction, language, model |
| keyframes | `style`, `characters`, `shots[].image_prompt/shot_size/seed` | `outputs/keyframes/<shot>-<hash>.png` | full prompt, seed, model, steps (+ reference files for FLUX.2) |
| shots | `shots[].motion_prompt/seed/render` + keyframe hash | `outputs/shots/<shot>-<hash>.mp4`, `manifest.json` | keyframe hash, motion prompt, seed, size, frames, model |
| music | `music` | `outputs/music/candidates/`, `manifest.json` | — (a human chooses `music.chosen`) |
| assemble | everything + the manifests | `outputs/final/`, `outputs/radio_cut.mp4` | per-segment: source hash, move, crop, size |

Each stage writes a `manifest.json` mapping shot id → the file for the *current* storyboard, so assembly never
has to guess which of several cached files is current.

## Prompt composition
Keyframe prompt = shot size + `image_prompt` + each character's fixed `description` + the fixed `style_block`.
Only the shot-specific part varies between shots, which is what keeps characters and look consistent.
Motion prompts carry only motion and camera, because the keyframe already fixes subject, place and light.

## Caching
Outputs are named by a 12-character SHA-256 of their inputs. A stage skips any output that already exists, so a
rerun after editing one shot makes one new model call and re-renders one video segment. The style block is part
of every keyframe key, so changing it regenerates every keyframe — on purpose.

## Failure handling
- **Retries:** quota (429), overload (5xx) and network errors retry with exponential backoff and jitter (4 tries);
  every attempt is its own line in `runs.jsonl`. Other errors fail fast with the provider's message.
- **Fallbacks:** a Wan shot without a clip for its current inputs falls back to a Ken Burns move over the keyframe
  (flagged in the shots manifest and the build summary); no chosen score falls back to a placeholder pad.
  The pipeline always produces a complete film.
- **Validation before generation:** schema + semantic checks (unique ids, known characters, subtitles for every
  narrated line, cue ranges, 60–90 s total) run before any stage spends quota.
- **Consent gate:** stages that generate or publish a likeness refuse to run while a real person lacks recorded consent.
- **GPU work off-machine:** Wan and ACE-Step jobs are exported as JSON, run on Kaggle, and imported by file name
  (`<shot>-<clip_key>.mp4`), so a stale clip can never be matched to a changed shot. The Kaggle scripts skip
  clips that already exist, so a timed-out session can resume.

## Assembly (FFmpeg)
Narration lines are placed at each shot's start + `offset_s` → music trimmed, faded and ducked under the voice
with `sidechaincompress` → `loudnorm` to -14 LUFS / -1 dBTP → one segment per shot (Wan clip reframed with
`crop_focus_x`, or `zoompan` Ken Burns) → AI end card → concat → subtitles burned from an ASS file sized in real
pixels (vertical: kept above the bottom 20% that platform buttons cover) → both aspect ratios.
