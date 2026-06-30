@echo off
setlocal
set "ROOT=%~dp0"
set "PYTHONPATH=%ROOT%src;%PYTHONPATH%"
start "" pyw "%ROOT%main.py" %*
