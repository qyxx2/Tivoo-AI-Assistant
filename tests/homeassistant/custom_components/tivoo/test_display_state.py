"""P6.6b0: pure display arbitration and screen power gate contracts."""

import asyncio

import pytest
from custom_components.tivoo.commands import TivooCommand
from custom_components.tivoo.display_state import (
    DisplayState,
    ExpressionCoordinator,
    ScreenPowerGate,
    build_expression_command,
)
from homeassistant.exceptions import HomeAssistantError


class RecordingAdapter:
    def __init__(self):
        self.commands = []
        self.fail_next = False

    async def async_execute(self, command):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("transport failed")
        self.commands.append(command)

    @property
    def displays(self):
        return [cmd for cmd in self.commands if cmd.name != "set_screen_power"]

    @property
    def powers(self):
        return [
            cmd.data["value"] for cmd in self.commands if cmd.name == "set_screen_power"
        ]


def expression(name):
    return build_expression_command(name)


def display_names(adapter):
    return [cmd.data["name"] for cmd in adapter.displays]


async def test_expression_command_matches_existing_service_registry():
    from custom_components.tivoo.services import PRESET_REGISTRY

    cmd = build_expression_command("fish")
    description, factory = PRESET_REGISTRY["fish"]
    frames, delays = factory()
    assert cmd == TivooCommand(
        name="set_expression",
        data={
            "name": "fish",
            "description": description,
            "frames": frames,
            "delays": delays,
        },
    )
    with pytest.raises(KeyError):
        build_expression_command("not-a-preset")


async def test_priority_and_generic_restore_without_pairwise_fallback():
    adapter = RecordingAdapter()
    coordinator = ExpressionCoordinator(adapter)
    await coordinator.async_start()
    coordinator.begin_generation("turn-1")
    assert coordinator.desired_state is DisplayState.IDLE
    assert len(adapter.displays) == 1

    commands = {
        DisplayState.FOLLOWUP_WAIT: "standby",
        DisplayState.AI_MOOD: "happy",
        DisplayState.EXPLICIT_CONTENT: "fish",
        DisplayState.ACTIVE_LISTENING: "smiley",
        DisplayState.THINKING: "thinking",
        DisplayState.TOOLUSE: "tooluse",
        DisplayState.SPEAKING: "music",
        DisplayState.WAKE_CONFIRMED: "question",
    }
    # Submit in ascending priority to test each layer taking precedence.
    for state, name in commands.items():
        await coordinator.async_set_intent(
            state,
            expression(name),
            generation=(None if state is DisplayState.EXPLICIT_CONTENT else "turn-1"),
        )
        assert coordinator.desired_state is state
        assert adapter.displays[-1].data["name"] == name

    # Clear winners one by one; the next still-valid intent must reappear.
    for state in reversed(tuple(commands)):
        await coordinator.async_clear_intent(
            state,
            generation=None if state is DisplayState.EXPLICIT_CONTENT else "turn-1",
        )
    assert coordinator.desired_state is DisplayState.IDLE
    # Random idle may equal the last restored command, so one send can dedupe.
    assert len(adapter.displays) >= 15
    await coordinator.async_shutdown()


async def test_generation_replacement_rejects_stale_set_clear_and_end():
    adapter = RecordingAdapter()
    coordinator = ExpressionCoordinator(adapter)
    await coordinator.async_start()
    await coordinator.async_set_intent(
        DisplayState.EXPLICIT_CONTENT, expression("fish")
    )
    coordinator.begin_generation("old")
    await coordinator.async_set_intent(
        DisplayState.THINKING, expression("thinking"), generation="old"
    )
    coordinator.begin_generation("new")
    await coordinator.async_set_intent(
        DisplayState.SPEAKING, expression("music"), generation="new"
    )
    before = len(adapter.displays)
    await coordinator.async_set_intent(
        DisplayState.WAKE_CONFIRMED, expression("question"), generation="old"
    )
    await coordinator.async_clear_intent(DisplayState.SPEAKING, generation="old")
    await coordinator.async_end_generation("old")
    assert coordinator.active_generation == "new"
    assert coordinator.desired_state is DisplayState.SPEAKING
    assert len(adapter.displays) == before
    await coordinator.async_end_generation("new")
    assert coordinator.active_generation is None
    assert coordinator.desired_state is DisplayState.EXPLICIT_CONTENT
    await coordinator.async_clear_intent(DisplayState.EXPLICIT_CONTENT)
    assert coordinator.desired_state is DisplayState.IDLE
    await coordinator.async_shutdown()


async def test_stale_ttl_callback_cannot_remove_new_generation_intent():
    adapter = RecordingAdapter()
    coordinator = ExpressionCoordinator(adapter)
    await coordinator.async_start()
    coordinator.begin_generation("old")
    await coordinator.async_set_intent(
        DisplayState.SPEAKING, expression("music"), generation="old", ttl=0.02
    )
    coordinator.begin_generation("new")
    await coordinator.async_set_intent(
        DisplayState.SPEAKING, expression("music"), generation="new"
    )
    await asyncio.sleep(0.05)
    assert coordinator.desired_state is DisplayState.SPEAKING
    assert coordinator.active_generation == "new"
    await coordinator.async_shutdown()


async def test_ttl_expires_while_mood_is_hidden_and_does_not_replay():
    adapter = RecordingAdapter()
    coordinator = ExpressionCoordinator(adapter)
    await coordinator.async_start()
    coordinator.begin_generation("a")
    await coordinator.async_set_intent(
        DisplayState.AI_MOOD, expression("happy"), generation="a", ttl=0.02
    )
    await coordinator.async_set_intent(
        DisplayState.SPEAKING, expression("music"), generation="a"
    )
    await asyncio.sleep(0.05)
    count = display_names(adapter).count("happy")
    await coordinator.async_clear_intent(DisplayState.SPEAKING, generation="a")
    assert coordinator.desired_state is DisplayState.IDLE
    assert display_names(adapter).count("happy") == count
    await coordinator.async_shutdown()


async def test_b4_mood_priority_and_session_scope():
    adapter = RecordingAdapter()
    coordinator = ExpressionCoordinator(adapter)
    await coordinator.async_start()

    with pytest.raises(HomeAssistantError, match="active voice generation"):
        await coordinator.async_set_mood("happy")

    coordinator.begin_generation("mood-turn")
    await coordinator.async_set_intent(
        DisplayState.FOLLOWUP_WAIT, expression("standby"), generation="mood-turn"
    )
    await coordinator.async_set_mood("happy")
    assert coordinator.desired_state is DisplayState.AI_MOOD
    assert coordinator.desired_command.data["name"] == "happy"

    for state, preset in (
        (DisplayState.ACTIVE_LISTENING, "standby"),
        (DisplayState.THINKING, "thinking"),
        (DisplayState.TOOLUSE, "tooluse"),
        (DisplayState.SPEAKING, "music"),
    ):
        await coordinator.async_set_intent(
            state, expression(preset), generation="mood-turn"
        )
        assert coordinator.desired_state is state
        await coordinator.async_clear_intent(state, generation="mood-turn")
        assert coordinator.desired_state is DisplayState.AI_MOOD

    await coordinator.async_end_generation("mood-turn")
    assert coordinator.desired_state is DisplayState.IDLE
    await coordinator.async_shutdown()


async def test_b4_mood_ttl_keeps_running_while_hidden(monkeypatch):
    import custom_components.tivoo.display_state as module

    monkeypatch.setattr(module, "MOOD_TTL_SECONDS", 0.02)
    adapter = RecordingAdapter()
    coordinator = ExpressionCoordinator(adapter)
    await coordinator.async_start()
    coordinator.begin_generation("mood-turn")
    await coordinator.async_set_mood("happy")
    await coordinator.async_set_intent(
        DisplayState.SPEAKING, expression("music"), generation="mood-turn"
    )
    await asyncio.sleep(0.05)
    happy_count = display_names(adapter).count("happy")

    await coordinator.async_clear_intent(DisplayState.SPEAKING, generation="mood-turn")
    assert coordinator.desired_state is DisplayState.IDLE
    assert display_names(adapter).count("happy") == happy_count
    await coordinator.async_shutdown()


async def test_same_state_ttl_replacement_is_not_cleared_by_older_expiry():
    adapter = RecordingAdapter()
    coordinator = ExpressionCoordinator(adapter)
    await coordinator.async_start()
    coordinator.begin_generation("a")
    await coordinator.async_set_intent(
        DisplayState.AI_MOOD, expression("happy"), generation="a", ttl=0.02
    )
    await asyncio.sleep(0.01)
    await coordinator.async_set_intent(
        DisplayState.AI_MOOD, expression("sad"), generation="a", ttl=0.08
    )
    await asyncio.sleep(0.03)
    assert coordinator.desired_command.data["name"] == "sad"
    await coordinator.async_shutdown()


async def test_idle_rotates_using_existing_pool_and_interval(monkeypatch):
    import custom_components.tivoo.display_state as module

    names = iter(("standby", "fish", "sun"))
    intervals = []
    monkeypatch.setattr(module.random, "choice", lambda choices: next(names))

    def interval(start, end):
        intervals.append((start, end))
        return 0.015

    monkeypatch.setattr(module.random, "uniform", interval)

    adapter = RecordingAdapter()
    coordinator = ExpressionCoordinator(adapter)
    await coordinator.async_start()
    await asyncio.sleep(0.04)
    assert display_names(adapter)[:3] == ["standby", "fish", "sun"]
    assert intervals and all(t == (30.0, 90.0) for t in intervals)
    await coordinator.async_shutdown()


async def test_gate_multiple_inhibits_and_idempotence():
    transitions = []

    async def on_change(is_on):
        transitions.append(is_on)

    gate = ScreenPowerGate(on_change)
    await gate.async_acquire("night")
    await gate.async_acquire("night")
    await gate.async_acquire("script")
    await gate.async_release("night")
    await gate.async_release("night")
    assert gate.is_on is False
    await gate.async_release("script")
    await gate.async_release("script")
    assert gate.is_on is True
    assert transitions == [False, True]
    await gate.async_shutdown()


async def test_gate_overlapping_temporary_wakes_preserve_inhibits():
    transitions = []

    async def on_change(is_on):
        transitions.append(is_on)

    gate = ScreenPowerGate(on_change)
    await gate.async_acquire("night")
    await gate.async_temporary_wake("alert-1", 0.02)
    await gate.async_temporary_wake("alert-2", 0.07)
    await asyncio.sleep(0.04)
    assert gate.is_on is True
    assert gate.inhibit_owners == frozenset({"night"})
    await asyncio.sleep(0.05)
    assert gate.is_on is False
    assert transitions == [False, True, False]
    await gate.async_shutdown()


async def test_off_updates_desired_but_never_writes_display_until_on():
    adapter = RecordingAdapter()
    coordinator = ExpressionCoordinator(adapter)
    await coordinator.async_start()
    await coordinator.async_acquire_screen_off("night")
    count = len(adapter.displays)
    coordinator.begin_generation("now")
    await coordinator.async_set_intent(
        DisplayState.THINKING, expression("thinking"), generation="now"
    )
    assert coordinator.desired_state is DisplayState.THINKING
    assert len(adapter.displays) == count
    assert adapter.powers == [False]
    await coordinator.async_release_screen_off("night")
    assert adapter.powers == [False, True]
    assert display_names(adapter)[-1] == "thinking"
    await coordinator.async_shutdown()


async def test_temporary_wake_facade_forces_redraw_and_returns_off():
    adapter = RecordingAdapter()
    coordinator = ExpressionCoordinator(adapter)
    await coordinator.async_start()
    await coordinator.async_acquire_screen_off("night")
    await coordinator.async_temporary_wake("alert", 0.02)
    assert adapter.powers == [False, True]
    assert adapter.displays[-1].data["name"] in {
        "standby",
        "smiley",
        "sleepy",
        "sun",
        "fish",
    }
    await asyncio.sleep(0.05)
    assert adapter.powers == [False, True, False]
    await coordinator.async_shutdown()


async def test_send_failure_preserves_unsent_desired_for_forced_retry():
    adapter = RecordingAdapter()
    coordinator = ExpressionCoordinator(adapter)
    await coordinator.async_start()
    earlier = coordinator.last_sent
    coordinator.begin_generation("a")
    adapter.fail_next = True
    with pytest.raises(RuntimeError, match="transport failed"):
        await coordinator.async_set_intent(
            DisplayState.THINKING, expression("thinking"), generation="a"
        )
    assert coordinator.desired_state is DisplayState.THINKING
    assert coordinator.last_sent is earlier
    await coordinator.async_force_recompute()
    assert coordinator.last_sent == coordinator.desired_command
    assert adapter.displays[-1].data["name"] == "thinking"
    await coordinator.async_shutdown()


async def test_force_recompute_reasserts_off_without_display():
    adapter = RecordingAdapter()
    coordinator = ExpressionCoordinator(adapter)
    await coordinator.async_start()
    await coordinator.async_acquire_screen_off("night")
    initial_display_count = len(adapter.displays)
    await coordinator.async_force_recompute()
    assert adapter.powers == [False, False]
    assert len(adapter.displays) == initial_display_count
    await coordinator.async_shutdown()


async def test_b1_facade_compatibility_screen_power_preserves_other_owners():
    adapter = RecordingAdapter()
    coordinator = ExpressionCoordinator(adapter)
    await coordinator.async_start()
    await coordinator.async_acquire_screen_off("night")
    await coordinator.async_set_screen_power(False)
    await coordinator.async_set_explicit(TivooCommand("show_text", {"value": "first"}))
    before = len(adapter.displays)
    await coordinator.async_set_screen_power(True)
    assert adapter.powers == [False]
    assert len(adapter.displays) == before
    assert coordinator.desired_state is DisplayState.EXPLICIT_CONTENT
    await coordinator.async_release_screen_off("night")
    assert adapter.powers == [False, True]
    assert adapter.displays[-1].data["value"] == "first"
    await coordinator.async_shutdown()


async def test_b1_spp_disconnect_invalidates_cache_and_reconnect_repaints():
    adapter = RecordingAdapter()
    coordinator = ExpressionCoordinator(adapter)
    await coordinator.async_start()
    explicit = TivooCommand("show_text", {"value": "persist"})
    await coordinator.async_set_explicit(explicit)
    await coordinator.async_on_spp_state("spp_disconnected")
    assert coordinator.last_sent is None
    await coordinator.async_set_explicit(TivooCommand("show_text", {"value": "new"}))
    assert adapter.displays[-1] == explicit
    await coordinator.async_on_spp_state("spp_connected")
    assert adapter.displays[-1].data["value"] == "new"
    await coordinator.async_acquire_screen_off("night")
    await coordinator.async_on_spp_state("spp_disconnected")
    count = len(adapter.displays)
    await coordinator.async_on_spp_state("spp_connected")
    assert adapter.powers[-1] is False
    assert len(adapter.displays) == count
    await coordinator.async_shutdown()


async def test_b1_screen_action_is_not_delayed_through_screen_off():
    from homeassistant.exceptions import HomeAssistantError

    adapter = RecordingAdapter()
    coordinator = ExpressionCoordinator(adapter)
    await coordinator.async_start()
    await coordinator.async_acquire_screen_off("night")
    with pytest.raises(HomeAssistantError, match="screen is off"):
        await coordinator.async_execute_screen_action(
            TivooCommand("start_countdown", {"countdown": "00:30"})
        )
    await coordinator.async_release_screen_off("night")
    assert not any(cmd.name == "start_countdown" for cmd in adapter.commands)
    await coordinator.async_execute_screen_action(
        TivooCommand("start_countdown", {"countdown": "00:30"})
    )
    assert adapter.commands[-1].name == "start_countdown"
    await coordinator.async_shutdown()


async def test_b1_repeated_explicit_command_replays_while_visible():
    adapter = RecordingAdapter()
    coordinator = ExpressionCoordinator(adapter)
    await coordinator.async_start()
    command = TivooCommand("show_text", {"value": "repeat"})
    await coordinator.async_set_explicit(command)
    count = len(adapter.displays)
    await coordinator.async_set_explicit(command)
    assert adapter.displays[-1] == command
    assert len(adapter.displays) == count + 1
    await coordinator.async_shutdown()


async def test_voice_candidate_hold_probability_cooldown_and_stale_timer(monkeypatch):
    import custom_components.tivoo.display_state as module

    monkeypatch.setattr(module, "CANDIDATE_HOLD_SECONDS", 0.02, raising=False)
    monkeypatch.setattr(module, "CANDIDATE_COOLDOWN_SECONDS", 0.12, raising=False)
    monkeypatch.setattr(module.random, "random", lambda: 0.8)
    adapter = RecordingAdapter()
    display = ExpressionCoordinator(adapter)
    await display.async_start()
    display.begin_generation("a")
    display.begin_candidate("a")
    await asyncio.sleep(0.01)
    display.end_candidate("a")
    await asyncio.sleep(0.03)
    assert display.desired_state is DisplayState.IDLE  # short noise

    display.begin_candidate("a")
    await asyncio.sleep(0.04)
    assert display.desired_state is DisplayState.IDLE  # random miss
    display.end_candidate("a")
    monkeypatch.setattr(module.random, "random", lambda: 0.1)
    display.begin_candidate("a")
    await asyncio.sleep(0.04)
    assert display.desired_state is DisplayState.ACTIVE_LISTENING
    display.end_candidate("a")
    await asyncio.sleep(0.01)
    assert display.desired_state is DisplayState.IDLE
    display.begin_candidate("a")
    await asyncio.sleep(0.04)
    assert display.desired_state is DisplayState.IDLE  # 10s cooldown
    display.end_candidate("a")

    display.begin_generation("b")
    display.begin_candidate("b")
    display.begin_generation("c")
    await asyncio.sleep(0.04)
    assert display.active_generation == "c"
    assert display.desired_state is DisplayState.IDLE
    await display.async_shutdown()
