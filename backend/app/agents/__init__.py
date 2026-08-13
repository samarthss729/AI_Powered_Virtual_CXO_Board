"""Executive agent personas for the AI Boardroom."""

from app.agents.cfo import CFO
from app.agents.cmo import CMO
from app.agents.coo import COO
from app.agents.cso import CSO

BOARD_EXECUTIVES = [CFO, CMO, COO, CSO]

__all__ = ["CFO", "CMO", "COO", "CSO", "BOARD_EXECUTIVES"]
