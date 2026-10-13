@echo off
setlocal
cd /d "%~dp0.."
if not defined VCToolsInstallDir (
  if exist "D:\Development Programs\VS\Program\VC\Auxiliary\Build\vcvars64.bat" (
    call "D:\Development Programs\VS\Program\VC\Auxiliary\Build\vcvars64.bat" >nul
  ) else (
    echo Run this script from an x64 Native Tools Command Prompt for Visual Studio.
    exit /b 1
  )
)
if not exist maxcraft\_native mkdir maxcraft\_native
cl /nologo /LD /O2 /W4 native\atomics.c /Fo:maxcraft\_native\atomics.obj /Fe:maxcraft\_native\atomics.dll /link /NOLOGO
exit /b %errorlevel%

