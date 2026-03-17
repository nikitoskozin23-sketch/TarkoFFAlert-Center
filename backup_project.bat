@echo off
setlocal

cd /d "%~dp0"

set "PROJECT_DIR=%cd%"
set "BACKUP_ROOT=E:\OBS\BACKUPS"
set "RELEASE_EXE=%PROJECT_DIR%\release\TarkoFF Stream Center\TarkoFF Stream Center.exe"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set "STAMP=%%i"

set "FOLDER_NAME=tarkoff_stream_center_v0_1_%STAMP%"
set "DEST_DIR=%BACKUP_ROOT%\%FOLDER_NAME%"
set "ZIP_PATH=%BACKUP_ROOT%\%FOLDER_NAME%.zip"
set "COMMIT_MSG=Auto backup %STAMP%"
set "COMMIT_CREATED=0"

echo ========================================
echo   BACKUP + SMART GIT PUSH + RESTART
echo ========================================
echo Project: %PROJECT_DIR%
echo Backup : %DEST_DIR%
echo Zip    : %ZIP_PATH%
echo.

echo [1/8] Closing running app processes...
taskkill /IM "TarkoFF Stream Center.exe" /F >nul 2>&1
taskkill /IM "backend.exe" /F >nul 2>&1
timeout /t 2 /nobreak >nul

echo [2/8] Create backup folder if needed...
if not exist "%BACKUP_ROOT%" (
    mkdir "%BACKUP_ROOT%"
)

echo [3/8] Copy project folder...
powershell -NoProfile -Command ^
    "Copy-Item -Path '%PROJECT_DIR%' -Destination '%DEST_DIR%' -Recurse -Force"
if errorlevel 1 goto :error

echo [4/8] Create zip archive...
powershell -NoProfile -Command ^
    "Compress-Archive -Path '%PROJECT_DIR%\*' -DestinationPath '%ZIP_PATH%' -Force"
if errorlevel 1 goto :error

echo [5/8] Check git repository...
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    echo Git repo not found. Git steps skipped.
    goto :restart_app
)

echo [6/8] Check for git changes...
git status --porcelain > "%TEMP%\tarkoff_git_status.txt"

set "HAS_CHANGES=0"
for %%A in ("%TEMP%\tarkoff_git_status.txt") do (
    if %%~zA gtr 0 set "HAS_CHANGES=1"
)

if "%HAS_CHANGES%"=="1" (
    echo Changes found. Running git add...
    git add .
    if errorlevel 1 (
        echo git add failed.
        goto :restart_app
    )

    echo Creating git commit...
    git commit -m "%COMMIT_MSG%"
    if errorlevel 1 (
        echo git commit failed.
        goto :restart_app
    ) else (
        set "COMMIT_CREATED=1"
        echo Git commit created: %COMMIT_MSG%
    )
) else (
    echo No git changes found. Commit skipped.
)

echo [7/8] Push to remote if needed...
if "%COMMIT_CREATED%"=="1" (
    git remote get-url origin >nul 2>&1
    if errorlevel 1 (
        echo Remote origin not found. Push skipped.
        goto :restart_app
    )

    git push
    if errorlevel 1 (
        echo git push failed.
    ) else (
        echo Git push completed successfully.
    )
) else (
    echo No new commit created. Push skipped.
)

:restart_app
echo [8/8] Restart app...
if exist "%RELEASE_EXE%" (
    start "" "%RELEASE_EXE%"
    echo Started: %RELEASE_EXE%
) else (
    echo Release exe not found:
    echo %RELEASE_EXE%
    echo App restart skipped.
)

echo.
echo Folder backup created:
echo %DEST_DIR%
echo.
echo Zip backup created:
echo %ZIP_PATH%
echo.
pause
exit /b 0

:error
echo.
echo Backup failed.
pause
exit /b 1