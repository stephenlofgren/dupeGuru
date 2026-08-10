from hscommon.jobprogress import job
from hscommon.trans import tr

from core.engine import Match
from core.ve.duration_window import duration_window_pair_count, iter_duration_window_pairs


def _duration_match_percentage(first_duration, second_duration):
    max_duration = max(first_duration, second_duration, 0.001)
    delta = abs(first_duration - second_duration)
    return max(0, 100 - int((delta / max_duration) * 100))


def getmatches(files, threshold, duration_tolerance_seconds, j=job.nulljob):
    j = j.start_subjob([2, 8])
    for f in j.iter_with_progress(files, tr("Read duration of %d/%d videos")):
        f.duration  # force lazy ffprobe read

    files = [f for f in files if f.duration > 0]
    matches = []
    pair_count = duration_window_pair_count(files, duration_tolerance_seconds)
    for first, second in j.iter_with_progress(
        iter_duration_window_pairs(files, duration_tolerance_seconds),
        tr("Compared %d/%d video pairs"),
        count=max(1, pair_count),
        every=100,
    ):
        if first.is_ref and second.is_ref:
            continue
        percentage = _duration_match_percentage(first.duration, second.duration)
        if percentage >= threshold:
            matches.append(Match(first, second, percentage))
    return matches
