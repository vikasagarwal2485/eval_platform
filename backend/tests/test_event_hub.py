import asyncio

from app.core.events import EventHub, agent_channel


def test_run_channel_backward_compatible_with_bare_int():
    hub = EventHub()
    hub.begin(1)
    hub.publish(1, "run_started", {})
    assert hub.is_active(1) is True
    assert hub.current(1) == {}


def test_agent_channel_is_namespaced_and_never_collides_with_a_run_of_the_same_id():
    hub = EventHub()
    hub.begin(1)
    hub.publish(1, "run_started", {"x": "run"})
    hub.publish(agent_channel(1), "turn_started", {"x": "agent"})
    assert [e.type for e in hub._streams["run:1"].events] == ["run_started"]
    assert [e.type for e in hub._streams["agent:1"].events] == ["turn_started"]


def test_subscribe_open_delivers_backlog_then_stops_when_the_consumer_stops():
    hub = EventHub()
    hub.publish(agent_channel(5), "turn_started", {"turn": 1})
    hub.publish(agent_channel(5), "turn_finished", {"turn": 1})

    async def go():
        seen = []
        async for ev in hub.subscribe_open(agent_channel(5)):
            seen.append(ev.type)
            if len(seen) == 2:
                break  # the consumer stops; subscribe_open itself never emits a terminal event
        return seen

    assert asyncio.run(go()) == ["turn_started", "turn_finished"]


def test_subscribe_open_delivers_live_events_published_after_subscribing():
    hub = EventHub()

    async def go():
        seen = []

        async def consume():
            async for ev in hub.subscribe_open(agent_channel(7)):
                seen.append(ev.type)
                if len(seen) == 1:
                    return

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)  # let the subscriber register before we publish
        hub.publish(agent_channel(7), "evaluation_finished", {})
        await task
        return seen

    assert asyncio.run(go()) == ["evaluation_finished"]
