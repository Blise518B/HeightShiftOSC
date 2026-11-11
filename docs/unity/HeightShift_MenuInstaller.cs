// HeightShift — one-click VRChat expression-menu installer.
//
// Drop this file anywhere inside Assets/ (e.g. Assets/HeightShiftMenu/Editor/),
// select your avatar in the Hierarchy, then run
//   Tools → HeightShift → Install VRChat Menu
//
// It adds the nine HeightShift/* parameters (Grow, Shrink, Play, Stop, Reset,
// Roll and Pause Bool, Load and Save Int — all unsynced and unsaved, i.e.
// ZERO sync bits) to the avatar's Expression Parameters, creates a
// "HeightShift" submenu asset (Grow, Shrink, Play / Pause, Stop, Own height
// and Random height buttons, a Pause cards toggle, and a Saved heights
// submenu with Load 1-4 and a Save current submenu with Save 1-4) and links
// it into the avatar's root expressions menu. (No icons here; the VRCFury
// prefab carries them.) Everything is done through the VRC SDK's own API —
// no hand-rolled asset GUIDs — and re-running is idempotent (updates in
// place, never duplicates).
//
// Works with or without VRCFury: it edits the avatar descriptor's own
// menu/parameter assets, which VRCFury preserves and merges on top of at
// build time. See docs/VRCHAT_MENU.md for what the parameters do.
//
// The VRCFury prefab (HeightShift-VRCFury.unitypackage) is built from the
// same parameter table and AddControls() by
// tools/unity/HeightShiftVrcfPrefabBuilder.cs, with the icons from
// docs/unity/icons/ — change the menu here and rebuild it with
// tools/build_vrcf_prefab.py.

#if UNITY_EDITOR
using System;
using System.Linq;
using UnityEditor;
using UnityEngine;
using VRC.SDK3.Avatars.Components;
using VRC.SDK3.Avatars.ScriptableObjects;

namespace HeightShift
{
    public static class HeightShiftMenuInstaller
    {
        // Not Assets/HeightShift: that is where the VRCFury package lands,
        // so importing it never touches what the installer made.
        private const string AssetDir = "Assets/HeightShiftMenu";
        private const string SubMenuPath = AssetDir + "/HeightShift_Menu.asset";

        // The OSC contract with the app (constants.py MENU_*): do not rename.
        private const string GrowParam = "HeightShift/Grow";
        private const string ShrinkParam = "HeightShift/Shrink";
        private const string PlayParam = "HeightShift/Play";
        private const string StopParam = "HeightShift/Stop";
        private const string LoadParam = "HeightShift/Load";
        private const string SaveParam = "HeightShift/Save";
        private const string ResetParam = "HeightShift/Reset";
        private const string RollParam = "HeightShift/Roll";
        private const string PauseParam = "HeightShift/Pause";
        internal const string SubMenuControlName = "HeightShift";

        // The app's four saved heights: Load N / Save N send N.
        private const int Slots = 4;

        // All unsynced and unsaved: they only talk to the app over OSC, so
        // they cost the avatar no synced memory and read 0 after every load.
        internal static readonly (string name,
            VRCExpressionParameters.ValueType type, float defaultValue)[]
            Parameters =
        {
            (GrowParam, VRCExpressionParameters.ValueType.Bool, 0f),
            (ShrinkParam, VRCExpressionParameters.ValueType.Bool, 0f),
            (PlayParam, VRCExpressionParameters.ValueType.Bool, 0f),
            (StopParam, VRCExpressionParameters.ValueType.Bool, 0f),
            (LoadParam, VRCExpressionParameters.ValueType.Int, 0f),
            (SaveParam, VRCExpressionParameters.ValueType.Int, 0f),
            (ResetParam, VRCExpressionParameters.ValueType.Bool, 0f),
            (RollParam, VRCExpressionParameters.ValueType.Bool, 0f),
            (PauseParam, VRCExpressionParameters.ValueType.Bool, 0f),
        };

        [MenuItem("Tools/HeightShift/Install VRChat Menu")]
        public static void Install()
        {
            var go = Selection.activeGameObject;
            var descriptor = go != null ? go.GetComponent<VRCAvatarDescriptor>() : null;
            if (descriptor == null)
            {
                EditorUtility.DisplayDialog(
                    "HeightShift",
                    "Select your avatar (the object with the VRC Avatar " +
                    "Descriptor) in the Hierarchy first, then run this again.",
                    "OK");
                return;
            }

            try
            {
                EnsureAssetDir();
                var parameters = EnsureParameters(descriptor);
                foreach (var (name, type, defaultValue) in Parameters)
                    AddOrUpdateParameter(parameters, name, type, defaultValue);
                EditorUtility.SetDirty(parameters);

                var subMenu = BuildSubMenu();
                var linked = LinkIntoRootMenu(descriptor, subMenu);

                AssetDatabase.SaveAssets();

                EditorUtility.DisplayDialog(
                    "HeightShift",
                    "Done!\n\n" +
                    "• HeightShift/Grow, Shrink, Play, Stop (Bool) and " +
                    "HeightShift/Load, Save (Int) added — all unsynced, so " +
                    "they cost 0 sync bits.\n" +
                    "• \"HeightShift\" submenu " +
                    (linked ? "linked into your expressions menu."
                            : "created, but your root menu already has 8 " +
                              "controls — add the submenu asset at\n  " +
                              SubMenuPath + "\nto any menu with a free slot.") +
                    "\n\nUpload the avatar. If the app doesn't react to the " +
                    "menu afterwards, delete VRChat's cached OSC config " +
                    "(see docs/VRCHAT_MENU.md).",
                    "OK");
            }
            catch (Exception e)
            {
                EditorUtility.DisplayDialog(
                    "HeightShift",
                    "Install failed: " + e.Message +
                    "\n\nNothing destructive was done. Full details are in " +
                    "the Console.",
                    "OK");
                Debug.LogException(e);
            }
        }

        private static void EnsureAssetDir()
        {
            if (!AssetDatabase.IsValidFolder(AssetDir))
                AssetDatabase.CreateFolder("Assets", "HeightShiftMenu");
        }

        // The avatar may have no custom expressions yet, or share default
        // SDK assets. In both cases give it its own parameters asset under
        // Assets/HeightShiftMenu so we never mutate an SDK-shipped default.
        private static VRCExpressionParameters EnsureParameters(
            VRCAvatarDescriptor descriptor)
        {
            var current = descriptor.expressionParameters;
            if (current != null && IsEditable(current))
            {
                Undo.RecordObject(current, "HeightShift parameters");
                return current;
            }
            var fresh = ScriptableObject.CreateInstance<VRCExpressionParameters>();
            fresh.parameters = current != null && current.parameters != null
                ? current.parameters.Select(Clone).ToArray()
                : new VRCExpressionParameters.Parameter[0];
            AssetDatabase.CreateAsset(fresh, AssetDir + "/HeightShift_Parameters.asset");
            Undo.RecordObject(descriptor, "HeightShift parameters");
            descriptor.customExpressions = true;
            descriptor.expressionParameters = fresh;
            EditorUtility.SetDirty(descriptor);
            return fresh;
        }

        private static bool IsEditable(UnityEngine.Object asset)
        {
            var path = AssetDatabase.GetAssetPath(asset);
            // Immutable = ships inside a package (the SDK defaults) — clone
            // instead of mutating.
            return !string.IsNullOrEmpty(path) && path.StartsWith("Assets/");
        }

        private static VRCExpressionParameters.Parameter Clone(
            VRCExpressionParameters.Parameter p)
        {
            return new VRCExpressionParameters.Parameter
            {
                name = p.name,
                valueType = p.valueType,
                saved = p.saved,
                defaultValue = p.defaultValue,
                networkSynced = p.networkSynced,
            };
        }

        internal static void AddOrUpdateParameter(
            VRCExpressionParameters parameters, string name,
            VRCExpressionParameters.ValueType type, float defaultValue)
        {
            var list = (parameters.parameters
                        ?? new VRCExpressionParameters.Parameter[0]).ToList();
            var existing = list.FirstOrDefault(p => p != null && p.name == name);
            if (existing == null)
            {
                existing = new VRCExpressionParameters.Parameter { name = name };
                list.Add(existing);
            }
            existing.valueType = type;
            existing.defaultValue = defaultValue;
            existing.networkSynced = false;     // see Parameters
            existing.saved = false;
            parameters.parameters = list.ToArray();
        }

        private static VRCExpressionsMenu BuildSubMenu()
        {
            var menu = AssetDatabase.LoadAssetAtPath<VRCExpressionsMenu>(SubMenuPath);
            if (menu == null)
            {
                menu = ScriptableObject.CreateInstance<VRCExpressionsMenu>();
                AssetDatabase.CreateAsset(menu, SubMenuPath);
            }
            Undo.RecordObject(menu, "HeightShift submenu");
            AddControls(menu, SubMenuAsset, _ => null);
            EditorUtility.SetDirty(menu);
            return menu;
        }

        // The nested menus each live in an asset of their own next to the
        // submenu, updated in place on a re-run.
        private static VRCExpressionsMenu SubMenuAsset(string key)
        {
            var path = AssetDir + "/HeightShift_Menu_" + key + ".asset";
            var menu = AssetDatabase.LoadAssetAtPath<VRCExpressionsMenu>(path);
            if (menu == null)
            {
                menu = ScriptableObject.CreateInstance<VRCExpressionsMenu>();
                AssetDatabase.CreateAsset(menu, path);
            }
            Undo.RecordObject(menu, "HeightShift submenu");
            EditorUtility.SetDirty(menu);
            return menu;
        }

        // The submenu's controls, replacing whatever the menu held; nested
        // menus in memory (for comparing against a built avatar).
        internal static void AddControls(VRCExpressionsMenu menu)
        {
            AddControls(menu, _ => ScriptableObject.CreateInstance<VRCExpressionsMenu>(), _ => null);
        }

        // `subMenu(key)` hands back the (empty or stale) menu to fill for one
        // nested menu: "SavedHeights" or "SaveCurrent". `icon(name)` the
        // icon to show (one of docs/unity/icons/*.png by file name), or
        // null. VRChat caps every menu at 8 controls.
        internal static void AddControls(VRCExpressionsMenu menu,
                                         Func<string, VRCExpressionsMenu> subMenu,
                                         Func<string, Texture2D> icon)
        {
            menu.controls.Clear();
            // Buttons, not Toggles: Grow and Shrink run while held, Play and
            // Stop act once per press.
            menu.controls.Add(Button("Grow", GrowParam, 1, icon("grow")));
            menu.controls.Add(Button("Shrink", ShrinkParam, 1, icon("shrink")));
            menu.controls.Add(Button("Play / Pause", PlayParam, 1, icon("play_pause")));
            menu.controls.Add(Button("Stop", StopParam, 1, icon("stop")));
            menu.controls.Add(Button("Own height", ResetParam, 1, icon("own_height")));
            menu.controls.Add(Button("Random height", RollParam, 1, icon("roll")));
            // a Toggle: the size parameter cards wait while it is on
            menu.controls.Add(Toggle("Pause cards", PauseParam, 1, icon("pause_cards")));

            var saved = subMenu("SavedHeights");
            saved.controls.Clear();
            for (var n = 1; n <= Slots; n++)
                saved.controls.Add(Button("Load " + n, LoadParam, n, icon("load" + n)));
            var save = subMenu("SaveCurrent");
            save.controls.Clear();
            for (var n = 1; n <= Slots; n++)
                save.controls.Add(Button("Save " + n, SaveParam, n, icon("save" + n)));
            // A submenu of its own, so a stray tap while loading can't
            // overwrite a saved height.
            saved.controls.Add(Folder("Save current", save, icon("save")));
            menu.controls.Add(Folder("Saved heights", saved, icon("saved")));
        }

        private static VRCExpressionsMenu.Control Button(string name, string param, int value,
                                                         Texture2D icon)
        {
            return new VRCExpressionsMenu.Control
            {
                name = name,
                icon = icon,
                type = VRCExpressionsMenu.Control.ControlType.Button,
                parameter = new VRCExpressionsMenu.Control.Parameter { name = param },
                value = value,
            };
        }

        private static VRCExpressionsMenu.Control Toggle(string name, string param, int value,
                                                         Texture2D icon)
        {
            var control = Button(name, param, value, icon);
            control.type = VRCExpressionsMenu.Control.ControlType.Toggle;
            return control;
        }

        private static VRCExpressionsMenu.Control Folder(string name, VRCExpressionsMenu menu,
                                                         Texture2D icon)
        {
            return new VRCExpressionsMenu.Control
            {
                name = name,
                icon = icon,
                type = VRCExpressionsMenu.Control.ControlType.SubMenu,
                subMenu = menu,
            };
        }

        private static bool LinkIntoRootMenu(
            VRCAvatarDescriptor descriptor, VRCExpressionsMenu subMenu)
        {
            var root = descriptor.expressionsMenu;
            if (root == null || !IsEditable(root))
            {
                var fresh = ScriptableObject.CreateInstance<VRCExpressionsMenu>();
                if (root != null)
                    fresh.controls.AddRange(root.controls);
                AssetDatabase.CreateAsset(fresh, AssetDir + "/HeightShift_RootMenu.asset");
                Undo.RecordObject(descriptor, "HeightShift root menu");
                descriptor.customExpressions = true;
                descriptor.expressionsMenu = fresh;
                EditorUtility.SetDirty(descriptor);
                root = fresh;
            }
            else
            {
                Undo.RecordObject(root, "HeightShift root menu");
            }

            if (root.controls.Any(c =>
                    c.type == VRCExpressionsMenu.Control.ControlType.SubMenu
                    && c.subMenu == subMenu))
                return true;    // already linked — idempotent re-run
            if (root.controls.Count >= 8)
                return false;   // no free slot; the caller explains
            root.controls.Add(new VRCExpressionsMenu.Control
            {
                name = SubMenuControlName,
                type = VRCExpressionsMenu.Control.ControlType.SubMenu,
                subMenu = subMenu,
            });
            EditorUtility.SetDirty(root);
            return true;
        }
    }
}
#endif
