# Ethics: consent, licences, labelling

## Consent record
Required before anything of a real person (face, likeness, voice) is generated. **Without this, the film scores
zero.** After recording consent, set `characters[].consent.recorded = true` in storyboard.json.

| Person | Relationship | What they agreed to (likeness / voice / their story / these exact words) | How recorded (voice note, message, signed) and where kept | Date |
|---|---|---|---|---|
| TODO | | | | |

Did they hear or see the narration lines before release? TODO

## Licences
Check each one yourself and note the date.

| Model / tool | Used for | Licence or terms | Output usable for a public post? | Checked |
|---|---|---|---|---|
| Wan 2.2 TI2V-5B | moving shots | Apache 2.0 (per brief) | | TODO |
| ACE-Step 1.5 | score | MIT; outputs usable commercially (per brief) | | TODO |
| FLUX.1 schnell / FLUX.2 klein 4B | keyframes | Apache 2.0 (klein 9B is non-commercial) | | TODO |
| Gemini Flash / Flash-Lite / TTS | script, translation, narration | Gemini API terms (free tier may use inputs for training) | | TODO |
| Cloudflare Workers AI | hosting FLUX | Cloudflare terms | | TODO |
| FFmpeg | assembly | LGPL/GPL | | TODO |

## Private data
What family details did you keep out of free endpoints that may train on inputs? TODO

## Labelling plan
- AI end card in the film (`storyboard.json` → `end_card`).
- Platform AI disclosure switched on when posting: TODO which platform and setting.
- Watermarks / provenance metadata (SynthID, C2PA) left intact: TODO.
- Style described by qualities, not by naming a living artist.
