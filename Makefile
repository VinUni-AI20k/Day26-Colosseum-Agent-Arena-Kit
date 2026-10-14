VENV := .venv
# Prefer the interpreter that actually exists; this also works when GNU make
# does not import Windows_NT from the parent environment.
ifneq ($(wildcard $(VENV)/Scripts/python.exe),)
PY ?= py -3.12
VENV_PY := $(VENV)/Scripts/python.exe
else
PY ?= python3.12
VENV_PY := $(VENV)/bin/python
endif
BOT ?= rookie
# GNU make defines AS as its assembler; use the command-line AS value as the role.
ROLE ?= all
ifeq ($(origin AS), command line)
ROLE := $(AS)
endif

.PHONY: install spar ui validate validate-bots qualify submit test clean check-no-key check-referee check-world doctor

install:
	uv venv --python 3.12 --seed $(VENV) || $(PY) -m venv $(VENV)
	$(VENV_PY) -m pip install -q --upgrade pip
	$(VENV_PY) -m pip install -q pytest
	@echo ready. no api key needed, ever.

spar:
	$(VENV_PY) spar.py --bot $(BOT) --as $(ROLE)

ui:
	$(VENV_PY) -m kit.arena_ui.build_ui
	$(VENV_PY) -m kit.arena_ui.serve

WORLD := $(firstword $(wildcard kit/world/*/manifest.json))

validate:
	$(VENV_PY) -c "import sys; sys.exit(0 if '$(WORLD)' else 'no world exported - run make check-world')"
	$(VENV_PY) validate_deck.py deck/deck.json deck/lineup.json --world "$(dir $(WORLD))"

validate-bots:
	$(VENV_PY) -c "import sys; sys.exit(0 if '$(WORLD)' else 'no world exported - run make check-world')"
	$(VENV_PY) -c "import subprocess,sys; bots=('rookie','operator','adversary'); world='$(dir $(WORLD))'; results=[subprocess.run([r'$(VENV_PY)','validate_deck.py',f'bots/{b}/deck.json',f'bots/{b}/lineup.json','--world',world]).returncode for b in bots]; sys.exit(any(results))"

qualify:
	@echo make qualify: retired - nothing consumed submissions/radar.json.
	@echo Your conformance check is make test (the public suite).
	@echo Then: make validate and make submit TEAM=your-team
	@exit 1

submit: validate
	$(VENV_PY) -c "import sys; sys.exit(0 if '$(TEAM)' else 'usage: make submit TEAM=<your-team-name>')"
	$(VENV_PY) -m kit.submit --team "$(TEAM)"

test: check-no-key
	$(VENV_PY) -m pytest tests/

check-referee:
	@$(VENV_PY) -c "import os,sys; sys.exit(0 if os.path.isdir('kit/referee') else 'kit/referee missing - ask your instructor to run tools.sync_referee')"
	@$(VENV_PY) -c "from kit.referee.rubric import CLASSES; from kit.referee.adjudicate import LOCAL_ONLY; print(f'referee: {len(CLASSES)} classes, local_only={LOCAL_ONLY}')"

check-world:
	@$(VENV_PY) -c "from pathlib import Path; import sys; sys.exit(0 if Path(r'$(WORLD)').is_file() else 1)"
	@$(VENV_PY) -c "import json; m=json.load(open(r'$(WORLD)', encoding='utf8')); print('world', m.get('world_id'), '-', sum(m.get('counts',{}).values()), 'pages')"
	@$(VENV_PY) -c "from pathlib import Path; import sys; sys.exit('FAIL: truth.json must never ship to students' if any(x.name == 'truth.json' for x in Path('kit/world').rglob('truth.json')) else 0)"

doctor: check-no-key check-world check-referee validate
	@echo ready to spar.

check-no-key:
	@$(VENV_PY) -m kit.gate_no_key

clean:
	$(PY) -c "import pathlib,shutil; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('__pycache__') if p.is_dir()]; shutil.rmtree('.pytest_cache', ignore_errors=True)"
