from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSpacerItem,
    QSpinBox,
    QWidget,
)

from hscommon.trans import trget
from core.app import AppMode
from core.scanner import ScanType
from qt.preferences_dialog import PreferencesDialogBase

tr = trget("ui")


class PreferencesDialog(PreferencesDialogBase):
    def _setupPreferenceWidgets(self):
        self._setupFilterHardnessBox()
        self.widgetsVLayout.addLayout(self.filterHardnessHLayout)

        self._setupAddCheckbox("videoMatchScaledBox", tr("Allow frame comparisons with different dimensions"))
        self.widgetsVLayout.addWidget(self.videoMatchScaledBox)
        self._setupAddCheckbox("mixFileKindBox", tr("Can mix file kind"))
        self.widgetsVLayout.addWidget(self.mixFileKindBox)
        self._setupAddCheckbox("useRegexpBox", tr("Use regular expressions when filtering"))
        self.widgetsVLayout.addWidget(self.useRegexpBox)
        self._setupAddCheckbox("removeEmptyFoldersBox", tr("Remove empty folders on delete or move"))
        self.widgetsVLayout.addWidget(self.removeEmptyFoldersBox)
        self._setupAddCheckbox(
            "ignoreHardlinkMatches",
            tr("Ignore duplicates hardlinking to the same file"),
        )
        self.widgetsVLayout.addWidget(self.ignoreHardlinkMatches)

        row = QWidget(self)
        row.setMinimumSize(QSize(0, 30))
        layout = QHBoxLayout(row)
        self.durationToleranceLabel = QLabel(tr("Duration tolerance (seconds):"), row)
        self.durationToleranceSpinBox = QDoubleSpinBox(row)
        self.durationToleranceSpinBox.setRange(0.0, 60.0)
        self.durationToleranceSpinBox.setDecimals(2)
        self.durationToleranceSpinBox.setSingleStep(0.1)
        layout.addWidget(self.durationToleranceLabel)
        layout.addWidget(self.durationToleranceSpinBox)
        layout.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        self.widgetsVLayout.addWidget(row)

        row = QWidget(self)
        layout = QHBoxLayout(row)
        self.sampleCountLabel = QLabel(tr("Frame samples per video:"), row)
        self.sampleCountSpinBox = QSpinBox(row)
        self.sampleCountSpinBox.setRange(1, 20)
        layout.addWidget(self.sampleCountLabel)
        layout.addWidget(self.sampleCountSpinBox)
        layout.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        self.widgetsVLayout.addWidget(row)

        row = QWidget(self)
        layout = QHBoxLayout(row)
        self.ffmpegPathLabel = QLabel(tr("ffmpeg executable path:"), row)
        self.ffmpegPathEdit = QLineEdit(row)
        layout.addWidget(self.ffmpegPathLabel)
        layout.addWidget(self.ffmpegPathEdit)
        self.widgetsVLayout.addWidget(row)

        row = QWidget(self)
        layout = QHBoxLayout(row)
        self.ffprobePathLabel = QLabel(tr("ffprobe executable path:"), row)
        self.ffprobePathEdit = QLineEdit(row)
        layout.addWidget(self.ffprobePathLabel)
        layout.addWidget(self.ffprobePathEdit)
        self.widgetsVLayout.addWidget(row)
        self._setupBottomPart()

    def _load(self, prefs, setchecked, section):
        scan_type = prefs.get_scan_type(AppMode.VIDEO)
        frame_scan = scan_type == ScanType.VIDEOFRAMES
        self.filterHardnessSlider.setEnabled(True)
        self.sampleCountSpinBox.setEnabled(frame_scan)
        self.videoMatchScaledBox.setEnabled(frame_scan)
        setchecked(self.videoMatchScaledBox, prefs.video_match_scaled)
        self.durationToleranceSpinBox.setValue(float(prefs.video_duration_tolerance))
        self.sampleCountSpinBox.setValue(int(prefs.video_frame_sample_count))
        self.ffmpegPathEdit.setText(str(prefs.video_ffmpeg_path))
        self.ffprobePathEdit.setText(str(prefs.video_ffprobe_path))

    def _save(self, prefs, ischecked):
        prefs.video_match_scaled = ischecked(self.videoMatchScaledBox)
        prefs.video_duration_tolerance = float(self.durationToleranceSpinBox.value())
        prefs.video_frame_sample_count = int(self.sampleCountSpinBox.value())
        prefs.video_ffmpeg_path = str(self.ffmpegPathEdit.text()).strip() or "ffmpeg"
        prefs.video_ffprobe_path = str(self.ffprobePathEdit.text()).strip() or "ffprobe"
