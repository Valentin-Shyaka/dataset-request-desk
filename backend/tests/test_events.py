import asyncio

from app.events import Broker, format_sse
from app.models import Role


def test_format_sse():
    assert format_sse({"type": "request.created", "data": {"id": 1}}) == \
        'event: request.created\ndata: {"id": 1}\n\n'


def test_broker_delivers_events_published_from_worker_threads():
    async def scenario():
        broker = Broker()
        broker.bind_loop(asyncio.get_running_loop())
        queue = broker.subscribe()
        # our endpoints are sync, so FastAPI runs them in a threadpool; publish must be thread-safe
        await asyncio.to_thread(broker.publish, {"type": "request.created", "data": {"id": 7}})
        event = await asyncio.wait_for(queue.get(), timeout=1)
        broker.unsubscribe(queue)
        return event

    assert asyncio.run(scenario()) == {"type": "request.created", "data": {"id": 7}}


def test_publish_without_loop_is_a_no_op():
    Broker().publish({"type": "x", "data": {}})  # must not raise (e.g. in tests, CLI)


def test_only_staff_can_subscribe(anon, login, make_user):
    assert anon.get("/api/events").status_code == 401
    assert login(make_user(Role.CLIENT)).get("/api/events").status_code == 403
