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

    matches = []
    pair_count = len(files) * (len(files) - 1) // 2
    j.start_job(max(1, pair_count), tr("Compared %d/%d video pairs") % (0, pair_count))
    for i, (first, second) in enumerate(combinations(files, 2), start=1):
        status = tr("Compared %d/%d video pairs (%s vs %s)") % (i, pair_count, first.name, second.name)
        if first.is_ref and second.is_ref:
            j.set_progress(i, status)
            continue
        if duration_tolerance_seconds > 0 and abs(first.duration - second.duration) > duration_tolerance_seconds:
            j.set_progress(i, status)
            continue
        sample_scores = []
        duration = min(first.duration, second.duration)
        with tempfile.TemporaryDirectory(prefix="dupeguru-video-frames-") as td:
            tmp_dir = Path(td)
            for idx, pos in enumerate(_sample_positions(sample_count)):
                ts = duration * pos
                first_frame = tmp_dir / f"first_{idx}.png"
                second_frame = tmp_dir / f"second_{idx}.png"
                ok_first = _extract_frame(first.path, first_frame, ts, ffmpeg_path)
                ok_second = _extract_frame(second.path, second_frame, ts, ffmpeg_path)
                if not ok_first or not ok_second:
                    logging.debug("Could not extract frame %d for %s and %s", idx, first.path, second.path)
                    continue
                sample_scores.append(_frame_match_percentage(first_frame, second_frame, threshold, match_scaled))
        if sample_scores:
            percentage = int(sum(sample_scores) / len(sample_scores))
            if percentage >= threshold:
                matches.append(Match(first, second, percentage))
        j.set_progress(i, status)
    return matches
