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
    """Compare two frame image paths (used for later samples)."""
    photo_class = pe_photo.PLAT_SPECIFIC_PHOTO_CLASS
    if photo_class is None:
        raise OSError("Picture backend is not initialized; cannot run video frame comparisons.")
    first_photo = photo_class(first_image)
    second_photo = photo_class(second_image)
    return _pair_blocks_percentage(
        first_photo.get_blocks(BLOCK_COUNT_PER_SIDE),
        first_photo.dimensions,
        second_photo.get_blocks(BLOCK_COUNT_PER_SIDE),
        second_photo.dimensions,
        threshold,
        match_scaled,
    )


def _pair_blocks_percentage(first_blocks, first_dims, second_blocks, second_dims, threshold, match_scaled):
    if first_blocks is None or second_blocks is None:
        return 0
    if not match_scaled and first_dims != second_dims:
        return 0
    try:
        diff = avgdiff(first_blocks, second_blocks, 100 - threshold, MIN_ITERATIONS)
        return max(0, 100 - diff)
    except (DifferentBlockCountError, NoBlocksError, OSError, ValueError):
        return 0


def _blocks_for_frame(frame_path):
    """Return (blocks, dimensions) for a cached frame image, or (None, None)."""
    if frame_path is None:
        return None, None
    photo_class = pe_photo.PLAT_SPECIFIC_PHOTO_CLASS
    if photo_class is None:
        raise OSError("Picture backend is not initialized; cannot run video frame comparisons.")
    try:
        photo = photo_class(frame_path)
        return photo.get_blocks(BLOCK_COUNT_PER_SIDE), photo.dimensions
    except (OSError, ValueError, MemoryError) as e:
        logging.debug("Could not prepare blocks for %s: %s", frame_path, e)
        return None, None


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


def _worker_count(item_count):
    if item_count <= 1:
        return 1
    return max(1, min(item_count, (os.cpu_count() or 4) * 2))


# Backwards-compatible alias used by tests.
_first_frame_worker_count = _worker_count


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

    def get_cached(self, video_file, sample_idx):
        return self._frames.get((str(video_file.path), sample_idx))

    def preload_sample(self, files, sample_idx, relative_pos, j=job.nulljob):
        """Extract one sample index for every video, in parallel."""
        self.preload_samples(files, [(sample_idx, relative_pos)], j=j)

    def preload_samples(self, files, sample_positions, j=job.nulljob):
        """Extract many (sample_idx, relative_pos) frames for every video, in parallel."""
        work = []
        for video_file in files:
            for sample_idx, relative_pos in sample_positions:
                key = (str(video_file.path), sample_idx)
                if key in self._frames:
                    continue
                out = self._cache_dir / f"{self._next_id}_{sample_idx}.jpg"
                self._next_id += 1
                ts = video_file.duration * relative_pos
                work.append((key, video_file.path, out, ts))

        if not work:
            return

        label = tr("Extract frames %d/%d")
        j.start_job(len(work), label % (0, len(work)))
        workers = _worker_count(len(work))
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_extract_frame, path, out, ts, self._ffmpeg_path): (key, out) for key, path, out, ts in work
            }
            for future in as_completed(futures):
                key, out = futures[future]
                ok = False
                try:
                    ok = future.result()
                except Exception:
                    logging.debug("Frame extract failed for %s sample %s", key[0], key[1], exc_info=True)
                self._frames[key] = out if ok else None
                done += 1
                j.set_progress(done, label % (done, len(work)))


def _prepare_frame_blocks(files, frame_cache, sample_indices, j=job.nulljob):
    """Build (path, sample_idx) -> (blocks, dimensions) for cached frame images."""
    prepared = {}
    work = [(f, idx) for f in files for idx in sample_indices]
    if not work:
        return prepared

    j.start_job(len(work), tr("Prepared frame blocks %d/%d") % (0, len(work)))
    workers = _worker_count(len(work))

    def prepare_one(item):
        video_file, sample_idx = item
        frame_path = frame_cache.get_cached(video_file, sample_idx)
        return (str(video_file.path), sample_idx), _blocks_for_frame(frame_path)

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(prepare_one, item) for item in work]
        for future in as_completed(futures):
            key, blocks_dims = future.result()
            prepared[key] = blocks_dims
            done += 1
            j.set_progress(done, tr("Prepared frame blocks %d/%d") % (done, len(work)))
    return prepared


def _first_frame_blocks_by_path(prepared_blocks):
    """Map path -> (blocks, dims) for sample index 0."""
    return {path: blocks_dims for (path, idx), blocks_dims in prepared_blocks.items() if idx == 0}


def _score_first_frame_pairs(
    pairs,
    blocks_by_path,
    threshold,
    match_scaled,
    sample_count,
    pair_count=None,
    j=job.nulljob,
):
    """Parallel first-frame scoring using precomputed blocks. Returns viable (a, b, score).

    ``pairs`` may be a list or iterator. Pass ``pair_count`` when using a generator so
    progress is accurate without materializing every pair in memory.
    """
    if pair_count is None:
        pairs = list(pairs)
        pair_count = len(pairs)

    if pair_count <= 0:
        j.start_job(1, tr("Compared %d/%d first-frame pairs") % (0, 0))
        j.set_progress(1, tr("Compared %d/%d first-frame pairs") % (0, 0))
        return []

    j.start_job(pair_count, tr("Compared %d/%d first-frame pairs") % (0, pair_count))
    workers = _worker_count(min(pair_count, 512))
    viable = []
    done = 0
    chunk_size = max(workers * 32, 256)
    pair_iter = iter(pairs)

    def score_one(pair):
        first, second = pair
        first_blocks, first_dims = blocks_by_path.get(str(first.path), (None, None))
        second_blocks, second_dims = blocks_by_path.get(str(second.path), (None, None))
        score = _pair_blocks_percentage(first_blocks, first_dims, second_blocks, second_dims, threshold, match_scaled)
        return first, second, score

    with ThreadPoolExecutor(max_workers=workers) as pool:
        while True:
            chunk = []
            try:
                for _ in range(chunk_size):
                    chunk.append(next(pair_iter))
            except StopIteration:
                pass
            if not chunk:
                break
            futures = [pool.submit(score_one, pair) for pair in chunk]
            for future in as_completed(futures):
                first, second, score = future.result()
                done += 1
                if done % 100 == 0 or done >= pair_count:
                    progress = min(done, pair_count)
                    j.set_progress(
                        progress,
                        tr("Compared %d/%d first-frame pairs") % (progress, pair_count),
                    )
                if not _cannot_reach_threshold([score], sample_count, threshold):
                    viable.append((first, second, score))
        if done < pair_count:
            j.set_progress(pair_count, tr("Compared %d/%d first-frame pairs") % (pair_count, pair_count))
    return viable


def _score_sample(frame_cache, first, second, sample_idx, relative_pos, threshold, match_scaled, prepared_blocks=None):
    if prepared_blocks is not None:
        first_blocks, first_dims = prepared_blocks.get((str(first.path), sample_idx), (None, None))
        second_blocks, second_dims = prepared_blocks.get((str(second.path), sample_idx), (None, None))
        if first_blocks is not None and second_blocks is not None:
            return _pair_blocks_percentage(
                first_blocks, first_dims, second_blocks, second_dims, threshold, match_scaled
            )
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
    preload_all_frames=False,
    j=job.nulljob,
):
    _ensure_ffmpeg_available(ffmpeg_path, ffprobe_path)
    # duration -> extract frames -> prepare blocks -> first-pass pairs -> deep samples
    j = j.start_subjob([1, 3, 2, 3, 1] if preload_all_frames else [1, 2, 2, 3, 2])
    for f in j.iter_with_progress(files, tr("Read duration of %d/%d videos")):
        f.duration  # force lazy ffprobe read

    # Zero-duration / failed probes cannot produce useful frame matches.
    files = [f for f in files if f.duration > 0]
    positions = _sample_positions(sample_count)
    matches = []
    sample_indices = list(range(sample_count)) if preload_all_frames else [0]

    with tempfile.TemporaryDirectory(prefix="dupeguru-video-frames-") as td:
        frame_cache = _FrameCache(td, ffmpeg_path)
        if preload_all_frames:
            frame_cache.preload_samples(files, list(enumerate(positions)), j=j)
        else:
            frame_cache.preload_sample(files, 0, positions[0], j=j)

        prepared_blocks = _prepare_frame_blocks(files, frame_cache, sample_indices, j=j)
        blocks_by_path = _first_frame_blocks_by_path(prepared_blocks)

        pair_count = duration_window_pair_count(files, duration_tolerance_seconds)
        candidate_pairs = (
            (first, second)
            for first, second in iter_duration_window_pairs(files, duration_tolerance_seconds)
            if not (first.is_ref and second.is_ref)
        )
        viable = _score_first_frame_pairs(
            candidate_pairs,
            blocks_by_path,
            threshold,
            match_scaled,
            sample_count,
            pair_count=pair_count,
            j=j,
        )

        deep_blocks = prepared_blocks if preload_all_frames else None
        for first, second, first_score in j.iter_with_progress(
            viable,
            tr("Deep-compared %d/%d video pairs"),
            count=max(1, len(viable)),
            every=10,
        ):
            sample_scores = [first_score]
            if sample_count == 1:
                percentage = int(first_score)
                if percentage >= threshold:
                    matches.append(Match(first, second, percentage))
                continue

            for idx, pos in enumerate(positions[1:], start=1):
                sample_scores.append(
                    _score_sample(
                        frame_cache,
                        first,
                        second,
                        idx,
                        pos,
                        threshold,
                        match_scaled,
                        prepared_blocks=deep_blocks,
                    )
                )
                if _cannot_reach_threshold(sample_scores, sample_count, threshold):
                    sample_scores = []
                    break

            if sample_scores and len(sample_scores) == sample_count:
                percentage = int(sum(sample_scores) / len(sample_scores))
                if percentage >= threshold:
                    matches.append(Match(first, second, percentage))
    return matches
