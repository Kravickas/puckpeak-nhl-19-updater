# Changelog

What changed in each version, for players.

## Unreleased

### Changed

- **Patch's progress bar follows the time.** It used to jump between fixed points (2, 50, 60, 62, 65, 85, 92 %) and
  stand still for minutes at 62 % and 65 % while the jerseys were made and the art was written. Now Patch first
  measures its work (the textures to make, the bytes to check, copy, write and read back), turns it into time with
  this PC's speed for each kind of work, and the bar moves by that: 1 % is about 1 % of the time. A step that turns
  out larger or smaller than measured never makes the bar jump back or ahead, only go slower or faster. Each step's
  speed is measured while it runs, and kept after the Patch (`patch_speed.json` in the cache), so the next Patch
  starts with this PC's speeds. The log says how long each step took against its plan.
- **A faster first Patch:**
  - The texture encoder makes BC7 textures about 20 % faster (the jerseys' slowest kind), byte for byte the same
    textures: the same numbers in the same order, fewer copies of them. Jerseys made before stay as they are.
  - The club logos are made on every core (processes, as the jerseys): on threads they used two or three.
  - A pack downloaded by the app and found to be the published file (its sha256) is not unpacked again at the first
    Patch to check it; each texture is still checked against its sha256 as it is written into the game's archives.
  - A pack that is checked in full (one from the exe or the repository, or the 3D jerseys against the game the first
    time) is checked on every core.
  - Jerseys and club logos made at Patch are not unpacked again right after: they were checked as they were made.
  - The game's archives are listed once per Patch for the club logos and every jersey family.
- **A Patch with the art unchanged no longer writes it again.** Patch wrote every art archive again and read it all
  back on every press (over 15 GB with every pack on). An archive is kept when its content is the one the last Patch
  wrote (the same textures by sha256 in the same order, the same game archive under a copy), it is still as it was
  written (size and time, else its sha256) and its table still lists every texture at its size. The first Patch after
  updating writes everything once.
- **The 3D jerseys pack is checked against the game once**, not on every Patch: its deltas are laid on the game's
  files and checked in full the first time, then recorded with the game's archives (names, sizes, times). While
  neither changes, each texture is still checked against its sha256 as it is written.

## 0.90.2 (2026-11-11)

### Added

- **Play NHL 19 button.** A green button at the top right of every tab starts the game. It is grey until the app has
  found NHL 19, and shows the download progress while it fetches the emulator.
- **Choose the emulator build: Nightly or Kravickas.** Nightly (the default) is the official shadPS4 pre-release
  `4788f0b` (2026-11-10), unchanged from its GitHub release; on a test PC it ran about 20 % faster than our previous
  build. Kravickas is the Overtime build of Kravickas's NHL19-Build from 0.90.0. Pick one under Setup, Boost; the app
  downloads it and keeps both. Source: https://github.com/shadps4-emu/shadPS4 and
  https://github.com/MatusRiedl/shadPS4/tree/overtime-ship-1.
- **Live matches.** Matches being played right now show in Online, Matches with a pulsing red LIVE dot and how many
  minutes they are in. The game sends the score only at the end, so a live row has no score.
- **My games, redone.** Goals for and against per game as a chart, meters for your rates, you-against-opponents bars,
  your recent form as W/L pills, and a Big view pop-up with the larger charts.
- **Ping readout in any online match.** The connection pill now also shows in a match found inside NHL 19 (not only
  in lobby matches), when the game was started from the app.

### Changed

- **Good emulator settings from the start.** The first time the app finds a game, it turns on PS4 Pro mode, direct
  memory access and the shader cache, sets extra DMem to 3500 MB (never lowers a bigger value) and vblank to 9999.
  These are set once; you can change any of them later in Game settings.
- **First-run Patch defaults.** A new install has teams, league, menus and server texts on, and of Updated assets
  only team art, 3D jerseys and player photos, which it downloads on its own after the first look.
- **Lobby matches no longer lock vblank to 60.** Each player keeps their own vblank; mixed values play fine.
- **Lobbies use the emulator build the server picks**, and the app gets it on its own. Update to 0.90.2 to keep
  joining lobby matches.
- Online: "History" is now "Online", "Recent matches" is now "Matches", and Ranks has its own section next to the
  leaderboard. The "Match review ready" banner and the CONFIRMED tag are gone.
- Setup: the Folders checks are folded away (open them to see each one); the Boost resolution buttons line up left.
- New splash screen.

## 0.90.1 (2026-11-11)

### Changed

- **Lobbies are Quick only for now.** CHEL lobbies are not ready yet, so the app no longer offers them: Host a lobby
  makes a Quick lobby (two players), the public list shows Quick lobbies only, and a CHEL lobby code says CHEL lobbies
  are not available yet. World of Chel itself is unchanged.

## 0.90.0 (2026-11-11)

### Added

- **World of Chel online.** The World of Chel tile is back: the hub, your CHEL player and customization (every item
  unlocked; level and XP are shown but lock nothing), drop-in 6s, 3s and 3-on-3, clubs, club seasons, Ones and Pro-Am
  run on the Overtime servers. Some modes are still being tested with real players; see the known issues below.
- **CHEL lobbies.** Create a Quick lobby (two players, as before) or a CHEL lobby for 1 to 12 players. The host picks
  the mode, and drop-in lobbies can split into Home and Away. The lobby list shows which kind each lobby is. In NHL 19,
  open World of Chel, pick the lobby's mode and press Play.
- **Every human game counts.** World of Chel games between people are rated in the same rank as Versus, Shootout and
  Threes. Games against the CPU only, and Pro-Am, are logged but not rated.
- **Rank icons.** Each rank has its own icon in the leaderboard, the ranks list, next to your rating and in the
  after-game pop-up.
- **Smoother emulator.** Lobby matches and Boost now use an Overtime build of shadPS4: Kravickas's NHL19-Build
  749170d plus earlier frame flips, steadier frame pacing and higher thread priority. On a test PC at unlocked vblank
  (average / 1% low / 0.1% low fps): 77 / 46 / 44 before, 94 / 71 / 66 now. The CPU math is unchanged, so Intel and AMD
  PCs still play in step. GPL source: https://github.com/MatusRiedl/shadPS4/tree/overtime-ship-1 (tag
  `overtime-ship-1`). Players on 0.90.0 meet players on the same emulator build only, so update together.

### Changed

- **"Keep the World of Chel tile" is on by default**, also for existing patches (re-patch once).
- Creating a CHEL lobby on a server that is not updated yet now says the server needs the update (Quick lobbies still
  work), instead of "the game mode is versus, shootout or threes".
- The app no longer says an older Kravickas build is "newer" when the server runs an Overtime build on top of it.

### Known issues

- Ones: PLAY NOW does not find a game yet. Pro-Am: the challenge list is empty. Club games: the dressing room fails
  before the search. Club Members: the screen does not load.
- A new profile fails the World of Chel player check until NHL 19 is restarted once after creating the CHEL player.
- Class and trait names show as "Class 13" and "Trait 6".

## 0.83.0 (2026-11-10)

### Added

- **No shadPS4 install needed.** Find game takes NHL 19's `eboot.bin` or its PKG. When there is no shadPS4 on the PC,
  the app downloads Kravickas's NHL19-Build (the build Boost and lobby matches already use) and plays on it. A shadPS4
  you already have is used as before.
- **Install from a PKG.** Pick the game PKG and the app installs it into a new folder next to the PKG; pick the 1.60
  update PKG and it goes into a `-patch` folder beside the game, which shadPS4 loads. DLC PKGs are refused, free space
  is checked first and nothing already there is overwritten. It uses shadPS4Plus's `pkg_extractor` (GPL-2.0, a
  separate program), downloaded from its GitHub release the first time and checked by its sha256.
- **Connection in the corner.** While a match runs, a small pill at the top right of the game shows the ping and the
  packet loss: green, yellow or red, and "NO PACKETS" or "NO DATA" when the link stops. Its switch, "Connection in
  the corner", is under "When the game starts" (on by default). Windows only.
- **Game settings, Controllers and Keyboard.** Setup → Boost performance has a Settings row. Game settings shows
  shadPS4's settings for NHL 19 in tabs, with a description of each one; settings Overtime needs are shown locked.
  Controllers maps the pad's buttons, sticks, deadzones and lightbar; Keyboard binds up to three keys, a combination
  or a mouse button per button, and the mouse as a stick. Press F8 in the game to use new bindings at once.
- **Fullscreen (Borderless) by default.** NHL 19 now opens borderless for everyone, from the next Patch or Play. Pick
  another display mode in Game settings and the app keeps it. Lobby matches play exclusive Fullscreen as borderless.
- **Newer Kravickas builds are announced.** The Overtime server checks Kravickas's NHL19-Build on GitHub. When a
  newer one is out, the Boost card says so; Overtime moves to it after a test.

### Changed

- **The same graphics settings for everyone.** Patch sets shadPS4's Readbacks mode to Precise and turns on Readback
  Linear Images in NHL 19's own shadPS4 settings, against graphical glitches. Play puts them back if they were
  changed, lobby matches always play with them, and Unpatch gives you your own values back.
- **The firewall rule is optional.** Matches go through the Overtime server, so the rule no longer decides whether
  you are ready. Multiplayer → Advanced still has "Allow..." for it: it only helps a direct link, used when the
  server cannot carry a match.
- **Multiplayer → Advanced in one grid.** Server, CPU, Reports and Firewall share the same columns; "Send the
  result..." is now "Send result...".
- ShadNet sign-in works on a PC that never ran shadPS4 (the app writes shadPS4's default users first).
- **Cleaner screens.** The Update tab no longer shows the steps row or the "patched by an older Overtime" line.
  Setup's roster card shows "13 free save slots from 15 total." and drops its hint line, and the Boost card says what
  it does: 60 FPS.

### Fixed

- With nothing picked yet, Setup said "shadPS4 and NHL 19 are ready" and Folders said "all found".

## 0.82.0 (2026-11-10)

0.80.1 and 0.81.0 were never published; what they had is in here. The texture encoder, 720p, the movable downloads
folder, the power-cut-safe writes and the faster Patch are Kravickas's work (pull request #1).

### Fixed

- **Intel and AMD PCs play each other online without drifting apart.** Two instructions the game uses in its movement
  math give slightly different answers on Intel and AMD CPUs, so the two games drifted apart (a goal not counted, then
  LOST CONNECTION). The game patch now has a **Cross-CPU fix** that makes those answers the same on every CPU, and on
  an Intel PC the app also turns on shadPS4's AMD math (its `redzone_patches` setting) when it installs the patch, so
  online play outside a lobby has it too. A 10th gen Intel against a Ryzen 7 9800X3D stayed in step for the whole
  test match.
- The app finds your saves when shadPS4's first player is not user 1000.
- **Sharper jerseys, club logos and photos made on this PC.** They were compressed with Pillow's own BCn writer, which
  picks a block's two colours badly, never gives BC3 alpha its own ends and cannot write BC7. A new encoder (numpy,
  in the exe) does it properly, checked against two decoders. Every texture keeps the game's own size, format, mips and
  header (checked byte for byte on the game's Czech jerseys). How close a made texture is to its picture (100 % =
  identical, from the average difference of every colour value), and how much smaller that difference got, measured on
  the national team pack (10 of each kind, at the game's sizes):
  - 3D jerseys 98.7 % to 99.8 % (the difference 84 % smaller), socks 98.6 % to 99.9 % (93 % smaller), the numbers
    99.2 % to 99.9 % (85 % smaller);
  - UI jerseys, logos and photos (the game's BC7 art) stay BC7 instead of turning into BC3: UI jerseys 99.7 % to 99.8 %
    (45 % smaller), a photo 98.9 % to 99.7 % (73 % smaller), a logo with soft edges 98.9 % to 99.6 % (61 % smaller);
  - the Czech chest logo on the game's own jersey textures 98.2 % to 99.5 % (home, 71 % smaller), 98.8 % to 99.4 %
    (away, 48 % smaller): no stair steps, specks or pink white;
  - a block of one colour (three quarters of a jersey) gets the best colour pair there is, from a table.
- **Mips made like the game's own.** Measured on NHL 19's own Czech jerseys, their mips are their full size scaled
  down with a bicubic filter in the stored colour numbers; the made ones were box-filtered, which is softer. The mips
  (what shows a few metres away: the screenshot's chest logo is mip 2) are now made that way, weighted by alpha, and
  the smallest ones are no longer darkened by black padding.
- The textures made before are made again once, at the first Update or Patch that makes them.
- **Nothing breaks when the power goes.** Every file the program writes now reaches the disk before it takes the old
  one's name: the patch files and their record, roster saves, settings, your edits, shadPS4's and QtLauncher's files,
  the downloads, the jerseys, club logos and photos made on this PC, the record of the packs checked, and the program
  itself when it updates. Before, a power cut right after a write could leave a file of the right size full of zeros,
  which Patch's quick check took as intact.
  - Settings were written in place: a cut while saving them lost them. Now whole or not at all.
  - Repairing a roster save swaps the whole folder, so its two files always belong together; a swap the power stopped
    halfway is put back at the next start.
  - A damaged patch record now says what to do instead of stopping the Game patch tab.
- Two match setups can no longer run over each other (a lobby match starting while the app still puts the last one
  back): each one is put back only by what made it.
- A lobby match keeps the text language your patch was made with (it fell back to English).
- Downloads and cache: a picked folder that already holds other files gets a folder of its own inside it, and moving
  away from such a folder leaves its other files where they are.

### Added

- The Game patch card's Online row checks the Cross-CPU fix after NHL 19 starts: "Cross-CPU: ready", or a red line
  not to play online in that session (with the reason).
- **3 min** in Period length, and **new lobbies start at 3-minute periods** (quick games). 4 to 20 minutes are still
  there.
- Each match game's log is kept (`%APPDATA%\OvertimeRoster\match\logs`, the newest 8), so a desync can be checked.
- **Check my CPU** (Multiplayer → Advanced, the CPU row): it downloads a small test program
  (`cpu-estimates.exe`; its source is `tools/cpu_estimates.py` in this repository), runs it for about a minute (two on
  a CPU with two kinds of cores) and says whether your CPU gives the same answers as the tested AMD or Intel CPUs. It
  runs only when you press it and sends nothing by itself; "Send the result..." asks first.
- **Reports, off unless you turn them on.** After a crash, or a match the server saw end early, the app can send the
  game's log so the problem can be found. It asks once after the update; Multiplayer → Advanced has the switch and a
  "Send a report" button that asks every time. Folder paths, user and computer names, your Online ID, IP and e-mail
  addresses are taken out of the log, and a password never goes. The Privacy list there says everything a report
  holds. Reports are kept for 30 days.
- **720p.** The Resolution choice (Boost performance card) has 720p next to 1080p and 1440p: Kravickas's
  "Resolution 1280x720 (16:9)" patch, for a weaker GPU. It renders below the game's own 1600x900 size, so it needs no
  memory patch and no Additional DMem (your own value stays). Built into the app like 1440p, nothing to download;
  a patched game takes it at its next start, no Patch needed.
- **Setup, Folders: Downloads and cache.** Where the downloaded packs and the files made on this PC (jerseys, club
  logos, photos, several GB with every pack) go, a folder like the others: Change... moves them to a folder you pick,
  for example on the drive NHL 19 is on, so nothing big stays on C:. Auto moves them back. On another drive every file
  is copied and checked first, the program switches to the new folder only once all are there, and only then removes
  the old ones; a copy that fails changes nothing. A folder inside NHL 19, its update or mods, shadPS4's data or the
  saves is refused. When the drive of the folder you picked is not there, the program uses its own folder until it is
  back.
- **Setup is wider on the left** (as the Game patch tab), the rosters on the right take less room. **Each folder is
  one line in a tile** like the Update tab's switches: its bar green when the folder is there and good (found or
  yours), red when it is not; the paths line up.

### Changed

- **Only finished matches count** (server update, 2026-11-10). A match that a player leaves or drops before the end
  counts for no one: it leaves the list, the board, the in-game Recent Games and every rating. This replaces the 1-0
  forfeit loss. A match with no result or only one report stays listed for an hour, so the result can still be
  entered or confirmed.
- **Everyone needs 0.82.0.** An older app and 0.82.0 are never paired, because only one of the two games would have
  the Cross-CPU fix. When one app is older, the lobby says who updates.
- **Games meet only games set up like them.** The app gives the game an online version that stands for its patch and
  shadPS4 build, so the server pairs only games that stay in step. Lobby matches always play on the same shadPS4 build
  (the Boost one). If a game started from Game patch → Start runs another build or has no Cross-CPU fix, Start says so.
- **The Boost and lobby shadPS4 build is the newest Kravickas NHL19-Build** (749170d, 2026-11-09): graphics, file and
  save fixes since the last one. Boost players get it as an update; lobby matches use it.
- **Patch reads the art once, then checks it at the end.** It used to unpack every texture of every art pack three
  times: a full check before writing, again to write it, and once more from the written archive. Now a pack zip
  checked in full once is not unpacked again until it changes (size or time; the record is `packs_checked.json` in
  the cache): each texture is unpacked once, checked against its pack's sha256 as it is written. At the end of
  Patch every written archive is read back whole and its sha256 compared with the one taken while writing; one that
  does not match is removed and Patch says so (press Patch again: the packs are still in the cache). 27 % less
  time on 560 MB of test art from the second Patch on (2.98 to 2.17 s, warm disk here).
- **Every core.** Jerseys, club logos and photos are made on every core the program may use. The game's archives and
  the packs are read on one thread and the packs are written in order, so they are byte for byte the ones one thread
  makes (checked with 1 and 6 workers). A texture made on its own splits its blocks over the cores instead.
- Making a texture takes longer: a jersey colour map (2048 x 2048, its mips included) about 2.7 s instead of 0.5 s
  on one core, a 512 x 340 BC7 photo about 1.4 s. A photo is made once and kept in the photo cache, next to its
  picture.
- **The art archive is read on every core while Patch writes it**: each texture is unpacked and checked against its
  pack on its own thread, written in order (byte for byte the archive one core writes). The game's normal and colour
  maps the jerseys cover are unpacked on the workers too, not on the one thread that reads the archives.
- The exe is about 10 MB larger (numpy).
- **A faster Update**: each team's look at the roster reads a table's column in one pass instead of one field at a
  time. Measured on tables of 11,000 players: 57 to 21 ms and 37 to 12 ms per team. The roster it writes is the same.
- **Texture blocks put in the PS4's order in one pass**, in an order worked out once per texture size (a 1024 x 1024
  BC3 texture with its mips: 45 to 14 ms to retile). The bytes are the same (checked on 3360 shapes).

### Known

- The Cross-CPU fix is made for the v1.60 `eboot.bin` (CUSA11126 and CUSA11116 have the same one). A game with
  another `eboot.bin` gets the patch without it and meets only games like its own; the Game patch card says so.
- Intel 12th to 14th gen (performance and efficiency cores) is not measured yet.

## 0.80.0 (2026-11-08)

### Added

- **Online Threes.** MULTIPLAYER, Match rules has **VERSUS | SHOOTOUT | THREES**: 3 on 3, one player a side, the other
  skaters are CPU. Once both are ready the game opens Threes online by itself. Threes games show in your history and
  the rating strip ("Threes w-l").
- **Ready makes both games match, for that match only.** In a lobby, Ready now sets up a match copy of the game on each
  side: the NHL 19 build of shadPS4 (its own copy, downloaded once), the host's online patch plus your own picture
  settings (1440p and the like stay yours), and the match timing. Your own shadPS4, rosters, data, art and settings are
  never changed: everything goes back when NHL 19 closes, or at the next start of the app after a crash.
- **No need to close NHL 19 before Ready.** If it is open, the app restarts it for the match (it asks the game to close
  first and waits up to 10 seconds).
- An unpatched game can play online: the Patch row says "Online ready: Ready sets up each match by itself".

### Changed

- **MULTIPLAYER has three columns:** you and the checks before a match, the lobby, then your rating and history.
- With a 0.80.0 partner, Ready no longer switches your own shadPS4 to the NHL 19 build or patches your game; the match
  copy does that instead.
- While a match setup is in place, Game patch waits ("press again after that") instead of writing over it.

### Known

- Both players need 0.80.0 for the match setup. With a 0.70.x partner the lobby works as before and names who updates.
- The match setup was tested in code and on the server, not yet in a two-player game over the internet.

## 0.70.8 (2026-11-08)

### Changed

- **Ready gets your game ready for online play by itself.** Before it tells the lobby, Ready switches NHL 19 to the
  NHL 19 build of shadPS4 (Boost performance, the build every online player uses; also a newer published one), brings
  the game patch up to this version and, on a game that was never patched, puts in only what online play needs (about
  a second, no roster or art). No button to press. The card shows what it is doing.
- **The patch check compares only what reaches the other game.** A 1440p game and a 1080p game, Be a Pro on or off, or
  the server written as a name or an address no longer count as "patch differs".

### Fixed

- A match the two players finished could end with "Failed to retrieve data" when an earlier try of the same two had
  been left early (server fix).
- Two different shadPS4 builds playing each other drift apart in play (repeated faceoffs, then the match ends): the
  lobby now says so before the game starts, and Ready fixes it on your side.

## 0.70.7 (2026-11-07)

### Added

- **Online Shootout.** MULTIPLAYER, Match rules has **VERSUS | SHOOTOUT** left of Roster: the lobby host picks the game
  before Ready. SHOOTOUT greys out the rules a shootout does not use and keeps skill level, game style and goalie
  control. Once both are ready the game opens Online Shootout by itself; pick a team, READY, play.
- Searching from the game's own Online Shootout menu with the default settings meets other shootout players only.
- **My games** shows Shootout numbers on their own (attempts, goals, scoring % and save %); the Versus per-game numbers
  count Versus games only, and game rows say "Shootout".
- One rating over Versus and Shootout; the win-loss record is kept per game.

### Known

- Played in the lab (two games on one network), not yet between two players over the internet.

## 0.70.6 (2026-11-07)

### Changed

- **A much faster Patch** (measured here on the real game, warm disk):
  - League, menus and database are prepared in 0.12 / 0.12 / 0.50 s instead of 0.88 / 0.44 / 1.66 s: each game
    archive's file list is read once per Patch, not 660 times.
  - The game's text (76,000 strings) decodes 4.7 times faster, same strings.
  - The Patch tab no longer hashes your patch files each time it opens (0.37 s before, about 0 now).
  - A second Patch no longer reads back 15.6 GB of art to check files it wrote itself (about 9 s warm, more on a cold
    disk or a hard drive); Patch and Unpatch compare size and time first and hash only when they differ.
  - Update reads the people pack's list, not its 5,900 photos (2 s before, 0.02 s now).
- The first Patch after updating still hashes the copied archives once; the speed-up shows from the second Patch on.
  Writing the files is unchanged, so a Patch is faster but not instant.

## 0.70.5 (2026-11-07)

### Fixed

- **Play uses the shadPS4 data folder you set.** shadPS4 reads the `user` folder inside the folder it is started from.
  With QtLauncher's layout (shadPS4 in `...\ShadPS4\NHL`, its data in `...\ShadPS4\user`) Play started it from the
  exe's folder, so shadPS4 made a fresh `%APPDATA%\shadPS4`: no Overtime patch, network and ShadNet off, no saves. The
  game asked to set NHL up again, showed no ShadNet id and never reached the server. Play now starts shadPS4 from the
  folder above `user`, as QtLauncher does. A data folder shadPS4 cannot use (not named `user`, not
  `%APPDATA%\shadPS4`) is refused in Setup and at Play.

### Changed

- **Faster Patch** (thanks to Kravickas): each pack and game archive stays open while the art layer reads it, instead
  of being opened again for every texture. Reading the people pack's 5,900 portraits went from 59 s to 2 s here.

## 0.70.4 (2026-11-07)

### Fixed

- **Portable shadPS4 is found.** Find game looks for shadPS4 next to the NHL 19 folder you pick (up to two folders
  above it), and for NHL 19 next to the shadPS4 you pick, instead of relying on `%APPDATA%` (empty when shadPS4 keeps a
  `user\` folder beside its exe). Saves follow shadPS4's Home Folder setting (shadPS4 Settings, Paths tab).
- **Texture mods on the EU game (CUSA11116).** Patch stopped with "art layer: ...teamlogos/hutcardheritage/t1.gnf ...
  archive is unknown" while applying logo packs. A texture whose folder this game lacks now goes into the archive of its
  nearest parent folder.
- **A game folder with only the update in it** is refused at the start with a clear message (the base game's
  `databigs\inxp_10.big` and others are missing), instead of the patch stopping halfway.

### Added

- **Folders list** (Setup, "Where is NHL 19?" card): shadPS4, NHL 19, shadPS4 data and Saves, each "found" or "yours".
  Change... sets one yourself (checked first), Auto finds it again. A folder you set is never replaced by what the
  program finds.
- **Lobby chimes:** a soft tone when your lobby opens, another when somebody joins, a third when you leave or the lobby
  closes.
- **MULTIPLAYER tab shines in gold**, and the Setup card is now called "Where is NHL 19?".

### Changed

- A lobby nobody joins closes after 30 minutes.

## 0.70.3 (2026-11-07)

### Added

- **60 fps replays, menus and cutscenes.** NHL 19 dropped to 30 fps on its own for menus, goal replays, celebrations and
  close-up cutscenes (live play was already 60). Kravickas's "60 FPS replays" patch is now part of the Overtime patch,
  on for everyone.
- **Resolution: 1080p or 1440p** (Setup, Boost performance card). 1080p is the game's own; 1440p renders at 2560x1440
  (Kravickas's resolution patch), sharper, needs a stronger GPU, and sets shadPS4's Additional DMem to 3500 MB. Back to
  1080p, or Unpatch, puts your own value back. Works with any shadPS4 build.
- **No re-patching:** update the app and press Play; the game picks up both on its next start.

Both patches are Kravickas's work (github.com/Kravickas/ps4_cheats), shipped with his OK.

## 0.70.2 (2026-11-07)

### Added

- **Hometown Remix jerseys (BETA).** A new switch in Game patch, Updated assets. Each NHL team gets its Hometown Remix
  jersey in place of one of its other jerseys (Vegas: the away jersey, Utah: the third, Seattle: the alternate). Made on
  your PC at Patch from retail photos, so colours, crest and stripes are close but not exact. Switch it off and Patch
  again, and the normal jerseys are back. Not finished: expect rough edges.

### Also in 0.70.1 (no more silent SIGN IN REQUIRED)

- **Game patch** writes shadPS4's two network switches into the game's "Network" section too, and fills empty ShadNet
  server fields there. Unpatch takes out what it added.
- **Lobby start** is refused, with words, when shadPS4 has no ShadNet sign-in for NHL 19; after the game boots, the card
  says so when the network is off or ShadNet refused the sign-in, instead of pressing through.
- **Setup:** one "Find game..." button (shadPS4QtLauncher.exe, shadPS4.exe or NHL 19's eboot.bin).
- **Game patch, "What's in your game now"** is a short verdict plus what is patched in and the Online row; less red in
  the app (card numbers and markers are metal).

## 0.70.0 (2026-11-07)

### Changed

- **Game patch, simpler.** The switches sit in three groups you can open: Teams and league, Menus and server texts, and
  Updated assets. Each group has its own switch (on: its main parts, off: everything in it), and you open a group to
  pick single parts. No more all-or-nothing art pack.
- **Updated assets download one by one.** Team art, 3D jerseys, player photos, the alternate and national team jerseys
  and the centre ice of every league each download when you switch them on. A dot before each name shows whether it is
  already in the game (green) or needs Patch (yellow).
- **Plain names.** "NHL 27" is gone from the app: Updated assets, Team art, 3D jerseys, Updated ratings and types. The
  default roster switch now just says what it does (all 32 teams; its "?" explains NHL 19 shipped with 31 in 2018,
  before Seattle). The World of Chel switch says it only keeps the tile (Overtime does not run World of Chel yet).
- **"What's in your game now"** (Game patch, right card) uses plain words: Patched in, files changed and intact,
  Check for damage, Backup copy of the game.
- **Update tab fits without scrolling:** the switches are compact tiles, with the season and data choices in one bar.

### Fixed

- **Real lines and captains** now shows on the Update tab (the switch was missing).

### Also in 0.60.3 and 0.60.4 (in-app updates)

- **ShadNet sign-in and sign-up in the app** (Multiplayer); your account is found without starting NHL 19 first.
- **Lobby host picks the roster:** the server roster, or the host's own open roster with its lines, uploaded at Ready.
- **Both players need the same game patch** before Ready in a lobby.
- **Forfeit:** a player who leaves or drops a match in play loses it 1-0 (server update).
- Multiplayer tab no longer crashes on the rank progress bar.

## 0.60.2 (2026-11-07)

### Fixed

- **Online Versus: a player quitting no longer freezes the other game.** When your opponent leaves mid-match, your game
  shows "Lost connection" and takes you out of the match instead of freezing on the ice. The match is not counted.
  (Server update: works on every app version.)
- **ShadNet showed as off** on PCs where shadPS4's settings files start with a byte-order mark (some editors save them
  that way).

### New

- **Online Versus: pick your team.** Both players can change their team on the Online Versus setup screen; before, each
  played their favourite team. (Server update.)
- **Multiplayer: a new lobby is in the public list by default.** Untick "Show it in the public list" for a private lobby.
- **Clean sheet:** the match history and standings start fresh with this release.

## 0.60.1 (2026-11-05)

### Changed

- **Update comes first.** The tabs now read Setup, Update, Game patch, and a strip on both tabs shows the order: Update, then
  Game patch, then in NHL 19 pick the new roster in Rosters > Active Rosters. Patch makes the club logos and jerseys for the
  roster NHL 19 plays, so patching before updating gave the old roster's logos.

## 0.60.0 (2026-11-05)

### New

- **Penticton Vees in the WHL** for 2026-27 (Play Now and Roster Management, like NHL Legacy), with their name, logo and roster.
- **Patch tab:** the patch explanation is a "?" next to the Patch button.
- **New app icon** (the app, its window and the splash).

### Fixed

- **Versus:** Stats Central no longer loads forever and Recent Games answers with a message instead of an empty reply (server update).
- **Logos:** the six clubs NHL 27 lacks keep their NHL 19 logos, the result says so, and all 32 AHL logos were checked in game.
- **Jerseys:** throwback rows read ALTERNATE instead of a stale "2016-17 HOME" (press Update again).
- **Utah:** helmets stay black with a roster made by this version (press Update again, then pick it in Rosters > Active Roster).
- **"Server not reachable":** the game gets the network settings it needs on more PCs.

## 0.50.1 (2026-11-04)

### Fixed

- **Club logos of the AHL clubs that moved.** Abbotsford, Henderson, Hamilton and Calgary kept their 2018 logos when the club logo pack
  arrived after Update, or when Patch ran in a later session of the app. Patch now makes the logos of the roster you play.
- **Update says when it skips the club logos.** It downloads the club logo pack first when it is missing, and the result says when it
  could not.
- **The result says when a club has no logo**, and Update says when new players got no photo because the photo pack is not in the game.

## 0.50.0 (2026-11-03)

NHL 19 now gets what NHL Legacy gets from the same data: the same people on the same clubs, their lines, letters, numbers,
contracts, attributes and photos.

### What is new

- **Same rosters as NHL Legacy.** The AHL, SHL, Liiga, DEL, Extraliga, NL, OHL, QMJHL and WHL now come from the leagues' own data. NHL 27
  is used only where that data has nothing: the ECHL, ICE Hockey League, HockeyAllsvenskan and the other European clubs.
- **Real numbers, letters and sizes.** A club's own list gives each player their number, height, weight, shot and C or A. Players nobody
  rates get a rating from Legacy's rule.
- **Real contracts.** Contract values follow the same list as NHL Legacy, and players without an NHL deal get a starter deal by league and rating.
- **Real lines where they exist.** Clubs with published lines play them. Clubs without, and Columbus and Winnipeg's forward lines today, are
  dealt by rating.
- **National teams.** The eight smaller teams are built by Legacy's rule. Canada, the USA and the other big teams come from the IIHF
  lists: NHL Legacy's own squads for those are not in the shared data, so those teams differ.
- **Player photos of every league.** A new pack of about 200 MB gives some 6,000 players of every league their photo.
- **Rink art from NHL 27.** A new switch on the Game patch tab: the IIHF emblem at centre ice and the IIHF puck in national team games, and NHL 27's pucks,
  board ads and league logos. National team games keep NHL 19's board ads.
- **Club logos and centre ice of every league.** Clubs that changed their logo since 2018 show their current one, made on your PC from a 43 MB pack.
- **Jerseys of every league, much smaller downloads.** The extra jerseys (NHL alternates, national teams, and now the AHL, ECHL, junior and
  European clubs) are made on your PC from small packs (13 to 169 MB instead of up to 1.2 GB each). The first Patch with them on takes longer
  (about 15 minutes with all three on; the club jerseys alone about 11); after that it is quick. NHL teams whose pants changed colour since 2018 wear the new colour.
- **The 2026 AHL.** Henderson Silver Knights, Abbotsford Canucks, Hamilton Hammers and Calgary Wranglers take the four slots of the clubs that
  moved, with their names, arenas, colours and jerseys, and every NHL team has its 2026 farm club. Coachella Valley, Seattle's farm club,
  gets its real players too and shows in the app's AHL list; in the game it plays in Season and Franchise only (NHL 19's Play Now has no
  place for it).
- **2026 arenas.** Every NHL team plays in its 2026 arena, and Buffalo, Columbus and the Islanders wear their current colours in the menus.
- **New players' photos.** A player new since the photo pack gets his photo downloaded when you press Update.
- **Changes by team.** The list of changes now starts with a section per team: who joined, left, was called up, signed or retired.

### Fixed

- **Players kept their NHL rights.** A prospect playing in junior or in Europe was cut from his NHL team's list. He stays on it now.
- **Free agents retired too young.** Every free agent no list named retired, 25-year-olds too. Now only those of 30 and more do, and last
  season's NHL players nobody signed are free agents you can sign.
- **Small clubs signed NHL stars.** An ECHL club short of a player signed the best free agents. Clubs now sign players of their own level,
  and junior clubs young players.
- **Call-ups.** An NHL team that cannot dress a full line-up calls up from its farm club before it signs a free agent.
- **Gear.** A goalie who changes team wears his new team's mask, a skater who comes to an NHL team gets a stick in its colours, and new
  players no longer wear their look-alike's gear.
- **Salaries without the 2026 cap.** With the 2026-27 salary cap switched off, contracts are scaled to NHL 19's own cap.

- **The roster you saved must be the active one.** Update saves a new roster but does not change which one NHL 19 plays. If yours is
  not active, the Update tab now says so in red, and tells you where: in NHL 19, Rosters > Active Rosters.
- **Lines were wrong after Update then Patch.** The default roster the Patch makes after an Update dealt its lines by rating. It now plays the
  real lines.
- **Photos went missing after an Update.** A roster saved by Update lost its photo flags, so many players showed no photo.
- **The European NHL 19 (CUSA11116).** Patch stopped with "eng_us-meta.xml not in ...". It now uses the English text file
  your game has. A folder with only the game's update gets a plain message saying which folder to pick.
- **"Server not reachable" on some PCs.** Overtime now also trusts the certificate list it carries, as NHL Legacy does, so a
  PC without Windows' newest certificates can reach the server. If it still says not reachable, the error log says why.
- **No Patch after changing network settings.** A new server address, or shadPS4's network switches turned off, is put
  right when you press Play. Changing other shadPS4 settings no longer asks you to Patch again.

## 0.40.0 (2026-11-02)

Update now takes the whole game: every league, player, calendar and national team.

### What is new

- **Real rosters for the big leagues.** SHL, Liiga, DEL, Extraliga, NL, OHL, QMJHL and WHL come from the leagues' own data, the same
  source as NHL Legacy. The AHL, ECHL, ICE Hockey League and HockeyAllsvenskan come from NHL 27. New players get ratings too.
- **New clubs.** A club that left a league makes room for one that has no place in the game: Wenatchee Wild, Newfoundland Regiment and
  others take the slot, with the old slot's logo and arena.
- **Real calendars.** 2026-27 schedules for the SHL, DEL, Extraliga, NL, OHL, QMJHL, WHL and ECHL, next to the NHL, AHL and Liiga.
  Clubs that have no slot in NHL 19 lose their games, and each league is evened out, so some play fewer games than in real life.
- **National teams.** 20 squads from the IIHF. Russia has played no IIHF event since 2022, so its team is the best Russians at clubs.

## 0.30.0 (2026-11-01)

Rosters of every club league from NHL 27, centre ice for the clubs of every league (not national teams), national team jerseys, and many fixes.

### What is new

- **Every club league from NHL 27.** The Update tab now rebuilds the SHL, Liiga, DEL, Extraliga, NL, ICE Hockey League, the
  European clubs, OHL, QMJHL, WHL, ECHL and HockeyAllsvenskan from NHL 27, as it did for the AHL. Clubs NHL 27 has under a new
  name take that name (Frolunda HC). Clubs it does not have keep their 2018 roster.
- **More jerseys and ice** (new switches on the Game patch tab): centre ice for the clubs of every league (45 MB), national team jerseys (149 MB)
  and NHL alternate jerseys (765 MB) from NHL 27. Switch one on and it downloads by itself, switch it off and it stays on your PC.
  Press Patch to put them in the game. Alternates take the place of a team's throwback jerseys.
- **Boost performance** (new on Setup): one button puts NHL 19 on Kravickas's NHL 19 build of shadPS4, for better performance and
  graphics. Thanks to Kravickas for allowing it. Disable puts your own shadPS4 back. Your saves stay the same.
- **My games** on the Multiplayer tab: your games with score, teams, opponent and box score, and your totals.
- **Your hand-set lines stay.** Lines you set in the Lines tab survive an update.
- **The app updates itself:** from this version on, Update now downloads, checks and restarts on its own. 0.20.0 updates to
  this version the way it always did.

- **A window that never comes up.** "Starting..." shows until the app is ready. If the window stays blank the app reloads it, then
  opens in your browser, with Try again and a start log to send us. Each start has its own browser folder.
- **A player who leaves pays for it.** When your game reported the result and the other player never did, it counts after an hour,
  unless their own report says otherwise. Results typed in the app still need both players.
- **Update warns you.** The result names a club short of 2 goalies or 18 skaters (the game hangs on it) and free agents who are also on a club.

### Fixed

- **Goalies stay goalies.** A real goalie is never matched to a skater with the same name and birth date.
- **Any shadPS4 works.** The app no longer asks for the NHL19-Build. Pick your emulator folder or `shadPS4.exe`; with QtLauncher, the
  version selected in it is found by itself. The app now opens on Setup.
- **The game closed when you picked a custom roster.** A first save on a PC without an online roster was written wrong. The
  app repairs such saves by itself when it starts, with a backup first.
- **Be a Pro with Seattle:** the first games now match Seattle's calendar.
- **Seattle in other leagues' Season lists** is gone.
- **A first save with no game save yet** now works, and saving is refused while shadPS4 is running.
- **Multiplayer tab:** it says why ShadNet does not connect and what to do next.
- **"Patched, with 1 problem"** no longer shows for a file this version builds itself.
- **Split installs:** `-UPDATE` and `-patch` are read the way shadPS4 mounts them.
- **CUSA11116** is recognised as well as CUSA11126.

### Known limits

- Not proven with two PCs yet: that the game sends its own result report, which a leaver's loss needs.
- Not run in the game yet: the league rebuilds, the national team jerseys, NHL alternates, centre ice for all leagues, kept lines,
  and a first save with no game save. If the game does not start, switch the packs off and press Patch again.
- With every pack on, Patch needs about 6 GB of free disk space.
- Boost performance does not work with a shadPS4 that keeps its saves in a `user` folder next to the exe. The button itself is new
  and has had little testing: if the game does not start, press Disable.
- A team with only home and away jerseys has no room for an alternate.
- The ALTERNATE label shows with the default roster; other rosters show the jersey's old name.
- This exe is not signed, so Windows may warn about it.

## 0.20.0 (2026-10-30)

A hotfix for players whose NHL 19 update sits in a folder of its own.

### Fixed

- **NHL 19 with the update in its own folder.** shadPS4 can install update 1.60 beside the game, as `CUSA11126-patch`
  (or `CUSA11126-UPDATE`) next to the base game `CUSA11126`. Overtime read only one of the two folders and stopped with
  errors like `nhl/data/kettle/loc/eng_us-meta.xml not in ...\CUSA11126-patch`. Now it reads the two together, as the
  emulator does, whichever of them is picked:
  - Setup lists the game once, as the base folder.
  - The game patch goes to `CUSA11126-mods`, the folder shadPS4 reads for that game. If 0.10.0 left a
    `CUSA11126-patch-mods` folder, delete it.
  - The Quick check and Verify every file cover both folders.
  - If you merged the update into the base folder by hand to get around this, that keeps working.
- **Calendar tab:** "My season" no longer says it comes after beta2. It is still to come.
- **Setup tab:** the Online card (server address, firewall) shows only on the Multiplayer tab now, not on both.

## 0.10.0 (2026-10-29)

The first public release. It includes everything from the closed betas (0.1.0-beta1 to beta4).

### What is new

- **Multiplayer tab** (closed beta): join or host a lobby on the Overtime server, the host picks the match rules and
  both games bake them in, the game starts with one press, and finished games land in your match history. Elo
  rating with nine ranks, a leaderboard in the app and on the public web board, lobby chat and an in-game overlay.
  - The app presses READY on Game Setup once the server sees your game there, instead of on a timer. If no search
    starts, the card tells you to press it.
  - The match rules use the game's own words (Competitive, Full Sim, Continuous OT, ...).
  - The History card says what the Overtime server keeps about you. "Show me on the web board" hides your name
    there.
  - The game gets the online roster itself: when you press PLAY in Online Versus, it downloads the current one if
    yours is older.
- **Update warns when NHL 19 needs the patch**: when the game is not patched, the patch has a problem, or an older
  Overtime patched it. "Go to Game patch" takes you there.
- **Seattle in Be a Pro.** Choose Team lists the Seattle Kraken and a career on Seattle plays, saves and loads. It
  needs the game patch with the league layer; with the league layer off, Be a Pro keeps the game's 31 teams.
- **Real 2026-27 calendars for the AHL and Liiga**, next to the NHL's:
  - AHL: all 32 clubs, 72 games each, each real club on its NHL parent's farm-team place (Coachella Valley on
    Seattle's). Official statistics provided by American Hockey League.
  - Liiga: the game's 15 clubs, 56 games each. Jokerit and K-Espoo have no place in NHL 19, so their games are left
    out.
  - The Calendar tab shows them: pick an AHL or Liiga club for its games, or "All AHL games" / "All Liiga games".
  - Every other league keeps the game's own calendar: no official schedule feed was found for the ECHL, OHL, WHL,
    QMJHL, SHL, HockeyAllsvenskan, DEL, Czech Extraliga, Swiss National League, ICE Hockey League, Champions League
    or the Spengler Cup.
  - **The calendars travel with the roster.** A new Franchise or Season takes its league calendars from the roster
    you have loaded in the game. The new default and online rosters carry them; an older saved or downloaded roster
    keeps the game's AHL and Liiga calendars until you run Update over it (Update writes them) or load the new online
    roster.
  - 32 Team Expansion Draft Franchise: Seattle and Utah each play their own real schedule in their own division, 84
    games each.
- **Photos and logos are a download now.** The Game patch tab has one "Photos, logos pack" card (about 155 MB):
  Download gets the four packs and switches them on, Remove deletes them. A fresh install starts with them off and
  Patch never downloads by itself. If you had the packs already, they stay on. Without the pack, Utah plays in the
  Coyotes' look and Seattle shows a stand-in crest (EA SPORTS) and kit; games play normally.
- **Sign free agents** from the Front office (Free agents group, Sign window, one Undo).
- **Photos switch**: put back the game's own player photos without undoing the rest of the patch.
- **Real equipment** from the NHL 27 pack (sock tuck, pants, tape colours, goalie neck guard).
- **Export to a folder** picks the game slot the folder is made for.
- The Lines tab shows each player's shooting or catching hand. Game patch sits before Update. Easier-to-read
  headings.
- Fixed: Patch brings the hub's Puck Peak news tile back where a beta patch had left it empty (press Patch once
  with 0.10.0; the Update tab asks for it).
- Fixed: Update no longer crashes on a roster save without the game's career tables.
- **Fewer refusals when you edit a roster.** The app now allows these edits: two teammates with the same number, more than three
  letters, an empty or doubled place in the lines. Save lists these as warnings and saves anyway. It still stops what
  breaks the game: a roster place for a missing player or team, one player on two teams, a skater in goal or a goalie
  in a skater's place, more rows than the game holds, or more than 40 players on a team.
  Roster keys out of order are put right on Save.

### Known limits

- **Be a Pro, Seattle and Utah dates.** Be a Pro keeps Seattle in the Central and Utah in the Pacific. Each team's
  divisional games match that, but Seattle plays Utah's real 2026-27 dates and Utah plays Seattle's. A 32 Team
  Expansion Draft Franchise is right.
- **Classic Franchise and NHL Season have 31 clubs.** The team lists show 32, but the game builds the league with
  Seattle in Utah's place: Utah is not in the league and Seattle plays Utah's real 82-game calendar. For both teams,
  start a Franchise with "32 Team Expansion Draft". This has been so since Overtime added Seattle; it is not new in
  0.10.0.
- Season mode lists Seattle (0 OVR) among the teams of other leagues too, for example the Liiga. It is not part of
  those leagues: the season plays with the league's own clubs.
- Multiplayer is a closed beta: the lobby trusts the name you give it, and a game between two separate PCs has not been
  played through yet.
- Lines you set by hand are not kept in My edits while Real lines and captains is on (as in beta4).
- The looser roster edits were checked in game on every NHL team at once (shared numbers, five letters, an empty and a
  doubled line place, cloned skaters): the roster loads, the hub runs and Play Now reaches team select. A full match
  with all of them together was not played before release.
