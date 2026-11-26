@echo off
setlocal
pushd "%~dp0"
"%~dp0..\..\EnEx\Scripts\python.exe" -m energy_gui
if errorlevel 1 pause
popd
endlocal
