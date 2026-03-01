@echo off
setlocal enabledelayedexpansion
REM integration-tests\make.cmd — Windows equivalent of the integration-tests Makefile
REM Usage:  make help | install | up | down | test | clean

if "%PYTHON%"==""  set PYTHON=python
if "%PIP%"==""     set PIP=pip
if "%COMPOSE%"=="" set COMPOSE=docker compose

if "%~1"=="" goto :help
goto :%~1 2>nul || (
    echo Unknown target: %~1
    goto :help
)

:help
echo.
echo   Available targets:
echo.
echo   help      Show this help
echo   install   Install test dependencies
echo   up        Start the Docker Compose stack
echo   down      Stop the Docker Compose stack
echo   test      Run integration tests (starts stack automatically)
echo   clean     Tear down stack and remove volumes
echo.
goto :eof

:install
%PIP% install -r requirements.txt
goto :eof

:up
%COMPOSE% up --build -d
goto :eof

:down
%COMPOSE% down
goto :eof

:test
call :up
%PYTHON% -m pytest . -v --timeout=60
set TEST_EXIT=%ERRORLEVEL%
%COMPOSE% down
exit /b %TEST_EXIT%

:clean
%COMPOSE% down -v --remove-orphans
goto :eof
