@echo off
setlocal enabledelayedexpansion
REM backend\make.cmd — Windows equivalent of the backend Makefile
REM Usage:  make help | install | build | test | test-cov | lint | format | clean | docker | dev

if "%PYTHON%"==""  set PYTHON=python
if "%PIP%"==""     set PIP=pip
if "%IMAGE%"==""   set IMAGE=vibe-coded-backend
if "%TAG%"==""     set TAG=latest

if "%~1"=="" goto :help
goto :%~1 2>nul || (
    echo Unknown target: %~1
    goto :help
)

:help
echo.
echo   Available targets:
echo.
echo   help        Show this help
echo   install     Install runtime and test dependencies
echo   build       Run Alembic migration check
echo   test        Run the test suite
echo   test-cov    Run tests with coverage report
echo   lint        Lint with ruff
echo   format      Auto-format with ruff
echo   clean       Remove build artifacts and caches
echo   docker      Build the Docker image
echo   dev         Run the development server with auto-reload
echo.
goto :eof

:install
%PIP% install -r requirements.txt -r tests\requirements.txt
goto :eof

:build
%PYTHON% -m alembic check 2>nul || %PYTHON% -m alembic heads
goto :eof

:test
%PYTHON% -m pytest tests/ -v --import-mode=importlib --cache-clear
goto :eof

:test-cov
%PYTHON% -m pytest tests/ -v --import-mode=importlib --cache-clear --cov=. --cov-report=term-missing
goto :eof

:lint
%PYTHON% -m ruff check .
goto :eof

:format
%PYTHON% -m ruff format .
goto :eof

:clean
for /d /r %%d in (__pycache__) do if exist "%%d" rd /s /q "%%d"
if exist .pytest_cache rd /s /q .pytest_cache
if exist .ruff_cache rd /s /q .ruff_cache
if exist .hypothesis rd /s /q .hypothesis
if exist .coverage del .coverage
if exist htmlcov rd /s /q htmlcov
goto :eof

:docker
docker build -t %IMAGE%:%TAG% .
goto :eof

:dev
%PYTHON% -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
goto :eof
