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


def test_preload_sample_extracts_first_frames_in_parallel(monkeypatch, tmpdir):
    calls = []

    def fake_extract(video_path, output_path, timestamp_seconds, ffmpeg_path):
        calls.append(str(video_path))
        Path(output_path).write_bytes(b"fake")
        return True

    monkeypatch.setattr(matchframes, "_extract_frame", fake_extract)
    monkeypatch.setattr(matchframes, "_first_frame_worker_count", lambda n: 4)

    cache = matchframes._FrameCache(str(tmpdir), "ffmpeg")
    files = [
        _FakeVideo("/videos/a.mp4", 100.0),
        _FakeVideo("/videos/b.mp4", 100.0),
        _FakeVideo("/videos/c.mp4", 100.0),
    ]
    cache.preload_sample(files, 0, 0.25)
    eq_(sorted(calls), ["/videos/a.mp4", "/videos/b.mp4", "/videos/c.mp4"])
    # Second preload is a no-op (already cached).
    cache.preload_sample(files, 0, 0.25)
    eq_(len(calls), 3)
    eq_(cache.get(files[0], 0, 0.25).name.endswith("_0.jpg"), True)


def test_getmatches_skips_later_samples_when_first_fails(monkeypatch):
    extract_calls = []
    compare_calls = []

    def fake_extract(video_path, output_path, timestamp_seconds, ffmpeg_path):
        extract_calls.append((str(video_path), round(timestamp_seconds, 3)))
        Path(output_path).write_bytes(b"fake")
        return True

    def fake_compare(first_image, second_image, threshold, match_scaled):
        compare_calls.append((str(first_image), str(second_image)))
        return 0  # first sample cannot reach threshold 90 with 5 samples

    monkeypatch.setattr(matchframes, "_ensure_ffmpeg_available", lambda *a, **k: None)
    monkeypatch.setattr(matchframes, "_extract_frame", fake_extract)
    monkeypatch.setattr(matchframes, "_frame_match_percentage", fake_compare)

    files = [
        _FakeVideo("/videos/a.mp4", 100.0),
        _FakeVideo("/videos/b.mp4", 100.0),
        _FakeVideo("/videos/c.mp4", 100.0),
    ]
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
    # Only first-sample extracts (one per file); no later sample indexes.
    eq_(len(extract_calls), 3)
    assert all(ts == round(100.0 / 6, 3) for _, ts in extract_calls)  # first of 5 interior samples
    eq_(len(compare_calls), 3)


def test_getmatches_extracts_later_samples_only_after_first_match(monkeypatch):
    extract_calls = []

    def fake_extract(video_path, output_path, timestamp_seconds, ffmpeg_path):
        extract_calls.append((str(video_path), round(timestamp_seconds, 3)))
        Path(output_path).write_bytes(b"fake")
        return True

    def fake_compare(first_image, second_image, threshold, match_scaled):
        return 100

    monkeypatch.setattr(matchframes, "_ensure_ffmpeg_available", lambda *a, **k: None)
    monkeypatch.setattr(matchframes, "_extract_frame", fake_extract)
    monkeypatch.setattr(matchframes, "_frame_match_percentage", fake_compare)

    files = [
        _FakeVideo("/videos/a.mp4", 100.0),
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
    eq_(len(matches), 1)
    eq_(matches[0].percentage, 100)
    # First frames for both videos, then remaining 2 samples for both => 2 + 4 = 6.
    eq_(len(extract_calls), 6)
    first_sample_ts = round(100.0 * (1 / 4), 3)
    later_ts = {round(100.0 * (2 / 4), 3), round(100.0 * (3 / 4), 3)}
    first_extracts = [c for c in extract_calls if c[1] == first_sample_ts]
    later_extracts = [c for c in extract_calls if c[1] in later_ts]
    eq_(len(first_extracts), 2)
    eq_(len(later_extracts), 4)


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


def test_getmatches_skips_pairs_outside_duration_window(monkeypatch):
    compare_calls = []

    def fake_extract(video_path, output_path, timestamp_seconds, ffmpeg_path):
        Path(output_path).write_bytes(b"fake")
        return True

    def fake_compare(first_image, second_image, threshold, match_scaled):
        compare_calls.append(1)
        return 100

    monkeypatch.setattr(matchframes, "_ensure_ffmpeg_available", lambda *a, **k: None)
    monkeypatch.setattr(matchframes, "_extract_frame", fake_extract)
    monkeypatch.setattr(matchframes, "_frame_match_percentage", fake_compare)

    files = [
        _FakeVideo("/videos/short.mp4", 10.0),
        _FakeVideo("/videos/short2.mp4", 10.2),
        _FakeVideo("/videos/long.mp4", 60.0),
    ]
    matches = matchframes.getmatches(
        files,
        threshold=80,
        sample_count=1,
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
        duration_tolerance_seconds=1.0,
        match_scaled=True,
    )
    # Only short vs short2 is inside the 1s window; long is never compared.
    eq_(len(matches), 1)
    eq_({matches[0].first.name, matches[0].second.name}, {"short.mp4", "short2.mp4"})
    eq_(len(compare_calls), 1)
