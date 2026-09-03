# AVR-25D — one command per thing worth doing.
#
# `make bench` is the only sanctioned source of numbers (NFR-5, PRD §11).
# A figure that reaches a slide traces to a row of results.json, and
# results.json comes from here.

PY      ?= backend/.venv/bin/python
SEQ     ?= 00 04 05     # several sequences pool into one result (§11.3.1)
MODE    ?= geometric
LIMIT   ?=
CACHE   ?= data/cache/network

LIMIT_ARG := $(if $(LIMIT),--limit $(LIMIT),)

.PHONY: help test bench bench-network bench-cached bench-authoritative \
	scenes finetune clean-bench

help:
	@echo "make test           — the whole pytest suite"
	@echo "make bench          — results.json + docs/RESULTS.md (geometric)"
	@echo "make bench-network  — same, live ONNX inference"
	@echo "make bench-cached   — same, from the prebuilt label cache"
	@echo "make bench-authoritative — the Day 12 run: all sequences, cached"
	@echo "make scenes         — regenerate the synthetic scenes S1-S7"
	@echo "make finetune       — Q-1 probe, 5-class split, fine-tune, before/after"
	@echo ""
	@echo "  SEQ='00 04 05'  MODE=geometric  LIMIT=  (override any of these)"

test:
	cd model && ../$(PY) -m pytest -q

bench:
	cd model && ../$(PY) -m avr25d.bench --seq $(SEQ) --mode $(MODE) $(LIMIT_ARG)

bench-network:
	cd model && ../$(PY) -m avr25d.bench --seq $(SEQ) --mode network $(LIMIT_ARG)

bench-cached:
	cd model && ../$(PY) -m avr25d.bench --seq $(SEQ) --mode cached \
		--cache $(CACHE) $(LIMIT_ARG)

# The Day 12 run: every sequence, cached mode, hazards included.  This is the
# command whose results.json is handed to Veda and stored in MongoDB.
bench-authoritative:
	cd model && ../$(PY) -m avr25d.bench --seq 00 04 05 --mode cached \
		--cache $(CACHE)

scenes:
	cd model && ../$(PY) -m avr25d.synth

# Days 9-10.  `probe` answers Q-1, `split` writes the 5-class manifest,
# `train` fine-tunes the decoder and head, `evaluate` produces the before/after.
finetune:
	$(PY) tools/finetune.py probe
	$(PY) tools/finetune.py split
	$(PY) tools/finetune.py train --epochs 3
	$(PY) tools/finetune.py evaluate

clean-bench:
	rm -f model/results.json docs/RESULTS.md
