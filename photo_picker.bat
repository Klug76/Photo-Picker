@echo off
python "%~dp0photo_picker.py" %*
if errorlevel 1 (
    echo.
    echo Error: make sure Python and Pillow are installed.
    echo   pip install Pillow
    pause
)
