# packs\cpu_estimates.zip: tools\cpu_estimates.py as one exe (PyInstaller, stdlib only) for Check my CPU
# (overtime_roster\app\cpucheck.py). build.ps1 stages it like the other packs and latest.json pins its sha256.
# Run from the repository root: powershell -File packaging\cpu_pack.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$pyi = Join-Path $root '.venv-build\Scripts\pyinstaller.exe'
if (-not (Test-Path $pyi)) { throw "No $pyi (the build venv)." }
& $pyi --noconfirm --onefile --console --name cpu-estimates --distpath dist\cpu-estimates `
    --workpath build\pyi-cpu --specpath build tools\cpu_estimates.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
$exe = Join-Path $root 'dist\cpu-estimates\cpu-estimates.exe'
$zip = Join-Path $root 'packs\cpu_estimates.zip'
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $exe -DestinationPath $zip
$py = Join-Path $root '.venv-build\Scripts\python.exe'
& $py -c 'import sys; from overtime_roster.app import packdownload as p; p.check_cputest(sys.argv[1])' $zip
if ($LASTEXITCODE -ne 0) { throw "$zip does not read as the CPU check pack." }
$sha = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
Write-Host "packs\cpu_estimates.zip $((Get-Item $zip).Length) bytes, sha256 $sha"
