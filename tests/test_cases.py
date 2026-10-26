from datetime import timedelta

from warden.modlog import Action, CaseStore


async def test_case_numbers_are_per_guild(db):
    store = CaseStore(db)
    a1 = await store.create(1, Action.WARN, target_id=10, moderator_id=99, reason="spam")
    a2 = await store.create(1, Action.TIMEOUT, 10, 99, None, timedelta(minutes=10))
    b1 = await store.create(2, Action.BAN, 10, 99, "raid")

    assert (a1.case_number, a2.case_number, b1.case_number) == (1, 2, 1)
    assert a2.duration == timedelta(minutes=10)
    assert a1.duration is None


async def test_history_and_counts(db):
    store = CaseStore(db)
    for _ in range(3):
        await store.create(1, Action.WARN, 10, 99, None)
    await store.create(1, Action.KICK, 10, 99, None)
    await store.create(1, Action.WARN, 11, 99, None)

    history = await store.for_member(1, 10)
    assert [c.case_number for c in history] == [4, 3, 2, 1]
    assert await store.count(1, 10, Action.WARN) == 3
    assert await store.count(1, 11, Action.WARN) == 1
