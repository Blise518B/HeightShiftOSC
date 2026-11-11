"""Size parameters (avatar parameters that grow / shrink you), the random
card, the saved heights' keys and the VR gesture: the pure rules, and the
controller with the fakes from test_controller (no VRChat, Qt offscreen)."""

import math
import unittest

from tests import test_controller as tc  # noqa: F401  (Qt app, fakes, sys.path)

from PySide6.QtTest import QTest

from constants import (
    CONTACT_GROW,
    CONTACT_RANDOM,
    CONTACT_SHRINK,
    GESTURE_LEFT,
    GESTURE_RIGHT,
    GROUNDED,
    MENU_PAUSE,
    MENU_RESET,
    MENU_ROLL,
    VR_RESET_HOLD_S,
)
from height_logic import (
    KIND_RANDOM,
    clean_size_param,
    drive_height,
    flatten_parameters,
    gestures_match,
    param_level,
    param_rose,
    param_type,
    random_height,
    speed_text,
    vr_reset_gesture,
)
from hotkeys import DEFAULT_SLOT_KEYS, Hotkey

GROW_CARD = {"kind": "param", "param": "Headpat", "type": "Float", "dir": "grow",
             "speed": 10.0, "unit": "cm"}
SHRINK_CARD = {"kind": "param", "param": "Stomp", "type": "Bool", "dir": "shrink",
               "speed": 10.0, "unit": "cm"}


class TestRules(unittest.TestCase):
    def test_how_hard_a_parameter_pushes(self):
        self.assertEqual(param_level(True), 1.0)
        self.assertEqual(param_level(False), 0.0)
        self.assertEqual(param_level(3), 1.0)            # an Int not 0
        self.assertEqual(param_level(0), 0.0)
        self.assertEqual(param_level(0.42), 0.42)
        self.assertEqual(param_level(-0.5), 0.0)         # VRChat's -1..1: below 0 is off
        self.assertEqual(param_level(7.0), 1.0)
        self.assertEqual(param_level(None), 0.0)
        self.assertEqual(param_level(float("nan")), 0.0)

    def test_cm_cards_add_percent_cards_multiply(self):
        self.assertAlmostEqual(drive_height(100.0, 2.0, [(1, 5.0, "cm", 1.0)]), 110.0)
        self.assertAlmostEqual(drive_height(100.0, 2.0, [(1, 5.0, "cm", 0.5)]), 105.0)
        self.assertAlmostEqual(drive_height(100.0, 1.0, [(1, 10.0, "pct", 1.0)]), 110.0)
        self.assertAlmostEqual(drive_height(110.0, 1.0, [(-1, 10.0, "pct", 1.0)]), 100.0)
        # the same speed both ways holds still
        self.assertAlmostEqual(drive_height(170.0, 3.0, [(1, 7.0, "pct", 1.0),
                                                         (-1, 7.0, "pct", 1.0)]), 170.0)
        self.assertAlmostEqual(drive_height(170.0, 3.0, [(1, 7.0, "cm", 1.0),
                                                         (-1, 7.0, "cm", 1.0)]), 170.0)
        self.assertEqual(drive_height(170.0, 3.0, [(1, 7.0, "cm", 0.0)]), 170.0)

    def test_a_card_from_the_config_is_checked(self):
        card = clean_size_param({"param": "/avatar/parameters/Foo ", "speed": 1e9,
                                 "unit": "pct", "dir": "sideways"})
        self.assertEqual(card["param"], "Foo")
        self.assertEqual(card["speed"], 5.0)              # out of range: the default
        self.assertEqual(card["dir"], "grow")
        self.assertEqual(card["kind"], "param")
        self.assertIsNone(clean_size_param("nope"))
        self.assertIsNone(clean_size_param({"param": 5}))
        rnd = clean_size_param({"kind": "random", "min": 900, "max": 20, "go": "fly"})
        self.assertEqual((rnd["min"], rnd["max"], rnd["go"]), (20.0, 900.0, "instant"))

    def test_random_heights_are_even_on_the_scale(self):
        self.assertEqual(random_height(100, 10_000, 0.0), 100.0)
        self.assertEqual(random_height(100, 10_000, 0.5), 1000.0)   # the middle decade
        self.assertEqual(random_height(100, 10_000, 0.9999999), 10_000.0)
        self.assertEqual(random_height(10_000, 100, 0.0), 100.0)    # either order
        self.assertEqual(random_height(1, 5, 0.5), 2.2)             # tenths below 10 cm
        for k in range(50):
            cm = random_height(30, 1000, k / 50)
            self.assertTrue(30 <= cm <= 1000)

    def test_a_rise_is_off_to_on(self):
        self.assertTrue(param_rose(False, True))
        self.assertTrue(param_rose(0.0, 0.4))
        self.assertFalse(param_rose(None, True))      # a first value: an avatar loading
        self.assertFalse(param_rose(True, True))
        self.assertFalse(param_rose(True, False))

    def test_the_vr_gesture(self):
        self.assertTrue(gestures_match(1, 1, 1, 1))
        self.assertFalse(gestures_match(1, 2, 1, 1))
        self.assertFalse(gestures_match(None, 1, 1, 1))
        self.assertTrue(vr_reset_gesture(1, 1, True, False))         # fists, feet leave
        self.assertFalse(vr_reset_gesture(1, 1, False, True))        # landing
        self.assertFalse(vr_reset_gesture(1, 1, None, False))        # not known before
        self.assertFalse(vr_reset_gesture(1, 0, True, False))
        self.assertTrue(vr_reset_gesture(7, 3, True, False, 7, 3))   # thumbs up + point

    def test_vrchats_tree_flattens_to_names(self):
        tree = {"FULL_PATH": "/avatar/parameters", "CONTENTS": {
            "Headpat": {"FULL_PATH": "/avatar/parameters/Headpat", "TYPE": "f",
                        "VALUE": [0.25]},
            "Toggle": {"FULL_PATH": "/avatar/parameters/Toggle", "TYPE": "T",
                       "VALUE": [True]},
            "Off": {"FULL_PATH": "/avatar/parameters/Off", "TYPE": "F"},
            "Gesture": {"FULL_PATH": "/avatar/parameters/Gesture", "TYPE": "i",
                        "VALUE": [3]},
            "Name": {"FULL_PATH": "/avatar/parameters/Name", "TYPE": "s", "VALUE": ["x"]},
            "VF12_Outfit": {"FULL_PATH": "/avatar/parameters/VF12_Outfit", "CONTENTS": {
                "Hoodie": {"FULL_PATH": "/avatar/parameters/VF12_Outfit/Hoodie",
                           "TYPE": "T", "VALUE": [False]}}},
        }}
        self.assertEqual(flatten_parameters(tree), {
            "Headpat": ("Float", 0.25), "Toggle": ("Bool", True), "Off": ("Bool", False),
            "Gesture": ("Int", 3), "VF12_Outfit/Hoodie": ("Bool", False)})
        self.assertEqual(flatten_parameters("junk"), {})
        self.assertIsNone(param_type("s"))

    def test_speeds_read_like_the_settings(self):
        self.assertEqual(speed_text(5, "cm"), "5 cm/s")
        self.assertEqual(speed_text(2.5, "pct", -1), "−2.5 %/s")
        self.assertEqual(speed_text(4.2, "cm", 1), "+4.2 cm/s")


class SizeParamsTest(unittest.TestCase):
    setUp = tc.ControllerTest.setUp
    tearDown = tc.ControllerTest.tearDown
    make = tc.ControllerTest.make
    connect = tc.ControllerTest.connect
    report = tc.ControllerTest.report
    hold = tc.ControllerTest.hold
    release = tc.ControllerTest.release
    menu = tc.ControllerTest.menu
    tap = tc.ControllerTest.tap

    def ready(self, cards=(GROW_CARD,), metres=1.7, **config):
        self.make(size_params=[dict(c) for c in cards], **config)
        self.connect()
        self.report(metres)
        return self.c

    def param(self, name, value):
        self.c._on_param(name, value, self.clock.t)

    def run_cards(self, seconds, step=0.1):
        for _ in range(int(round(seconds / step))):
            self.clock.t += step
            self.c._param_tick()

    # --- the defaults ----------------------------------------------------
    def test_a_first_start_has_the_contact_examples_cards(self):
        self.make()
        names = [(p["param"], p["dir"]) for p in self.c.size_params]
        self.assertEqual(names, [(CONTACT_GROW, "grow"), (CONTACT_SHRINK, "shrink")])
        self.assertTrue(self.c.size_params_on)
        self.assertEqual(len(self.window.size_board.cards), 2)
        self.assertGreaterEqual(self.osc.watched, {CONTACT_GROW, CONTACT_SHRINK})

    def test_a_new_random_card_listens_to_the_contact_example(self):
        self.make(size_params=[])
        self.c._on_size_param_added(KIND_RANDOM, "", "", -1)
        self.assertEqual(self.c.size_params[0]["param"], CONTACT_RANDOM)
        self.assertFalse(self.window.picker_open)

    # --- driving the height -----------------------------------------------
    def test_a_parameter_on_grows_at_its_cards_speed(self):
        self.ready([dict(GROW_CARD, type="Bool")])
        self.param("Headpat", True)
        self.assertTrue(self.c._param_timer.isActive())
        self.run_cards(2.0)
        self.assertAlmostEqual(self.osc.sent[-1], 190.0, places=3)   # 10 cm/s for 2 s
        self.assertIn("growing", self.window.activity_chip.text())
        self.param("Headpat", False)
        self.assertFalse(self.c._param_timer.isActive())
        self.assertIn("Grew to 190 cm", self.window.status_msg.text())

    def test_a_float_pushes_at_its_share(self):
        self.ready()
        self.param("Headpat", 0.5)
        self.run_cards(2.0)
        self.assertAlmostEqual(self.osc.sent[-1], 180.0, places=3)   # half of 10 cm/s

    def test_grow_and_shrink_cards_add_up(self):
        self.ready([dict(GROW_CARD, speed=10.0), dict(SHRINK_CARD, speed=4.0)])
        self.param("Headpat", 1.0)
        self.param("Stomp", True)
        self.run_cards(1.0)
        self.assertAlmostEqual(self.osc.sent[-1], 176.0, places=3)

    def test_it_stops_at_the_limit_and_says_so(self):
        self.ready([dict(SHRINK_CARD, speed=1000.0)], metres=0.05)
        self.param("Stomp", True)
        self.run_cards(1.0)
        self.assertEqual(self.osc.sent[-1], 1.0)
        self.assertIn("minimum", self.window.status_msg.text())

    def test_paused_cards_do_nothing(self):
        self.ready([dict(GROW_CARD, on=False)])
        self.param("Headpat", 1.0)
        self.run_cards(1.0)
        self.assertEqual(self.osc.sent, [])
        self.c._on_size_params_toggled(False)
        self.c._on_size_param_changed(self.c.size_params[0]["id"], {"on": True})
        self.param("Headpat", 1.0)
        self.run_cards(1.0)
        self.assertEqual(self.osc.sent, [])                 # all paused
        self.c._on_size_params_toggled(True)
        self.run_cards(1.0)
        self.assertTrue(self.osc.sent)

    def test_vrchats_pause_parameter_pauses_them(self):
        self.ready()
        self.menu(MENU_PAUSE, True)
        self.param("Headpat", 1.0)
        self.run_cards(1.0)
        self.assertEqual(self.osc.sent, [])
        self.assertIn("VRChat", self.window.size_note.text())
        self.menu(MENU_PAUSE, False)
        self.run_cards(1.0)
        self.assertTrue(self.osc.sent)

    def test_a_held_key_goes_first(self):
        self.ready(hotkeys_enabled=True, hotkey_speed=5.0, hotkey_speed_unit="cm")
        self.param("Headpat", 1.0)
        self.c.keys.down.add(tc.DEFAULT_SHRINK)
        self.c._hotkey_tick()
        for _ in range(10):
            self.clock.t += 0.1
            self.c._hotkey_tick()
            self.c._param_tick()
        self.assertLess(self.osc.sent[-1], 170.0)           # only the key moved it
        self.release()
        before = self.osc.sent[-1]
        self.run_cards(1.0)
        self.assertAlmostEqual(self.osc.sent[-1], before + 10.0, places=3)  # from there on

    def test_a_card_starting_stops_the_transition(self):
        self.ready()
        self.c._on_play()
        self.assertIsNotNone(self.c.transition)
        self.param("Headpat", 1.0)
        self.run_cards(0.2)
        self.assertIsNone(self.c.transition)
        self.c._on_play()                                   # and Play waits for it
        self.assertIsNone(self.c.transition)
        self.assertIn("size parameter", self.window.status_msg.text())

    def test_another_change_is_carried_on_from(self):
        self.ready()
        self.param("Headpat", 1.0)
        self.run_cards(1.0)                                 # 180 cm
        self.c._on_adjust(100.0)                            # +100 while it grows
        self.run_cards(1.0)
        self.assertAlmostEqual(self.osc.sent[-1], 290.0, places=3)

    def test_an_avatar_change_forgets_the_values(self):
        self.ready()
        self.param("Headpat", 1.0)
        self.c._on_avatar_change("avtr_x", self.clock.t)
        self.assertEqual(self.c._param_values, {})
        self.assertFalse(self.c._param_timer.isActive())

    def test_values_come_from_vrchats_tree_first(self):
        self.make(size_params=[dict(GROW_CARD)])
        self.osc.params = {"Headpat": ("Float", 0.75), "Other": ("Bool", True)}
        self.connect()
        self.report(1.7)
        self.c._read_params()
        for _ in range(50):
            QTest.qWait(10)
            if "Headpat" in self.c._param_values:
                break
        self.assertEqual(self.c._param_values["Headpat"], 0.75)
        self.assertNotIn("Other", self.c._param_values)     # only what is watched

    def test_a_missing_parameter_is_said(self):
        self.ready()
        self.c._on_params_read(self.c._params_round, {"Other": ("Bool", True)})
        card = self.window.size_board.cards[self.c.size_params[0]["id"]]
        self.assertIn("not on this avatar", card.live.text())

    # --- the cards ---------------------------------------------------------
    def test_cards_are_added_sorted_changed_removed_and_saved(self):
        self.make(size_params=[dict(GROW_CARD), dict(SHRINK_CARD)])
        first, second = (p["id"] for p in self.c.size_params)
        self.c._on_size_param_moved(second, 0)
        self.assertEqual([p["param"] for p in self.c.size_params], ["Stomp", "Headpat"])
        self.c._on_size_param_changed(first, {"dir": "shrink", "unit": "pct", "speed": 500})
        card = self.c._size_param(first)
        self.assertEqual((card["dir"], card["unit"], card["speed"]), ("shrink", "pct", 100.0))
        self.c._on_size_param_added("param", "Kiss", "Bool", 1)
        self.assertEqual([p["param"] for p in self.c.size_params], ["Stomp", "Kiss", "Headpat"])
        self.c._on_size_param_removed(second)
        saved = self.c.config.config["size_params"]
        self.assertEqual([p["param"] for p in saved], ["Kiss", "Headpat"])
        self.assertNotIn("id", saved[0])
        self.assertEqual(self.osc.watched, {"Kiss", "Headpat", GESTURE_LEFT,
                                            GESTURE_RIGHT, GROUNDED})

    def test_a_new_card_opens_the_list_and_a_click_fills_it(self):
        self.make(size_params=[])
        self.c._on_size_param_added("param", "", "", -1)
        pid = self.c.size_params[0]["id"]
        self.assertTrue(self.window.picker_open)
        self.window._on_param_picked("Contacts/Headpat", "Float")
        self.assertEqual(self.c.size_params[0]["param"], "Contacts/Headpat")
        self.assertEqual(self.c.size_params[0]["type"], "Float")
        self.assertFalse(self.window.picker_open)           # picked: closed again
        self.assertIn(pid, self.window.size_board.cards)

    def test_the_list_shows_the_avatars_parameters(self):
        self.make(size_params=[])
        self.osc.params = {"B": ("Bool", True), "a": ("Float", 0.5)}
        self.connect()
        self.window.open_picker("")
        for _ in range(50):
            QTest.qWait(10)
            if self.window.picker.names():
                break
        self.assertEqual(sorted(self.window.picker.names()), ["B", "a"])
        self.window._on_param_picked("a", "Float")          # no card picking: a new one
        self.assertEqual([p["param"] for p in self.c.size_params], ["a"])
        self.window.close_picker()

    # --- when the list shows (Blise: only with Settings, or while picking) ------
    def test_the_list_is_closed_at_first(self):
        self.make()
        self.assertFalse(self.window.picker_open)

    def test_the_list_shows_with_settings_and_goes_with_them(self):
        self.make()
        self.window.settings_btn.click()
        self.assertTrue(self.window.picker_open)
        self.window.settings_btn.click()
        self.assertFalse(self.window.picker_open)

    def test_a_pick_while_settings_are_open_keeps_the_list(self):
        self.make(size_params=[dict(GROW_CARD)], settings_open=True)
        pid = self.c.size_params[0]["id"]
        self.assertTrue(self.window.picker_open)
        self.window.open_picker(pid)
        self.window._on_param_picked("Other", "Bool")
        self.assertEqual(self.c.size_params[0]["param"], "Other")
        self.assertTrue(self.window.picker_open)           # Settings are still open

    def test_close_puts_it_away_until_settings_open_again(self):
        self.make(settings_open=True)
        self.window._on_picker_close()
        self.assertFalse(self.window.picker_open)
        self.window.settings_btn.click()                   # Settings shut …
        self.window.settings_btn.click()                   # … and opened again
        self.assertTrue(self.window.picker_open)

    def test_the_filter_is_kept_while_the_app_runs(self):
        self.make(size_params=[dict(GROW_CARD)])
        pid = self.c.size_params[0]["id"]
        self.window.open_picker(pid)
        self.window.picker.filter.setText("contact")
        self.window.close_picker()
        self.window.open_picker(pid)
        self.assertEqual(self.window.picker.filter.text(), "contact")
        self.assertNotIn("contact", str(self.c.config.config))   # not saved

    def test_opening_and_closing_the_list_gives_the_width_back(self):
        from PySide6.QtCore import Qt
        self.make(size_params=[dict(GROW_CARD)])
        self.window.setAttribute(Qt.WA_DontShowOnScreen, True)
        self.window.resize(740, 800)
        self.window.show()
        QTest.qWait(20)
        width = self.window.width()
        self.window.open_picker(self.c.size_params[0]["id"])
        QTest.qWait(20)
        opened = self.window.width()
        list_w = self.window.picker.width()
        # wider by the list — never by it twice (Qt may already have stretched
        # the window to its new minimum when the list appeared)
        self.assertGreaterEqual(opened, width + list_w - 1)
        self.assertLess(opened, width + 2 * list_w)
        self.window.close_picker()
        QTest.qWait(20)
        self.assertLess(self.window.width(), opened)

    # --- a card's name, typed --------------------------------------------------
    def test_a_typed_name_is_the_cards_parameter(self):
        self.make(size_params=[dict(GROW_CARD)])
        pid = self.c.size_params[0]["id"]
        field = self.window.size_board.cards[pid].name
        field.edit.setText("Contacts/Headpat_2")
        field.edit.editingFinished.emit()
        self.assertEqual(self.c.size_params[0]["param"], "Contacts/Headpat_2")
        self.assertIn("Contacts/Headpat_2", self.osc.watched)
        card = self.window.size_board.cards[pid]            # rebuilt with it
        self.assertEqual(card.name.edit.text(), "Contacts/Headpat_2")

    def test_the_toggle_is_a_drawn_icon(self):
        self.make(size_params=[dict(GROW_CARD)])
        card = next(iter(self.window.size_board.cards.values()))
        self.assertEqual(card.on_btn.text(), "")
        self.assertFalse(card.on_btn.icon().isNull())

    # --- the random card -----------------------------------------------------
    def rand(self, go="instant", lo=100.0, hi=400.0, param="Boop"):
        return {"kind": "random", "param": param, "type": "Bool", "min": lo, "max": hi,
                "go": go, "on": True}

    def test_a_roll_goes_to_a_height_in_its_range(self):
        self.ready([self.rand()])
        pid = self.c.size_params[0]["id"]
        for _ in range(5):
            self.c._roll(pid, "test")
        self.assertEqual(len(self.osc.sent), 5)
        for cm in self.osc.sent:
            self.assertTrue(100.0 <= cm <= 400.0, cm)

    def test_a_timed_roll_starts_the_transition_there(self):
        self.ready([self.rand(go="timed")])
        self.c._roll(self.c.size_params[0]["id"], "test")
        t = self.c.transition
        self.assertIsNotNone(t)
        self.assertTrue(100.0 <= t.end_cm <= 400.0)
        self.assertEqual(self.window.transition_inputs()[0], t.end_cm)

    def test_a_select_roll_only_sets_the_target(self):
        self.ready([self.rand(go="select")])
        self.c._roll(self.c.size_params[0]["id"], "test")
        self.assertEqual(self.osc.sent, [])
        self.assertTrue(100.0 <= self.window.transition_inputs()[0] <= 400.0)

    def test_its_parameter_rolls_when_it_turns_on(self):
        self.ready([self.rand()])
        self.param("Boop", True)                 # the first value: an avatar loading
        self.assertEqual(self.osc.sent, [])
        self.param("Boop", False)
        self.param("Boop", True)
        self.assertEqual(len(self.osc.sent), 1)
        self.param("Boop", True)                 # still on: no second roll
        self.assertEqual(len(self.osc.sent), 1)

    def test_the_menus_random_height_rolls_the_first_random_card(self):
        self.ready([dict(GROW_CARD), self.rand()])
        self.tap(MENU_ROLL)
        self.assertEqual(len(self.osc.sent), 1)

    # --- the menu's Own height ---------------------------------------------------
    def test_the_menus_own_height(self):
        self.ready(metres=0.85)
        self.c._on_scale_factor(0.5, self.clock.t)
        self.tap(MENU_RESET)
        self.assertEqual(self.osc.sent, [170.0])

    # --- the VR gesture ------------------------------------------------------------
    def test_both_fists_and_a_jump_go_back_to_the_own_height(self):
        self.ready(metres=0.85)
        self.c._on_scale_factor(0.5, self.clock.t)
        self.param(GROUNDED, True)
        self.param(GESTURE_LEFT, 1)
        self.param(GESTURE_RIGHT, 1)
        self.param(GROUNDED, False)                        # the jump
        self.assertEqual(self.osc.sent, [170.0])
        self.param(GROUNDED, True)
        self.clock.t += 0.5
        self.param(GROUNDED, False)                        # again at once: cooled down
        self.assertEqual(len(self.osc.sent), 1)

    def test_a_jump_without_both_fists_does_nothing(self):
        self.ready(metres=0.85)
        self.c._on_scale_factor(0.5, self.clock.t)
        self.param(GROUNDED, True)
        self.param(GESTURE_LEFT, 1)
        self.param(GESTURE_RIGHT, 2)
        self.param(GROUNDED, False)
        self.assertEqual(self.osc.sent, [])

    def test_the_gesture_can_be_another_and_held(self):
        self.ready(metres=0.85, vr_reset_left=7, vr_reset_right=7, vr_reset_then="hold")
        self.c._on_scale_factor(0.5, self.clock.t)
        self.param(GESTURE_LEFT, 7)
        self.param(GESTURE_RIGHT, 7)
        self.assertTrue(self.c._vr_hold_timer.isActive())
        QTest.qWait(int(VR_RESET_HOLD_S * 1000) + 150)
        self.assertEqual(self.osc.sent, [170.0])
        QTest.qWait(int(VR_RESET_HOLD_S * 1000) + 150)    # still held: once
        self.assertEqual(len(self.osc.sent), 1)

    def test_the_gesture_settings_are_saved(self):
        self.make()
        self.c._on_vr_reset({"left": 3, "right": 4, "then": "hold"})
        self.assertEqual((self.c.vr_left, self.c.vr_right, self.c.vr_then), (3, 4, "hold"))
        cfg = self.c.config.config
        self.assertEqual((cfg["vr_reset_left"], cfg["vr_reset_right"], cfg["vr_reset_then"]),
                         (3, 4, "hold"))
        self.c._on_vr_reset({"on": False})
        self.assertNotIn(GROUNDED, self.osc.watched)

    # --- the saved heights' keys ------------------------------------------------------
    def test_numpad_keys_pick_saved_heights(self):
        self.make(hotkeys_enabled=True, profiles={"profile1": 140.0, "profile9": 2000.0})
        self.connect()
        self.report(1.7)
        self.c.keys.taps.add(DEFAULT_SLOT_KEYS[8])          # numpad 9, tapped between polls
        self.c._hotkey_tick()
        self.assertEqual(self.window.transition_inputs()[0], 2000.0)
        self.assertEqual(self.osc.sent, [])                 # "select": only the target
        self.c._on_slot_action(1, "instant")
        self.c.keys.taps.add(DEFAULT_SLOT_KEYS[0])
        self.c._hotkey_tick()
        self.assertEqual(self.osc.sent, [140.0])
        self.c.keys.taps.add(DEFAULT_SLOT_KEYS[4])          # slot 5 is empty
        self.c._hotkey_tick()
        self.assertIn("empty", self.window.status_msg.text())

    def test_a_saved_heights_key_can_be_changed_but_not_doubled(self):
        self.make()
        self.c._on_hotkey_captured("slot3", 0x33, 0)        # 3 on the main row
        self.assertEqual(self.c.hotkey_slots[2], Hotkey(0x33))
        self.assertEqual(self.c.config.config["hotkey_slots"][2], {"vk": 0x33, "mods": 0})
        self.c._on_hotkey_captured("slot4", 0x33, 0)        # taken by slot 3
        self.assertEqual(self.c.hotkey_slots[3], DEFAULT_SLOT_KEYS[3])
        self.assertIn("already", self.window.status_msg.text())


if __name__ == "__main__":
    unittest.main()
