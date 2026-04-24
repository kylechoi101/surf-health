from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class SourceContext:
    raw_dir: Path
    curated_dir: Path
    research_dir: Path


class SourceConnector(ABC):
    source_name: str

    @abstractmethod
    async def fetch(self, context: SourceContext) -> pd.DataFrame:
        raise NotImplementedError

