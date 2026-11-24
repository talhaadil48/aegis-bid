"""Small bounded request groups, with cancellation-safe completion after SQL commit."""

import asyncio
from weakref import WeakKeyDictionary

_loops = WeakKeyDictionary()


async def grouped(name, key, item, execute, maximum=512, capacity=8192, collect_delay=0.002):
    loop = asyncio.get_running_loop()
    groups = _loops.setdefault(loop, {})
    group_key = (name, str(key))
    if group_key not in groups:
        groups[group_key] = {"pending": [], "running": False}
    group = groups[group_key]
    if len(group["pending"]) >= capacity:
        raise OverflowError("API intake buffer full; retry the same request UUID")
    future = loop.create_future()
    group["pending"].append((item, future))

    async def drain():
        try:
            while group["pending"]:
                await asyncio.sleep(collect_delay)
                batch = group["pending"][:maximum]
                del group["pending"][:maximum]
                try:
                    rows = await asyncio.to_thread(execute, key, [item for item, _ in batch])
                    if len(rows) != len(batch):
                        raise RuntimeError("Batch result count mismatch")
                except Exception as error:  # noqa: BLE001 -- propagate the original failure to every affected waiter
                    rows = [error] * len(batch)
                for (_, waiter), result in zip(batch, rows, strict=True):
                    if waiter.done():
                        continue
                    if isinstance(result, Exception):
                        waiter.set_exception(result)
                    else:
                        waiter.set_result(result)
        finally:
            group["running"] = False
            if not group["pending"]:
                groups.pop(group_key, None)

    if not group["running"]:
        group["running"] = True
        group["task"] = loop.create_task(drain())
    # A disconnect cannot cancel a group containing other admitted requests.
    return await asyncio.shield(future)
