.PHONY: setup api worker demo down reset chat ask learnset-sync ensure-pdf gkb-seed

setup:
	./scripts/setup_local.sh

api:
	./scripts/run_api.sh

worker:
	./scripts/run_worker.sh

demo:
	./scripts/vertical_slice_demo.sh

chat:
	./scripts/cli.sh chat --persona $(or $(PERSONA),sales) --technical-depth $(or $(DEPTH),medium) --output-tone $(or $(TONE),direct) --conciseness $(or $(CONCISE),0.6) $(if $(FAST),--fast-mode,)

ask:
	./scripts/cli.sh ask --persona $(or $(PERSONA),sales) --technical-depth $(or $(DEPTH),medium) --output-tone $(or $(TONE),direct) --conciseness $(or $(CONCISE),0.6) $(if $(FAST),--fast-mode,) "$(Q)"

ensure-pdf:
	@if [ ! -x api/.venv/bin/python ]; then \
		echo "api/.venv missing. Run: make setup"; \
		exit 1; \
	fi
	@api/.venv/bin/python -c "import pypdf" >/dev/null 2>&1 || api/.venv/bin/pip install pypdf==5.1.0

learnset-sync: ensure-pdf
	./scripts/cli.sh learnset sync --path ./learnset

gkb-seed:
	./scripts/cli.sh gkb seed

down:
	docker compose down

reset:
	docker compose down -v
