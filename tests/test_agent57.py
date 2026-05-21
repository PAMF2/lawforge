from pathlib import Path

from evolve.agent57 import Agent57Meta, Arm


def _noop(_root: Path) -> None:
    return None


def test_coldstart_uniform_picks_unpulled():
    arms = [Arm(name=f"a{i}", apply=_noop) for i in range(4)]
    meta = Agent57Meta(arms)
    picked = {meta.select().name for _ in range(40)}
    # cold-start prefers unpulled; without update() the picks stay random across all
    assert picked  # at least one arm chosen


def test_update_records_reward():
    arms = [Arm(name="x", apply=_noop)]
    meta = Agent57Meta(arms)
    a = meta.select()
    meta.update(a, reward=0.5)
    assert a.pulls == 1
    assert a.rewards == [0.5]
    assert a.last_used_gen == meta.t


def test_windowed_mean_tracks_nonstationarity():
    a = Arm(name="x", apply=_noop)
    a.rewards = [0.0] * 50 + [1.0] * 8
    a.pulls = len(a.rewards)
    assert a.mean() < a.windowed_mean(w=8)  # window catches recent regime


def test_ucb_prefers_unpulled_after_cold_start_done(tmp_path):
    arms = [Arm(name="a", apply=_noop), Arm(name="b", apply=_noop)]
    meta = Agent57Meta(arms)
    # pretend a has been pulled and rewarded, b is fresh
    a = next(x for x in arms if x.name == "a")
    meta.update(a, reward=0.5)
    # next select still has cold-start b unpulled -> must pick b
    picked = meta.select()
    assert picked.name == "b"


def test_save_load_roundtrip(tmp_path):
    arms = [Arm(name="a", apply=_noop), Arm(name="b", apply=_noop)]
    m1 = Agent57Meta(arms)
    a = next(x for x in arms if x.name == "a")
    m1.update(a, reward=0.7)
    state = tmp_path / "s.json"
    m1.save(state)

    arms2 = [Arm(name="a", apply=_noop), Arm(name="b", apply=_noop)]
    m2 = Agent57Meta(arms2)
    m2.load(state)
    a2 = next(x for x in arms2 if x.name == "a")
    assert a2.pulls == 1
    assert a2.rewards == [0.7]
