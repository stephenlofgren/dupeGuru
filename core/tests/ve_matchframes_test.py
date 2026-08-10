from pathlib import Path

from hscommon.testutil import eq_

from core.ve import matchframes


class _FakeVideo:
    def __init__(self, path, duration, is_ref=False):
        self.path = Path(path)
        self.name = self.path.name
        self.duration = duration
        self.is_ref = is_ref


def test_cannot_reach_threshold_after_first_low_score():
    # 5 samples, threshold 80: first score 0 => max average 80 exactly, still reachable
    assert not matchframes._cannot_reach_threshold([0], 5, 80)
    # first score 0 with threshold 81 => max 80 < 81
    assert matchframes._cannot_reach_threshold([0], 5, 81)
    # two mediocre scores cannot recover for high threshold
    assert matchframes._cannot_reach_threshold([50, 50], 5, 90)


def test_frame_cache_extracts_each_sample_once(monkeypatch, tmpdir):
    calls = []

    def fake_extract(video_path, output_path, timestamp_seconds, ffmpeg_path):
        calls.append((str(video_path), round(timestamp_seconds, 3)))
        Path(output_path).write_bytes(b"fake")
        return True

    monkeypatch.setattr(matchframes, "_extract_frame", fake_extract)
    cache = matchframes._FrameCache(str(tmpdir), "ffmpeg")
    video = _FakeVideo("/videos/a.mp4", duration=100.0)

    first = cache.get(video, 0, 0.25)
    second = cache.get(video, 0, 0.25)
    other = cache.get(video, 1, 0.5)

    eq_(first, second)
    assert first != other
    eq_(len(calls), 2)
    eq_(calls[0], ("/videos/a.mp4", 25.0))
    eq_(calls[1], ("/videos/a.mp4", 50.0))


def test_getmatches_reuses_frames_across_pairs_and_exits_early(monkeypatch):
    extract_calls = []
    compare_calls = []

    def fake_ensure(ffmpeg_path, ffprobe_path):
        return None

    def fake_extract(video_path, output_path, timestamp_seconds, ffmpeg_path):
        extract_calls.append(str(video_path))
        Path(output_path).write_bytes(b"fake")
        return True

    def fake_compare(first_image, second_image, threshold, match_scaled):
        compare_calls.append((str(first_image), str(second_image)))
        # Always fail hard so early-exit triggers after first sample.
        return 0

    monkeypatch.setattr(matchframes, "_ensure_ffmpeg_available", fake_ensure)
    monkeypatch.setattr(matchframes, "_extract_frame", fake_extract)
    monkeypatch.setattr(matchframes, "_frame_match_percentage", fake_compare)

    files = [
        _FakeVideo("/videos/a.mp4", 100.0),
        _FakeVideo("/videos/b.mp4", 100.0),
        _FakeVideo("/videos/c.mp4", 100.0),
    ]
    # 3 files => pairs (a,b), (a,c), (b,c). sample_count=5, threshold=90
    # Early exit after first sample (score 0) => at most 1 compare per pair.
    matches = matchframes.getmatches(
        files,
        threshold=90,
        sample_count=5,
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
        duration_tolerance_seconds=1.0,
        match_scaled=True,
    )
    eq_(matches, [])
    # Without cache: 3 pairs * 5 samples * 2 extracts = 30.
    # With cache + early exit: each file extracted once for sample 0 only => 3.
    eq_(len(extract_calls), 3)
    eq_(len(compare_calls), 3)


def test_getmatches_skips_zero_duration(monkeypatch):
    monkeypatch.setattr(matchframes, "_ensure_ffmpeg_available", lambda *a, **k: None)
    files = [
        _FakeVideo("/videos/a.mp4", 0.0),
        _FakeVideo("/videos/b.mp4", 100.0),
    ]
    matches = matchframes.getmatches(
        files,
        threshold=80,
        sample_count=3,
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
        duration_tolerance_seconds=1.0,
        match_scaled=True,
    )
    eq_(matches, [])
