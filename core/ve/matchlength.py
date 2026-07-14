from itertools import combinations

from hscommon.jobprogress import job
from hscommon.trans import tr

from core.engine import Match


def _duration_match_percentage(first_duration, second_duration):
    max_duration = max(first_duration, second_duration, 0.001)
    delta = abs(first_duration - second_duration)
    return max(0, 100 - int((delta / max_duration) * 100))


def getmatches(files, threshold, duration_tolerance_seconds, j=job.nulljob):
    j = j.start_subjob([2, 8])
    for f in j.iter_with_progress(files, tr("Read duration of %d/%d videos")):
        f.duration  # force lazy ffprobe read

    matches = []
    pair_count = len(files) * (len(files) - 1) // 2
    for first, second in j.iter_with_progress(
        combinations(files, 2),
        tr("Compared %d/%d video pairs"),
        count=pair_count,
        every=100,
    ):
        if first.is_ref and second.is_ref:
            continue
        delta = abs(first.duration - second.duration)
        if duration_tolerance_seconds > 0 and delta > duration_tolerance_seconds:
            continue
        percentage = _duration_match_percentage(first.duration, second.duration)
        if percentage >= threshold:
            matches.append(Match(first, second, percentage))
    return matches
