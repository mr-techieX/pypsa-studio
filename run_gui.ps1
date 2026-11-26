# Resolve both paths relative to this launcher, not the caller's working directory.
$python = Join-Path $PSScriptRoot '..\..\EnEx\Scripts\python.exe'
Push-Location $PSScriptRoot
try {
    & $python -m energy_gui @args
} finally {
    Pop-Location
}
