@echo off
setlocal
cd /d "%~dp0.."
if /I not "%VSCMD_ARG_TGT_ARCH%"=="x64" (
  call :find_msvc
  if errorlevel 1 exit /b 1
)
if not exist maxcraft\_native mkdir maxcraft\_native
cl /nologo /LD /O2 /MT /W4 native\atomics.c /Fo:maxcraft\_native\atomics.obj /Fe:maxcraft\_native\atomics.dll /link /NOLOGO
exit /b %errorlevel%

:find_msvc
set "MAXCRAFT_VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%MAXCRAFT_VSWHERE%" (
  echo Install Visual Studio Build Tools with Desktop development with C++.
  exit /b 1
)
set "MAXCRAFT_VS_ROOT="
for /f "usebackq delims=" %%i in (`"%MAXCRAFT_VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "MAXCRAFT_VS_ROOT=%%i"
if not defined MAXCRAFT_VS_ROOT (
  echo No Visual Studio installation with the x64 C++ tools was found.
  exit /b 1
)
call "%MAXCRAFT_VS_ROOT%\VC\Auxiliary\Build\vcvars64.bat" >nul
exit /b %errorlevel%

