# Build the Windows program into dist\ :
#   OvertimeNHL19.exe       the window (double-click): overtime_roster\web drawn by Edge WebView2 (the browser without
#                           it), with the NHL 27 data pack (-Nhl27, numbers and names only: checked by
#                           packaging\check_datapack.py) and the verified default roster (-DefaultDb, with its sha256
#                           recorded at build time) inside. No picture packs: since beta2 the app downloads them from
#                           the release host (overtime_roster\app\packdownload.py).
#   OvertimeNHL19-cli.exe   with -Cli: the same program with a console (--browser, --selftest, --update)
#   packs\<name>            the picture packs the app downloads, next to latest.json: -Packs (looks32.zip, looks.zip,
#                           photos.zip, people.zip, ice_all.zip, rink.zip, clubart.zip (the clubs' logos and centre
#                           ice the app makes on the player's PC, overtime_core\clubart.py), kitlayers_nhl.zip, kitlayers_intl.zip,
#                           kitlayers_clubs.zip (NHL 27's jerseys the app makes into the game's textures on the player's PC at
#                           Patch, overtime_core\kitcompose.py, tools\build_kitlayers.py) from packs\, made from the owner's own game files;
#                           never in git), -Kits <file> (kits.zip) and shadps4_nhl19.zip (Boost performance: Kravickas's build as
#                           its CI made it, docs/notes/shadps4-network.md). Each must read; photos.zip (p<artid> of that roster's bios) is checked
#                           against -DefaultDb with packaging\check_photos.py, its sha256 goes into the build record.
#   SHA256SUMS.txt          the exes' and the packs' checksums ("packs/<name>"): the downloads are compared with them
#   latest.json             the release file the self-update reads, with "packs": {name: {file, sha256, size}}
#                           (upload the exes, latest.json and SHA256SUMS.txt under /app/; each pack with
#                           POST /admin/pack?name=<name>&sha256=<sha256>, deploy\README.md)
#
# Uses its own virtual environment (.venv-build) so nothing is installed into your Python, and runs below normal
# priority (the PC is shared). -CheckOnly runs the checks (no PyInstaller needed: .venv-build's Python when there is
# one, else python) and stops before building; it writes only build\defaults.
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -DefaultDb <capture folder or its nhl_game.db>
#              [-DefaultDbSha <sha256>] [-NoPacks] [-Cli] [-Kits <kits.zip>] [-CheckOnly]

param(
    [switch]$NoPacks,       # stage no packs and leave the NHL 27 data pack out (a spike, or before the packs are made)
    [switch]$Cli,           # also build OvertimeNHL19-cli.exe
    [switch]$NoSplash,      # no start-up splash (it needs Tcl/Tk in the exe: about 2 MB more)
    [string[]]$Packs = @('looks32.zip', 'looks.zip', 'photos.zip', 'people.zip', 'ice_all.zip', 'rink.zip', 'clubart.zip', 'kitlayers_nhl.zip', 'kitlayers_intl.zip', 'kitlayers_clubs.zip', 'shadps4_nhl19.zip', 'cpu_estimates.zip'),   # the packs to stage (packdownload.KNOWN; cpu_estimates.zip: packaging\cpu_pack.ps1)
    [string]$Kits = '',     # the kits pack to stage too (e.g. re\extract\release-fixture\app\packs\kits.zip)
    [string]$DefaultDb = '',    # the verified default roster: a capture folder (or its nhl_game.db); main picks it
    [string]$DefaultDbSha = '', # its sha256, needed when the folder has no db.json (with one, both must agree)
    [string]$Nhl27 = 'packs\nhl27.json.gz',     # the NHL 27 data pack (numbers only) for the Update tab's rebuild
    [string]$SignThumbprint = '',   # sign the exes with this certificate of the Windows store (RFC 3161 timestamp)
    [string]$SignPfx = '',          # or with this .pfx (its password in $env:OVERTIME_SIGN_PASSWORD, never on the line)
    [string]$SignCommand = '',      # or by a signer's own command, {file} stands for each exe (Trusted Signing, SignPath)
    [string]$TimestampUrl = 'http://timestamp.digicert.com',
    [switch]$RequireSigned,         # fail instead of building an unsigned exe (the release build)
    [string]$Priority = 'BelowNormal',
    [switch]$CheckOnly      # run the checks (packs, NHL 27 pack, default roster + photos) and stop before building
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$name = 'OvertimeNHL19'
(Get-Process -Id $PID).PriorityClass = $Priority      # pip and PyInstaller inherit it

$distDir = Join-Path $root 'dist'     # only this checkout's exe is replaced: a copy running from elsewhere is fine
$running = Get-Process -Name $name, "$name-cli" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($distDir, [StringComparison]::OrdinalIgnoreCase) }
if ($running -and -not $CheckOnly) { throw "Close $name first: Windows does not let a running program be replaced." }

$py = Join-Path $root '.venv-build\Scripts\python.exe'
if ($CheckOnly) {
    if (-not (Test-Path $py)) { $py = 'python' }     # the checks need only the standard library
} else {
    if (-not (Test-Path $py)) {
        python -m venv .venv-build
        if ($LASTEXITCODE -ne 0) { throw "could not make the build environment (.venv-build)" }
    }
    # pywebview shows the window (WebView2 through pythonnet); certifi brings Mozilla's list of trusted certificates
    # (Windows' own list can lack the one the update server uses); Pillow draws the photos the packs lack on the
    # player's PC (overtime_core.photos) and numpy writes the textures made on it (overtime_core.bcn: BC1 / BC3 / BC5 /
    # BC7); both imported inside functions only, the server stays stdlib
    & $py -m pip install --quiet --upgrade pip pyinstaller "pywebview==6.2.1" certifi "pillow==12.1.1" "numpy==2.5.4"
    if ($LASTEXITCODE -ne 0) { throw "could not install PyInstaller, pywebview, certifi, Pillow and numpy" }
}

$version = (& $py -c "import overtime_roster; print(overtime_roster.VERSION)").Trim()
$web = Join-Path $root 'overtime_roster\web'
$assets = Join-Path $root 'overtime_roster\assets'
$textpack = Join-Path $root 'client\textpack'
if (-not (Test-Path (Join-Path $textpack 'eng_us.json'))) { throw "No client\textpack\eng_us.json (the text layer's pack)." }
$icon = Join-Path $assets 'app.ico'
if (-not (Test-Path $icon) -and -not $CheckOnly) {
    & $py packaging\make_icon.py
    if ($LASTEXITCODE -ne 0) { throw "could not draw the icon (packaging\make_icon.py)" }
}
$common = @(
    '--noconfirm', '--clean', '--onefile',
    '--paths', $root,
    '--add-data', "$web;overtime_roster\web",
    '--add-data', "$assets;overtime_roster\assets",
    # the text layer's pack (overtime_core.textpack.PACK_DIR = <root>\client\textpack, _MEI\client\textpack frozen)
    '--add-data', "$textpack;client\textpack",
    '--icon', $icon,
    '--distpath', 'dist', '--workpath', 'build\pyi', '--specpath', 'build'
)

# the picture packs: staged next to the exe for the release host, never inside it
$packDir = Join-Path $root 'packs'
$staged = [ordered]@{}      # name -> the file to publish
$shipped = @()              # what goes inside the exe (the NHL 27 data pack)
if (-not $NoPacks) {
    foreach ($pack in $Packs) {
        if ($pack -in @('kits.zip', 'nhl27.json.gz')) { throw "$pack does not go in with -Packs (the kits: -Kits)." }
        $file = Join-Path $packDir $pack
        if (-not (Test-Path $file)) {
            throw "No packs\$pack. Make it first (tools\build_looks.py, tools\build_photopack.py, packaging\cpu_pack.ps1), or build with -NoPacks."
        }
        $staged[$pack] = $file
    }
    # the NHL 27 data pack: numbers and names only, checked here
    $nhl27File = Join-Path $root $Nhl27
    if (-not (Test-Path $nhl27File)) { throw "No $Nhl27 (tools\build_datapack.py writes it), or build with -NoPacks." }
    & $py packaging\check_datapack.py $nhl27File
    if ($LASTEXITCODE -ne 0) { throw "$Nhl27 holds more than numbers and names: it does not go into the exe." }
    $common += @('--add-data', "$nhl27File;overtime_roster\packs")
    $shipped += 'nhl27.json.gz'
}
if ($Kits) {
    if (-not (Test-Path $Kits)) { throw "No kits pack at $Kits." }
    $staged['kits.zip'] = (Resolve-Path $Kits).Path
}
# each pack must read: every file of a picture pack against its checksum; the kits (a delta pack) its manifest, its
# bases are checked against the player's game when the patch lays it in; the emulator and the club art source pack by
# their own checks (packdownload.CHECKS)
$readPack = 'import sys; from overtime_core import art; from overtime_roster.app import packdownload as p; ' +
            'e = sys.argv[2] in p.CHECKS; p.CHECKS.get(sys.argv[2], p.check_zip)(sys.argv[1]); ' +
            'e or sys.argv[2] == sys.argv[3] or art.load_pack(sys.argv[1])'
foreach ($pack in $staged.Keys) {
    & $py -c $readPack $staged[$pack] $pack 'kits.zip'
    if ($LASTEXITCODE -ne 0) { throw "$($staged[$pack]) does not read as a pack." }
}

# the verified default roster (the bytes the in-game tests ran) and its build-time record; never a variant
if (-not $DefaultDb) { throw "Name the default roster the exe ships: -DefaultDb <capture folder> (main picks it)." }
$dbFile = (Resolve-Path (Join-Path $root $DefaultDb)).Path
if (Test-Path $dbFile -PathType Container) { $dbFile = Join-Path $dbFile 'nhl_game.db' }
if (-not (Test-Path $dbFile)) { throw "No $dbFile." }
if ($dbFile -match '\\variants\\') { throw "$DefaultDb is a variant: only the verified default ships." }
$dbSha = (Get-FileHash $dbFile -Algorithm SHA256).Hash.ToLower()
$dbJson = Join-Path (Split-Path $dbFile) 'db.json'
$dbRecord = if (Test-Path $dbJson) { Get-Content -Raw $dbJson | ConvertFrom-Json } else { $null }
$want = @(@($dbRecord.sha256, $DefaultDbSha.ToLower()) | Where-Object { $_ })
if (-not $want) { throw "$dbFile has no db.json next to it: give its sha256 with -DefaultDbSha." }
foreach ($w in $want) { if ($w -ne $dbSha) { throw "$dbFile is $dbSha, not the recorded $w." } }
$record = [ordered]@{ sha256 = $dbSha; bytes = (Get-Item $dbFile).Length; source = $DefaultDb; fix = $dbRecord.fix }
# photos.zip is keyed by this roster's artids: every portrait must be on one of its bios, else it is not published.
# Its sha256 goes into the record: the app knows that download fits without reading the game.
if ($staged.Contains('photos.zip')) {
    $photos = @(& $py packaging\check_photos.py $dbFile $staged['photos.zip'])
    $photos[0..($photos.Count - 2)]
    if ($LASTEXITCODE -ne 0) { throw "packs\photos.zip was not made for $DefaultDb (tools\build_photopack.py --database)." }
    $record.photos = $photos[-1] | ConvertFrom-Json
} elseif (-not $NoPacks) {
    throw "photos.zip is published with the default roster: keep it in -Packs."
}
$defaults = Join-Path $root 'build\defaults'
New-Item -ItemType Directory -Force $defaults | Out-Null
Copy-Item -Force $dbFile (Join-Path $defaults 'nhl_game.db')
$record | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 (Join-Path $defaults 'default.json')
# the pictures stay on the server: nothing the exe bundles may hold a game picture or archive
& $py packaging\check_bundle.py $web $assets $textpack $defaults
if ($LASTEXITCODE -ne 0) { throw "A picture or archive would go into the exe: the NHL 27 pictures are downloaded packs." }
if ($CheckOnly) {
    $inside = if ($shipped) { $shipped -join ', ' } else { 'no packs' }
    "checks passed: default roster $($dbSha.Substring(0, 8)) from $DefaultDb; inside: $inside"
    foreach ($pack in $staged.Keys) {
        $file = Get-Item $staged[$pack]
        "  to publish: packs/{0}  {1:N1} MB  {2}" -f $pack, ($file.Length / 1MB),
            (Get-FileHash $file.FullName -Algorithm SHA256).Hash.ToLower().Substring(0, 8)
    }
    Get-Content (Join-Path $defaults 'default.json')
    exit 0
}
$common += @('--add-data', "$defaults;overtime_roster\defaults")

New-Item -ItemType Directory -Force (Join-Path $root 'build') | Out-Null
# the splash the bootloader shows while it unpacks (the app closes it when its window shows); -NoSplash leaves it out
$splash = @()
if (-not $NoSplash) {
    & $py packaging\make_splash.py build\splash.png
    if ($LASTEXITCODE -ne 0) { throw "could not draw the splash (packaging\make_splash.py)" }
    $splash = @('--splash', (Join-Path $root 'build\splash.png'))
}
& $py -m PyInstaller @common --windowed @splash `
    --collect-all webview --collect-all pythonnet --collect-all clr_loader `
    --name $name packaging\launcher.py
if ($LASTEXITCODE -ne 0) { throw "building the window program failed" }

$cliExe = Join-Path $root "dist\$name-cli.exe"
if ($Cli) {
    & $py -m PyInstaller @common --console `
        --exclude-module webview --exclude-module pythonnet --exclude-module clr_loader --exclude-module clr `
        --name "$name-cli" packaging\launcher_cli.py
    if ($LASTEXITCODE -ne 0) { throw "building the command-line program failed" }
} elseif (Test-Path $cliExe) {
    Remove-Item -Force $cliExe          # an older build's: its checksum would be published with the new one
}

# signing (optional): a signed exe is a known publisher to Windows and lets the updater check that the next exe has the
# same signer. The checksums below are of the signed files. docs/notes/signing.md has the certificate options.
$toSign = @(Get-ChildItem "dist\$name*.exe")
$signing = $SignThumbprint -or $SignPfx -or $SignCommand
if ($RequireSigned -and -not $signing) { throw "-RequireSigned: give -SignThumbprint, -SignPfx or -SignCommand (docs\notes\signing.md)." }
if ($signing) {
    $signtool = $null
    if (-not $SignCommand) {
        $signtool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
        if (-not $signtool) {
            $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -match '\x64\' } | Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
        }
        if (-not $signtool) { throw "signtool.exe not found (Windows SDK)." }
    }
    foreach ($exe in $toSign) {
        if ($SignCommand) {
            & cmd /c ($SignCommand -replace '\{file\}', ('"' + $exe.FullName + '"'))
        } elseif ($SignPfx) {
            & $signtool sign /fd SHA256 /f $SignPfx /p $env:OVERTIME_SIGN_PASSWORD /tr $TimestampUrl /td SHA256 $exe.FullName
        } else {
            & $signtool sign /fd SHA256 /sha1 $SignThumbprint /tr $TimestampUrl /td SHA256 $exe.FullName
        }
        if ($LASTEXITCODE -ne 0) { throw "signing $($exe.Name) failed" }
        $sig = Get-AuthenticodeSignature -LiteralPath $exe.FullName
        if ($sig.Status -ne 'Valid') { throw "$($exe.Name) is signed but Windows does not accept it: $($sig.Status) $($sig.StatusMessage)" }
        if (-not $sig.TimeStamperCertificate) { throw "$($exe.Name) has no timestamp: it would stop being valid when the certificate expires." }
        Write-Host ("signed {0}: {1}" -f $exe.Name, $sig.SignerCertificate.Subject)
    }
} else {
    Write-Host "NOT SIGNED: Windows shows an unknown publisher for this exe (docs\notes\signing.md)."
}

# checksums of the programs (dist\ holds other things too: only ours are listed), and the release file
$exes = Get-ChildItem "dist\$name*.exe"
$sums = @($exes | ForEach-Object { "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name })
$main = Get-Item "dist\$name.exe"
$release = [ordered]@{
    version = $version
    exe     = $main.Name
    size    = $main.Length
    sha256  = (Get-FileHash $main.FullName -Algorithm SHA256).Hash.ToLower()
    notes   = ''
}
# the packs next to latest.json; an older build's that are not staged now go (latest.json would no longer name them)
$packsOut = Join-Path $root 'dist\packs'
if (Test-Path $packsOut) {
    Get-ChildItem $packsOut -File | Where-Object { -not $staged.Contains($_.Name) } | Remove-Item -Force
}
if ($staged.Count) {
    New-Item -ItemType Directory -Force $packsOut | Out-Null
    $release.packs = [ordered]@{}
}
foreach ($pack in $staged.Keys) {
    $out = Join-Path $packsOut $pack
    Copy-Item -Force $staged[$pack] $out
    $sha = (Get-FileHash $out -Algorithm SHA256).Hash.ToLower()
    if ($pack -eq 'photos.zip' -and $sha -ne $record.photos.sha256) { throw "packs\photos.zip changed while building." }
    $sums += "$sha  packs/$pack"
    $release.packs[$pack] = [ordered]@{ file = "packs/$pack"; sha256 = $sha; size = (Get-Item $out).Length }
}
$sums | Set-Content -Encoding ascii dist\SHA256SUMS.txt
$release | ConvertTo-Json -Depth 4 | Set-Content -Encoding ascii dist\latest.json

$inside = if ($shipped) { 'inside: ' + ($shipped -join ', ') } else { 'no packs inside' }
$exes | ForEach-Object { "{0}  {1:N1} MB  (version {2}, {3})" -f $_.Name, ($_.Length / 1MB), $version, $inside }
foreach ($pack in $staged.Keys) {
    "packs/{0}  {1:N1} MB  (download: POST /admin/pack?name={0}&sha256={2})" -f $pack,
        ((Get-Item (Join-Path $packsOut $pack)).Length / 1MB), $release.packs[$pack].sha256
}
