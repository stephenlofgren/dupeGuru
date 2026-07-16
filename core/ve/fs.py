import json
import subprocess

from hscommon.util import format_size, format_time, get_file_ext

from core import fs
from core.util import format_dupe_count, format_perc, format_timestamp


VIDEO_EXTS = {
    "mp4",
    "m4v",
    "mov",
    "mkv",
    "avi",
    "wmv",
    "webm",
    "flv",
    "mpg",
    "mpeg",
    "m2ts",
    "ts",
}

# Bare "ts" also matches TypeScript sources (get_file_ext uses the last dot only).
# Reject known TS suffixes; multi-dot video names like "vacation.2024.01.15.ts" still match.
NON_VIDEO_TS_SUFFIXES = (".d.ts", ".spec.ts", ".test.ts", ".stories.ts")


def is_video_filename(name):
    ext = get_file_ext(name)
    if ext not in VIDEO_EXTS:
        return False
    if ext == "ts":
        name_lower = name.lower()
        if any(name_lower.endswith(suffix) for suffix in NON_VIDEO_TS_SUFFIXES):
            return False
    return True


class VideoFile(fs.File):
    INITIAL_INFO = fs.File.INITIAL_INFO.copy()
    INITIAL_INFO.update({"duration": 0.0})
    __slots__ = fs.File.__slots__ + tuple(INITIAL_INFO.keys())
    ffprobe_path = "ffprobe"

    @classmethod
    def can_handle(cls, path):
        return fs.File.can_handle(path) and is_video_filename(path.name)

    def _get_duration(self):
        ffprobe_path = self.__class__.ffprobe_path
        cmd = [
            ffprobe_path,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_entries",
            "format=duration",
            str(self.path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise OSError(f"ffprobe failed for {self.path}: {proc.stderr.strip()}")
        data = json.loads(proc.stdout or "{}")
        duration = ((data.get("format") or {}).get("duration")) or "0"
        return float(duration)

    def _read_info(self, field):
        fs.File._read_info(self, field)
        if field == "duration":
            try:
                self.duration = self._get_duration()
            except OSError:
                # Cache failure so lazy reads do not re-run ffprobe on every pair comparison.
                self.duration = 0.0

    def get_display_info(self, group, delta):
        size = self.size
        mtime = self.mtime
        duration = self.duration
        m = group.get_match_of(self)
        if m:
            percentage = m.percentage
            dupe_count = 0
            if delta:
                r = group.ref
                size -= r.size
                mtime -= r.mtime
                duration -= r.duration
        else:
            percentage = group.percentage
            dupe_count = len(group.dupes)
        dupe_folder_path = getattr(self, "display_folder_path", self.folder_path)
        return {
            "name": self.name,
            "folder_path": str(dupe_folder_path),
            "size": format_size(size, 1, 1, False),
            "duration": format_time(duration, with_hours=False),
            "extension": self.extension,
            "mtime": format_timestamp(mtime, delta and m),
            "percentage": format_perc(percentage),
            "dupe_count": format_dupe_count(dupe_count),
        }
