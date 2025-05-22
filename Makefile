.PHONY: clean virtualenv test docker dist dist-upload

clean:
	find . -name '*.py[co]' -delete

virtualenv:
	virtualenv --prompt '|> ytdl-sync <| ' env
	env/bin/pip install --upgrade pip
	env/bin/pip install -r requirements.txt
	env/bin/pip install -r requirements-dev.txt
	@echo
	@echo "VirtualENV Setup Complete. Now run: source env/bin/activate"
	@echo

style:
	git ls-files --cached --modified --exclude-standard |egrep \.py$$ |xargs env/bin/pycodestyle --config .pycodestyle

autopep:
	git ls-files --cached --modified --exclude-standard |egrep \.py$$ |xargs env/bin/autopep8 -i

test:
	python -m pytest \
	        -v \
	        --cov=storops \
	        --cov-report=term \
	        --cov-report=html:coverage-report \
	        tests/

docker: clean
	docker build -t storops:latest .

dist: clean
	rm -rf dist/*
	python setup.py sdist
	python setup.py bdist_wheel
