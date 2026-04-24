from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset


@dataclass
class SplitFrames:
    train: pd.DataFrame
    valid: pd.DataFrame
    test: pd.DataFrame


def blocked_time_split(frame: pd.DataFrame, date_column: str = "sample_date") -> SplitFrames:
    ordered = frame.sort_values(date_column).reset_index(drop=True)
    n = len(ordered)
    train_end = int(n * 0.7)
    valid_end = int(n * 0.85)
    return SplitFrames(
        train=ordered.iloc[:train_end].copy(),
        valid=ordered.iloc[train_end:valid_end].copy(),
        test=ordered.iloc[valid_end:].copy(),
    )


class SequenceDataset(Dataset):
    def __init__(
        self,
        sequences: np.ndarray,
        static_features: np.ndarray,
        site_indices: np.ndarray,
        exceed_targets: np.ndarray,
        density_targets: np.ndarray,
    ) -> None:
        self.sequences = torch.as_tensor(np.array(sequences, copy=True), dtype=torch.float32)
        self.static_features = torch.as_tensor(np.array(static_features, copy=True), dtype=torch.float32)
        self.site_indices = torch.as_tensor(np.array(site_indices, copy=True), dtype=torch.long)
        self.exceed_targets = torch.as_tensor(np.array(exceed_targets, copy=True), dtype=torch.float32)
        self.density_targets = torch.as_tensor(np.array(density_targets, copy=True), dtype=torch.float32)

    def __len__(self) -> int:
        return len(self.sequences)

    def __getitem__(self, index: int):
        return {
            "sequence": self.sequences[index],
            "static": self.static_features[index],
            "site_index": self.site_indices[index],
            "target_exceed": self.exceed_targets[index],
            "target_density": self.density_targets[index],
        }
