.PHONY: install install-browser test lint typecheck run worker scheduler outbox metrics-sync migrate-postgres mcp demo schemas contracts package train-ranker loadtest

install:
	python -m pip install -e '.[dev,enterprise,ml,vision]'

install-browser:
	playwright install chromium

test:
	pytest --cov=xhs_skill --cov-report=term-missing

lint:
	ruff check .

typecheck:
	mypy src/xhs_skill scripts

run:
	uvicorn xhs_skill.api.app:create_app --factory --host 127.0.0.1 --port 8080 --reload

worker:
	xhs-skill worker

scheduler:
	python scripts/run_scheduler.py

outbox:
	python scripts/run_outbox.py

metrics-sync:
	python scripts/run_metrics_sync.py --tenant "*"

migrate-postgres:
	python scripts/migrate_postgres.py

mcp:
	python -m xhs_skill.mcp.server --transport stdio

demo:
	xhs-skill pipeline --topic "通勤防晒" --provider fixture --output output/demo.json

schemas:
	python scripts/export_schemas.py

contracts:
	python scripts/export_contracts.py

train-ranker:
	python scripts/train_lambdamart.py --help

package:
	python scripts/package_skill.py

loadtest:
	locust -f loadtests/locustfile.py --host http://localhost:8080
