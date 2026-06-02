from __future__ import annotations

from dataclasses import dataclass
import os

import numpy as np
import pandas as pd
import torch
os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(os.cpu_count() or 8))
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from torch import nn


def _numeric_columns(frame: pd.DataFrame) -> list[str]:
    return [column for column in frame.columns if pd.api.types.is_numeric_dtype(frame[column])]


@dataclass
class BaselineBundle:
    logistic: Pipeline
    linear: Pipeline
    tree_classifier: HistGradientBoostingClassifier
    tree_regressor: HistGradientBoostingRegressor


def make_baselines(frame: pd.DataFrame) -> BaselineBundle:
    numeric_columns = _numeric_columns(frame)
    transformer = ColumnTransformer(
        [
            (
                "numeric",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler()),
                    ]
                ),
                numeric_columns,
            )
        ],
        remainder="drop",
    )

    logistic = Pipeline(
        [
            ("prep", transformer),
            (
                "model",
                LogisticRegression(
                    class_weight="balanced",
                    max_iter=2000,
                    solver="lbfgs",
                ),
            ),
        ]
    )
    linear = Pipeline([("prep", transformer), ("model", ElasticNet(alpha=0.05, l1_ratio=0.15))])
    tree_classifier = HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_depth=6,
        max_iter=300,
        class_weight="balanced",
        random_state=42,
    )
    tree_regressor = HistGradientBoostingRegressor(
        learning_rate=0.05,
        max_depth=6,
        max_iter=300,
        random_state=42,
    )

    return BaselineBundle(
        logistic=logistic,
        linear=linear,
        tree_classifier=tree_classifier,
        tree_regressor=tree_regressor,
    )


class TemporalBlock(nn.Module):
    def __init__(self, channels: int, dilation: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv1d(channels, channels, kernel_size=3, padding=dilation, dilation=dilation),
            nn.GELU(),
            nn.Conv1d(channels, channels, kernel_size=3, padding=dilation, dilation=dilation),
            nn.GELU(),
        )
        self.norm = nn.BatchNorm1d(channels)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.norm(self.net(inputs) + inputs)


class BeachTCN(nn.Module):
    def __init__(
        self,
        sequence_features: int,
        static_features: int,
        num_sites: int,
        hidden_channels: int = 32,
        embedding_dim: int = 16,
        exogenous_hidden: int = 32,
    ) -> None:
        super().__init__()
        self.site_embedding = nn.Embedding(num_sites, embedding_dim)
        self.input_projection = nn.Conv1d(sequence_features, hidden_channels, kernel_size=1)
        self.blocks = nn.Sequential(
            TemporalBlock(hidden_channels, dilation=1),
            TemporalBlock(hidden_channels, dilation=2),
            TemporalBlock(hidden_channels, dilation=4),
            TemporalBlock(hidden_channels, dilation=8),
        )
        self.pool = nn.AdaptiveAvgPool1d(1)
        
        self.exogenous_net = nn.Sequential(
            nn.Linear(static_features, exogenous_hidden),
            nn.LayerNorm(exogenous_hidden),
            nn.GELU(),
            nn.Dropout(0.2),
            nn.Linear(exogenous_hidden, exogenous_hidden),
            nn.GELU(),
        )

        combined_dim = hidden_channels + exogenous_hidden + embedding_dim
        self.shared = nn.Sequential(
            nn.Linear(combined_dim, 96),
            nn.GELU(),
            nn.Dropout(0.2),
            nn.Linear(96, 48),
            nn.GELU(),
        )
        self.classifier = nn.Linear(48, 1)
        self.regressor = nn.Linear(48, 1)

    def forward(
        self, sequence: torch.Tensor, static_features: torch.Tensor, site_index: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        # Sequence input is [batch, time, features].
        x = sequence.transpose(1, 2)
        x = self.input_projection(x)
        x = self.blocks(x)
        x = self.pool(x).squeeze(-1)
        site = self.site_embedding(site_index)
        exo = self.exogenous_net(static_features)
        combined = torch.cat([x, exo, site], dim=-1)
        shared = self.shared(combined)
        return self.classifier(shared).squeeze(-1), self.regressor(shared).squeeze(-1)


class CNNBlock(nn.Module):
    def __init__(self, in_channels: int, out_channels: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv1d(in_channels, out_channels, kernel_size=3, padding=1),
            nn.BatchNorm1d(out_channels),
            nn.GELU(),
            nn.MaxPool1d(2)
        )

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.net(inputs)


class BeachCNN(nn.Module):
    def __init__(
        self,
        sequence_features: int,
        static_features: int,
        num_sites: int,
        hidden_channels: int = 32,
        embedding_dim: int = 16,
        exogenous_hidden: int = 32,
    ) -> None:
        super().__init__()
        self.site_embedding = nn.Embedding(num_sites, embedding_dim)
        self.input_projection = nn.Conv1d(sequence_features, hidden_channels, kernel_size=1)
        self.blocks = nn.Sequential(
            CNNBlock(hidden_channels, hidden_channels),
            CNNBlock(hidden_channels, hidden_channels),
            CNNBlock(hidden_channels, hidden_channels),
        )
        self.pool = nn.AdaptiveAvgPool1d(1)
        
        self.exogenous_net = nn.Sequential(
            nn.Linear(static_features, exogenous_hidden),
            nn.LayerNorm(exogenous_hidden),
            nn.GELU(),
            nn.Dropout(0.2),
            nn.Linear(exogenous_hidden, exogenous_hidden),
            nn.GELU(),
        )

        combined_dim = hidden_channels + exogenous_hidden + embedding_dim
        self.shared = nn.Sequential(
            nn.Linear(combined_dim, 96),
            nn.GELU(),
            nn.Dropout(0.2),
            nn.Linear(96, 48),
            nn.GELU(),
        )
        self.classifier = nn.Linear(48, 1)
        self.regressor = nn.Linear(48, 1)

    def forward(
        self, sequence: torch.Tensor, static_features: torch.Tensor, site_index: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        x = sequence.transpose(1, 2)
        x = self.input_projection(x)
        x = self.blocks(x)
        x = self.pool(x).squeeze(-1)
        site = self.site_embedding(site_index)
        exo = self.exogenous_net(static_features)
        combined = torch.cat([x, exo, site], dim=-1)
        shared = self.shared(combined)
        return self.classifier(shared).squeeze(-1), self.regressor(shared).squeeze(-1)


class BeachLSTM(nn.Module):
    def __init__(
        self,
        sequence_features: int,
        static_features: int,
        num_sites: int,
        hidden_channels: int = 32,
        embedding_dim: int = 16,
        exogenous_hidden: int = 32,
    ) -> None:
        super().__init__()
        self.site_embedding = nn.Embedding(num_sites, embedding_dim)
        self.lstm = nn.LSTM(
            input_size=sequence_features,
            hidden_size=hidden_channels,
            num_layers=2,
            batch_first=True,
            dropout=0.2
        )
        self.exogenous_net = nn.Sequential(
            nn.Linear(static_features, exogenous_hidden),
            nn.LayerNorm(exogenous_hidden),
            nn.GELU(),
            nn.Dropout(0.2),
            nn.Linear(exogenous_hidden, exogenous_hidden),
            nn.GELU(),
        )

        combined_dim = hidden_channels + exogenous_hidden + embedding_dim
        self.shared = nn.Sequential(
            nn.Linear(combined_dim, 96),
            nn.GELU(),
            nn.Dropout(0.2),
            nn.Linear(96, 48),
            nn.GELU(),
        )
        self.classifier = nn.Linear(48, 1)
        self.regressor = nn.Linear(48, 1)

    def forward(
        self, sequence: torch.Tensor, static_features: torch.Tensor, site_index: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        lstm_out, _ = self.lstm(sequence)
        x = lstm_out[:, -1, :]
        site = self.site_embedding(site_index)
        exo = self.exogenous_net(static_features)
        combined = torch.cat([x, exo, site], dim=-1)
        shared = self.shared(combined)
        return self.classifier(shared).squeeze(-1), self.regressor(shared).squeeze(-1)


class BeachTransformer(nn.Module):
    def __init__(
        self,
        sequence_features: int,
        static_features: int,
        num_sites: int,
        hidden_channels: int = 32,
        embedding_dim: int = 16,
        exogenous_hidden: int = 32,
    ) -> None:
        super().__init__()
        self.site_embedding = nn.Embedding(num_sites, embedding_dim)
        
        self.input_projection = nn.Linear(sequence_features, hidden_channels)
        
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=hidden_channels, 
            nhead=4, 
            dim_feedforward=hidden_channels * 2, 
            dropout=0.2, 
            batch_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=2)
        
        self.exogenous_net = nn.Sequential(
            nn.Linear(static_features, exogenous_hidden),
            nn.LayerNorm(exogenous_hidden),
            nn.GELU(),
            nn.Dropout(0.2),
            nn.Linear(exogenous_hidden, exogenous_hidden),
            nn.GELU(),
        )

        combined_dim = hidden_channels + exogenous_hidden + embedding_dim
        self.shared = nn.Sequential(
            nn.Linear(combined_dim, 96),
            nn.GELU(),
            nn.Dropout(0.2),
            nn.Linear(96, 48),
            nn.GELU(),
        )
        self.classifier = nn.Linear(48, 1)
        self.regressor = nn.Linear(48, 1)

    def forward(
        self, sequence: torch.Tensor, static_features: torch.Tensor, site_index: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        x = self.input_projection(sequence)
        x = self.transformer(x)
        x = x.mean(dim=1)
        
        site = self.site_embedding(site_index)
        exo = self.exogenous_net(static_features)
        combined = torch.cat([x, exo, site], dim=-1)
        shared = self.shared(combined)
        return self.classifier(shared).squeeze(-1), self.regressor(shared).squeeze(-1)


class BeachPINN_MultiTask(nn.Module):
    def __init__(
        self,
        sequence_features: int,
        static_features: int,
        num_sites: int,
        hidden_channels: int = 32,
        embedding_dim: int = 16,
        exogenous_hidden: int = 32,
    ) -> None:
        super().__init__()
        self.site_embedding = nn.Embedding(num_sites, embedding_dim)
        
        self.input_projection = nn.Conv1d(sequence_features, hidden_channels, kernel_size=1)
        self.blocks = nn.Sequential(
            TemporalBlock(hidden_channels, dilation=1),
            TemporalBlock(hidden_channels, dilation=2),
            TemporalBlock(hidden_channels, dilation=4),
            TemporalBlock(hidden_channels, dilation=8),
        )
        self.pool = nn.AdaptiveAvgPool1d(1)
        
        self.exogenous_net = nn.Sequential(
            nn.Linear(static_features, exogenous_hidden),
            nn.LayerNorm(exogenous_hidden),
            nn.GELU(),
            nn.Dropout(0.2),
            nn.Linear(exogenous_hidden, exogenous_hidden),
            nn.GELU(),
        )

        combined_dim = hidden_channels + exogenous_hidden + embedding_dim
        self.shared = nn.Sequential(
            nn.Linear(combined_dim, 96),
            nn.GELU(),
            nn.Dropout(0.2),
            nn.Linear(96, 48),
            nn.GELU(),
        )
        self.classifier = nn.Linear(48, 1)
        self.regressor = nn.Linear(48, 1)
        
        self.physics_out = nn.Linear(48, 1)

    def forward(
        self, sequence: torch.Tensor, static_features: torch.Tensor, site_index: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        x = sequence.transpose(1, 2)
        x = self.input_projection(x)
        x = self.blocks(x)
        x = self.pool(x).squeeze(-1)
        site = self.site_embedding(site_index)
        exo = self.exogenous_net(static_features)
        combined = torch.cat([x, exo, site], dim=-1)
        shared = self.shared(combined)
        
        return (
            self.classifier(shared).squeeze(-1), 
            self.regressor(shared).squeeze(-1), 
            self.physics_out(shared).squeeze(-1)
        )


def persistence_probabilities(frame: pd.DataFrame) -> np.ndarray:
    latest = frame.groupby("beach_id")["exceeds_stv"].shift(1).fillna(0.0)
    return latest.to_numpy(dtype=float)
