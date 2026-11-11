# VRChat expression menu (HeightShift/*)

Change your height from VRChat's Action Menu without leaving VR. The menu
only talks to the HeightShift app over OSC: the app must be running and
connected, and it does exactly what its own buttons do.

```
HeightShift ▸
  Grow · Shrink · Play / Pause · Stop · Own height · Random height · Pause cards
  Saved heights ▸
    Load 1 · Load 2 · Load 3 · Load 4
    Save current ▸
      Save 1 · Save 2 · Save 3 · Save 4
```

* **Grow / Shrink** — grows or shrinks smoothly for as long as you hold it,
  at the app's hold speed (the one the hold-to-grow hotkeys use; the
  hotkeys themselves can stay off).
* **Play / Pause** — Go timed: starts the timed transition to the target and duration
  set in the app; pressed again it pauses, then resumes.
* **Stop** — stops the timed transition where it is.
* **Own height** — back to the avatar's own height at once (the one it has
  before any scaling).
* **Random height** — the first 🎲 Random card in the app's *Size
  parameters* rolls (select it / go instant / go timed, as the card says).
* **Pause cards** — a toggle: while it is on, the app's size parameter cards
  wait (contacts don't change your size). A prefab can drive
  `HeightShift/Pause` itself too.
* **Load 1–4** — sets your height to saved height 1–4 (an empty slot does
  nothing; the status bar says so).
* **Save 1–4** — stores your current height as saved height 1–4. It is a
  submenu of its own so a stray tap while loading can't overwrite one.

Every control but Pause cards is a **Button** (momentary), and every parameter is
**unsynced and unsaved**: they cost 0 sync bits and read 0 after every
avatar load. Nothing is animated, so the avatar needs no FX layer for it.

| Parameter            | Type | Control           | Value                                   |
|----------------------|------|-------------------|-----------------------------------------|
| `HeightShift/Grow`   | Bool | Button            | true while held                          |
| `HeightShift/Shrink` | Bool | Button            | true while held                          |
| `HeightShift/Play`   | Bool | Button            | true while held; one press = one action |
| `HeightShift/Stop`   | Bool | Button            | true while held; one press = one action |
| `HeightShift/Load`   | Int  | Buttons Load 1–4  | N while held, 0 when let go             |
| `HeightShift/Save`   | Int  | Buttons Save 1–4  | N while held, 0 when let go             |
| `HeightShift/Reset`  | Bool | Button            | true while held; one press = one action |
| `HeightShift/Roll`   | Bool | Button            | true while held; one press = one action |
| `HeightShift/Pause`  | Bool | Toggle            | true while the cards should wait        |

For about a second after an avatar load the app ignores the menu: VRChat
replays every parameter's default then, which is not a press.

The app's Settings end with the same overview, with the menu's icons, and
link here and to the prefab.

## Option A — VRCFury prefab (easiest)

Needs [VRCFury](https://vrcfury.com) in your avatar project (Creator
Companion → Manage Project → add VRCFury). The package is attached to every
release: [HeightShift-VRCFury.unitypackage](https://github.com/Blise518B/HeightShiftOSC/releases/latest/download/HeightShift-VRCFury.unitypackage)
(the newest), and it is in this repository too.

1. Import [`HeightShift-VRCFury.unitypackage`](unity/HeightShift-VRCFury.unitypackage):
   drag it into Unity's Project window (or *Assets → Import Package →
   Custom Package*).
2. Drag `Assets/HeightShift/HeightShift.prefab` onto your avatar in the
   Hierarchy — anywhere inside it. (The menus, parameters and icons it uses
   are in `Assets/HeightShift/Menu`; leave them there.)
3. Upload the avatar.

When you upload (or press Play), VRCFury adds the parameters — under their
own names, so the app can reach them — and the *HeightShift* submenu, every
control with its icon. Your avatar's own menu and parameter files are never
edited, so taking it out again is deleting the object.

The submenu lands in your root menu. To put it inside another submenu
instead, select the prefab and type that submenu's name into the *Prefix*
field of its Full Controller.

A newer version of the package imports over the old one and updates it in
place; the prefab on your avatar picks the change up.

### Contact examples: touch → size

The package also brings `Assets/HeightShift/Contacts/`: three small prefabs
that show how a touch drives the app's *Size parameters* cards. Each is a
**Contact Receiver** (local only, others' contacts) that sets one parameter,
a VRCFury **Armature Link** that puts it on a body part, a VRCFury **Full
Controller** that declares the parameter (unsynced: 0 sync bits), and a
VRCFury **Gizmo** — its text in the Scene view says what to change.

| Prefab                       | Sets                         | Set off by        | The app's card            |
|------------------------------|------------------------------|-------------------|---------------------------|
| `HeightShift Contact Grow`   | `HeightShift/Contact/Grow`   | Hand, Finger      | Grow (there on a first start) |
| `HeightShift Contact Shrink` | `HeightShift/Contact/Shrink` | Foot              | Shrink (there on a first start) |
| `HeightShift Contact Random` | `HeightShift/Contact/Random` | Finger            | a new 🎲 card listens to it |

1. Drag one onto your avatar (anywhere inside it).
2. In its *Armature Link*, pick the body part (the head by default: a
   headpat grows you, a foot on your head shrinks you).
3. In its *Contact Receiver*, pick the *Collision Tags* that set it off,
   and move / size the sphere. *Allow Self* lets your own hands do it.
4. Upload. In the app the matching card's line shows the value as you're
   touched.

Copy one under another name for more (another body part, another tag);
put the new parameter name on a card of its own — the app lists every
parameter of the avatar you're wearing beside the window.

## Option B — one-click installer (no VRCFury needed)

1. Copy [`docs/unity/HeightShift_MenuInstaller.cs`](unity/HeightShift_MenuInstaller.cs)
   into your avatar project, anywhere under `Assets/` (e.g.
   `Assets/HeightShiftMenu/Editor/`).
2. Select your avatar in the Hierarchy.
3. Run **Tools → HeightShift → Install VRChat Menu**, then upload.

It adds the nine parameters to the avatar's Expression Parameters, builds the
*HeightShift* submenu (without icons) in `Assets/HeightShiftMenu` and links it
into your root menu. Re-running it is safe (it updates in place), and it
never edits SDK-shipped default assets (it copies them first).

**Use one or the other, not both.** If you used the installer on an avatar
and switch to the prefab, remove the *HeightShift* submenu the installer
added to your root menu; otherwise VRCFury merges the two and every control
shows up twice. The parameters it added can stay.

## Troubleshooting

* **The menu does nothing** — VRChat caches an OSC config per avatar that
  lists its parameters, and an avatar you have worn before keeps its old
  list after you add the menu. Close VRChat, delete
  `%USERPROFILE%\AppData\LocalLow\VRChat\VRChat\OSC\` once (or just that
  avatar's file in its `usr_…\Avatars\` folder — it is regenerated), and
  load the avatar again.
* **Still nothing** — check that OSC is on in VRChat (Action Menu →
  Options → OSC → Enabled) and that the app is connected. The app's *VRChat
  menu* box says whether the avatar you're wearing has the menu.

## For maintainers

The package is built, never edited by hand:
`venv\Scripts\python.exe tools\build_vrcf_prefab.py "<avatar project>"`
runs `tools/unity/HeightShiftVrcfPrefabBuilder.cs` headless in a Unity
project with the VRChat SDK and VRCFury (closed in Unity, without an
`Assets/HeightShift` folder), exports the package, imports it back, runs
VRChat's upload preprocess on test avatars and only then replaces the
committed package. The menu and parameters come from
`docs/unity/HeightShift_MenuInstaller.cs`, the icons from
`docs/unity/icons/` (`tools/make_menu_icons.py`); the contact examples from
the builder's `Contacts` table (their names are `constants.CONTACT_*`, the
app's default cards). Two things must stay:
`HeightShift/*` in the Full Controller's global parameters (VRCFury renames
every other parameter, and OSC reaches one by name only) and the pinned
GUIDs (with fresh ones, a newer package imports as duplicates instead of
updating). `tests/test_vrcf_prefab.py` checks the committed package against
`constants.MENU_PARAMS`.
