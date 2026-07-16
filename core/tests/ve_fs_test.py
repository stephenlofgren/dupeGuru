from pathlib import Path

from hscommon.testutil import eq_

from core.ve.fs import VideoFile, is_video_filename


def test_is_video_filename_accepts_multi_dot_video_names():
    assert is_video_filename("vacation.2024.01.15.mp4")
    assert is_video_filename("my.movie.part1.mkv")
    assert is_video_filename("recording.2024.01.ts")
    assert is_video_filename("clip.m2ts")


def test_is_video_filename_rejects_typescript_ts():
    assert not is_video_filename("zh-Hans-MO.d.ts")
    assert not is_video_filename("component.spec.ts")
    assert not is_video_filename("widget.test.ts")
    assert not is_video_filename("button.stories.ts")


def test_can_handle(tmpdir):
    p = Path(str(tmpdir))
    video = p / "movie.2024.01.15.mp4"
    video.write_bytes(b"")
    ts_file = p / "recording.2024.01.ts"
    ts_file.write_bytes(b"")
    dts = p / "zh-Hans-MO.d.ts"
    dts.write_bytes(b"")
    assert VideoFile.can_handle(video)
    assert VideoFile.can_handle(ts_file)
    assert not VideoFile.can_handle(dts)


def test_duration_probe_failure_is_cached(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return type("Proc", (), {"returncode": 1, "stdout": "", "stderr": "bad input"})()

    monkeypatch.setattr("core.ve.fs.subprocess.run", fake_run)
    vf = VideoFile(Path("/fake/video.mp4"))
    eq_(vf.duration, 0.0)
    eq_(vf.duration, 0.0)
    eq_(len(calls), 1)
