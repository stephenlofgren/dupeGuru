from hscommon.testutil import eq_

from core.ve.duration_window import duration_window_pair_count, iter_duration_window_pairs


class _FakeVideo:
    def __init__(self, name, duration, is_ref=False):
        self.name = name
        self.duration = duration
        self.is_ref = is_ref


def test_duration_window_only_pairs_within_tolerance():
    files = [
        _FakeVideo("a", 10.0),
        _FakeVideo("b", 10.5),
        _FakeVideo("c", 20.0),
        _FakeVideo("d", 20.4),
        _FakeVideo("e", 100.0),
    ]
    pairs = {(f.name, s.name) for f, s in iter_duration_window_pairs(files, 1.0)}
    eq_(pairs, {("a", "b"), ("c", "d")})
    eq_(duration_window_pair_count(files, 1.0), 2)


def test_duration_window_zero_tolerance_means_all_pairs():
    files = [_FakeVideo("a", 1.0), _FakeVideo("b", 50.0), _FakeVideo("c", 100.0)]
    pairs = list(iter_duration_window_pairs(files, 0))
    eq_(len(pairs), 3)
    eq_(duration_window_pair_count(files, 0), 3)


def test_duration_window_count_matches_iterator():
    files = [_FakeVideo(str(i), float(i)) for i in range(50)]
    for tol in (0.5, 2.0, 10.0, 100.0):
        eq_(duration_window_pair_count(files, tol), len(list(iter_duration_window_pairs(files, tol))))
