// HeightShift — builds the VRCFury prefab and docs/unity/
// HeightShift-VRCFury.unitypackage. Not something avatar owners install.
//
// One prefab, Assets/HeightShift/HeightShift.prefab: a VRCFury Full
// Controller that adds the HeightShift/* parameters and a "HeightShift"
// submenu to the avatar's root menu, with the icons in docs/unity/icons/
// (drawn by tools/make_menu_icons.py).
//
// And the contact examples, Assets/HeightShift/Contacts/HeightShift Contact
// Grow / Shrink / Random.prefab: a contact receiver that sets the parameter
// the app's matching card listens to (HeightShift/Contact/<name>, Bool,
// unsynced), a VRCFury Armature Link to the head (change it: the body part
// to touch), a Full Controller that declares the parameter, and a VRCFury
// Gizmo whose text in the Scene view says what to change.
//
// tools/build_vrcf_prefab.py copies this file, its .asmdef and
// docs/unity/HeightShift_MenuInstaller.cs (the menu and parameter
// definitions both share) into a throwaway Editor folder of a Unity project
// that has the VRChat SDK and VRCFury, runs BuildFromCommandLine in batch
// mode and takes the folder out again.
//
// Everything is made through the SDK's and VRCFury's own APIs, so no GUID or
// serialized field is written by hand. After exporting, the package itself is
// checked rather than the assets that went into it: the built folder is
// deleted, the .unitypackage imported, the prefab put on throwaway avatars
// and VRChat's upload preprocess run on them — the pipeline a real upload
// runs, VRCFury included — and the menu and parameters that come out are
// compared with what the app expects.

#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using com.vrcfury.api;
using UnityEditor;
using UnityEditor.Animations;
using UnityEditor.SceneManagement;
using UnityEngine;
using VRC.Dynamics;
using VRC.SDK3.Avatars.Components;
using VRC.SDK3.Dynamics.Contact.Components;
using VRC.SDK3.Avatars.ScriptableObjects;
using VRC.SDKBase.Editor.BuildPipeline;
using Object = UnityEngine.Object;

namespace HeightShift.Build
{
    public static class HeightShiftVrcfPrefabBuilder
    {
        // Everything the package brings lands in its own top-level folder,
        // Assets/HeightShift — apart from Assets/HeightShiftMenu, where the
        // one-click installer writes, so importing it never touches the
        // installer's assets. Only the prefab sits at the top, where it is
        // picked up; the parts it uses are in Menu/.
        private const string Dir = "Assets/HeightShift";
        private const string PartsDir = Dir + "/Menu";
        private const string IconsDir = PartsDir + "/Icons";
        private const string ParamsPath = PartsDir + "/HeightShift_VRCF_Parameters.asset";
        private const string ControlsPath = PartsDir + "/HeightShift_VRCF_Controls.asset";
        private const string MenuPath = PartsDir + "/HeightShift_VRCF_Menu.asset";
        private const string PrefabPath = Dir + "/HeightShift.prefab";
        private const string ContactsDir = Dir + "/Contacts";
        private const string ContactPartsDir = ContactsDir + "/Parts";

        // The contact examples: the app's default cards listen to these
        // (constants.py CONTACT_*). Name, parameter, tags that set it off,
        // what it does — all on the head; the Gizmo says to change that.
        private static readonly (string name, string param, string[] tags, string what)[]
            Contacts =
        {
            ("Grow", "HeightShift/Contact/Grow", new[] { "Hand", "Finger" },
             "grows you while someone's hand is on it (a headpat)"),
            ("Shrink", "HeightShift/Contact/Shrink", new[] { "Foot" },
             "shrinks you while someone's foot is on it"),
            ("Random", "HeightShift/Contact/Random", new[] { "Finger" },
             "rolls the app's Random card when a finger boops it"),
        };

        // Everything the app listens to is under HeightShift/. VRCFury
        // renames any parameter its Full Controller doesn't list as global,
        // and OSC addresses the name, so a renamed one would never reach the
        // app.
        private const string GlobalParams = "HeightShift/*";
        private const string ParamPrefix = "HeightShift/";

        // VRChat's limit on menu icons; the SDK warns about anything larger.
        private const int IconSize = 256;
        private const double TimeoutSeconds = 600;

        private static readonly List<string> Report = new List<string>();
        private static string _packagePath;
        private static string _reportPath;
        private static DateTime _started;
        private static bool _done;

        public static void BuildFromCommandLine()
        {
            _started = DateTime.Now;
            try
            {
                _packagePath = Path.GetFullPath(Arg("-hsOut"));
                _reportPath = Path.GetFullPath(Arg("-hsReport"));
                var iconsSource = Path.GetFullPath(Arg("-hsIcons"));
                if (AssetDatabase.IsValidFolder(Dir))
                    throw new Exception(Dir + " already exists in this " +
                                        "project; build in one without it.");

                Build(iconsSource);
                PinIds();
                Directory.CreateDirectory(Path.GetDirectoryName(_packagePath));
                AssetDatabase.ExportPackage(Dir, _packagePath,
                    ExportPackageOptions.Recurse);
                Log("exported " + _packagePath + " (" +
                    new FileInfo(_packagePath).Length + " bytes)");

                AssetDatabase.DeleteAsset(Dir);
                AssetDatabase.importPackageCompleted += _ => Verify();
                AssetDatabase.importPackageFailed += (_, error) =>
                    Finish(false, "import failed: " + error);
                EditorApplication.update += Watchdog;
                AssetDatabase.ImportPackage(_packagePath, false);
                // Returns with the import queued; Unity keeps running in
                // batch mode until Finish() exits.
            }
            catch (Exception e)
            {
                Finish(false, e.ToString());
            }
        }

        private static Texture2D ImportIcon(string source, string path)
        {
            File.Copy(source, path);
            AssetDatabase.ImportAsset(path);
            var importer = (TextureImporter)AssetImporter.GetAtPath(path);
            importer.textureType = TextureImporterType.Default;
            importer.alphaIsTransparency = true;
            importer.mipmapEnabled = false;
            importer.wrapMode = TextureWrapMode.Clamp;
            importer.maxTextureSize = IconSize;
            importer.textureCompression = TextureImporterCompression.Compressed;
            importer.SaveAndReimport();
            return AssetDatabase.LoadAssetAtPath<Texture2D>(path);
        }

        private static void Build(string iconsSource)
        {
            AssetDatabase.CreateFolder("Assets", "HeightShift");
            AssetDatabase.CreateFolder(Dir, "Menu");
            AssetDatabase.CreateFolder(PartsDir, "Icons");

            var icons = new Dictionary<string, Texture2D>();
            foreach (var png in Directory.GetFiles(iconsSource, "*.png").OrderBy(f => f))
            {
                var name = Path.GetFileNameWithoutExtension(png);
                icons[name] = ImportIcon(png, IconsDir + "/" + name + ".png");
            }
            Log("imported " + icons.Count + " menu icons");
            Texture2D Icon(string name)
            {
                if (!icons.TryGetValue(name, out var tex))
                    throw new Exception("no icon " + name + ".png in " + iconsSource);
                return tex;
            }

            // The nested menus (Saved heights, Save current) are assets of
            // their own in Menu/.
            var nested = new Dictionary<string, VRCExpressionsMenu>();
            VRCExpressionsMenu Nested(string key)
            {
                if (!nested.TryGetValue(key, out var sub))
                {
                    sub = ScriptableObject.CreateInstance<VRCExpressionsMenu>();
                    AssetDatabase.CreateAsset(sub, NestedPath(key));
                    nested[key] = sub;
                }
                return sub;
            }

            var parameters = ScriptableObject.CreateInstance<VRCExpressionParameters>();
            parameters.parameters = new VRCExpressionParameters.Parameter[0];
            foreach (var (name, type, defaultValue) in HeightShiftMenuInstaller.Parameters)
                HeightShiftMenuInstaller.AddOrUpdateParameter(parameters, name, type, defaultValue);
            AssetDatabase.CreateAsset(parameters, ParamsPath);

            var controls = ScriptableObject.CreateInstance<VRCExpressionsMenu>();
            HeightShiftMenuInstaller.AddControls(controls, Nested, Icon);
            AssetDatabase.CreateAsset(controls, ControlsPath);

            // VRCFury merges this menu into the avatar's root, so its one
            // control — the submenu, with its icon — is what appears there.
            // Its Prefix field moves it into another submenu.
            var menu = ScriptableObject.CreateInstance<VRCExpressionsMenu>();
            menu.controls.Add(new VRCExpressionsMenu.Control
            {
                name = HeightShiftMenuInstaller.SubMenuControlName,
                type = VRCExpressionsMenu.Control.ControlType.SubMenu,
                subMenu = controls,
                icon = Icon("menu"),
            });
            AssetDatabase.CreateAsset(menu, MenuPath);

            var go = new GameObject("HeightShift");
            var controller = FuryComponents.CreateFullController(go);
            controller.AddMenu(menu);
            controller.AddParams(parameters);
            controller.AddGlobalParam(GlobalParams);
            PrefabUtility.SaveAsPrefabAsset(go, PrefabPath);
            Object.DestroyImmediate(go);
            Log("built " + PrefabPath);

            foreach (var sub in nested.Values)
                EditorUtility.SetDirty(sub);
            AssetDatabase.SaveAssets();
            BuildContacts();
        }

        private static string ContactPrefabPath(string name) =>
            ContactsDir + "/HeightShift Contact " + name + ".prefab";

        private static string ContactParamsPath(string name) =>
            ContactPartsDir + "/HeightShift_Contact_" + name + "_Parameters.asset";

        private static void BuildContacts()
        {
            AssetDatabase.CreateFolder(Dir, "Contacts");
            AssetDatabase.CreateFolder(ContactsDir, "Parts");
            foreach (var (name, param, tags, what) in Contacts)
            {
                // the parameter, unsynced and unsaved (OSC reads it locally:
                // no synced bits), and in FX too, for the receiver to set
                var parameters = ScriptableObject.CreateInstance<VRCExpressionParameters>();
                parameters.parameters = new VRCExpressionParameters.Parameter[0];
                HeightShiftMenuInstaller.AddOrUpdateParameter(parameters, param,
                    VRCExpressionParameters.ValueType.Bool, 0f);
                AssetDatabase.CreateAsset(parameters, ContactParamsPath(name));
                var fx = AnimatorController.CreateAnimatorControllerAtPath(
                    ContactPartsDir + "/HeightShift_Contact_" + name + ".controller");
                fx.AddParameter(param, AnimatorControllerParameterType.Bool);

                var go = new GameObject("HeightShift Contact " + name);
                var receiver = go.AddComponent<VRCContactReceiver>();
                receiver.shapeType = ContactBase.ShapeType.Sphere;
                receiver.radius = 0.12f;
                receiver.position = new Vector3(0f, 0.1f, 0f);   // above the head bone
                receiver.collisionTags = new List<string>(tags);
                receiver.receiverType = ContactReceiver.ReceiverType.Constant;
                receiver.parameter = param;
                receiver.allowSelf = false;     // someone else's hand, foot, finger
                receiver.allowOthers = true;
                receiver.localOnly = true;      // the app reads it on your own PC

                var link = FuryComponents.CreateArmatureLink(go);
                link.LinkTo(HumanBodyBones.Head);
                // onto the bone, upright, at world scale 1 (so the radius is
                // in metres on any rig): the public API has no switch for these
                var model = Field(link, "c");
                SetField(model, "alignPosition", true);
                SetField(model, "alignRotation", true);
                SetField(model, "alignScale", false);
                SetField(model, "forceOneWorldScale", true);

                var controller = FuryComponents.CreateFullController(go);
                controller.AddController(fx);
                controller.AddParams(parameters);
                controller.AddGlobalParam(GlobalParams);

                AddGizmo(go, "HeightShift Contact " + name + ": " + what + ".\n" +
                             "1. Armature Link (VRCFury): pick the body part.\n" +
                             "2. Contact Receiver: pick the Collision Tags that set it off, " +
                             "and move / size it.\n" +
                             "Sets " + param + " — the app's card of that name acts on it.");
                PrefabUtility.SaveAsPrefabAsset(go, ContactPrefabPath(name));
                Object.DestroyImmediate(go);
                Log("built " + ContactPrefabPath(name));
            }
            AssetDatabase.SaveAssets();
        }

        // VRCFury's text-in-the-Scene-view feature (not in its public API):
        // a note on the prefab that goes away at upload with VRCFury itself.
        private static void AddGizmo(GameObject go, string text)
        {
            var vrcfury = Type.GetType("VF.Model.VRCFury, VRCFury")
                          ?? throw new Exception("VRCFury's component type not found");
            var gizmoType = Type.GetType("VF.Model.Feature.Gizmo, VRCFury")
                            ?? throw new Exception("VRCFury's Gizmo feature not found");
            var component = go.AddComponent(vrcfury);
            var gizmo = Activator.CreateInstance(gizmoType, true);
            SetField(gizmo, "text", text);
            SetField(gizmo, "rotation", Vector3.zero);
            SetField(gizmo, "sphereRadius", 0.12f);
            SetField(gizmo, "arrowLength", 0f);
            SetField(component, "content", gizmo);
        }

        private static object Field(object target, string name)
        {
            var field = target.GetType().GetField(name,
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                ?? throw new Exception(target.GetType().Name + " has no field " + name);
            return field.GetValue(target);
        }

        private static void SetField(object target, string name, object value)
        {
            var field = target.GetType().GetField(name,
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                ?? throw new Exception(target.GetType().Name + " has no field " + name);
            field.SetValue(target, value);
        }

        private static string FeatureName(Component vrcfury)
        {
            var content = Field(vrcfury, "content");
            return content == null ? "(none)" : content.GetType().Name;
        }

        private static string NestedPath(string key) =>
            PartsDir + "/HeightShift_VRCF_" + key + ".asset";

        // Unity gives every new asset a random GUID and a new prefab random
        // object IDs. A package whose GUIDs changed lands next to the older
        // copy as duplicates ("HeightShift_VRCF_Menu 1.asset") instead of
        // updating it, so every ID is replaced with one derived from the
        // file's path: the same on every build. tests/test_vrcf_prefab.py
        // checks them.
        private static void PinIds()
        {
            var files = Directory.GetFiles(Dir, "*", SearchOption.AllDirectories)
                .Select(f => f.Replace('\\', '/')).Append(Dir + ".meta").ToList();
            var guids = files.Where(f => f.EndsWith(".meta"))
                .Select(f => f.Substring(0, f.Length - ".meta".Length))
                .ToDictionary(a => AssetDatabase.AssetPathToGUID(a), a => StableGuid(a));
            var yaml = files.Where(f => f.EndsWith(".meta") || f.EndsWith(".asset")
                                        || f.EndsWith(".prefab"))
                .ToDictionary(f => f, f => File.ReadAllText(f));
            var binary = files.Where(f => !yaml.ContainsKey(f))
                .ToDictionary(f => f, f => File.ReadAllBytes(f));

            AssetDatabase.DeleteAsset(Dir);
            foreach (var entry in binary)
            {
                Directory.CreateDirectory(Path.GetDirectoryName(entry.Key));
                File.WriteAllBytes(entry.Key, entry.Value);
            }
            foreach (var entry in yaml)
            {
                Directory.CreateDirectory(Path.GetDirectoryName(entry.Key));
                var text = entry.Value;
                foreach (var guid in guids)
                    text = text.Replace(guid.Key, guid.Value);
                if (entry.Key.EndsWith(".prefab"))
                    text = PinLocalIds(text, entry.Key);
                File.WriteAllText(entry.Key, text);
            }
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            Log("pinned the GUIDs of " + guids.Count + " assets");
        }

        // The prefab's object anchors (&id) and VRCFury's managed-reference
        // ids (rid), numbered in file order.
        private static string PinLocalIds(string text, string path)
        {
            var ids = Regex.Matches(text, @"--- !u!\d+ &(\d+)")
                .Cast<Match>().Concat(Regex.Matches(text, @"\brid: (\d+)").Cast<Match>())
                .Select(m => m.Groups[1].Value).Distinct().ToList();
            var map = ids.Select((id, i) => (id, i)).ToDictionary(
                p => p.id, p => StableLong(path + "#" + p.i).ToString());
            return Regex.Replace(text, @"\b\d+\b",
                m => map.TryGetValue(m.Value, out var pinned) ? pinned : m.Value);
        }

        private static string StableGuid(string assetPath)
        {
            return string.Concat(Md5("HeightShift:" + assetPath)
                .Select(b => b.ToString("x2")));
        }

        private static long StableLong(string key)
        {
            // Positive and never 0: Unity reserves 0 and the negatives.
            return (BitConverter.ToInt64(Md5(key), 0) & 0x0FFFFFFFFFFFFFFF) | 1;
        }

        private static byte[] Md5(string text)
        {
            using (var md5 = MD5.Create())
                return md5.ComputeHash(Encoding.UTF8.GetBytes(text));
        }

        // --- Checking the imported package ------------------------------

        private static void Verify()
        {
            try
            {
                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath);
                if (prefab == null)
                    throw new Exception("the imported package has no " + PrefabPath);
                Log("imported the package back");
                EditorSceneManager.NewScene(NewSceneSetup.EmptyScene);

                var ok = true;
                ok &= Scenario("HeightShift on an avatar with no menu of its own", prefab,
                    avatar => { });
                ok &= Scenario("HeightShift on an avatar whose root menu is full", prefab,
                    avatar => GiveMenu(avatar, 8, false));
                ok &= Scenario("avatar that already has the HeightShift parameters", prefab,
                    avatar => GiveMenu(avatar, 3, true));
                // What VRCHAT_MENU.md tells someone switching over from the
                // one-click installer rests on this one; it is reported,
                // not checked.
                ok &= Scenario("avatar that still has the installer's submenu", prefab,
                    avatar =>
                    {
                        GiveMenu(avatar, 3, true);
                        var old = ScriptableObject.CreateInstance<VRCExpressionsMenu>();
                        HeightShiftMenuInstaller.AddControls(old);
                        avatar.GetComponent<VRCAvatarDescriptor>().expressionsMenu.controls.Add(
                            new VRCExpressionsMenu.Control
                            {
                                name = HeightShiftMenuInstaller.SubMenuControlName,
                                type = VRCExpressionsMenu.Control.ControlType.SubMenu,
                                subMenu = old,
                            });
                    }, reportOnly: true);
                ok &= CheckContacts();
                AssetDatabase.DeleteAsset(Dir);
                Finish(ok, ok ? "all checks passed" : "some checks FAILED");
            }
            catch (Exception e)
            {
                Finish(false, e.ToString());
            }
        }

        // Each contact example as the package brings it, and put on a test
        // avatar: its parameter must come out unsynced, unsaved, not renamed,
        // and its receiver must still set it. (The test avatar has no
        // humanoid rig, so the Armature Link is taken off that copy: what it
        // does is VRCFury's own, checked in the prefab instead.)
        private static bool CheckContacts()
        {
            var ok = true;
            var vrcfuryType = Type.GetType("VF.Model.VRCFury, VRCFury");
            foreach (var (name, param, tags, _) in Contacts)
            {
                Log("");
                Log("== contact example " + name);
                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(ContactPrefabPath(name));
                if (prefab == null)
                {
                    ok = Fail("the package has no " + ContactPrefabPath(name));
                    continue;
                }
                var receiver = prefab.GetComponent<VRCContactReceiver>();
                if (receiver == null || receiver.parameter != param || !receiver.localOnly
                    || receiver.receiverType != ContactReceiver.ReceiverType.Constant
                    || !receiver.collisionTags.SequenceEqual(tags))
                    ok = Fail(name + ": the receiver isn't " + param + ", Constant, local, " +
                              string.Join("+", tags));
                var features = prefab.GetComponents(vrcfuryType).Select(FeatureName).ToList();
                Log("VRCFury: " + string.Join(", ", features));
                foreach (var want in new[] { "ArmatureLink", "FullController", "Gizmo" })
                    if (!features.Contains(want))
                        ok = Fail(name + ": no VRCFury " + want);

                var avatar = new GameObject("HeightShift Contact Test Avatar");
                avatar.AddComponent<Animator>();
                var descriptor = avatar.AddComponent<VRCAvatarDescriptor>();
                descriptor.baseAnimationLayers = DefaultLayers(
                    VRCAvatarDescriptor.AnimLayerType.Base,
                    VRCAvatarDescriptor.AnimLayerType.Additive,
                    VRCAvatarDescriptor.AnimLayerType.Gesture,
                    VRCAvatarDescriptor.AnimLayerType.Action,
                    VRCAvatarDescriptor.AnimLayerType.FX);
                descriptor.specialAnimationLayers = DefaultLayers(
                    VRCAvatarDescriptor.AnimLayerType.Sitting,
                    VRCAvatarDescriptor.AnimLayerType.TPose,
                    VRCAvatarDescriptor.AnimLayerType.IKPose);
                var instance = (GameObject)PrefabUtility.InstantiatePrefab(prefab, avatar.transform);
                foreach (var c in instance.GetComponents(vrcfuryType))
                    if (FeatureName(c) == "ArmatureLink")
                        Object.DestroyImmediate(c);
                var clone = Object.Instantiate(avatar);
                try
                {
                    if (!VRCBuildPipelineCallbacks.OnPreprocessAvatar(clone))
                    {
                        ok = Fail(name + ": the upload preprocess refused it (see the Unity log)");
                        continue;
                    }
                    var built = clone.GetComponent<VRCAvatarDescriptor>();
                    var all = built.expressionParameters.parameters ??
                              new VRCExpressionParameters.Parameter[0];
                    var found = all.Where(p => p != null && p.name == param).ToList();
                    if (found.Count != 1 || found[0].networkSynced || found[0].saved
                        || found[0].valueType != VRCExpressionParameters.ValueType.Bool)
                        ok = Fail(name + ": " + param + " found " + found.Count +
                                  " times, or synced / saved / not a Bool");
                    var builtReceiver = clone.GetComponentsInChildren<VRCContactReceiver>(true)
                        .FirstOrDefault(r => r.parameter == param);
                    if (builtReceiver == null)
                        ok = Fail(name + ": after the build no receiver sets " + param);
                    Log((ok ? "ok" : "FAIL") + ": " + param + " unsynced, unsaved, set by its " +
                        "receiver (" + built.expressionParameters.CalcTotalCost() + " synced bits in all)");
                }
                finally
                {
                    Object.DestroyImmediate(clone);
                    Object.DestroyImmediate(avatar);
                }
            }
            return ok;
        }

        private static bool Scenario(string title, GameObject prefab,
                                     Action<GameObject> setUp,
                                     bool reportOnly = false)
        {
            Log("");
            Log("== " + title);
            var avatar = new GameObject("HeightShift Test Avatar");
            avatar.AddComponent<Animator>();
            var descriptor = avatar.AddComponent<VRCAvatarDescriptor>();
            // The descriptor's inspector fills the layer slots; one added
            // from code has none, and VRCFury walks them.
            descriptor.baseAnimationLayers = DefaultLayers(
                VRCAvatarDescriptor.AnimLayerType.Base,
                VRCAvatarDescriptor.AnimLayerType.Additive,
                VRCAvatarDescriptor.AnimLayerType.Gesture,
                VRCAvatarDescriptor.AnimLayerType.Action,
                VRCAvatarDescriptor.AnimLayerType.FX);
            descriptor.specialAnimationLayers = DefaultLayers(
                VRCAvatarDescriptor.AnimLayerType.Sitting,
                VRCAvatarDescriptor.AnimLayerType.TPose,
                VRCAvatarDescriptor.AnimLayerType.IKPose);
            setUp(avatar);
            PrefabUtility.InstantiatePrefab(prefab, avatar.transform);
            // Like VRCFury's own "Build a test copy": preprocess a clone so
            // the original keeps its unbuilt state.
            var clone = Object.Instantiate(avatar);
            var ok = true;
            try
            {
                if (!VRCBuildPipelineCallbacks.OnPreprocessAvatar(clone))
                {
                    Log("FAIL: the upload preprocess refused the avatar " +
                        "(see the Unity log)");
                    return false;
                }
                var built = clone.GetComponent<VRCAvatarDescriptor>();
                if (reportOnly)
                {
                    DescribeMenu(built.expressionsMenu, "");
                    return true;
                }
                ok &= CheckParameters(built.expressionParameters);
                ok &= CheckMenu(built.expressionsMenu);
                return ok;
            }
            finally
            {
                Object.DestroyImmediate(clone);
                Object.DestroyImmediate(avatar);
            }
        }

        private static VRCAvatarDescriptor.CustomAnimLayer[] DefaultLayers(
            params VRCAvatarDescriptor.AnimLayerType[] types)
        {
            return types.Select(t => new VRCAvatarDescriptor.CustomAnimLayer
            {
                type = t,
                isDefault = true,
            }).ToArray();
        }

        // Gives the avatar its own root menu with `count` placeholder
        // toggles, and with `hsParameters` the HeightShift parameters as the
        // one-click installer would have left them.
        private static void GiveMenu(GameObject avatar, int count, bool hsParameters)
        {
            var descriptor = avatar.GetComponent<VRCAvatarDescriptor>();
            var parameters = ScriptableObject.CreateInstance<VRCExpressionParameters>();
            var list = new List<VRCExpressionParameters.Parameter>();
            var menu = ScriptableObject.CreateInstance<VRCExpressionsMenu>();
            for (var i = 0; i < count; i++)
            {
                list.Add(new VRCExpressionParameters.Parameter
                {
                    name = "Placeholder" + i,
                    valueType = VRCExpressionParameters.ValueType.Bool,
                    networkSynced = true,
                });
                menu.controls.Add(new VRCExpressionsMenu.Control
                {
                    name = "Placeholder " + i,
                    type = VRCExpressionsMenu.Control.ControlType.Toggle,
                    parameter = new VRCExpressionsMenu.Control.Parameter
                    { name = "Placeholder" + i },
                    value = 1,
                });
            }
            parameters.parameters = list.ToArray();
            if (hsParameters)
                foreach (var (name, type, defaultValue) in HeightShiftMenuInstaller.Parameters)
                    HeightShiftMenuInstaller.AddOrUpdateParameter(parameters, name, type, defaultValue);
            descriptor.customExpressions = true;
            descriptor.expressionParameters = parameters;
            descriptor.expressionsMenu = menu;
        }

        private static bool CheckParameters(VRCExpressionParameters built)
        {
            var ok = true;
            var all = built.parameters ?? new VRCExpressionParameters.Parameter[0];
            var wanted = HeightShiftMenuInstaller.Parameters;
            foreach (var (name, type, defaultValue) in wanted)
            {
                var found = all.Where(p => p != null && p.name == name).ToList();
                if (found.Count != 1)
                {
                    ok = Fail(name + ": found " + found.Count + " times, wanted 1");
                    continue;
                }
                var p0 = found[0];
                if (p0.valueType != type || p0.networkSynced || p0.saved
                    || Math.Abs(p0.defaultValue - defaultValue) > 1e-6)
                    ok = Fail(name + ": " + p0.valueType + ", synced " +
                              p0.networkSynced + ", saved " + p0.saved +
                              ", default " + p0.defaultValue);
            }
            // A renamed copy (VRCFury prefixes the names it isn't told are
            // global) would mean the menu drives a parameter OSC never sees.
            var extra = all.Where(p => p != null && p.name.Contains(ParamPrefix)
                && wanted.All(q => q.name != p.name))
                .Select(p => p.name).ToList();
            if (extra.Count > 0)
                ok = Fail("renamed or extra parameters: " + string.Join(", ", extra));
            Log((ok ? "ok" : "FAIL") + ": the HeightShift parameters, unsynced, " +
                "unsaved, not renamed (" + built.CalcTotalCost() +
                " synced bits in all)");
            return ok;
        }

        private static bool CheckMenu(VRCExpressionsMenu root)
        {
            var expected = ScriptableObject.CreateInstance<VRCExpressionsMenu>();
            HeightShiftMenuInstaller.AddControls(expected);
            var rootName = HeightShiftMenuInstaller.SubMenuControlName;
            var found = new List<(VRCExpressionsMenu.Control control, string path)>();
            FindSubmenus(root, "", new HashSet<VRCExpressionsMenu>(), found, rootName);
            Log("root menu: " + string.Join(" | ",
                root.controls.Select(c => c.name + (c.subMenu != null
                    ? " [" + c.subMenu.controls.Count + "]" : ""))));
            if (found.Count != 1)
                return Fail("found " + found.Count + " \"" + rootName + "\" submenus, wanted 1");
            var (submenu, path) = found[0];
            var ok = true;
            if (submenu.icon == null)
                ok = Fail("the submenu has no icon");
            ok &= SameMenu(submenu.subMenu, expected, path);
            ok &= CheckIcons(submenu.subMenu, path, new HashSet<VRCExpressionsMenu>());
            return ok;
        }

        // Every control shows an icon.
        private static bool CheckIcons(VRCExpressionsMenu menu, string path,
                                       HashSet<VRCExpressionsMenu> seen)
        {
            if (menu == null || !seen.Add(menu)) return true;
            var ok = true;
            foreach (var c in menu.controls)
            {
                if (c.icon == null)
                    ok = Fail(path + "/" + c.name + " has no icon");
                if (c.type == VRCExpressionsMenu.Control.ControlType.SubMenu)
                    ok &= CheckIcons(c.subMenu, path + "/" + c.name, seen);
            }
            return ok;
        }

        // The built menu against the expected one, nested menus included.
        private static bool SameMenu(VRCExpressionsMenu got, VRCExpressionsMenu expected,
                                     string path)
        {
            var ok = true;
            if (got == null)
                return Fail(path + " is missing");
            if (got.controls.Count != expected.controls.Count)
                ok = Fail(path + " has " + got.controls.Count + " controls, wanted " +
                          expected.controls.Count);
            for (var i = 0; i < Math.Min(got.controls.Count, expected.controls.Count); i++)
            {
                var g = got.controls[i];
                var e = expected.controls[i];
                if (Describe(g) != Describe(e))
                    ok = Fail(path + " control " + i + " is " + Describe(g) +
                              ", wanted " + Describe(e));
                else if (e.type == VRCExpressionsMenu.Control.ControlType.SubMenu)
                    ok &= SameMenu(g.subMenu, e.subMenu, path + "/" + e.name);
            }
            Log((ok ? "ok" : "FAIL") + ": " + path + " with " + got.controls.Count +
                " controls: " + string.Join(" | ", got.controls.Select(Describe)));
            return ok;
        }

        private static void FindSubmenus(
            VRCExpressionsMenu menu, string path, HashSet<VRCExpressionsMenu> seen,
            List<(VRCExpressionsMenu.Control, string)> found, string name)
        {
            if (menu == null || !seen.Add(menu)) return;
            foreach (var c in menu.controls)
            {
                if (c.type != VRCExpressionsMenu.Control.ControlType.SubMenu) continue;
                var here = path + "/" + c.name;
                if (c.name == name)
                    found.Add((c, here));
                else
                    FindSubmenus(c.subMenu, here, seen, found, name);
            }
        }

        private static void DescribeMenu(VRCExpressionsMenu menu, string path)
        {
            Log((path == "" ? "/" : path) + ": " + string.Join(" | ",
                menu.controls.Select(c => c.name)));
            foreach (var c in menu.controls)
                if (c.type == VRCExpressionsMenu.Control.ControlType.SubMenu
                    && c.subMenu != null)
                    DescribeMenu(c.subMenu, path + "/" + c.name);
        }

        private static string Describe(VRCExpressionsMenu.Control c)
        {
            var param = c.type == VRCExpressionsMenu.Control.ControlType.RadialPuppet
                ? c.subParameters?.FirstOrDefault()?.name
                : c.parameter?.name;
            return c.name + " " + c.type + " " + param + "=" + c.value;
        }

        // --- Plumbing ---------------------------------------------------

        private static void Watchdog()
        {
            if ((DateTime.Now - _started).TotalSeconds > TimeoutSeconds)
                Finish(false, "timed out waiting for the package import");
        }

        private static void Finish(bool ok, string message)
        {
            if (_done) return;
            _done = true;
            EditorApplication.update -= Watchdog;
            Log("");
            Log((ok ? "PASS: " : "FAIL: ") + message);
            try
            {
                if (_reportPath != null)
                    File.WriteAllLines(_reportPath, Report);
            }
            catch (Exception e)
            {
                Debug.LogException(e);
            }
            EditorApplication.Exit(ok ? 0 : 1);
        }

        private static bool Fail(string message)
        {
            Log("FAIL: " + message);
            return false;
        }

        private static void Log(string line)
        {
            Report.Add(line);
            Debug.Log("[HeightShift prefab] " + line);
        }

        private static string Arg(string name)
        {
            var args = Environment.GetCommandLineArgs();
            var i = Array.IndexOf(args, name);
            if (i < 0 || i + 1 >= args.Length)
                throw new ArgumentException("missing " + name + " <path>");
            return args[i + 1];
        }
    }
}
#endif
