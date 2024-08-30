

.PHONY: all build_wheel list_wheel build_sdist list_sdist install clean test tox

all: build_wheel list_wheel

build_wheel: clean
	python -m build --wheel .

list_wheel: build_wheel
	unzip -l dist/*.whl

build_sdist: clean
	python -m build --sdist .

list_sdist: build_sdist
	tar -ztvf dist/*.tar.gz

install: build_wheel
	pip install --force-reinstall dist/*.whl

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache .tox .venv
	rm -rf htmlcov .coverage*
	rm -rf build dist
	find . -name '*.egg-info' -type d | xargs rm -rf
	find . -name '__pycache__' -type d | xargs rm -rf

test:
	pytest -v --doctest-modules

tox: clean
	tox
