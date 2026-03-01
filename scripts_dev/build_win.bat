@echo off
REM build_win.bat — Build SuperBirdStamp Windows package using PyInstaller
REM
REM Usage (from project root):
REM   scripts_dev\build_win.bat [--clean] [--console]
REM
REM Options:
REM   --clean    Remove dist\ and build\ before building
REM   --console  Build with console window (for viewing logs; exe shows terminal)
REM
REM Prerequisites (run once):
REM   pip install pyinstaller pyinstaller-hooks-contrib
REM
REM Output:
REM   dist\SuperBirdStamp\SuperBirdStamp.exe  (onedir bundle)
REM   dist\SuperBirdStamp-win.zip
REM ---------------------------------------------------------------------------

setlocal enabledelayedexpansion

REM ── locate project root ──────────────────────────────────────────────────────
cd /d "%~dp0\.."
set "PROJECT_ROOT=%CD%"

REM ── parse arguments ──────────────────────────────────────────────────────────
set "CLEAN=0"
set "CONSOLE=0"
:parse_args
if "%~1"=="--clean" ( set "CLEAN=1" & shift & goto parse_args )
if "%~1"=="--console" ( set "CONSOLE=1" & shift & goto parse_args )
if not "%~1"=="" ( echo Unknown option: %~1 & exit /b 1 )

REM ── resolve Python ───────────────────────────────────────────────────────────
set "PYTHON=python"
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"

%PYTHON% --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: python not found. Activate your venv first.
    exit /b 1
)

REM ── ensure PyInstaller is available ──────────────────────────────────────────
%PYTHON% -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    %PYTHON% -m pip install pyinstaller pyinstaller-hooks-contrib
    if errorlevel 1 ( echo ERROR: pip install failed. & exit /b 1 )
)

set "APP_NAME=SuperBirdStamp"
set "APP_DIR=dist\%APP_NAME%"
set "ZIP_FILE=dist\%APP_NAME%-win.zip"

REM ── optional clean ────────────────────────────────────────────────────────────
if "%CLEAN%"=="1" (
    echo Cleaning dist\ and build\ ...
    if exist dist rmdir /s /q dist
    if exist build rmdir /s /q build
)

REM ── build ─────────────────────────────────────────────────────────────────────
set "SPEC_FILE=BirdStamp_win.spec"
if "%CONSOLE%"=="1" (
    echo Building with CONSOLE (log visible in terminal) ...
    if not exist build mkdir build
    %PYTHON% -c "p=open('BirdStamp_win.spec', encoding='utf-8').read(); open('build/BirdStamp_win_console.spec', 'w', encoding='utf-8').write(p.replace('console=False', 'console=True'))"
    set "SPEC_FILE=build\BirdStamp_win_console.spec"
)

echo ============================================================
echo  Building %APP_NAME% (this may take several minutes) ...
echo ============================================================

%PYTHON% -m PyInstaller %SPEC_FILE% --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    exit /b 1
)

if not exist "%APP_DIR%" (
    echo ERROR: Build failed — %APP_DIR% not found.
    exit /b 1
)

REM ── smoke test ───────────────────────────────────────────────────────────────
set "EXE=%APP_DIR%\SuperBirdStamp.exe"
if not exist "%EXE%" (
    echo ERROR: Executable not found: %EXE%
    exit /b 1
)

echo.
echo Build succeeded: %EXE%
echo.
echo Smoke test — launching with --help ...
"%EXE%" --help >nul 2>&1
echo   Smoke test complete (non-zero exit is normal for GUI-only builds).

REM ── create zip (PowerShell Compress-Archive) ──────────────────────────────────
echo.
echo Creating zip: %ZIP_FILE% ...
if exist "%ZIP_FILE%" del /q "%ZIP_FILE%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Compress-Archive -Path '%APP_DIR%' -DestinationPath '%ZIP_FILE%' -Force"
if errorlevel 1 (
    echo WARNING: zip creation failed. Packaged folder is still at %APP_DIR%
) else (
    echo Zip created: %ZIP_FILE%
)

echo.
echo Done.
echo   Dir : %APP_DIR%\
echo   Zip : %ZIP_FILE%
endlocal
