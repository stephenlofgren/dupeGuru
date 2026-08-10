"""Duration-sorted sliding window for video pair candidates.

Avoids O(N^2) enumeration when a duration tolerance is set: only pairs whose
durations differ by at most ``tolerance`` are yielded.
"""

from itertools import combinations


def duration_window_pair_count(files, tolerance_seconds):
    """Return how many pairs ``iter_duration_window_pairs`` would yield."""
    n = len(files)
    if n < 2:
        return 0
    if tolerance_seconds <= 0:
        return n * (n - 1) // 2
    ordered = sorted(files, key=lambda f: f.duration)
    count = 0
    right = 0
    for left in range(n):
        if right < left + 1:
            right = left + 1
        while right < n and ordered[right].duration - ordered[left].duration <= tolerance_seconds:
            right += 1
        count += right - left - 1
    return count


def iter_duration_window_pairs(files, tolerance_seconds):
    """Yield (first, second) pairs within duration tolerance.

    Files are compared in duration order. Complexity is O(N + P) where P is the
    number of pairs inside the window (not O(N^2) when durations are spread out).

    If ``tolerance_seconds <= 0``, falls back to all combinations (legacy behavior
    when duration filtering is disabled).
    """
    if len(files) < 2:
        return
    if tolerance_seconds <= 0:
        yield from combinations(files, 2)
        return
    ordered = sorted(files, key=lambda f: f.duration)
    n = len(ordered)
    right = 0
    for left in range(n):
        if right < left + 1:
            right = left + 1
        while right < n and ordered[right].duration - ordered[left].duration <= tolerance_seconds:
            right += 1
        for mid in range(left + 1, right):
            yield ordered[left], ordered[mid]
