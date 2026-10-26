from warden.levels import LevelStore, level_for, progress_for, reward_roles_for, xp_to_next


def test_curve():
    assert xp_to_next(0) == 100
    assert level_for(0) == 0
    assert level_for(99) == 0
    assert level_for(100) == 1
    assert level_for(100 + 155) == 2
    p = progress_for(130)
    assert (p.level, p.xp_into_level, p.xp_needed) == (1, 30, 155)


async def test_store_rank_and_top(db):
    store = LevelStore(db)
    await store.add_xp(1, 10, 50)
    await store.add_xp(1, 11, 300)
    await store.add_xp(1, 12, 120)
    await store.add_xp(2, 10, 999)

    assert await store.rank(1, 11) == 1
    assert await store.rank(1, 10) == 3
    assert await store.rank(1, 99) is None
    assert await store.top(1, limit=2) == [(11, 300), (12, 120)]
    assert await store.count(1) == 3

    old, new = await store.add_xp(1, 10, -500)
    assert (old, new) == (50, 0)


async def test_rewards(db):
    store = LevelStore(db)
    await store.add_reward(1, 5, 500)
    await store.add_reward(1, 10, 1000)
    await store.add_reward(1, 10, 1001)
    await store.add_reward(1, 5, 500)  # duplicate ignored
    rewards = await store.rewards(1)
    assert rewards == [(5, 500), (10, 1000), (10, 1001)]

    assert reward_roles_for(4, rewards, stack=True) == set()
    assert reward_roles_for(7, rewards, stack=True) == {500}
    assert reward_roles_for(12, rewards, stack=True) == {500, 1000, 1001}
    assert reward_roles_for(12, rewards, stack=False) == {1000, 1001}

    assert await store.remove_reward(1, 10, 1001) is True
    assert await store.remove_reward(1, 10, 1001) is False
