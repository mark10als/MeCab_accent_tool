@echo off
cd /d "%~dp0"

set PYTHON=C:\Users\DAIBO\AppData\Local\Programs\Python\Python310\python.exe

if not exist "%PYTHON%" (
    echo ERROR: Python not found: %PYTHON%
    pause
    exit /b 1
)

echo Starting MeCab Accent Tool...
echo URL: http://127.0.0.1:7861
echo.
%PYTHON% mecab_accent_tool.py
pause
