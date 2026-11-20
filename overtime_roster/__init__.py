"""Overtime Roster: roster editor for NHL 19 (PS4, CUSA11126 v1.60) on shadPS4."""
import sys

APP_NAME = 'Overtime Roster'
VERSION = '0.98.1'
__version__ = VERSION
SITE, SITE_LABEL = 'https://www.puckpeak.com', 'www.puckpeak.com'   # the header's link (shell.open_site)
DISCORD = 'https://gg.puckpeak.com'     # the Puck Peak Discord (a redirect): Setup's first button, as in Legacy
KOFI = 'https://ko-fi.com/iksperial'    # tips for the development: the button beside it, as in Legacy
TAGLINE = 'NHL & hockey analytics like never before'
BRAND = 'Overtime'                  # the header's wordmark, "brought to you by" Puck Peak (owner 2026-11-13); APP_NAME
SUBTITLE = 'NHL 19 · PC Online'     # stays: it names folders, dialogs and the window
# the header's app dock, left of the wordmark (owner 2026-11-13, docs/ui/mockups/apps-promo.html): the Puck Peak apps,
# this one greyed in the middle; shell.open_app opens only these
SISTER_APPS = {'blueline': 'https://github.com/MatusRiedl/nhl-legacy-pc-online-blueline',
               'faceoff': 'https://github.com/MatusRiedl/nhl27-pc-faceoff'}
# the program file of a release: packaging/build.ps1 builds the exe, .github/workflows/build-desktop.yml the others;
# app/selfupdate.py replaces the exe and the AppImage (its SYSTEM_ASSETS names the same files)
EXE_NAME = {'linux': 'OvertimeNHL19-x86_64.AppImage', 'darwin': 'OvertimeNHL19-macos.dmg'}.get(sys.platform,
                                                                                              'OvertimeNHL19.exe')
