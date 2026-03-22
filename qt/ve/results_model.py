from qt.column import Column
from qt.results_model import ResultsModel as ResultsModelBase


class ResultsModel(ResultsModelBase):
    COLUMNS = [
        Column("marked", default_width=30),
        Column("name", default_width=200),
        Column("folder_path", default_width=180),
        Column("size", default_width=60),
        Column("duration", default_width=60),
        Column("extension", default_width=50),
        Column("mtime", default_width=120),
        Column("percentage", default_width=60),
        Column("dupe_count", default_width=80),
    ]
