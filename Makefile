export PYTHONPATH := src

.PHONY: install seed test evals demo api dashboard

install:
	pip install -r requirements.txt

seed:
	python -m data.generate_data

test:
	python -m pytest tests/ -q

evals:
	python -m evals.run_evals

demo: seed
	python -m inventory_agents.cli cycle_review

api:
	uvicorn inventory_agents.api:app --reload --app-dir src

dashboard:
	streamlit run dashboard/app.py
