# Hyperparameter tuning (validation only)

Validation origins: 2025-04-01 to 2025-10-01 (exclusive). Training rows are purged so no training target falls at or after the validation start. The Phase 4 test period is never loaded. Early stopping uses this same validation block, so these scores are mildly optimistic; the backtest in `reports/results.md` is the real out-of-sample evaluation.

## Validation scores (all models on the same rows)

`neso_stored_forecast` is a short-lead nowcast, not a 24-48h forecast; it is shown for reference and is not a like-for-like comparison. `oracle_weather` uses observed weather at the target time and is a leaky upper bound.

| model | n | mae | rmse | mape | skill_vs_seasonal_naive_day |
|---|---|---|---|---|---|
| persistence | 35798.000 | 46.873 | 58.860 | 47.726 | -0.067 |
| seasonal_naive_day | 35798.000 | 43.928 | 55.208 | 42.953 | 0.000 |
| seasonal_naive_week | 35798.000 | 44.890 | 57.151 | 45.927 | -0.022 |
| neso_stored_forecast | 35798.000 | 9.064 | 12.191 | 8.667 | 0.794 |
| no_weather | 35798.000 | 34.712 | 42.752 | 39.822 | 0.210 |
| weather_forecast | 35798.000 | 24.384 | 30.587 | 24.336 | 0.445 |
| no_weather_short | 35798.000 | 38.902 | 48.116 | 40.033 | 0.114 |
| oracle_weather | 35798.000 | 23.504 | 29.057 | 25.599 | 0.465 |

## Chosen parameters

**no_weather** (validation MAE 34.677, 86 rounds): `{'objective': 'regression', 'learning_rate': 0.1, 'num_leaves': 31, 'min_data_in_leaf': 1000, 'feature_fraction': 0.8, 'bagging_fraction': 0.7, 'lambda_l2': 0.0, 'bagging_freq': 1}`

**weather_forecast** (validation MAE 24.446, 141 rounds): `{'objective': 'regression_l1', 'learning_rate': 0.03, 'num_leaves': 31, 'min_data_in_leaf': 200, 'feature_fraction': 0.6, 'bagging_fraction': 1.0, 'lambda_l2': 1.0, 'bagging_freq': 0}`

## All trials

| variant | trial | objective | learning_rate | num_leaves | min_data_in_leaf | feature_fraction | bagging_fraction | lambda_l2 | bagging_freq | best_iteration | val_mae | seconds |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| no_weather | 2 | regression | 0.100 | 31 | 1,000 | 0.800 | 0.700 | 0.000 | 1 | 86 | 34.677 | 1.800 |
| no_weather | 1 | regression | 0.030 | 127 | 50 | 0.600 | 0.700 | 10.000 | 1 | 218 | 34.976 | 10.300 |
| no_weather | 9 | regression | 0.050 | 31 | 50 | 0.600 | 1.000 | 1.000 | 0 | 129 | 35.313 | 2.400 |
| no_weather | 6 | regression_l1 | 0.030 | 31 | 200 | 0.600 | 1.000 | 1.000 | 0 | 202 | 35.377 | 3.700 |
| no_weather | 3 | regression | 0.030 | 63 | 1,000 | 1.000 | 0.700 | 10.000 | 1 | 209 | 35.445 | 5.300 |
| no_weather | 11 | regression_l1 | 0.100 | 31 | 1,000 | 1.000 | 0.700 | 10.000 | 1 | 55 | 35.600 | 1.700 |
| no_weather | 5 | regression | 0.100 | 255 | 200 | 0.800 | 0.700 | 0.000 | 1 | 48 | 35.791 | 7.700 |
| no_weather | 12 | regression | 0.030 | 255 | 200 | 0.800 | 0.700 | 10.000 | 1 | 166 | 35.816 | 13.900 |
| no_weather | 8 | regression_l1 | 0.100 | 127 | 1,000 | 0.600 | 0.700 | 0.000 | 1 | 47 | 35.895 | 4.700 |
| no_weather | 4 | regression | 0.100 | 255 | 50 | 0.800 | 1.000 | 0.000 | 0 | 53 | 35.983 | 7.900 |
| no_weather | 7 | regression_l1 | 0.030 | 255 | 1,000 | 0.600 | 1.000 | 0.000 | 0 | 157 | 36.155 | 13.300 |
| no_weather | 10 | regression_l1 | 0.100 | 127 | 50 | 0.800 | 1.000 | 0.000 | 0 | 55 | 36.272 | 4.600 |
| weather_forecast | 6 | regression_l1 | 0.030 | 31 | 200 | 0.600 | 1.000 | 1.000 | 0 | 141 | 24.446 | 1.800 |
| weather_forecast | 7 | regression_l1 | 0.030 | 255 | 1,000 | 0.600 | 1.000 | 0.000 | 0 | 172 | 24.500 | 3.000 |
| weather_forecast | 10 | regression_l1 | 0.100 | 127 | 50 | 0.800 | 1.000 | 0.000 | 0 | 45 | 24.650 | 3.500 |
| weather_forecast | 8 | regression_l1 | 0.100 | 127 | 1,000 | 0.600 | 0.700 | 0.000 | 1 | 56 | 24.684 | 1.300 |
| weather_forecast | 11 | regression_l1 | 0.100 | 31 | 1,000 | 1.000 | 0.700 | 10.000 | 1 | 47 | 24.928 | 1.100 |
| weather_forecast | 9 | regression | 0.050 | 31 | 50 | 0.600 | 1.000 | 1.000 | 0 | 87 | 25.126 | 1.400 |
| weather_forecast | 2 | regression | 0.100 | 31 | 1,000 | 0.800 | 0.700 | 0.000 | 1 | 37 | 25.160 | 0.900 |
| weather_forecast | 3 | regression | 0.030 | 63 | 1,000 | 1.000 | 0.700 | 10.000 | 1 | 134 | 25.206 | 1.800 |
| weather_forecast | 1 | regression | 0.030 | 127 | 50 | 0.600 | 0.700 | 10.000 | 1 | 140 | 25.480 | 6.300 |
| weather_forecast | 12 | regression | 0.030 | 255 | 200 | 0.800 | 0.700 | 10.000 | 1 | 131 | 25.607 | 7.200 |
| weather_forecast | 5 | regression | 0.100 | 255 | 200 | 0.800 | 0.700 | 0.000 | 1 | 28 | 25.680 | 4.100 |
| weather_forecast | 4 | regression | 0.100 | 255 | 50 | 0.800 | 1.000 | 0.000 | 0 | 45 | 26.357 | 6.500 |
