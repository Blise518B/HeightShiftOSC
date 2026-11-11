"""The VRCFury menu prefab must keep matching the app.

`docs/unity/HeightShift-VRCFury.unitypackage` is what an avatar owner drags
in to get the HeightShift menu. It is built by `tools/build_vrcf_prefab.py`,
which needs Unity and also tests the package on avatars there -- so these
tests only read the committed package: it adds exactly the parameters the app
listens to (constants.MENU_PARAMS), with the types the app reads, unsynced
and unsaved, under names VRCFury leaves alone; the menu is the one the app
expects, every button sending what the app reads; and its GUIDs are the
pinned ones, without which importing a newer package next to an older one
duplicates every asset instead of updating it.

A failure here after changing a MENU_* constant means: change
`docs/unity/HeightShift_MenuInstaller.cs` to match and rebuild the package.
"""

import hashlib
import re
import tarfile
import unittest
from pathlib import Path

from tests import _pathfix  # noqa: F401  (sys.path bootstrap)

import constants

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "docs" / "unity" / "HeightShift-VRCFury.unitypackage"
INSTALLER = REPO / "docs" / "unity" / "HeightShift_MenuInstaller.cs"
ICONS = REPO / "docs" / "unity" / "icons"
ROOT = "Assets/HeightShift"   # the package's own folder, nothing outside it
DIR = f"{ROOT}/Menu"          # the parts the prefab uses
PREFAB = f"{ROOT}/HeightShift.prefab"
PARAMETERS = f"{DIR}/HeightShift_VRCF_Parameters.asset"
WRAPPER = f"{DIR}/HeightShift_VRCF_Menu.asset"   # the one-control menu VRCFury merges
MENUS = ("Controls", "SavedHeights", "SaveCurrent")
CONTACTS = f"{ROOT}/Contacts"   # the contact examples
CONTACT_NAMES = {"Grow": constants.CONTACT_GROW, "Shrink": constants.CONTACT_SHRINK,
                 "Random": constants.CONTACT_RANDOM}

# VRCExpressionParameters.ValueType and VRCExpressionsMenu.Control.ControlType.
VALUE_TYPES = {"int": 0, "float": 1, "bool": 2}
BUTTON, TOGGLE, SUBMENU = 101, 102, 103


def button(name, param, value, icon):
    return (name, BUTTON, param, value, icon, None)


def toggle(name, param, value, icon):
    return (name, TOGGLE, param, value, icon, None)


def folder(name, icon, controls):
    return (name, SUBMENU, "", None, icon, controls)


# What the app expects, written out from the spec (not from the C#): the
# app acts on Load N / Save N by the Int value N.
EXPECTED_MENU = [
    folder("HeightShift", "menu", [
        button("Grow", constants.MENU_GROW, 1, "grow"),
        button("Shrink", constants.MENU_SHRINK, 1, "shrink"),
        button("Play / Pause", constants.MENU_PLAY, 1, "play_pause"),
        button("Stop", constants.MENU_STOP, 1, "stop"),
        button("Own height", constants.MENU_RESET, 1, "own_height"),
        button("Random height", constants.MENU_ROLL, 1, "roll"),
        toggle("Pause cards", constants.MENU_PAUSE, 1, "pause_cards"),
        folder("Saved heights", "saved", [
            *(button(f"Load {n}", constants.MENU_LOAD, n, f"load{n}") for n in range(1, 5)),
            folder("Save current", "save", [
                button(f"Save {n}", constants.MENU_SAVE, n, f"save{n}") for n in range(1, 5)
            ]),
        ]),
    ]),
]


def read_package():
    """{asset path: (guid, asset bytes or None for a folder, meta text)}"""
    entries = {}
    with tarfile.open(PACKAGE, "r:gz") as tar:
        members = {m.name: m for m in tar.getmembers()}
        for name, member in members.items():
            if not name.endswith("/pathname"):
                continue
            guid = name.split("/")[0]
            path = tar.extractfile(member).read().decode("utf-8").splitlines()[0]
            asset = members.get(f"{guid}/asset")
            meta = members.get(f"{guid}/asset.meta")
            entries[path] = (guid,
                             tar.extractfile(asset).read() if asset else None,
                             tar.extractfile(meta).read().decode("utf-8") if meta else "")
    return entries


def pinned(path):
    return hashlib.md5(f"HeightShift:{path}".encode()).hexdigest()


def parse_controls(text):
    """The controls of a serialized VRCExpressionsMenu, in order."""
    section = text.split("\n  controls:\n", 1)[1]
    controls = []
    for block in re.split(r"\n  - (?=name: )", "\n" + section)[1:]:
        icon = re.search(r"\n    icon: \{fileID: \d+(?:, guid: (\w+))?", block)
        sub = re.search(r"\n    subMenu: \{fileID: \d+(?:, guid: (\w+))?", block)
        controls.append({
            "name": re.match(r"name: (.*)", block).group(1).strip().strip("'\""),
            "icon": icon.group(1) if icon else None,
            "type": int(re.search(r"\n    type: (\d+)", block).group(1)),
            "param": re.search(r"\n    parameter:\n      name: ?(.*)", block).group(1).strip(),
            "value": float(re.search(r"\n    value: (\S+)", block).group(1)),
            "subMenu": sub.group(1) if sub else None,
        })
    return controls


class TestVrcfPrefab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package = read_package()
        cls.by_guid = {guid: path for path, (guid, _, _) in cls.package.items()}

    def text(self, path):
        return self.package[path][1].decode("utf-8")

    def test_holds_the_prefab_and_its_assets(self):
        icons = sorted(f.stem for f in ICONS.glob("*.png"))
        self.assertTrue(icons, "no icons in docs/unity/icons -- run tools/make_menu_icons.py")
        self.assertEqual(set(self.package), {
            ROOT,
            DIR,
            f"{DIR}/Icons",
            *(f"{DIR}/Icons/{name}.png" for name in icons),
            PREFAB,
            PARAMETERS,
            WRAPPER,
            *(f"{DIR}/HeightShift_VRCF_{key}.asset" for key in MENUS),
            CONTACTS,
            f"{CONTACTS}/Parts",
            *(f"{CONTACTS}/HeightShift Contact {name}.prefab" for name in CONTACT_NAMES),
            *(f"{CONTACTS}/Parts/HeightShift_Contact_{name}_Parameters.asset"
              for name in CONTACT_NAMES),
            *(f"{CONTACTS}/Parts/HeightShift_Contact_{name}.controller"
              for name in CONTACT_NAMES),
        })

    def test_contact_examples_set_the_cards_parameters(self):
        # each sets the parameter the app's default card (or a new 🎲 card)
        # listens to, unsynced and unsaved, and keeps its name (global)
        for name, param in CONTACT_NAMES.items():
            with self.subTest(name):
                prefab = self.text(f"{CONTACTS}/HeightShift Contact {name}.prefab")
                self.assertIn(f"parameter: {param}", prefab)
                self.assertIn("localOnly: 1", prefab)
                self.assertIn(f"- {constants.MENU_PREFIX}*", prefab)        # global
                for feature in ("ArmatureLink", "FullController", "Gizmo"):
                    self.assertIn(f"type: {{class: {feature}, ns: VF.Model.Feature", prefab)
                params = self.text(f"{CONTACTS}/Parts/HeightShift_Contact_{name}_Parameters.asset")
                self.assertRegex(params, rf"- name: {re.escape(param)}\n\s+valueType: 2\n"
                                         rf"\s+saved: 0\n\s+defaultValue: 0\n"
                                         rf"\s+networkSynced: 0")

    def test_the_icons_are_the_drawn_ones(self):
        for f in ICONS.glob("*.png"):
            _, data, meta = self.package[f"{DIR}/Icons/{f.name}"]
            self.assertEqual(data, f.read_bytes(), f.name)
            # Imported at VRChat's 256 px menu-icon limit.
            self.assertIn("maxTextureSize: 256", meta, f.name)

    def test_guids_are_pinned(self):
        for path, (guid, _, _) in self.package.items():
            self.assertEqual(guid, pinned(path), path)

    def test_parameters_are_the_apps_unsynced_and_unsaved(self):
        found = {m["name"]: m for m in re.finditer(
            r"- name: (?P<name>\S+)\n\s+valueType: (?P<type>\d)\n"
            r"\s+saved: (?P<saved>\d)\n\s+defaultValue: (?P<default>\S+)\n"
            r"\s+networkSynced: (?P<synced>\d)",
            self.text(PARAMETERS))}
        self.assertEqual(set(found), set(constants.MENU_PARAMS))
        for name, kind in constants.MENU_PARAMS.items():
            with self.subTest(name):
                self.assertTrue(name.startswith(constants.MENU_PREFIX))
                self.assertEqual(int(found[name]["type"]), VALUE_TYPES[kind])
                self.assertEqual(found[name]["saved"], "0")
                self.assertEqual(found[name]["synced"], "0")
                self.assertEqual(float(found[name]["default"]), 0.0)

    def test_vrcfury_keeps_the_names(self):
        # VRCFury renames every parameter its globalParams don't match, and
        # OSC reaches a parameter by its name only.
        prefab = self.text(PREFAB)
        block = re.search(r"globalParams:\n((?:\s+- .*\n)+)", prefab)
        patterns = [line.strip()[2:] for line in block.group(1).splitlines()]
        self.assertEqual(patterns, [constants.MENU_PREFIX + "*"])
        for name in constants.MENU_PARAMS:
            self.assertTrue(any(name == p or (p.endswith("*") and name.startswith(p[:-1]))
                                for p in patterns), name)

    def test_prefab_brings_the_menu_and_parameters(self):
        prefab = self.text(PREFAB)
        self.assertIn("type: {class: FullController, ns: VF.Model.Feature, asm: VRCFury}",
                      prefab)
        refs = re.findall(r"objRef: \{fileID: 11400000, guid: (\w+), type: 2\}", prefab)
        self.assertEqual(sorted(refs), sorted([pinned(WRAPPER), pinned(PARAMETERS)]))
        self.assertIn("controllers: []", prefab)   # no animator: OSC only

    def test_menu_is_the_apps(self):
        def walk(path, expected, where):
            got = parse_controls(self.text(path))
            self.assertEqual([c["name"] for c in got], [e[0] for e in expected], where)
            self.assertLessEqual(len(got), 8, where)   # VRChat's limit per menu
            for c, (name, kind, param, value, icon, children) in zip(got, expected):
                here = f"{where}/{name}"
                self.assertEqual(c["type"], kind, here)
                self.assertEqual(c["icon"], pinned(f"{DIR}/Icons/{icon}.png"), here)
                if children is None:
                    self.assertEqual(c["param"], param, here)
                    self.assertEqual(c["value"], value, here)
                    self.assertIsNone(c["subMenu"], here)
                else:
                    self.assertIn(c["subMenu"], self.by_guid, here)
                    walk(self.by_guid[c["subMenu"]], children, here)

        walk(WRAPPER, EXPECTED_MENU, "")

    def test_menu_uses_every_parameter(self):
        used = {c["param"] for key in MENUS
                for c in parse_controls(self.text(f"{DIR}/HeightShift_VRCF_{key}.asset"))}
        self.assertTrue(set(constants.MENU_PARAMS) <= used)

    def test_installer_names_the_apps_parameters(self):
        # The package is built from the installer's table; a renamed
        # parameter must change both.
        names = set(re.findall(r'const string \w+Param = "([^"]+)";',
                               INSTALLER.read_text(encoding="utf-8")))
        self.assertEqual(names, set(constants.MENU_PARAMS))


if __name__ == "__main__":
    unittest.main()
