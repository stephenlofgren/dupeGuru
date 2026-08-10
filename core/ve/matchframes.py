import logging
import subprocess
import tempfile
from itertools import combinations
from pathlib import Path

from hscommon.jobprogress import job
from hscommon.trans import tr

from core.engine import Match
from core.pe.block import DifferentBlockCountError, NoBlocksError, avgdiff
from core.pe.matchblock import BLOCK_COUNT_PER_SIDE, MIN_ITERATIONS
from core.pe import photo as pe_photo


def _ensure_ffmpeg_available(ffmpeg_path, ffprobe_path):
    ffmpeg_ok = subprocess.run([ffmpeg_path, "-version"], capture_output=True, text=True, check=False)
    ffprobe_ok = subprocess.run([ffprobe_path, "-version"], capture_output=True, text=True, check=False)
    if ffmpeg_ok.returncode != 0:
        raise OSError(f"Unable to execute {ffmpeg_path}. Ensure ffmpeg is installed and in PATH.")
    if ffprobe_ok.returncode != 0:
        raise OSError(f"Unable to execute {ffprobe_path}. Ensure ffprobe is installed and in PATH.")


def _extract_frame(video_path, output_path, timestamp_seconds, ffmpeg_path):
    # -ss before -i seeks in container (fast). jpg is cheaper to encode/decode than png.
    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{timestamp_seconds:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        "-y",
        str(output_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return proc.returncode == 0 and output_path.exists()


def _frame_match_percentage(first_image, second_image, threshold, match_scaled):
    photo_class = pe_photo.PLAT_SPECIFIC_PHOTO_CLASS
    if photo_class is None:
        raise OSError("Picture backend is not initialized; cannot run video frame comparisons.")
    first_photo = photo_class(first_image)
    second_photo = photo_class(second_image)
    if not match_scaled and first_photo.dimensions != second_photo.dimensions:
        return 0
    try:
        first_blocks = first_photo.get_blocks(BLOCK_COUNT_PER_SIDE)
        second_blocks = second_photo.get_blocks(BLOCK_COUNT_PER_SIDE)
        diff = avgdiff(first_blocks, second_blocks, 100 - threshold, MIN_ITERATIONS)
        return max(0, 100 - diff)
    except (DifferentBlockCountError, NoBlocksError, OSError, ValueError):
        return 0


def _sample_positions(sample_count):
    if sample_count <= 1:
        return [0.5]
    # spread samples in the interior of the video to avoid intro/outro bias.
    return [(i + 1) / (sample_count + 1) for i in range(sample_count)]


def _cannot_reach_threshold(scores, sample_count, threshold):
    """True if even perfect remaining samples cannot push the mean to threshold."""
    remaining = sample_count - len(scores)
    if remaining < 0:
        return True
    max_possible = (sum(scores) + 100 * remaining) / sample_count
    return max_possible < threshold


class _FrameCache:
    """Extract each (video, sample index) frame at most once for the whole scan."""

    def __init__(self, cache_dir, ffmpeg_path):
        self._cache_dir = Path(cache_dir)
        self._ffmpeg_path = ffmpeg_path
        # (path_str, sample_idx) -> Path | None (None = extraction failed)
        self._frames = {}
        self._next_id = 0

    def get(self, video_file, sample_idx, relative_pos):
        key = (str(video_file.path), sample_idx)
        if key in self._frames:
            return self._frames[key]
        out = self._cache_dir / f"{self._next_id}_{sample_idx}.jpg"
        self._next_id += 1
        ts = video_file.duration * relative_pos
        ok = _extract_frame(video_file.path, out, ts, self._ffmpeg_path)
        path = out if ok else None
        self._frames[key] = path
        return path


def getmatches(
    files,
    threshold,
    sample_count,
    ffmpeg_path,
    ffprobe_path,
    duration_tolerance_seconds,
    match_scaled,
    j=job.nulljob,
):
    _ensure_ffmpeg_available(ffmpeg_path, ffprobe_path)
    j = j.start_subjob([2, 8])
    for f in j.iter_with_progress(files, tr("Read duration of %d/%d videos")):
        f.duration  # force lazy ffprobe read

    # Zero-duration / failed probes cannot produce useful frame matches.
    files = [f for f in files if f.duration > 0]
    positions = _sample_positions(sample_count)
    matches = []
    pair_count = len(files) * (len(files) - 1) // 2
    j.start_job(max(1, pair_count), tr("Compared %d/%d video pairs") % (0, pair_count))

    with tempfile.TemporaryDirectory(prefix="dupeguru-video-frames-") as td:
        frame_cache = _FrameCache(td, ffmpeg_path)
        for i, (first, second) in enumerate(combinations(files, 2), start=1):
            status = tr("Compared %d/%d video pairs (%s vs %s)") % (i, pair_count, first.name, second.name)
            if first.is_ref and second.is_ref:
                j.set_progress(i, status)
                continue
            if duration_tolerance_seconds > 0 and abs(first.duration - second.duration) > duration_tolerance_seconds:
                j.set_progress(i, status)
                continue

            sample_scores = []
            for idx, pos in enumerate(positions):
                first_frame = frame_cache.get(first, idx, pos)
                second_frame = frame_cache.get(second, idx, pos)
                if first_frame is None or second_frame is None:
                    logging.debug("Could not extract frame %d for %s and %s", idx, first.path, second.path)
                    # Treat failed extract as score 0 so early-exit math stays conservative.
                    sample_scores.append(0)
                else:
                    sample_scores.append(
                        _frame_match_percentage(first_frame, second_frame, threshold, match_scaled)
                    )
                if _cannot_reach_threshold(sample_scores, sample_count, threshold):
                    sample_scores = []
                    break

            if sample_scores and len(sample_scores) == sample_count:
                percentage = int(sum(sample_scores) / len(sample_scores))
                if percentage >= threshold:
                    matches.append(Match(first, second, percentage))
            j.set_progress(i, status)
    return matches
