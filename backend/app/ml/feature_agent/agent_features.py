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


import pandas as pd
import numpy as np

def build_novel_feature_1(beach_day_df, advisories_df, stations_df, **kwargs):
    """
    Engineers the 'regional_active_advisory_ratio' feature.
    
    Hypothesis: A high proportion of active advisories across a region indicates a 
    systemic pollution event that increases the probability of an exceedance 
    at any individual beach within that same region.
    """
    
    # 1. Map every advisory record to its corresponding region
    # advisories_df: [beach_id, started_at, ended_at, cause]
    # stations_df: [beach_id, region, ...]
    advisories_with_region = advisories_df.merge(
        stations_df[['beach_id', 'region']], 
        on='beach_id', 
        how='left'
    )
    
    # 2. To avoid a massive Cartesian product on the full beach_day_df, 
    # we only calculate the ratio for unique (sample_date, region) pairs.
    unique_dates_regions = beach_day_df[['sample_date', 'region']].drop_duplicates()
    
    # 3. Join unique date-region pairs with advisories in the same region
    # This creates a temporary table of all advisories that *could* have been active 
    # in a region on a specific date.
    merged = unique_dates_regions.merge(
        advisories_with_region, 
        on='region', 
        how='inner'
    )
    
    # 4. Filter for advisories that were actually active at that moment
    # Condition: started_at <= sample_date AND (ended_at > sample_date OR ended_at is NaT)
    active_mask = (
        (merged['sample_date'] >= merged['started_at']) & 
        ((merged['sample_date'] < merged['ended_at']) | (merged['ended_at'].isna()))
    )
    active_advisories = merged[active_mask]
    
    # 5. Count concurrently active advisories per region per date
    regional_counts = active_advisories.groupby(['sample_date', 'region']).size().reset_index(name='active_count')
    
    # 6. Calculate total number of beaches per region for the denominator
    region_totals = stations_df.groupby('region').size().reset_index(name='total_beaches')
    
    # 7. Compute the ratio: (active advisories in region) / (total beaches in region)
    ratios = regional_counts.merge(region_totals, on='region', how='left')
    ratios['regional_active_advisory_ratio'] = (
        ratios['active_count'] / (ratios['total_beaches'] + 1e-9)
    )
    
    # 8. Join the calculated ratio back to the original beach_day_df
    # We only need beach_id and sample_date for the final output
    final_df = beach_day_df[['beach_id', 'sample_date', 'region']].merge(
        ratios[['sample_date', 'region', 'regional_active_advisory_ratio']], 
        on=['sample_date', 'region'], 
        how='left'
    )
    
    # Fill NaNs with 0 (meaning no active advisories were found for that region/date)
    final_df['regional_active_advisory_ratio'] = final_df['regional_active_advisory_ratio'].fillna(0)
    
    # Return only the required columns
    return final_df[['beach_id', 'sample_date', 'regional_active_advisory_ratio']]
AGENT_BUILDERS.append(build_novel_feature_1)


import pandas as pd
import numpy as np

def build_novel_feature_2(beach_day_df, advisories_df, stations_df, **kwargs):
    """
    Engineers the 'freshwater_plume_intensity' feature.
    
    Hypothesis: A simultaneous drop in salinity and spike in streamflow indicates 
    a concentrated freshwater plume reaching the beach, transporting land-based enterococcus.
    """
    # 1. Prepare a working copy with only necessary columns and sort for time-based rolling
    df = beach_day_df[['beach_id', 'sample_date', 'salinity_psu', 'streamflow_cfs_latest']].copy()
    df = df.sort_values(['beach_id', 'sample_date'])

    # 2. Set sample_date as index to enable time-based rolling windows ('30D')
    df = df.set_index('sample_date')

    # 3. Calculate 30-day rolling means for salinity and streamflow
    # closed='left' ensures the current sample is not included in its own window
    rolling_stats = (
        df.groupby('beach_id')[['salinity_psu', 'streamflow_cfs_latest']]
        .rolling('30D', closed='left')
        .mean()
        .reset_index()
    )

    # 4. Rename rolling columns to avoid collisions during merge
    rolling_stats = rolling_stats.rename(columns={
        'salinity_psu': 'salinity_rolling_mean',
        'streamflow_cfs_latest': 'streamflow_rolling_mean'
    })

    # 5. Merge rolling statistics back to the main dataframe
    df = df.reset_index()
    df = df.merge(rolling_stats, on=['beach_id', 'sample_date'], how='left')

    # 6. Calculate Salinity Deficit: positive when current salinity is lower than the rolling mean
    salinity_deficit = df['salinity_rolling_mean'] - df['salinity_psu']

    # 7. Calculate Streamflow Surplus: positive when current streamflow is higher than the rolling mean
    streamflow_surplus = df['streamflow_cfs_latest'] - df['streamflow_rolling_mean']

    # 8. Calculate Feature: product of deficit and surplus, clipped at 0 to isolate co-occurrence
    df['freshwater_plume_intensity'] = (salinity_deficit * streamflow_surplus).clip(lower=0)

    # 9. Return only the required columns, ensuring sample_date remains datetime
    return df[['beach_id', 'sample_date', 'freshwater_plume_intensity']]
AGENT_BUILDERS.append(build_novel_feature_2)


import pandas as pd
import numpy as np

def build_novel_feature_54(beach_day_df, advisories_df, stations_df, **kwargs):
    df = beach_day_df[['beach_id', 'sample_date', 'streamflow_cfs_latest']].copy()
    df = df.sort_values(['beach_id', 'sample_date'])
    rolling_mean = (
        df.groupby('beach_id')['streamflow_cfs_latest']
        .rolling(window=7, min_periods=1, closed='left')
        .mean()
        .reset_index(level=0, drop=True)
    )
    ratio = df['streamflow_cfs_latest'] / (rolling_mean + 1e-9)
    ratio = np.clip(ratio, 0, 10)
    df['streamflow_spike_ratio_7d'] = (
        df.assign(_ratio=ratio)
        .groupby('beach_id')['_ratio']
        .shift(1)
        .values
    )
    return df[['beach_id', 'sample_date', 'streamflow_spike_ratio_7d']]
AGENT_BUILDERS.append(build_novel_feature_54)
