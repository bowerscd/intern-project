#!/bin/sh
python -m pytest . --import-mode=importlib --cache-clear $@
