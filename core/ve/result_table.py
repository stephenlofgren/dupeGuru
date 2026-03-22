from hscommon.gui.column import Column
from hscommon.trans import trget

from core.gui.result_table import ResultTable as ResultTableBase

coltr = trget("columns")


class ResultTable(ResultTableBase):
    COLUMNS = [
        Column("marked", ""),
        Column("name", coltr("Filename")),
        Column("folder_path", coltr("Folder"), optional=True),
        Column("size", coltr("Size (MB)"), optional=True),
        Column("duration", coltr("Time"), optional=True),
        Column("extension", coltr("Kind"), optional=True),
        Column("mtime", coltr("Modification"), visible=False, optional=True),
        Column("percentage", coltr("Match %"), optional=True),
        Column("dupe_count", coltr("Dupe Count"), visible=False, optional=True),
    ]
    DELTA_COLUMNS = {"size", "duration", "mtime"}
