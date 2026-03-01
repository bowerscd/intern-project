@echo off
setlocal enabledelayedexpansion
REM frontend\make.cmd — Windows equivalent of the frontend Makefile
REM Usage:  make help | install | build | test | test-py | test-ts | lint | format | clean | docker | dev

if "%PYTHON%"==""      set PYTHON=python
if "%PIP%"==""         set PIP=pip
if "%NPM%"==""         set NPM=npm
if "%OPENAPI_URL%"=="" set OPENAPI_URL=http://localhost:8000/openapi.json
if "%IMAGE%"==""       set IMAGE=vibe-coded-frontend
if "%TAG%"==""         set TAG=latest

if "%~1"=="" goto :help
goto :%~1 2>nul || (
    echo Unknown target: %~1
    goto :help
)

:help
echo.
echo   Available targets:
echo.
echo   help              Show this help
echo   install           Install Python and Node dependencies
echo   build             Compile TypeScript to static/dist
echo   generate-openapi  Regenerate the OpenAPI client
echo   dev               Run the Flask development server
echo   test              Run all tests (Python + TypeScript)
 echo   test-py           Run Python tests only
 echo   test-py-cov       Run Python tests with coverage
 echo   test-ts           Run TypeScript (vitest) tests only
 echo   test-ts-cov       Run TypeScript tests with coverage
echo   lint              Lint Python (ruff) and TypeScript (tsc)
echo   format            Auto-format Python code with ruff
echo   clean             Remove build artifacts and caches
echo   docker            Build the Docker image
echo.
goto :eof

:install
%PIP% install -r requirements.txt -r tests\requirements.txt
%NPM% install
goto :eof

:build
call npx tsc -p tsconfig.json
goto :eof

:generate-openapi
set OPENAPI_URL=%OPENAPI_URL%
%PYTHON% scripts\generate_openapi_client.py
goto :eof

:dev
set FLASK_APP=app.py
set FLASK_DEBUG=1
flask run --port 5001
goto :eof

:test
call :test-py
call :test-ts
goto :eof

:test-py
%PYTHON% -m pytest tests/ -v
goto :eof

:test-py-cov
%PYTHON% -m pytest tests/ --cov=app --cov-report=term-missing
goto :eof

:test-ts
call npx vitest run
goto :eof

:test-ts-cov
call npx vitest run --coverage
goto :eof

:lint
%PYTHON% -m ruff check .
call npx tsc -p tsconfig.json --noEmit
goto :eof

:format
%PYTHON% -m ruff format .
goto :eof

:clean
if exist static\dist rd /s /q static\dist
for /d /r %%d in (__pycache__) do if exist "%%d" rd /s /q "%%d"
if exist .pytest_cache rd /s /q .pytest_cache
if exist .ruff_cache rd /s /q .ruff_cache
if exist .coverage del .coverage
if exist htmlcov rd /s /q htmlcov
goto :eof

:docker
docker build -t %IMAGE%:%TAG% .
goto :eof
