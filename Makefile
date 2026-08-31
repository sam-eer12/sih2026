# AVR-25D — one command per thing worth doing.
#
# `make bench` is the only sanctioned source of numbers (NFR-5, PRD §11).
# A figure that reaches a slide traces to a row of results.json, and
# results.json comes from here.

PY      ?= backend/.venv/bin/python
SEQ     ?= 04
MODE    ?= geometric
LIMIT   ?=
CACHE   ?= data/cache/network

LIMIT_ARG := $(if $(LIMIT),--limit $(LIMIT),)

.PHONY: help test bench bench-network bench-cached scenes clean-bench

help:
	@echo "make test           — the whole pytest suite"
	@echo "make bench          — results.json + docs/RESULTS.md (geometric)"
	@echo "make bench-network  — same, live ONNX inference"
	@echo "make bench-cached   — same, from the prebuilt label cache"
	@echo "make scenes         — regenerate the synthetic scenes S1-S5"
	@echo ""
	@echo "  SEQ=04  MODE=geometric  LIMIT=  (override any of these)"

test:
	cd model && ../$(PY) -m pytest -q

bench:
	cd model && ../$(PY) -m avr25d.bench --seq $(SEQ) --mode $(MODE) $(LIMIT_ARG)

bench-network:
	cd model && ../$(PY) -m avr25d.bench --seq $(SEQ) --mode network $(LIMIT_ARG)

bench-cached:
	cd model && ../$(PY) -m avr25d.bench --seq $(SEQ) --mode cached \
		--cache $(CACHE) $(LIMIT_ARG)

scenes:
	cd model && ../$(PY) -m avr25d.synth

clean-bench:
	rm -f model/results.json docs/RESULTS.md
