@echo off
setlocal

cd /d "%~dp0"

echo [1/5] Cleaning old build folders...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist release rmdir /s /q release

echo [2/5] Building GUI...
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm gui.spec
if errorlevel 1 goto :error

echo [3/5] Building backend...
.\backend\.venv\Scripts\python.exe -m PyInstaller --noconfirm backend.spec
if errorlevel 1 goto :error

echo [4/5] Creating release folder...
mkdir "release\TarkoFF Stream Center"
mkdir "release\TarkoFF Stream Center\backend"

xcopy /e /i /y "dist\TarkoFF Stream Center\*" "release\TarkoFF Stream Center\"
xcopy /e /i /y "dist\backend\*" "release\TarkoFF Stream Center\backend\"

copy /y "start_app.bat" "release\TarkoFF Stream Center\start_app.bat" >nul

echo [5/5] Done.
echo Release folder:
echo %cd%\release\TarkoFF Stream Center
exit /b 0

:error
echo.
echo Build failed.
exit /b 1