from __future__ import annotations

from dataclasses import dataclass
import os
import sys

# macOS only: torch + xgboost each bundle libomp; their OpenMP pools deadlock
# during torch training. Pin to one thread to break it (set before libomp loads).
# Not set on Linux/CI → full multithreaded performance.
if sys.platform == "darwin":
    os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np
import pandas as pd
# Import xgboost before torch: both ship a libomp, and on macOS loading torch's
# first then xgboost's segfaults (duplicate OpenMP runtime). Forcing xgboost's
# OpenMP to initialize first avoids it; harmless on Linux CI.
import xgboost  # noqa: F401
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


class XGBUndersampleEnsemble:
    """XGBoost balanced-undersample soft-ensemble (an EasyEnsemble variant).

    Keeps every positive and draws ``n_estimators_ensemble`` equal-size random
    undersamples of the majority class (``negative_ratio`` negatives per
    positive), fits one XGBoost per subsample, and soft-averages the per-class
    probabilities. Spatial leave-one-CA-county-out validation selected this over
    the incumbent single balanced GBM (+0.069 AUCPR / better Brier on held-out
    counties). sklearn-compatible fit/predict_proba so the existing isotonic
    calibration + spatial-gate machinery wrap it unchanged.
    """

    def __init__(
        self,
        *,
        n_estimators_ensemble: int = 12,
        negative_ratio: float = 2.0,
        n_estimators: int = 250,
        max_depth: int = 6,
        learning_rate: float = 0.05,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        random_state: int = 42,
        n_jobs: int = 12,
    ) -> None:
        self.n_estimators_ensemble = n_estimators_ensemble
        self.negative_ratio = negative_ratio
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.subsample = subsample
        self.colsample_bytree = colsample_bytree
        self.random_state = random_state
        self.n_jobs = n_jobs
        self.members_: list = []
        self.classes_ = np.array([0, 1])

    def _numeric(self, X: pd.DataFrame) -> pd.DataFrame:
        frame = X if isinstance(X, pd.DataFrame) else pd.DataFrame(X)
        return frame.select_dtypes(include=["number"]).fillna(0.0)

    def fit(self, X: pd.DataFrame, y) -> "XGBUndersampleEnsemble":
        from xgboost import XGBClassifier

        features = self._numeric(X).reset_index(drop=True)
        self.feature_names_ = list(features.columns)
        labels = np.asarray(y).astype(int)
        pos = np.flatnonzero(labels == 1)
        neg = np.flatnonzero(labels == 0)
        rng = np.random.default_rng(self.random_state)
        self.members_ = []
        # Degenerate single-class input: fall back to one plain fit so downstream
        # never crashes (the spatial gate already filters these folds out).
        if len(pos) < 1 or len(neg) < 1:
            model = XGBClassifier(
                n_estimators=self.n_estimators, max_depth=self.max_depth,
                learning_rate=self.learning_rate, subsample=self.subsample,
                colsample_bytree=self.colsample_bytree, eval_metric="aucpr",
                tree_method="hist", random_state=self.random_state,
                n_jobs=self.n_jobs, verbosity=0,
            )
            model.fit(features, labels)
            self.members_.append(model)
            return self
        k = min(int(len(pos) * self.negative_ratio), len(neg))
        for i in range(self.n_estimators_ensemble):
            draw = rng.choice(neg, size=k, replace=False)
            idx = np.concatenate([pos, draw])
            model = XGBClassifier(
                n_estimators=self.n_estimators, max_depth=self.max_depth,
                learning_rate=self.learning_rate, subsample=self.subsample,
                colsample_bytree=self.colsample_bytree, eval_metric="aucpr",
                tree_method="hist", random_state=self.random_state + i,
                n_jobs=self.n_jobs, verbosity=0,
            )
            model.fit(features.iloc[idx], labels[idx])
            self.members_.append(model)
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if not self.members_:
            raise RuntimeError("XGBUndersampleEnsemble is not fitted")
        features = self._numeric(X)
        if getattr(self, "feature_names_", None):
            features = features.reindex(columns=self.feature_names_, fill_value=0.0)
        positive = np.mean([m.predict_proba(features)[:, 1] for m in self.members_], axis=0)
        return np.column_stack([1.0 - positive, positive])

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)


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
