from hscommon.trans import trget

from core.prioritize import (
    FilenameCategory,
    FolderCategory,
    KindCategory,
    MtimeCategory,
    NumericalCategory,
    SizeCategory,
)

coltr = trget("columns")


class DurationCategory(NumericalCategory):
    NAME = coltr("Duration")

    def extract_value(self, dupe):
        return dupe.duration


def all_categories():
    return [
        KindCategory,
        FolderCategory,
        FilenameCategory,
        SizeCategory,
        DurationCategory,
        MtimeCategory,
    ]
