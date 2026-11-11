# Changelog

All notable changes to HeightShift (formerly HeightShiftOSC) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.29] - 2026-11-11

### Added
- Size parameters: a card below Timed transition where avatar parameters grow or shrink you while
  they're on — a contact, a toggle, a radial. Each is a card of its own: Grow / Shrink, a speed in
  cm/s or %/s, its own ‖ / ▶; one switch pauses them all. A Bool works at the card's full speed, a
  Float (0–1) at that share of it, an Int while it isn't 0. Several at once add up. A held hotkey or
  menu button goes first; a running timed transition stops when a card starts. Only the parameters
  on cards are decoded (it stays light in the background).
- The avatar's parameters beside the window (OscGoesPurrr's Avatar Remote list): + Parameter, or a
  card's name, opens it on the right and widens the window; filter, click one to use it, or drag it
  onto a card (or onto free room for a new card). Cards are sorted by dragging their ⠿.
- 🎲 Random height cards: a height between two (even on the height scale), on 🎲 or when a parameter
  turns on; then select it, go instant or go timed.
- Nine saved heights (were six), on numpad 1–9 — a press does what a click on it does. Each key can
  be changed in Settings → Grow & shrink while held. Quick taps between two polls count too.
- VR: a gesture puts you back at the avatar's own height — both fists (grip + trigger) and a jump by
  default; the gesture on each hand and "jump" or "hold 1.5 s" are set in Settings. Read from
  VRChat's own gesture parameters, so any controller works and nothing is added to the avatar.
- The VRChat menu (VRCFury prefab and one-click installer): Own height and Random height buttons, and
  a Pause cards toggle (`HeightShift/Pause`: the size parameter cards wait while it is on). Still
  zero synced bits.
- Contact examples in the VRCFury package: `HeightShift Contact Grow / Shrink / Random.prefab` — a
  contact receiver (local only, others' Hand / Finger / Foot) linked to the head with an Armature Link,
  its parameter declared unsynced, and a VRCFury Gizmo saying what to change. A first start comes with
  the Grow and Shrink cards for them, and a new 🎲 card listens to the Random one.
- Linux: `HeightShift-Linux-x86_64.AppImage` with every release. It updates itself like the Windows exe
  (the new AppImage replaces the old one and starts once the old one has closed). The hold-to-grow
  hotkeys are Windows-only; the VRChat menu's Grow / Shrink work everywhere.
- Back to the avatar's own height: an "↺ Own height · 1.43 m" button top right of NOW, and a reset key (numpad
  `*` by default, your own in Settings → Grow & shrink while held). The own height is current ÷ VRChat's
  `ScaleFactor`, which VRChat sends for every avatar (and is asked for after connecting and after an
  avatar switch, so the button shows it before it is pressed).
- Releases are built on GitHub: tests on Windows and Linux, then the exe and the AppImage, then the
  release — published only if all of it passed (`release.bat`, `.github/workflows/release.yml`).

### Changed
- Much lighter in the background: idle with face tracking running it used ~10–13 % of a CPU core, now
  ~3.5 %. VRChat streams every avatar parameter to it (~2,900 packets a second here); only the four it
  reads are decoded, by a plain receive loop. The hotkeys are polled at 10 Hz while nothing is pressed
  (the send rate while something is), the front window is only asked when a key is down, and what a
  transition or VRChat's echo changes is redrawn at most 10 times a second while another window has
  the focus, not at all while minimized (OscGoesPurrr's rules).
- A saved height's action (select / go instant / go timed) is chosen with a small ▾ joined to its
  right edge, shown while Settings are open — instead of a grid of buttons in Settings. Right-click
  still works.

## [2.0.26] - 2026-11-11

### Added
- What's new (as in OscGoesPurrr): after an update the app shows once what changed — one page per
  release, Back / Next when several were skipped, "Take me there" to the place a change lives, which
  lights up for a moment. A first install stays quiet. Settings → Updates → What's new shows it again.
- Six saved heights (were four), three across in a wider Height panel.
- What a click does, per saved height: *Select* (load it as the target, as before), *Go instant*
  (pink: go there at once) or *Go timed* (yellow: start the timed transition there). Set it by
  right-clicking the saved height, or in Settings → Height. A pink 1 cm is one click from 1 cm.
- The same choice for the height scale, as a button on top of the picture: *Select height* (the
  default), *Go instant* or *Go timed*; pressed, the other two unfold inside the card.

### Fixed
- Go timed from 1 cm: VRChat's 32-bit 1 cm (0.99999998 cm) was refused as "below the 1 cm minimum".
  A height within float rounding of a limit now is the limit, everywhere a height is checked.
- An empty (or locked) saved height takes a right-click, so its action can be set before a height is
  saved into it.
- Heights read right at the unit edges: 999.96 cm shows "10 m" (was "1,000 cm"), metres show to the
  millimetre (12.345 m, was 12.35 m, 5 mm off when typed back), and the line under the big number
  always shows the other unit. tests/test_numbers.py runs every action from VRChat's float values.
- The update window grows for its "Downloading…" line instead of squeezing the text above it.
- A nudge past a limit stops at it instead of doing nothing: −100 at 85 cm goes to 1 cm, as in 1.x.
- −1 at 2 cm reaches 1 cm: VRChat's 32-bit 2 cm is 1.99999995 cm, and 1 cm minus a hair was refused.

### Changed
- A first start opens a 740 × 810 window, so the wider Height panel and the picture fit side by side.
  The VRChat menu still has saved heights 1–4.

## [2.0.23] - 2026-11-11

### Fixed
- The number fields (the target, the transition's time, the scale range, the hold speed, the fixed
  height) were empty and could not be typed in. 2.0.20 was built with Qt 6.12, which shrinks the text
  part of a styled number field without step arrows to 1 px. The fields now keep hidden arrows, the
  build is pinned to the tested Qt (PySide6 6.11.1), and a test checks every field under the real
  stylesheet.

## [2.0] - 2026-11-11

A reworked window around one idea: pick a target, then go there instantly or over time.

### Added
- The figure: your height and the target as two copies of the same figure (OscGoesPurrr's Suits cat
  girl), one in front of the other — the target a soft shadow behind, your height bright lines in
  front — standing on a logarithmic height scale with their eyes at their height (VRChat's height is eye
  height): the height line runs up to each head and on past it, and a faint dotted line crosses the
  face. The ratio is written out.
  They ease smoothly (and quickly: settled in about 0.2 s) on every click, transition step and held
  key; the pointer, the ring, their height lines and the height number are at the new height at once,
  and she grows into it. Everything on the scale can be grabbed from well off it (VR-sized: the
  pointer 16 px above or below, a head line 10 px, the scale 18 px to its left).
- The height scale picks the target: click or drag anywhere along it, drag its pointer, or pull either
  head up or down (a dashed line with the height follows the mouse first). Picking never sends — Go
  instant or Go timed does; the ring on it only shows where you are. Its ends are the range (MIN / MAX,
  LIMIT at the cap) — click either number to type a new one right there; the four saved heights are
  numbered marks on it, and a dragged target snaps onto them.
- The Height panel beside the figure: your height and Nudge now (±1 / ±10 / ±100 cm); the target, typed
  as a height (`50 m`, `1,7 m`, `1.2 km`); Load as target (the four saved heights) and Save current height
  to; and **Go instant** or **Go timed**. Below, the Timed transition card keeps only the timing:
  duration, curve, graph and status.
- Hold-to-grow hotkeys: hold a key to grow or shrink smoothly, in cm per second (5 cm/s to start) or %
  per second. Your own keys (numpad + / − by default, modifiers allowed), on from the first start (they
  can be switched off), and only while VRChat is in front
  unless you say otherwise. Read by polling the key state, never a keyboard hook. A held key stops a
  running transition, stops at the height limit, and waits for VRChat's real height like everything else.
- Self-update (VRCParameterRelay's updater): at every start the app asks GitHub for the newest release;
  a newer one lights an orange chip in the header and opens a window — Install now downloads it,
  checks its size and SHA-256, swaps the exe and restarts. Later is the default (Enter never installs),
  "Don't remind me" quiets that version, Settings → Updates checks by hand. Run from source, it offers
  the release page. Releases carry `HeightShift.exe` (build.bat writes it) and the menu package.
- Settings end with a mini guide to the VRChat menu: each of its icons and what it does, in the menu's
  order, with links to the VRCFury prefab (the newest release's) and the setup guide.
- The status bar's names are links: HeightShift to its GitHub page, Blise518B to his GitHub profile.
- A website, https://blise518b.github.io/HeightShiftOSC/: the download, what it does and the VRChat menu,
  on one short page.
- VRChat menu: a VRCFury prefab (docs/VRCHAT_MENU.md) with Grow / Shrink while held, Play / Pause,
  Stop, and Load / Save for the four saved heights. Unsynced parameters, no animator; the app says in
  Settings whether the current avatar has it. Grow / Shrink use the hold speed shared with the hotkeys.

### Changed
- A first start comes with a 20-second timed transition (was 10 minutes) and one saved height, slot 1
  at 140 cm; the hotkeys are on, at 5 cm per second.
- A timed transition and a held key (hotkey or VRChat menu) send your height 30 times a second instead
  of 10, so growing looks smoother; Settings → Height → Updates per second offers 10 / 30 / 60.
- A scale range that can't be (a top above the limit, a bottom above the top) is refused with a reason
  instead of being quietly clamped.
- A saved height no longer sets your height when clicked in the window: it becomes the target (Go
  instant / Go timed then takes you there). The VRChat menu's Load still sets it at once.
- A first start opens a compact window (608 × 778) with the Height panel beside the figure and Settings
  folded. In a narrower window the figure shrinks first (to about 60 %); only when even that doesn't
  fit does the panel go under it, and the window never gets narrower than its controls.
- Nudge now is three columns, +1 over −1, +10 over −10, +100 over −100: grow in a red frame, shrink
  in a blue one.
- Go instant is filled pink, Go timed yellow — and the Timed transition card it runs wears the same
  yellow (frame, bar, the chosen unit and curve, the graph).
- "Unlock upper limit" goes up to 1000 m (was 100 km), and switching it on stretches the height
  scale's top from 100 m to 1000 m (off: back to 100 m; a range narrowed by hand stays).

## [1.1] - 2026-11-10

### Added
- Slow transition: target height + duration (s / min / h), Play / Pause / Resume / Stop, a graph
  with a playhead, "even speed" and "even growth" curves.
- "Unlock upper limit": heights up to 100 km (off = nothing above 100 m is ever sent).
- 518 design system: Neon / Midnight (live, no restart), Aldrich headline with `v1.1 · b<build>`,
  status bar with the identity tag, settings side panel with a hint under every setting, text size
  control (Ctrl + wheel, Ctrl + / −, Ctrl + 0), the wheel never changes a setting, the window reopens
  where it was left.
- Single instance: a second start brings the running window to the front.

### Fixed — values written to VRChat
- On startup the app wrote the height it had just read back to VRChat, rounded to whole cm and
  clamped to 1 cm–100 m (e.g. 1.29905 m became 1.30 m on every launch). It now only reads.
- ± steps, profile saves and the avatar-switch burst used a 170 cm default when the height wasn't known
  yet, so "+1 cm" could jump a small avatar to 171 cm. They now wait for the real height.
- Pressing a height button while VRChat was not connected marked the (unsent) value as the current
  height and skipped the real read when VRChat appeared.
- After an avatar change the height to keep could already be the new avatar's default (packets are
  handled on separate threads); it is now picked by receive time. A height change during the burst
  was overwritten by the burst; a manual change now cancels it.
- Rapid ± clicks could be pulled back by VRChat's echo of an earlier send.
- Clicking the slider track or using the arrow keys changed the display but sent nothing.
- After a VRChat restart the old height stayed "known" and steps started from it.
- Values read from VRChat above 100 m were clamped to 100 m and that clamped value was later resent.
- Height queries retried and applied via `QTimer.singleShot` on a plain Python thread, which never
  fires — retries never ran.
- The cached eye height survived an avatar change and could be handed out as the new avatar's.
- "Load fixed height" gave up 10 s after launch if VRChat started later.
- A config saved with a BOM (Notepad, PowerShell), broken JSON or wrong types silently reset everything
  to defaults and the next save overwrote the profiles; broken files are now kept aside and every value
  is type-checked.
- With "Hide console" on, run.bat's final `pause` waited in an invisible window after every run.

### Fixed — reading VRChat's height (OSC layer, checked against OscGoesPurrr)
- A height read over HTTP was stamped with the time its answer ARRIVED. A slow read that was on its
  way while you set a height could then replace that height (and the next ±1 cm started from the old
  value), or replace a newer OSC packet. Reads are now stamped with the time they were asked for.
- A read asked for before an avatar change could be taken as the new avatar's height.
- Every OSC packet was handled on its own new thread (VRChat streams every avatar parameter, hundreds
  a second with face tracking), in no guaranteed order. Now one thread, in arrival order, like
  OscGoesPurrr.
- After a VRChat restart the previous session's cached eye height could be handed out as the current
  one. The cache is gone: every read asks VRChat.
- A record left on the network by a crashed VRChat (OscGoesPurrr's log shows one next to the live
  game for 1.7 hours) took over: its dead port became the one the health check polls, so the working
  connection dropped every ~15 s. A record that doesn't answer is now ignored, and only a VRChat that
  answers can replace one that no longer does.
- The removal of an old VRChat record, or a health-check miss on its old port, could disconnect the
  current one.
- Two retry loops read the height at once (one in the OSC layer, one in the controller), and quick
  avatar swaps stacked more of them. There is one now, owned by the controller.
- Any mDNS service with "VRChat" anywhere in its name was taken for the game; now only VRChat's own
  `VRChat-Client-…` record is.
- osc_diagnostics.log was always written under `AppData\Roaming` (wrong on macOS / Linux); it now sits
  next to the config file.
- The "connected but nothing arrives" self-heal ran once per outage; it now repeats every 5 minutes,
  like OscGoesPurrr.

### Changed
- Code split by job: `main.py` (entry), `controller.py`, `osc/` (manager, OSCQuery documents, log,
  518 router), `ui/` (window, theme, widgets, graph). See the README's Development section.

### Removed
- The "VRChat IP" field: discovery always targets 127.0.0.1 and overwrote it, and the saved value was
  never applied — it had no effect.

## [Unreleased-legacy]

### Added
- GPL v3 License - All code contributions must be open-sourced
- Startup Mode Selection (Query vs Load Fixed Height)
- Preserve Height on Avatar Switch feature
- Rapid Burst System for avatar change detection

### Changed
- Updated documentation structure and added comprehensive guides
- Documentation now includes all features: Startup Mode, Preserve Height on Avatar, Rapid Burst system, and mDNS Discovery

## [1.0.0] - 2025-01-XX

### Added
- Initial release of HeightShiftOSC
- Real-time height adjustment (1 cm - 100 m range)
- Quick-adjust buttons: ±1 cm, ±10 cm, ±100 cm
- Profile system with 4 saved height presets
- VRChat OSC connection via IP/Port configuration
- Window geometry persistence
- Dark-themed modern UI using CustomTkinter

### Features
- **mDNS Discovery**: Automatically discovers VRChat's OSC port via Zeroconf
- **Avatar Change Detection**: Preserves height when switching avatars in VRChat
- **Rapid Burst System**: Sends 20 OSC messages over 2 seconds after avatar swap to ensure height locks
- **Dynamic Port Assignment**: Uses random high ports for OSC receiver to avoid conflicts

### Technical Details
- Python 3.7+ with CustomTkinter for GUI
- python-osc library for OSC communication
- Zeroconf for mDNS service discovery
- Requests for HTTP queries to VRChat's OSCQuery endpoint

## Version History Notes

| Date | Version | Status |
|------|---------|--------|
| 2025-XX-XX | 1.0.0 | Initial Release |

---

**License**: This project is licensed under the GNU GPL v3 - see the LICENSE file for details.