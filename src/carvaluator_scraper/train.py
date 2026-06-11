from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy.stats import chi2_contingency, pearsonr
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor, RandomForestRegressor, VotingRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, cross_val_score, train_test_split
from sklearn.neighbors import KNeighborsRegressor
from sklearn.pipeline import Pipeline
from sklearn.linear_model import Ridge
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.svm import SVR


TARGET_COLUMN = "price_eur"
CURRENT_YEAR = datetime.now(timezone.utc).year
BASE_FEATURE_COLUMNS = [
    "make",
    "model",
    "make_model",
    "version",
    "year",
    "vehicle_age",
    "first_registration_month",
    "first_registration_year",
    "mileage_km",
    "mileage_per_year",
    "fuel_type",
    "transmission",
    "body_type",
    "power_hp",
    "engine_capacity_cm3",
    "hp_per_liter",
    "seller_type",
    "location_city",
    "location_region",
]

NUMERIC_FEATURES = [
    "year",
    "vehicle_age",
    "first_registration_month",
    "first_registration_year",
    "mileage_km",
    "mileage_per_year",
    "power_hp",
    "engine_capacity_cm3",
    "hp_per_liter",
]

CATEGORICAL_FEATURES = [
    "make",
    "model",
    "make_model",
    "version",
    "fuel_type",
    "transmission",
    "body_type",
    "seller_type",
    "location_city",
    "location_region",
]

DEFAULT_FEATURE_SELECTION_ALPHA = 0.05
DEFAULT_MIN_ABS_PEARSON = 0.05
DEFAULT_MIN_CRAMERS_V = 0.25


def load_training_frame(csv_path: Path) -> pd.DataFrame:
    frame = pd.read_csv(csv_path)
    frame = frame.dropna(subset=[TARGET_COLUMN])
    frame = clean_training_frame(frame)
    frame = enrich_training_frame(frame)
    return frame


def build_preprocessor(scale_numeric: bool, feature_columns: list[str]) -> ColumnTransformer:
    numeric_features = [column for column in NUMERIC_FEATURES if column in feature_columns]
    categorical_features = [column for column in CATEGORICAL_FEATURES if column in feature_columns]
    numeric_steps: list[tuple[str, Any]] = [("imputer", SimpleImputer(strategy="median"))]
    if scale_numeric:
        numeric_steps.append(("scaler", StandardScaler()))

    categorical_pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]
    )

    return ColumnTransformer(
        transformers=[
            ("num", Pipeline(steps=numeric_steps), numeric_features),
            ("cat", categorical_pipeline, categorical_features),
        ]
    )


def build_models(random_state: int, feature_columns: list[str]) -> dict[str, Pipeline]:
    base_models = {
        "svr_rbf": Pipeline(
            steps=[
                ("preprocessor", build_preprocessor(scale_numeric=True, feature_columns=feature_columns)),
                ("model", SVR(C=55.0, epsilon=0.08, kernel="rbf")),
            ]
        ),
        "ridge": Pipeline(
            steps=[
                ("preprocessor", build_preprocessor(scale_numeric=True, feature_columns=feature_columns)),
                ("model", Ridge(alpha=2.0)),
            ]
        ),
        "knn_distance": Pipeline(
            steps=[
                ("preprocessor", build_preprocessor(scale_numeric=True, feature_columns=feature_columns)),
                ("model", KNeighborsRegressor(n_neighbors=13, weights="distance", metric="minkowski")),
            ]
        ),
        "random_forest": Pipeline(
            steps=[
                ("preprocessor", build_preprocessor(scale_numeric=False, feature_columns=feature_columns)),
                (
                    "model",
                    RandomForestRegressor(
                        n_estimators=450,
                        min_samples_leaf=2,
                        random_state=random_state,
                        n_jobs=-1,
                    ),
                ),
            ]
        ),
        "extra_trees": Pipeline(
            steps=[
                ("preprocessor", build_preprocessor(scale_numeric=False, feature_columns=feature_columns)),
                (
                    "model",
                    ExtraTreesRegressor(
                        n_estimators=500,
                        min_samples_leaf=2,
                        random_state=random_state,
                        n_jobs=-1,
                    ),
                ),
            ]
        ),
        "gradient_boosting": Pipeline(
            steps=[
                ("preprocessor", build_preprocessor(scale_numeric=False, feature_columns=feature_columns)),
                (
                    "model",
                    GradientBoostingRegressor(
                        n_estimators=350,
                        learning_rate=0.05,
                        max_depth=3,
                        subsample=0.9,
                        random_state=random_state,
                    ),
                ),
            ]
        ),
    }
    base_models["voting_ensemble"] = VotingRegressor(
        estimators=[
            ("svr_rbf", base_models["svr_rbf"]),
            ("extra_trees", base_models["extra_trees"]),
            ("gradient_boosting", base_models["gradient_boosting"]),
            ("knn_distance", base_models["knn_distance"]),
        ],
        weights=[4, 3, 2, 2],
    )
    return base_models


def train_and_evaluate(
    frame: pd.DataFrame,
    *,
    output_dir: Path,
    random_state: int = 42,
    test_size: float = 0.2,
    feature_selection_alpha: float = DEFAULT_FEATURE_SELECTION_ALPHA,
    min_abs_pearson: float = DEFAULT_MIN_ABS_PEARSON,
    min_cramers_v: float = DEFAULT_MIN_CRAMERS_V,
    disable_feature_selection: bool = False,
    log_target: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    available_features = [
        column
        for column in BASE_FEATURE_COLUMNS
        if column in frame.columns and frame[column].notna().sum() > 0
    ]
    model_frame = frame[available_features + [TARGET_COLUMN, "title", "source_listing_key"]].copy()
    x = model_frame[available_features]
    y = model_frame[TARGET_COLUMN]
    split_bins = build_target_bins(y)

    x_train, x_test, y_train, y_test, meta_train, meta_test = train_test_split(
        x,
        y,
        model_frame[["title", "source_listing_key"]],
        test_size=test_size,
        random_state=random_state,
        stratify=split_bins,
    )

    significance_frame = analyze_feature_significance(
        x_train.assign(**{TARGET_COLUMN: y_train.values}),
        feature_columns=available_features,
        target_column=TARGET_COLUMN,
        alpha=feature_selection_alpha,
        min_abs_pearson=min_abs_pearson,
        min_cramers_v=min_cramers_v,
    )
    significance_frame.to_csv(output_dir / "feature_significance.csv", index=False)

    if disable_feature_selection:
        selected_features = available_features
    else:
        selected_features = significance_frame.loc[significance_frame["keep_feature"], "feature"].tolist()
        if not selected_features:
            selected_features = available_features

    metrics: list[dict[str, Any]] = []
    best_name: str | None = None
    best_rmse = float("inf")
    best_predictions: pd.DataFrame | None = None
    best_pipeline: Pipeline | None = None
    trained_pipelines: dict[str, Any] = {}
    cv_splitter = build_cv_splitter()
    train_target = np.log1p(y_train) if log_target else y_train

    for name, pipeline in build_models(random_state, selected_features).items():
        pipeline.fit(x_train[selected_features], train_target)
        trained_pipelines[name] = pipeline
        raw_predictions = pipeline.predict(x_test[selected_features])
        predictions = np.expm1(raw_predictions) if log_target else raw_predictions
        predictions = np.clip(predictions, a_min=0, a_max=None)
        rmse = mean_squared_error(y_test, predictions) ** 0.5
        mae = mean_absolute_error(y_test, predictions)
        r2 = r2_score(y_test, predictions)
        cv_scores = cross_val_score(
            pipeline,
            x_train[selected_features],
            train_target,
            cv=cv_splitter,
            scoring="neg_root_mean_squared_error",
            n_jobs=1,
        )
        cv_rmse = float(abs(cv_scores.mean()))
        metrics.append(
            {
                "model": name,
                "rmse": float(rmse),
                "mae": float(mae),
                "r2": float(r2),
                "cv_rmse": cv_rmse,
                "trained_on_log_price": log_target,
            }
        )

        prediction_frame = meta_test.copy()
        prediction_frame["actual_price_eur"] = y_test.values
        prediction_frame["predicted_price_eur"] = predictions
        prediction_frame["abs_error_eur"] = (prediction_frame["actual_price_eur"] - prediction_frame["predicted_price_eur"]).abs()
        prediction_frame["model"] = name
        prediction_frame.to_csv(output_dir / f"predictions_{name}.csv", index=False)

        if rmse < best_rmse:
            best_rmse = rmse
            best_name = name
            best_predictions = prediction_frame
            best_pipeline = pipeline

    metrics_frame = pd.DataFrame(metrics).sort_values("rmse")
    metrics_frame.to_csv(output_dir / "metrics.csv", index=False)
    _make_dataset_plots(frame, output_dir)
    _make_model_performance_plot(metrics_frame, output_dir)
    if best_predictions is not None:
        best_predictions.sort_values("abs_error_eur", ascending=False).to_csv(
            output_dir / "best_model_predictions.csv",
            index=False,
        )
        _make_prediction_plot(best_predictions, best_name or "best_model", output_dir)
    if best_pipeline is not None and best_name is not None:
        save_model_bundle(
            output_dir / "best_model.joblib",
            pipeline=best_pipeline,
            model_name=best_name,
            selected_features=selected_features,
            log_target=log_target,
            feature_selection={
                "enabled": not disable_feature_selection,
                "alpha": feature_selection_alpha,
                "min_abs_pearson": min_abs_pearson,
                "min_cramers_v": min_cramers_v,
            },
            metrics=metrics,
            all_pipelines=trained_pipelines,
        )

    report = {
        "row_count": int(len(frame)),
        "train_rows": int(len(x_train)),
        "test_rows": int(len(x_test)),
        "target": TARGET_COLUMN,
        "candidate_features": available_features,
        "selected_features": selected_features,
        "feature_selection": {
            "enabled": not disable_feature_selection,
            "alpha": feature_selection_alpha,
            "min_abs_pearson": min_abs_pearson,
            "min_cramers_v": min_cramers_v,
        },
        "log_target": log_target,
        "models": metrics,
        "best_model": best_name,
        "cleaning": summarize_cleaning(frame),
    }
    (output_dir / "training_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def save_model_bundle(
    path: Path,
    *,
    pipeline: Pipeline,
    model_name: str,
    selected_features: list[str],
    log_target: bool,
    feature_selection: dict[str, Any],
    metrics: list[dict[str, Any]],
    all_pipelines: dict[str, Any],
) -> None:
    bundle = {
        "pipeline": pipeline,
        "model_name": model_name,
        "selected_features": selected_features,
        "log_target": log_target,
        "feature_selection": feature_selection,
        "metrics": metrics,
        "all_pipelines": all_pipelines,
        "target_column": TARGET_COLUMN,
    }
    joblib.dump(bundle, path)


def clean_training_frame(frame: pd.DataFrame) -> pd.DataFrame:
    cleaned = frame.copy()
    valid_power = cleaned["power_hp"].isna() | cleaned["power_hp"].between(30, 900, inclusive="both")
    valid_engine = cleaned["engine_capacity_cm3"].isna() | cleaned["engine_capacity_cm3"].between(600, 8000, inclusive="both")
    cleaned = cleaned[
        cleaned[TARGET_COLUMN].between(750, 250000, inclusive="both")
        & cleaned["year"].fillna(0).between(1995, CURRENT_YEAR, inclusive="both")
        & cleaned["mileage_km"].fillna(0).between(0, 500000, inclusive="both")
        & valid_power
        & valid_engine
    ].copy()
    lower_quantile = cleaned[TARGET_COLUMN].quantile(0.01)
    upper_quantile = cleaned[TARGET_COLUMN].quantile(0.995)
    cleaned = cleaned[cleaned[TARGET_COLUMN].between(lower_quantile, upper_quantile, inclusive="both")].copy()
    return cleaned


def enrich_training_frame(frame: pd.DataFrame) -> pd.DataFrame:
    enriched = frame.copy()
    enriched["make_model"] = (
        enriched["make"].fillna("").astype(str).str.strip() + " " + enriched["model"].fillna("").astype(str).str.strip()
    ).str.strip()
    enriched["make_model"] = enriched["make_model"].replace("", pd.NA)
    enriched["vehicle_age"] = enriched["year"].apply(lambda value: CURRENT_YEAR - value if pd.notna(value) else np.nan)
    enriched["vehicle_age"] = enriched["vehicle_age"].clip(lower=0)
    enriched["mileage_per_year"] = enriched["mileage_km"] / enriched["vehicle_age"].replace({0: np.nan})
    enriched["mileage_per_year"] = enriched["mileage_per_year"].replace([np.inf, -np.inf], np.nan)
    enriched["hp_per_liter"] = (
        enriched["power_hp"] / (enriched["engine_capacity_cm3"] / 1000.0).replace({0: np.nan})
    )
    enriched["hp_per_liter"] = enriched["hp_per_liter"].replace([np.inf, -np.inf], np.nan)
    return enriched


def summarize_cleaning(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "price_min": float(frame[TARGET_COLUMN].min()),
        "price_max": float(frame[TARGET_COLUMN].max()),
        "year_min": int(frame["year"].min()) if frame["year"].notna().any() else None,
        "year_max": int(frame["year"].max()) if frame["year"].notna().any() else None,
    }


def build_target_bins(target: pd.Series) -> pd.Series | None:
    try:
        bins = pd.qcut(target, q=5, duplicates="drop")
    except ValueError:
        return None
    return bins if bins.nunique() >= 2 else None


def build_cv_splitter() -> KFold:
    return KFold(n_splits=3, shuffle=True, random_state=42)


def analyze_feature_significance(
    frame: pd.DataFrame,
    *,
    feature_columns: list[str],
    target_column: str,
    alpha: float,
    min_abs_pearson: float,
    min_cramers_v: float,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for feature in feature_columns:
        if feature in NUMERIC_FEATURES:
            rows.append(
                analyze_numeric_feature(
                    frame,
                    feature=feature,
                    target_column=target_column,
                    alpha=alpha,
                    min_abs_pearson=min_abs_pearson,
                )
            )
        else:
            rows.append(
                analyze_categorical_feature(
                    frame,
                    feature=feature,
                    target_column=target_column,
                    alpha=alpha,
                    min_cramers_v=min_cramers_v,
                )
            )
    return pd.DataFrame(rows).sort_values(["keep_feature", "score"], ascending=[False, False])


def analyze_numeric_feature(
    frame: pd.DataFrame,
    *,
    feature: str,
    target_column: str,
    alpha: float,
    min_abs_pearson: float,
) -> dict[str, Any]:
    subset = frame[[feature, target_column]].dropna()
    if len(subset) < 3 or subset[feature].nunique() < 2:
        return {
            "feature": feature,
            "feature_type": "numeric",
            "test": "pearson",
            "sample_size": int(len(subset)),
            "unique_values": int(subset[feature].nunique()) if len(subset) else 0,
            "score": 0.0,
            "effect_size": 0.0,
            "p_value": None,
            "keep_feature": False,
            "reason": "not enough variation",
        }

    correlation, p_value = pearsonr(subset[feature], subset[target_column])
    effect_size = abs(float(correlation))
    keep = bool(p_value < alpha and effect_size >= min_abs_pearson)
    return {
        "feature": feature,
        "feature_type": "numeric",
        "test": "pearson",
        "sample_size": int(len(subset)),
        "unique_values": int(subset[feature].nunique()),
        "score": effect_size,
        "effect_size": effect_size,
        "p_value": float(p_value),
        "keep_feature": keep,
        "reason": "kept" if keep else "low pearson significance",
    }


def analyze_categorical_feature(
    frame: pd.DataFrame,
    *,
    feature: str,
    target_column: str,
    alpha: float,
    min_cramers_v: float,
) -> dict[str, Any]:
    subset = frame[[feature, target_column]].dropna().copy()
    if len(subset) < 5 or subset[feature].nunique() < 2:
        return {
            "feature": feature,
            "feature_type": "categorical",
            "test": "chi_square_binned_target",
            "sample_size": int(len(subset)),
            "unique_values": int(subset[feature].nunique()) if len(subset) else 0,
            "score": 0.0,
            "effect_size": 0.0,
            "p_value": None,
            "keep_feature": False,
            "reason": "not enough variation",
        }

    try:
        subset["target_bin"] = pd.qcut(subset[target_column], q=5, duplicates="drop")
    except ValueError:
        return {
            "feature": feature,
            "feature_type": "categorical",
            "test": "chi_square_binned_target",
            "sample_size": int(len(subset)),
            "unique_values": int(subset[feature].nunique()),
            "score": 0.0,
            "effect_size": 0.0,
            "p_value": None,
            "keep_feature": False,
            "reason": "target could not be binned",
        }

    if subset["target_bin"].nunique() < 2:
        return {
            "feature": feature,
            "feature_type": "categorical",
            "test": "chi_square_binned_target",
            "sample_size": int(len(subset)),
            "unique_values": int(subset[feature].nunique()),
            "score": 0.0,
            "effect_size": 0.0,
            "p_value": None,
            "keep_feature": False,
            "reason": "target bins not informative",
        }

    contingency = pd.crosstab(subset[feature].astype(str), subset["target_bin"])
    if contingency.shape[0] < 2 or contingency.shape[1] < 2:
        return {
            "feature": feature,
            "feature_type": "categorical",
            "test": "chi_square_binned_target",
            "sample_size": int(len(subset)),
            "unique_values": int(subset[feature].nunique()),
            "score": 0.0,
            "effect_size": 0.0,
            "p_value": None,
            "keep_feature": False,
            "reason": "contingency too small",
        }

    chi2, p_value, _, _ = chi2_contingency(contingency)
    sample_size = int(contingency.to_numpy().sum())
    phi2 = chi2 / sample_size if sample_size else 0.0
    row_count, col_count = contingency.shape
    cramers_v = math.sqrt(phi2 / max(1, min(row_count - 1, col_count - 1)))
    keep = bool(p_value < alpha and cramers_v >= min_cramers_v)
    return {
        "feature": feature,
        "feature_type": "categorical",
        "test": "chi_square_binned_target",
        "sample_size": sample_size,
        "unique_values": int(subset[feature].nunique()),
        "score": float(cramers_v),
        "effect_size": float(cramers_v),
        "p_value": float(p_value),
        "keep_feature": keep,
        "reason": "kept" if keep else "low chi-square significance",
    }


def _make_dataset_plots(frame: pd.DataFrame, output_dir: Path) -> None:
    sns.set_theme(style="whitegrid")

    plt.figure(figsize=(9, 5))
    sns.histplot(frame[TARGET_COLUMN], bins=30, kde=True)
    plt.title("Price Distribution")
    plt.xlabel("Price (EUR)")
    plt.tight_layout()
    plt.savefig(output_dir / "price_distribution.png", dpi=150)
    plt.close()

    plt.figure(figsize=(9, 5))
    sns.scatterplot(data=frame, x="mileage_km", y=TARGET_COLUMN, hue="fuel_type", alpha=0.7)
    plt.title("Price vs Mileage")
    plt.tight_layout()
    plt.savefig(output_dir / "price_vs_mileage.png", dpi=150)
    plt.close()

    corr_frame = frame[["year", "mileage_km", "power_hp", "engine_capacity_cm3", TARGET_COLUMN]].copy()
    corr = corr_frame.corr(numeric_only=True)
    plt.figure(figsize=(6, 5))
    sns.heatmap(corr, annot=True, cmap="Blues", fmt=".2f")
    plt.title("Numeric Correlation Heatmap")
    plt.tight_layout()
    plt.savefig(output_dir / "correlation_heatmap.png", dpi=150)
    plt.close()


def _make_prediction_plot(predictions: pd.DataFrame, model_name: str, output_dir: Path) -> None:
    plt.figure(figsize=(6, 6))
    sns.scatterplot(data=predictions, x="actual_price_eur", y="predicted_price_eur")
    max_value = max(predictions["actual_price_eur"].max(), predictions["predicted_price_eur"].max())
    plt.plot([0, max_value], [0, max_value], linestyle="--", color="red")
    plt.title(f"Actual vs Predicted Prices ({model_name})")
    plt.xlabel("Actual Price (EUR)")
    plt.ylabel("Predicted Price (EUR)")
    plt.tight_layout()
    plt.savefig(output_dir / "actual_vs_predicted.png", dpi=150)
    plt.close()


def _make_model_performance_plot(metrics: pd.DataFrame, output_dir: Path) -> None:
    plot_frame = metrics.sort_values("rmse").copy()
    plt.figure(figsize=(10, 5.5))
    sns.barplot(data=plot_frame, x="rmse", y="model", hue="model", palette="viridis", legend=False)
    plt.title("Model Performance by Test RMSE")
    plt.xlabel("RMSE (EUR, lower is better)")
    plt.ylabel("Model")
    for index, row in enumerate(plot_frame.itertuples(index=False)):
        plt.text(float(row.rmse) * 1.01, index, f"R2={float(row.r2):.3f}", va="center", fontsize=9)
    plt.tight_layout()
    plt.savefig(output_dir / "model_performance.png", dpi=150)
    plt.close()
