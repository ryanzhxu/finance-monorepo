PYTHON ?= .venv/bin/python

.PHONY: postman postman-push

postman:
	$(PYTHON) tools/generate_postman.py

postman-push:
	$(PYTHON) tools/postman_sync.py
