"""Build the Linux and the macOS app (docs/notes/linux-support.md, macos-support.md). The Windows exe is
packaging/build.ps1; .github/workflows/build-desktop.yml runs this file on GitHub's Linux and macOS machines.

    python packaging/build_unix.py --requirements > req.txt && python -m pip install -r req.txt
    python packaging/build_unix.py [--inputs <folder>] [--out dist] [--appimagetool <file>] [--sign <identity>]

Linux:  PyInstaller (one folder) -> an AppDir -> OvertimeNHL19-x86_64.AppImage (appimagetool, with the static
        runtime given as --runtime: no libfuse2 on the player's system) -> OvertimeNHL19-linux.tar.gz, which keeps
        the exec bit through a download. The AppImage alone is what a running app swaps itself for
        (selfupdate.LINUX_ASSET).
macOS:  PyInstaller (--windowed) -> "Overtime NHL19.app" -> OvertimeNHL19-macos.dmg with a link to Applications.

--inputs: the private data every released Windows exe carries too, as packaging/build.ps1 leaves it:
    <folder>/defaults/nhl_game.db + default.json     (build\\defaults: the verified default roster and its record)
    <folder>/packs/nhl27.json.gz                      (the NHL 27 data pack, numbers only)
Without --inputs the build has neither (a smoke build: the window and the patch flow work, there is no default roster);
its files are named "-nodata" and must not be released.

What goes in is packaging/bundle.json. No game data, picture or archive may be in it (packaging/check_bundle.py runs
first). Writes <out>/SHA256SUMS-<system>.txt and <out>/release-<system>.json, the value of latest.json's "linux" or
"macos" key. Standard library, plus Pillow for the icon (a build requirement anyway).
"""
import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE = os.path.join(ROOT, 'packaging', 'bundle.json')
APPIMAGE = 'OvertimeNHL19-x86_64.AppImage'      # selfupdate.LINUX_ASSET
TARBALL = 'OvertimeNHL19-linux.tar.gz'
DMG = 'OvertimeNHL19-macos.dmg'                 # selfupdate.MACOS_ASSET
DESKTOP_ID = 'overtime-nhl19'                   # desktopentry.ICON_NAME
APPRUN = '''#!/bin/sh
# Starts the app inside this AppImage (or this folder, when it was unpacked).
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/overtime-nhl19/{name}" "$@"
'''


class BuildError(RuntimeError):
    pass


def bundle():
    with open(BUNDLE, encoding='utf-8') as f:
        return json.load(f)


def version():
    sys.path.insert(0, ROOT)
    import overtime_roster
    return overtime_roster.VERSION


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def named(name, nodata):
    """A release file's name; a build without the private data says so in its name."""
    if not nodata:
        return name
    stem, dot, rest = name.partition('.')
    return f'{stem}-nodata{dot}{rest}'


def data_pairs(spec, inputs):
    """[(source path, folder inside the app)] of bundle.json's data, the private ones only with `inputs`.
    BuildError when a listed source is not there."""
    pairs = [(os.path.join(ROOT, *src.split('/')), dst) for src, dst in spec['data']]
    if inputs:
        pairs += [(os.path.join(inputs, *src.split('/')), dst) for src, dst in spec['private']]
    for src, _dst in pairs:
        if not os.path.exists(src):
            raise BuildError(f'{src} is not there (packaging/bundle.json lists it)')
    return pairs


def pyinstaller_args(spec, system, pairs, icon, work, sign=''):
    """PyInstaller's arguments for this system (Linux: one folder for the AppDir; macOS: the .app)."""
    name = spec['mac_name'] if system == 'darwin' else spec['name']
    args = ['--noconfirm', '--clean', '--onedir', '--windowed', '--name', name, '--paths', ROOT,
            '--distpath', os.path.join(work, 'dist'), '--workpath', os.path.join(work, 'pyi'), '--specpath', work]
    for src, dst in pairs:
        args += ['--add-data', f'{src}{os.pathsep}{dst}']
    for module in spec['collect'].get(system, []):
        args += ['--collect-all', module]
    for module in spec['hidden'].get(system, []):
        args += ['--hidden-import', module]
    for module in spec['exclude'].get(system, []):
        args += ['--exclude-module', module]
    if icon:
        args += ['--icon', icon]
    if system == 'darwin':
        args += ['--osx-bundle-identifier', spec['mac_id']]
        if sign:    # a Developer ID: PyInstaller signs every file of the app with it (else ad hoc)
            args += ['--codesign-identity', sign]
    return args + [os.path.join(ROOT, *spec['entry'].split('/'))]


def make_png(ico, png, size=256):
    """The window's and the app menu's icon: the .ico's largest picture as a PNG."""
    from PIL import Image
    with Image.open(ico) as im:
        im.size = max(im.info.get('sizes') or [im.size])        # the biggest frame (as packaging/make_icon.py)
        out = im.convert('RGBA')
        if out.size != (size, size):
            out = out.resize((size, size), Image.LANCZOS)
        out.save(png, 'PNG')
    return png


def desktop_text(spec, app_name):
    return '\n'.join(['[Desktop Entry]', 'Type=Application', f'Name={app_name}',
                      'Comment=NHL 19 on shadPS4: rosters, patch and online play', f'Exec={spec["name"]}',
                      f'Icon={DESKTOP_ID}', 'Terminal=false', 'Categories=Game;SportsGame;',
                      f'StartupWMClass={spec["name"]}', '']) + '\n'


def make_appdir(spec, folder, appdir, png, app_name):
    """The AppDir appimagetool packs: AppRun, the desktop entry and icon at the top, the app's folder under usr/lib."""
    if os.path.exists(appdir):
        shutil.rmtree(appdir)
    lib = os.path.join(appdir, 'usr', 'lib', 'overtime-nhl19')
    shutil.copytree(folder, lib, symlinks=True)
    run = os.path.join(appdir, 'AppRun')
    with open(run, 'w', encoding='utf-8', newline='\n') as f:
        f.write(APPRUN.format(name=spec['name']))
    os.chmod(run, 0o755)
    with open(os.path.join(appdir, DESKTOP_ID + '.desktop'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(desktop_text(spec, app_name))
    shutil.copyfile(png, os.path.join(appdir, DESKTOP_ID + '.png'))
    shutil.copyfile(png, os.path.join(appdir, '.DirIcon'))
    return appdir


def make_tarball(appimage, out):
    """The download: the AppImage alone in a tar.gz, its exec bit set whatever the file system here says."""
    with tarfile.open(out, 'w:gz', compresslevel=6) as tar:
        info = tar.gettarinfo(appimage, arcname=APPIMAGE)
        info.mode = 0o755
        info.uid = info.gid = 0
        info.uname = info.gname = ''
        with open(appimage, 'rb') as f:
            tar.addfile(info, f)
    return out


def record(system, files, out, ver):
    """SHA256SUMS-<system>.txt and release-<system>.json (latest.json's "linux" / "macos" value) for `files`,
    the first of which is the file the app's update names."""
    key = {'linux': 'linux', 'darwin': 'macos'}[system]
    lines = [f'{sha256(p)}  {os.path.basename(p)}' for p in files]
    with open(os.path.join(out, f'SHA256SUMS-{key}.txt'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    main = files[0]
    value = {'version': ver, 'exe': os.path.basename(main), 'sha256': sha256(main), 'size': os.path.getsize(main)}
    with open(os.path.join(out, f'release-{key}.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, indent=1)
        f.write('\n')
    return value


def built(system, out):
    """The release files of `system` already in `out`, the one the app's update names first ([] when none)."""
    names = [DMG] if system == 'darwin' else [APPIMAGE, TARBALL]
    for nodata in (False, True):
        files = [os.path.join(out, named(n, nodata)) for n in names]
        if all(os.path.isfile(f) for f in files):
            return files
    return []


def run(cmd, **kw):
    print('+', ' '.join(str(c) for c in cmd), flush=True)
    done = subprocess.run(cmd, **kw)
    if done.returncode:
        raise BuildError(f'{os.path.basename(str(cmd[0]))} ended with {done.returncode}')
    return done


def check_bundle(pairs):
    """No picture or archive of the game may go in, and the NHL 27 data pack holds numbers and names only
    (packaging/check_bundle.py and check_datapack.py, as the Windows build runs them)."""
    run([sys.executable, os.path.join(ROOT, 'packaging', 'check_bundle.py'),
         *[src for src, _dst in pairs if os.path.isdir(src)]])
    for src, _dst in pairs:
        if src.endswith('.json.gz'):
            run([sys.executable, os.path.join(ROOT, 'packaging', 'check_datapack.py'), src])


def requirements(spec, system):
    """What pip installs before a build on `system` (bundle.json's pins)."""
    return spec['requirements']['all'] + spec['requirements'].get(system, [])


LIB_DIRS = ('/usr/lib/x86_64-linux-gnu', '/usr/lib64', '/usr/lib')     # where a build machine keeps its libraries


def carry_libraries(spec, folder, dirs=LIB_DIRS):
    """System libraries Qt asks for that not every desktop has (bundle.json "libraries": Ubuntu 24.04 comes without
    libwayland-server, which Qt's web view loads; Qt's X11 window needs libxcb-cursor). Each goes beside the app's own
    libraries unless PyInstaller took it already; the names carried now. A build machine without one stops the build."""
    inner = os.path.join(folder, '_internal')
    carried = []
    for name in spec.get('libraries', {}).get('linux', []):
        dst = os.path.join(inner, name)
        if os.path.exists(dst):
            continue
        src = next((os.path.join(d, name) for d in dirs if os.path.exists(os.path.join(d, name))), None)
        if not src:
            raise BuildError(f'{name} is not on this machine (packaging/bundle.json "libraries" lists it)')
        shutil.copyfile(os.path.realpath(src), dst)
        os.chmod(dst, 0o755)
        carried.append(name)
    return carried


def build_linux(spec, args, png, work, nodata):
    folder = os.path.join(work, 'dist', spec['name'])
    carried = carry_libraries(spec, folder)
    print('system libraries carried:', ', '.join(carried) or 'none (PyInstaller took them)', flush=True)
    appdir = make_appdir(spec, folder, os.path.join(work, 'AppDir'), png, 'Overtime Roster')
    if not args.appimagetool:
        raise BuildError('--appimagetool: the appimagetool AppImage is needed to pack the AppDir')
    os.chmod(args.appimagetool, os.stat(args.appimagetool).st_mode | stat.S_IXUSR)
    image = os.path.join(args.out, named(APPIMAGE, nodata))
    # the tool is an AppImage itself; a build machine has no FUSE: it unpacks itself and runs
    runtime = ['--runtime-file', args.runtime] if args.runtime else []
    run([args.appimagetool, '--no-appstream', *runtime, appdir, image],
        env={**os.environ, 'ARCH': 'x86_64', 'APPIMAGE_EXTRACT_AND_RUN': '1'})
    os.chmod(image, 0o755)
    tarball = make_tarball(image, os.path.join(args.out, named(TARBALL, nodata)))
    return [image, tarball]


def build_macos(spec, args, work, nodata):
    app = os.path.join(work, 'dist', spec['mac_name'] + '.app')
    stage = os.path.join(work, 'dmg')
    if os.path.exists(stage):
        shutil.rmtree(stage)
    os.makedirs(stage)
    shutil.copytree(app, os.path.join(stage, os.path.basename(app)), symlinks=True)
    os.symlink('/Applications', os.path.join(stage, 'Applications'))
    dmg = os.path.join(args.out, named(DMG, nodata))
    if os.path.exists(dmg):
        os.remove(dmg)
    run(['hdiutil', 'create', '-volname', spec['mac_name'], '-srcfolder', stage, '-ov', '-format', 'UDZO', dmg])
    if args.sign:   # the disk image too: Gatekeeper opens it without the detour through Privacy & Security
        run(['codesign', '--force', '--timestamp', '--sign', args.sign, dmg])
    return [dmg]


def main(argv=None):
    ap = argparse.ArgumentParser(description='Build the Linux or macOS app (the system this runs on).')
    ap.add_argument('--inputs', default='', help='the folder with defaults/ and packs/nhl27.json.gz (private data)')
    ap.add_argument('--out', default=os.path.join(ROOT, 'dist'))
    ap.add_argument('--work', default=os.path.join(ROOT, 'build', 'unix'))
    ap.add_argument('--appimagetool', default='', help='Linux: the appimagetool AppImage')
    ap.add_argument('--runtime', default='', help="Linux: the AppImage runtime file (else the tool downloads "
                                                  "today's)")
    ap.add_argument('--sign', default='', help='macOS: a Developer ID Application identity (else ad-hoc)')
    ap.add_argument('--requirements', action='store_true', help='print what pip must install first, and stop')
    ap.add_argument('--record-only', action='store_true',
                    help='write the sums and release-<system>.json of the files already in --out again (they changed: '
                         'a notarized dmg), and stop')
    args = ap.parse_args(argv)
    system = 'darwin' if sys.platform == 'darwin' else 'linux'
    if args.requirements:
        for line in requirements(bundle(), system):
            print(line)
        return 0
    if sys.platform not in ('linux', 'darwin'):
        print('build_unix: this builds on Linux or macOS; the Windows exe is packaging/build.ps1', file=sys.stderr)
        return 2
    if args.record_only:
        files = built(system, args.out)
        if not files:
            print(f'build_unix: no built files in {args.out}', file=sys.stderr)
            return 1
        print(json.dumps(record(system, files, args.out, version()), indent=1))
        return 0
    try:
        spec = bundle()
        nodata = not args.inputs
        os.makedirs(args.out, exist_ok=True)
        os.makedirs(args.work, exist_ok=True)
        png = os.path.join(ROOT, 'overtime_roster', 'assets', 'app.png')
        ico = os.path.join(ROOT, 'overtime_roster', 'assets', 'app.ico')
        if not os.path.exists(ico):
            run([sys.executable, os.path.join(ROOT, 'packaging', 'make_icon.py')], cwd=ROOT)
        make_png(ico, png)
        pairs = data_pairs(spec, args.inputs)
        check_bundle(pairs)
        run([sys.executable, '-m', 'PyInstaller',
             *pyinstaller_args(spec, system, pairs, png, args.work, args.sign)], cwd=ROOT)
        files = (build_macos(spec, args, args.work, nodata) if system == 'darwin'
                 else build_linux(spec, args, png, args.work, nodata))
        value = record(system, files, args.out, version())
    except (BuildError, OSError) as err:
        print(f'build_unix: {err}', file=sys.stderr)
        return 1
    print(json.dumps(value, indent=1))
    for path in files:
        print(f'{os.path.getsize(path) / (1 << 20):8.1f} MB  {path}')
    if nodata:
        print('This is a smoke build without the default roster and the NHL 27 data: not for release.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
