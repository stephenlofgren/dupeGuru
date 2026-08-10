import logging
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from hscommon.jobprogress import job
from hscommon.trans import tr

from core.engine import Match
from core.pe.block import DifferentBlockCountError, NoBlocksError, avgdiff
from core.pe.matchblock import BLOCK_COUNT_PER_SIDE, MIN_ITERATIONS
from core.pe import photo as pe_photo
from core.ve.duration_window import duration_window_pair_count, iter_duration_window_pairs


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


def _first_frame_worker_count(file_count):
    if file_count <= 1:
        return 1
    return max(1, min(file_count, (os.cpu_count() or 4) * 2))


class _FrameCache:
    """Extract each (video, sample index) frame at most once for the whole scan."""

    def __init__(self, cache_dir, ffmpeg_path):
        self._cache_dir = Path(cache_dir)
        self._ffmpeg_path = ffmpeg_path
        # (path_str, sample_idx) -> Path | None (None = extraction failed)
        self._frames = {}
        self._next_id = 0

    def get(self, video_file, sample_idx, relative_pos):
        """Serial extract-or-reuse for later samples."""
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

    def preload_sample(self, files, sample_idx, relative_pos, j=job.nulljob):
        """Extract one sample index for every video, in parallel."""
        work = []
        for video_file in files:
            key = (str(video_file.path), sample_idx)
            if key in self._frames:
                continue
            out = self._cache_dir / f"{self._next_id}_{sample_idx}.jpg"
            self._next_id += 1
            ts = video_file.duration * relative_pos
            work.append((key, video_file.path, out, ts))

        if not work:
            return

        j.start_job(len(work), tr("Extract first frame of %d/%d videos") % (0, len(work)))
        workers = _first_frame_worker_count(len(work))
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_extract_frame, path, out, ts, self._ffmpeg_path): (key, out)
                for key, path, out, ts in work
            }
            for future in as_completed(futures):
                key, out = futures[future]
                ok = False
                try:
                    ok = future.result()
                except Exception:
                    logging.debug("First-frame extract failed for %s", key[0], exc_info=True)
                self._frames[key] = out if ok else None
                done += 1
                j.set_progress(done, tr("Extract first frame of %d/%d videos") % (done, len(work)))


def _score_sample(frame_cache, first, second, sample_idx, relative_pos, threshold, match_scaled):
    first_frame = frame_cache.get(first, sample_idx, relative_pos)
    second_frame = frame_cache.get(second, sample_idx, relative_pos)
    if first_frame is None or second_frame is None:
        logging.debug("Could not extract frame %d for %s and %s", sample_idx, first.path, second.path)
        return 0
    return _frame_match_percentage(first_frame, second_frame, threshold, match_scaled)


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
    j = j.start_subjob([1, 2, 7])
    for f in j.iter_with_progress(files, tr("Read duration of %d/%d videos")):
        f.duration  # force lazy ffprobe read

    # Zero-duration / failed probes cannot produce useful frame matches.
    files = [f for f in files if f.duration > 0]
    positions = _sample_positions(sample_count)
    matches = []
    pair_count = duration_window_pair_count(files, duration_tolerance_seconds)

    with tempfile.TemporaryDirectory(prefix="dupeguru-video-frames-") as td:
        frame_cache = _FrameCache(td, ffmpeg_path)
        # Parallelize first-frame extracts only. Later samples stay serial and are
        # only pulled for pairs that still look viable after the first comparison.
        frame_cache.preload_sample(files, 0, positions[0], j=j)

        for first, second in j.iter_with_progress(
            iter_duration_window_pairs(files, duration_tolerance_seconds),
            tr("Compared %d/%d video pairs"),
            count=max(1, pair_count),
            every=100,
        ):
            if first.is_ref and second.is_ref:
                continue

            first_score = _score_sample(frame_cache, first, second, 0, positions[0], threshold, match_scaled)
            sample_scores = [first_score]
            if _cannot_reach_threshold(sample_scores, sample_count, threshold):
                continue

            # First frame looks like a reasonable candidate: pull remaining samples serially.
            for idx, pos in enumerate(positions[1:], start=1):
                sample_scores.append(
                    _score_sample(frame_cache, first, second, idx, pos, threshold, match_scaled)
                )
                if _cannot_reach_threshold(sample_scores, sample_count, threshold):
                    sample_scores = []
                    break

            if sample_scores and len(sample_scores) == sample_count:
                percentage = int(sum(sample_scores) / len(sample_scores))
                if percentage >= threshold:
                    matches.append(Match(first, second, percentage))
    return matches
