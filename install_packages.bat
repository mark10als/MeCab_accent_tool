@echo off
cd /d "%~dp0"

set PYTHON=C:\Users\DAIBO\AppData\Local\Programs\Python\Python310\python.exe

echo === MeCab Accent Tool - Install Packages ===
echo.

if not exist "%PYTHON%" (
    echo ERROR: Python not found: %PYTHON%
    pause
    exit /b 1
)

%PYTHON% --version
echo.

echo [1/4] Installing gradio...
%PYTHON% -m pip install "gradio>=4.0"

echo.
echo [2/4] Installing mecab-python3...
%PYTHON% -m pip install "mecab-python3>=1.0"

echo.
echo [3/4] Installing pyopenjtalk-plus...
%PYTHON% -m pip install pyopenjtalk-plus

echo.
echo [4/4] Installing marine (UTF-8 mode)...
set PYTHONUTF8=1
%PYTHON% -m pip install marine
set PYTHONUTF8=

echo.
echo === Checking installed packages ===
%PYTHON% -c "import gradio; print('gradio:', gradio.__version__)"
%PYTHON% -c "import MeCab; print('MeCab: OK')"
%PYTHON% -c "import pyopenjtalk; print('pyopenjtalk-plus: OK')"
%PYTHON% -c "import marine; print('marine: OK')" 2>nul || echo marine: (not installed)
echo.
echo Done. Run launch_tool.bat to start.
echo.
pause
