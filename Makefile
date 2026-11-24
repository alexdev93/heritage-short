# Heritage Short — one command per step. `make film` runs the whole pipeline.
# ONLY=s03 limits keyframes/narration to some shots, e.g. `make keyframes ONLY=s03,s05`.

PY ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
ONLY_ARG = $(if $(ONLY),--only $(ONLY),)

.PHONY: help setup smoke test validate draft-storyboard translate narration keyframes candidates refs \
        shots shots-export shots-import music music-export music-import radio-cut film draft costs \
        fake-film fake-radio clean-tmp

help:
	@grep -E '^[a-z-]+:.*## ' Makefile | sed 's/:.*## /\t/' | expand -t 18

setup: ## create .venv and install dependencies
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt
	@[ -f .env ] || (cp .env.example .env && echo "created .env — fill in your keys")

smoke: ## call each provider once and log latency
	$(PY) -m pipeline.smoke

test: ## schema and cache tests
	$(PY) -m pytest -q tests

validate: ## validate storyboard.json against the schema
	$(PY) -m pipeline.validate

draft-storyboard: ## draft storyboard.draft.json from story/brief.md
	$(PY) -m pipeline.script draft

translate: ## fill narration.text from subtitle_en (TO_ENGLISH=1 for the reverse)
	$(PY) -m pipeline.script translate $(if $(TO_ENGLISH),--to-english,) $(if $(FORCE),--force,)

narration: ## TTS, one WAV per shot (cached)
	$(PY) -m pipeline.narration $(ONLY_ARG)

keyframes: ## one keyframe per shot (cached)
	$(PY) -m pipeline.keyframes build $(ONLY_ARG)

candidates: ## explore seeds for one shot: make candidates SHOT=s03 N=3
	$(PY) -m pipeline.keyframes candidates $(SHOT) -n $(or $(N),3)

refs: ## character sheet candidates: make refs CHAR=main_person N=4
	$(PY) -m pipeline.keyframes refs $(CHAR) -n $(or $(N),4)

shots: ## choose Wan clip or Ken Burns per shot
	$(PY) -m pipeline.shots build

shots-export: ## write Wan jobs for Kaggle
	$(PY) -m pipeline.shots export

shots-import: ## import Wan clips: make shots-import DIR=~/Downloads/clips
	$(PY) -m pipeline.shots import $(DIR)

music: ## resolve the score (chosen track or placeholder)
	$(PY) -m pipeline.music build

music-export: ## write the ACE-Step job for Kaggle/Colab
	$(PY) -m pipeline.music export -n $(or $(N),3)

music-import: ## import candidates: make music-import DIR=~/Downloads/music
	$(PY) -m pipeline.music import $(DIR)

radio-cut: ## narration + music on black, for user test 1
	$(PY) -m pipeline.run radio

film: ## the whole pipeline, both aspect ratios
	$(PY) -m pipeline.run film

draft: ## the whole pipeline at half resolution
	$(PY) -m pipeline.run draft

costs: ## tables for COSTS.md from runs.jsonl
	$(PY) -m pipeline.costs

fake-film: ## test the plumbing offline with stand-in models (outputs_fake/)
	PIPELINE_FAKE=1 $(PY) -m pipeline.run film

fake-radio: ## offline radio cut with stand-in models
	PIPELINE_FAKE=1 $(PY) -m pipeline.run radio

clean-tmp: ## delete intermediate segments (cached shots are kept)
	rm -rf outputs/tmp outputs_fake/tmp
