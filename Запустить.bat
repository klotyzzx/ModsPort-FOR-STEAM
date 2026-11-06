@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (
    py -3 loader.py
    goto finished
)
where python >nul 2>&1
if not errorlevel 1 (
    python loader.py
    goto finished
)
echo Python не найден. Установите Python 3.10 или новее с python.org.
echo При установке отметьте Add python.exe to PATH и компонент Tcl/Tk.
pause
exit /b 1
:finished
if errorlevel 1 (
    echo.
    echo Программа завершилась с ошибкой. Сообщение выше поможет найти причину.
    pause
)
