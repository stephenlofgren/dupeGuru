from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QAbstractItemView

from hscommon.trans import trget
from qt.details_dialog import DetailsDialog as DetailsDialogBase
from qt.details_table import DetailsTable

tr = trget("ui")


class DetailsDialog(DetailsDialogBase):
    def _setupUi(self):
        self.setWindowTitle(tr("Details"))
        self.resize(502, 295)
        self.setMinimumSize(QSize(250, 250))
        self.tableView = DetailsTable(self)
        self.tableView.setAlternatingRowColors(True)
        self.tableView.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tableView.setShowGrid(False)
        self.setWidget(self.tableView)
