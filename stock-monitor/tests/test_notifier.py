import asyncio

import pytest

from notifier import Notifier


@pytest.mark.asyncio
async def test_subscribe_and_publish():
    notifier = Notifier()
    queue = await notifier.subscribe()
    await notifier.publish({"title": "x"})
    item = await asyncio.wait_for(queue.get(), timeout=0.5)
    assert item == {"title": "x"}


@pytest.mark.asyncio
async def test_unsubscribe_stops_receiving():
    notifier = Notifier()
    queue = await notifier.subscribe()
    await notifier.unsubscribe(queue)
    await notifier.publish({"title": "x"})
    assert notifier.subscriber_count() == 0


@pytest.mark.asyncio
async def test_multiple_subscribers_all_receive():
    notifier = Notifier()
    q1 = await notifier.subscribe()
    q2 = await notifier.subscribe()
    await notifier.publish({"a": 1})
    assert (await asyncio.wait_for(q1.get(), 0.5)) == {"a": 1}
    assert (await asyncio.wait_for(q2.get(), 0.5)) == {"a": 1}
