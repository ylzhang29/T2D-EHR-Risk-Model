from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from external_rf_common import (
    HORIZON_YEARS, MODEL_VARIANTS, RISK_COLUMNS, apply_logistic_calibration,
    calibration_metrics, curve_data, fit_logistic_calibration, horizon_data,
    read_table, save_json, weighted_calibration_table, weighted_metrics,
)


METRICS = ("roc_auc", "average_precision", "brier", "calibration_intercept",
           "calibration_slope", "observed_to_expected_ratio")


def parse_thresholds(value: str) -> np.ndarray:
    if not value.strip(): return np.array([], float)
    values = np.unique([float(item) for item in value.split(",") if item.strip()])
    if np.any((values <= 0) | (values >= 1)):
        raise ValueError("Decision thresholds must be strictly between 0 and 1")
    return values


def evaluated_view(frame: pd.DataFrame, risk_column: str) -> tuple[dict, pd.DataFrame]:
    y, weight, eligible = horizon_data(frame.dm2.to_numpy(bool), frame.event_years.to_numpy(float))
    evaluated = frame.loc[eligible].reset_index(drop=True).copy()
    evaluated["horizon_outcome"] = y[eligible]
    evaluated["ipcw"] = weight[eligible]
    risk = evaluated[risk_column].to_numpy(float)
    metrics = weighted_metrics(evaluated.horizon_outcome.to_numpy(int), risk, evaluated.ipcw.to_numpy(float))
    metrics.update(calibration_metrics(evaluated.horizon_outcome.to_numpy(int), risk, evaluated.ipcw.to_numpy(float)))
    return metrics, evaluated


def bootstrap(frame: pd.DataFrame, variants: list[str], thresholds: np.ndarray,
              replicates: int, seed: int) -> pd.DataFrame:
    if replicates <= 0: return pd.DataFrame()
    rng = np.random.default_rng(seed); rows = []; n = len(frame)
    for replicate in range(replicates):
        sample = frame.iloc[rng.integers(0, n, n)].reset_index(drop=True)
        record = {"replicate": replicate}
        try:
            for variant in variants:
                metrics, view = evaluated_view(sample, RISK_COLUMNS[variant])
                for name in METRICS: record[f"{variant}__{name}"] = metrics[name]
                decision, impact = decision_tables(view, RISK_COLUMNS[variant], thresholds)
                for row in decision.itertuples(index=False):
                    token = f"{row.threshold:.10g}"
                    record[f"{variant}__net_benefit__{token}"] = row.net_benefit_model
                for row in impact.itertuples(index=False):
                    token = f"{row.threshold:.10g}"
                    for name in ("high_risk_per_1000", "true_positives_per_1000", "sensitivity", "positive_predictive_value", "alerts_per_true_positive"):
                        record[f"{variant}__{name}__{token}"] = getattr(row, name)
            if len(variants) == 2:
                for name in METRICS[:3]:
                    record[f"compact5_minus_compact10__{name}"] = record[f"compact5__{name}"] - record[f"compact10__{name}"]
            rows.append(record)
        except ValueError:
            continue
        if (replicate + 1) % 50 == 0: print(f"Bootstrap {replicate + 1}/{replicates}", flush=True)
    return pd.DataFrame(rows)


def interval_rows(points: dict[str, dict], boot: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for variant, metrics in points.items():
        for name in METRICS:
            values = boot.get(f"{variant}__{name}", pd.Series(dtype=float)).dropna().to_numpy(float)
            rows.append({"model_variant": variant, "metric": name, "estimate": metrics[name],
                         "ci_95_lower": float(np.quantile(values, .025)) if len(values) else np.nan,
                         "ci_95_upper": float(np.quantile(values, .975)) if len(values) else np.nan,
                         "bootstrap_replicates_valid": int(len(values))})
    return pd.DataFrame(rows)


def decision_tables(evaluated: pd.DataFrame, risk_column: str, thresholds: np.ndarray) -> tuple[pd.DataFrame, pd.DataFrame]:
    y = evaluated.horizon_outcome.to_numpy(bool); risk = evaluated[risk_column].to_numpy(float)
    weight = evaluated.ipcw.to_numpy(float); total = weight.sum(); prevalence = np.sum(weight * y) / total
    dca = []; cic = []
    for threshold in thresholds:
        positive = risk >= threshold
        tp = weight[positive & y].sum(); fp = weight[positive & ~y].sum(); high = weight[positive].sum()
        positives = weight[y].sum()
        dca.append({"threshold": threshold, "net_benefit_model": tp / total - fp / total * threshold / (1-threshold),
                    "net_benefit_treat_all": prevalence - (1-prevalence) * threshold / (1-threshold),
                    "net_benefit_treat_none": 0.0})
        cic.append({"threshold": threshold, "high_risk_per_1000": high/total*1000,
                    "true_positives_per_1000": tp/total*1000,
                    "sensitivity": tp/max(positives, 1e-12), "positive_predictive_value": tp/max(high, 1e-12),
                    "alerts_per_true_positive": high/max(tp, 1e-12)})
    return pd.DataFrame(dca), pd.DataFrame(cic)


def decision_interval_rows(dca: dict[str,pd.DataFrame], cic: dict[str,pd.DataFrame],
                           boot: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for variant in dca:
        for source, table, metrics in (
            ("DCA",dca[variant],["net_benefit_model"]),
            ("CIC",cic[variant],["high_risk_per_1000","true_positives_per_1000","sensitivity","positive_predictive_value","alerts_per_true_positive"]),
        ):
            for row in table.itertuples(index=False):
                token=f"{row.threshold:.10g}"
                for metric in metrics:
                    key_metric="net_benefit" if metric=="net_benefit_model" else metric
                    values=boot.get(f"{variant}__{key_metric}__{token}",pd.Series(dtype=float)).replace([np.inf,-np.inf],np.nan).dropna().to_numpy(float)
                    rows.append({"model_variant":variant,"analysis":source,"threshold":row.threshold,"metric":metric,
                                 "estimate":getattr(row,metric),"ci_95_lower":float(np.quantile(values,.025)) if len(values) else np.nan,
                                 "ci_95_upper":float(np.quantile(values,.975)) if len(values) else np.nan,
                                 "bootstrap_replicates_valid":int(len(values))})
    return pd.DataFrame(rows)


def subgroup_table(frame: pd.DataFrame, variants: list[str], columns: list[str]) -> pd.DataFrame:
    rows = []
    for column in columns:
        if column not in frame: continue
        for level, part in frame.groupby(column, dropna=False):
            if len(part) < 100: continue
            for variant in variants:
                try: metrics, _ = evaluated_view(part.reset_index(drop=True), RISK_COLUMNS[variant])
                except ValueError: continue
                rows.append({"subgroup_variable": column, "level": str(level), "model_variant": variant, **metrics})
    return pd.DataFrame(rows)


def plot_results(output: Path, evaluated: dict[str, pd.DataFrame], calibrations: dict[str, pd.DataFrame],
                 dca: dict[str, pd.DataFrame], cic: dict[str, pd.DataFrame]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = {"compact5": "#005A9C", "compact10": "#E57A21"}
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    for variant, view in evaluated.items():
        y=view.horizon_outcome.to_numpy(int); w=view.ipcw.to_numpy(float); risk=view[RISK_COLUMNS[variant]].to_numpy(float)
        curves=curve_data(y,risk,w)
        curves["roc"].to_csv(output/f"{variant}_roc_curve.csv",index=False)
        curves["pr"].to_csv(output/f"{variant}_pr_curve.csv",index=False)
        axes[0].plot(curves["roc"].false_positive_rate,curves["roc"].true_positive_rate,label=variant,color=colors[variant])
        axes[1].plot(curves["pr"].recall,curves["pr"].precision,label=variant,color=colors[variant])
        cal=calibrations[variant]
        axes[2].plot(cal.mean_predicted,cal.observed_fraction,marker="o",label=variant,color=colors[variant])
        single, single_axes=plt.subplots(1,3,figsize=(15,4.5))
        single_axes[0].plot(curves["roc"].false_positive_rate,curves["roc"].true_positive_rate,color=colors[variant]); single_axes[0].plot([0,1],[0,1],"--",color="grey")
        single_axes[1].plot(curves["pr"].recall,curves["pr"].precision,color=colors[variant])
        single_axes[2].plot(cal.mean_predicted,cal.observed_fraction,marker="o",color=colors[variant]); single_axes[2].plot([0,.2],[0,.2],"--",color="grey")
        single_axes[0].set(xlabel="False-positive rate",ylabel="True-positive rate",title="ROC")
        single_axes[1].set(xlabel="Recall",ylabel="Precision",title="Precision-recall")
        single_axes[2].set(xlabel="Mean transported risk",ylabel="Observed 5-year risk",title="Calibration",xlim=(0,.2),ylim=(0,.2))
        single.suptitle(variant); single.tight_layout(); single.savefig(output/f"{variant}_discrimination_calibration.png",dpi=300,bbox_inches="tight"); plt.close(single)
    axes[0].plot([0,1],[0,1],"--",color="grey"); axes[2].plot([0,.2],[0,.2],"--",color="grey")
    axes[0].set(xlabel="False-positive rate",ylabel="True-positive rate",title="ROC")
    axes[1].set(xlabel="Recall",ylabel="Precision",title="Precision-recall")
    axes[2].set(xlabel="Mean transported risk",ylabel="Observed 5-year risk",title="Calibration",xlim=(0,.2),ylim=(0,.2))
    for axis in axes: axis.legend(frameon=False)
    fig.tight_layout(); fig.savefig(output/"model_comparison_discrimination_calibration.png",dpi=300,bbox_inches="tight"); plt.close(fig)
    if any(len(table) for table in dca.values()):
        fig, axes = plt.subplots(1,2,figsize=(11,4.5))
        for variant in evaluated:
            if len(dca[variant]):
                axes[0].plot(dca[variant].threshold,dca[variant].net_benefit_model,label=variant,color=colors[variant])
                axes[1].plot(cic[variant].threshold,cic[variant].high_risk_per_1000,label=f"{variant}: high risk",color=colors[variant])
                axes[1].plot(cic[variant].threshold,cic[variant].true_positives_per_1000,label=f"{variant}: true positives",color=colors[variant],linestyle="--")
        first=next(iter(dca.values())); axes[0].plot(first.threshold,first.net_benefit_treat_all,"--",color="grey",label="Treat all")
        axes[0].axhline(0,color="black",linestyle=":",label="Treat none")
        axes[0].set(xlabel="Prespecified risk threshold",ylabel="Net benefit",title="Decision-curve analysis")
        axes[1].set(xlabel="Prespecified risk threshold",ylabel="IPCW-weighted patients per 1,000",title="Clinical impact")
        for axis in axes: axis.legend(frameon=False,fontsize=8)
        fig.tight_layout(); fig.savefig(output/"model_comparison_dca_cic.png",dpi=300,bbox_inches="tight"); plt.close(fig)
        for variant in evaluated:
            if not len(dca[variant]): continue
            single, single_axes=plt.subplots(1,2,figsize=(11,4.5))
            single_axes[0].plot(dca[variant].threshold,dca[variant].net_benefit_model,color=colors[variant],label=variant)
            single_axes[0].plot(dca[variant].threshold,dca[variant].net_benefit_treat_all,"--",color="grey",label="Treat all"); single_axes[0].axhline(0,color="black",linestyle=":",label="Treat none")
            single_axes[1].plot(cic[variant].threshold,cic[variant].high_risk_per_1000,color=colors[variant],label="High risk")
            single_axes[1].plot(cic[variant].threshold,cic[variant].true_positives_per_1000,color=colors[variant],linestyle="--",label="True positives")
            single_axes[0].set(xlabel="Prespecified risk threshold",ylabel="Net benefit",title="Decision-curve analysis")
            single_axes[1].set(xlabel="Prespecified risk threshold",ylabel="IPCW-weighted patients per 1,000",title="Clinical impact")
            for axis in single_axes: axis.legend(frameon=False)
            single.suptitle(variant); single.tight_layout(); single.savefig(output/f"{variant}_dca_cic.png",dpi=300,bbox_inches="tight"); plt.close(single)


def main() -> None:
    parser=argparse.ArgumentParser(description="Evaluate frozen T1D-excluded EHR model risks at five years")
    parser.add_argument("--input",type=Path,required=True); parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--model-variant",action="append",choices=MODEL_VARIANTS,required=True)
    parser.add_argument("--bootstrap",type=int,default=500); parser.add_argument("--seed",type=int,default=20260322)
    parser.add_argument("--subgroups",default="sex,age_group,cohort")
    parser.add_argument("--decision-thresholds",default="")
    parser.add_argument("--fit-local-recalibration-secondary",action="store_true")
    args=parser.parse_args(); variants=list(dict.fromkeys(args.model_variant)); args.output_dir.mkdir(parents=True,exist_ok=True)
    frame=read_table(args.input); required={"dm2","event_years",*(RISK_COLUMNS[v] for v in variants)}
    missing=sorted(required-set(frame.columns))
    if missing: raise ValueError(f"Scored table is missing: {missing}")
    if not frame.dm2.isin([0,1,False,True]).all(): raise ValueError("dm2 must contain only 0/1")
    if frame.event_years.isna().any() or (frame.event_years<=0).any(): raise ValueError("event_years must be complete and >0")
    points={}; views={}; calibrations={}; dca={}; cic={}; thresholds=parse_thresholds(args.decision_thresholds)
    local_secondary={}
    for variant in variants:
        column=RISK_COLUMNS[variant]
        if frame[column].isna().any() or not frame[column].between(0,1).all(): raise ValueError(f"Invalid {column}")
        points[variant],views[variant]=evaluated_view(frame,column)
        view=views[variant]; calibrations[variant]=weighted_calibration_table(view.horizon_outcome,view[column],view.ipcw)
        calibrations[variant].to_csv(args.output_dir/f"{variant}_calibration.csv",index=False)
        dca[variant],cic[variant]=decision_tables(view,column,thresholds)
        dca[variant].to_csv(args.output_dir/f"{variant}_decision_curve.csv",index=False)
        cic[variant].to_csv(args.output_dir/f"{variant}_clinical_impact.csv",index=False)
        if args.fit_local_recalibration_secondary:
            fit=fit_logistic_calibration(view.horizon_outcome,view[column],view.ipcw)
            local_risk=apply_logistic_calibration(view[column].to_numpy(float),fit)
            metric=weighted_metrics(view.horizon_outcome.to_numpy(int),local_risk,view.ipcw.to_numpy(float))
            metric.update(calibration_metrics(view.horizon_outcome.to_numpy(int),local_risk,view.ipcw.to_numpy(float)))
            local_secondary[variant]={"label":"secondary apparent local recalibration; not primary transported performance",
                                      "fit_on_same_external_cohort":True,"calibration":fit,"metrics":metric}
    boot=bootstrap(frame,variants,thresholds,args.bootstrap,args.seed); boot.to_csv(args.output_dir/"patient_level_bootstrap_metrics.csv",index=False)
    intervals=interval_rows(points,boot); intervals.to_csv(args.output_dir/"external_metrics_with_95CI.csv",index=False)
    decision_interval_rows(dca,cic,boot).to_csv(args.output_dir/"dca_cic_with_95CI.csv",index=False)
    subgroup_table(frame,variants,[x.strip() for x in args.subgroups.split(",") if x.strip()]).to_csv(args.output_dir/"external_subgroup_metrics.csv",index=False)
    if len(variants)==2:
        rows=[]
        for name in METRICS[:3]:
            values=boot.get(f"compact5_minus_compact10__{name}",pd.Series(dtype=float)).dropna().to_numpy(float)
            rows.append({"contrast":"compact5_minus_compact10","metric":name,
                         "estimate":points["compact5"][name]-points["compact10"][name],
                         "ci_95_lower":float(np.quantile(values,.025)) if len(values) else np.nan,
                         "ci_95_upper":float(np.quantile(values,.975)) if len(values) else np.nan,
                         "bootstrap_replicates_valid":len(values)})
        pd.DataFrame(rows).to_csv(args.output_dir/"paired_model_comparison.csv",index=False)
    plot_results(args.output_dir,views,calibrations,dca,cic)
    save_json({"analysis":"external validation of first recorded post-landmark T2D diagnosis; not biological onset or clinical deployment",
               "horizon_years":HORIZON_YEARS,"primary_analysis":"transported frozen natural-validation calibration",
               "natural_frequency_required":True,"models":points,"bootstrap_replicates_requested":args.bootstrap,
               "decision_thresholds_prespecified":thresholds.tolist(),"local_recalibration_secondary":local_secondary},
              args.output_dir/"external_metrics.json")
    print("External evaluation complete; primary results use transported calibration.")


if __name__=="__main__": main()
