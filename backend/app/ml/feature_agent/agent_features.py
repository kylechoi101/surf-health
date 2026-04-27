"""
Auto-generated features from the meta-learning feature-discovery agent.
Do not edit manually — entries are appended by run_agent.py when a feature
passes both the univariate AUCPR gate and the CV gate.

Each function signature:
    def build_novel_feature_NNN(beach_day_df, advisories_df, stations_df, **kwargs)
        -> pd.DataFrame  # columns: beach_id, sample_date, <feature_name>

AGENT_BUILDERS is imported by training.py to inject features before
_model_feature_columns selects the final column list.
"""
import pandas as pd
import numpy as np

AGENT_BUILDERS: list = []
