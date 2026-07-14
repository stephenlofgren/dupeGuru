from hscommon.trans import tr

from core.scanner import ScanOption, ScanType, Scanner as ScannerBase
from core.ve.fs import VideoFile
from core.ve import matchframes, matchlength


class ScannerVE(ScannerBase):
    duration_tolerance_seconds = 1.0
    frame_sample_count = 5
    ffmpeg_path = "ffmpeg"
    ffprobe_path = "ffprobe"
    video_match_scaled = True

    @staticmethod
    def _key_func(dupe):
        return (-dupe.duration, -dupe.size)

    @staticmethod
    def get_scan_options():
        return [
            ScanOption(ScanType.VIDEOLENGTH, tr("Video Length")),
            ScanOption(ScanType.VIDEOFRAMES, tr("Video Frames")),
        ]

    def _getmatches(self, files, j):
        VideoFile.ffprobe_path = self.ffprobe_path
        if self.scan_type == ScanType.VIDEOLENGTH:
            return matchlength.getmatches(
                files,
                threshold=self.min_match_percentage,
                duration_tolerance_seconds=self.duration_tolerance_seconds,
                j=j,
            )
        if self.scan_type == ScanType.VIDEOFRAMES:
            return matchframes.getmatches(
                files,
                threshold=self.min_match_percentage,
                sample_count=self.frame_sample_count,
                ffmpeg_path=self.ffmpeg_path,
                ffprobe_path=self.ffprobe_path,
                duration_tolerance_seconds=self.duration_tolerance_seconds,
                match_scaled=self.video_match_scaled,
                j=j,
            )
        raise ValueError("Invalid scan type")
