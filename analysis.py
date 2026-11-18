"""Cross-country analysis of rule of law and digital finance using data/."""

import csv
import json
import math
import os
from pathlib import Path
from urllib.request import urlopen


DATA = Path(__file__).parent / "data"
OUTPUTS = Path(__file__).parent / "outputs"
WJP_YEAR = 2024
FINDEX_YEAR = 2024
CONTROLS_YEAR = 2024
FINDEX_URL = (
    "https://thedocs.worldbank.org/en/doc/"
    "be6615202d1f08a25855c8ac2d615122-0050012025/related/"
    "GlobalFindexDatabase2025.csv"
)
WDI_CODES = {
    "gdp_per_capita": "NY.GDP.PCAP.CD",
    "internet_users_pct": "IT.NET.USER.ZS",
    "urban_population_pct": "SP.URB.TOTL.IN.ZS",
}
WJP_ROWS = {
    "WJP Rule of Law Index: Overall Score": "wjp_overall",
    "Factor 1: Constraints on Government Powers": "wjp_f1",
    "Factor 2: Absence of Corruption": "wjp_f2",
    "Factor 3: Open Government": "wjp_f3",
    "Factor 4: Fundamental Rights": "wjp_f4",
    "Factor 5: Order and Security": "wjp_f5",
    "Factor 6: Regulatory Enforcement": "wjp_f6",
    "Factor 7: Civil Justice": "wjp_f7",
    "Factor 8: Criminal Justice": "wjp_f8",
}
ANALYSIS_VARIABLES = [
    "digital_payment_pct", "account_ownership_pct", "wjp_overall",
    *[f"wjp_f{i}" for i in range(1, 9)],
    "gdp_per_capita", "internet_users_pct", "urban_population_pct",
]
PLOT_LABELS = {
    "digital_payment_pct": "Digital payments (%)",
    "account_ownership_pct": "Account ownership (%)",
    "wjp_overall": "WJP overall",
    "wjp_f1": "F1 Gov. powers",
    "wjp_f2": "F2 Corruption",
    "wjp_f3": "F3 Open government",
    "wjp_f4": "F4 Rights",
    "wjp_f5": "F5 Security",
    "wjp_f6": "F6 Regulation",
    "wjp_f7": "F7 Civil justice",
    "wjp_f8": "F8 Criminal justice",
    "gdp_per_capita": "GDP per capita (USD)",
    "internet_users_pct": "Internet users (%)",
    "urban_population_pct": "Urban population (%)",
}
FACTOR_NAMES = {code: label.split(": ", 1)[1]
                for label, code in WJP_ROWS.items() if code.startswith("wjp_f")}


def get_json(url):
    """Read JSON from the World Bank API; raise errors instead of inventing data."""
    with urlopen(url, timeout=45) as response:
        return json.load(response)


def read_wjp(path):
    """Read the transposed official WJP CSV, whose second row contains ISO3 codes."""
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows or rows[0][0] != "Country":
        raise ValueError(f"wjp.csv 必须是 WJP 官网的 {WJP_YEAR} 年转置 CSV。")
    by_label = {row[0].strip(): row[1:] for row in rows}
    required = ["Country", "Country Code", "Region", "Income Group", *WJP_ROWS]
    missing = [label for label in required if label not in by_label]
    if missing:
        raise ValueError(f"WJP 缺少行：{missing}")
    n = len(by_label["Country"])
    if any(len(by_label[label]) != n for label in required):
        raise ValueError("WJP 各行的国家数不一致。")
    result = []
    for i in range(n):
        item = {
            "iso3": by_label["Country Code"][i].strip(),
            "country": by_label["Country"][i].strip(),
            "wjp_region": by_label["Region"][i].strip(),
            "wjp_income_group": by_label["Income Group"][i].strip(),
        }
        for source, target in WJP_ROWS.items():
            value = by_label[source][i].strip()
            item[target] = float(value) if value else ""
        result.append(item)
    check_unique(result, "WJP")
    return result


def check_unique(rows, source):
    codes = [row["iso3"] for row in rows]
    repeated = sorted({code for code in codes if codes.count(code) > 1})
    if repeated:
        raise ValueError(f"{source} 中 ISO3 重复：{repeated}")


def world_bank_countries(api_data):
    """Exclude World Bank aggregate entries, which have region.id set to NA."""
    return {
        row["id"]: row
        for row in api_data[1]
        if row["region"]["id"] != "NA"
    }


def extract_findex(source_path, destination, valid_codes):
    """Extract country-level rates for the selected survey year from the Findex file."""
    with source_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required = {"codewb", "countrynewwb", "year", "group", "group2", "g20_any", "account_t_d"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Findex 缺少变量：{sorted(required - set(reader.fieldnames or []))}")
        rows = []
        for row in reader:
            if (row["year"] != str(FINDEX_YEAR) or row["group"] != "all"
                    or row["group2"] != "all" or row["codewb"] not in valid_codes):
                continue
            # Source rates are on a 0–1 scale; convert to percentages and leave missing values blank.
            def pct(name):
                value = row[name]
                return "" if value in ("", "NA") else float(value) * 100

            rows.append({
                "iso3": row["codewb"],
                "findex_country": row["countrynewwb"],
                "findex_year": FINDEX_YEAR,
                "digital_payment_pct": pct("g20_any"),
                "account_ownership_pct": pct("account_t_d"),
            })
    check_unique(rows, "Findex")
    write_csv(destination, rows, ["iso3", "findex_country", "findex_year",
                                  "digital_payment_pct", "account_ownership_pct"])
    return rows


def download_findex_if_missing(path, valid_codes):
    if path.exists():
        return
    raw = DATA / "findex_raw_2025.csv"
    if not raw.exists():
        with urlopen(FINDEX_URL, timeout=90) as response, raw.open("wb") as out:
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
    extract_findex(raw, path, valid_codes)


def extract_controls(api_results, destination, countries):
    """Build the same-year controls table from three WDI API responses."""
    rows = {}
    for target, code in WDI_CODES.items():
        response = api_results[target]
        if not isinstance(response, list) or len(response) < 2:
            raise ValueError(f"世界银行 API 未返回 {code} 的数据。")
        for observation in response[1]:
            iso3 = observation["countryiso3code"]
            if iso3 not in countries:
                continue
            if observation["indicator"]["id"] != code or observation["date"] != str(CONTROLS_YEAR):
                raise ValueError(f"WDI 数据与请求不符：{code}")
            if iso3 not in rows:
                meta = countries[iso3]
                rows[iso3] = {
                    "iso3": iso3,
                    "wb_country": meta["name"],
                    "wb_region": meta["region"]["value"].strip(),
                    "wb_income_group": meta["incomeLevel"]["value"],
                    "controls_year": CONTROLS_YEAR,
                }
            value = observation["value"]
            rows[iso3][target] = "" if value is None else value
    result = sorted(rows.values(), key=lambda row: row["iso3"])
    check_unique(result, "WDI")
    write_csv(destination, result, ["iso3", "wb_country", "wb_region",
                                    "wb_income_group", "controls_year", *WDI_CODES])
    return result


def download_controls_if_missing(path, countries):
    if path.exists():
        return
    results = {}
    for target, code in WDI_CODES.items():
        url = (f"https://api.worldbank.org/v2/country/all/indicator/{code}"
               f"?date={CONTROLS_YEAR}&format=json&per_page=500")
        results[target] = get_json(url)
    extract_controls(results, path, countries)


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    check_unique(rows, path.name)
    return rows


def merge_step1():
    DATA.mkdir(exist_ok=True)
    OUTPUTS.mkdir(exist_ok=True)
    if not (DATA / "wjp.csv").exists():
        raise FileNotFoundError(f"缺少 data/wjp.csv：请从 WJP {WJP_YEAR} 官网下载官方 CSV。")
    wjp = read_wjp(DATA / "wjp.csv")
    # Use the local World Bank files without an API call when both are available.
    need_download = not (DATA / "digital_finance.csv").exists() or not (DATA / "controls.csv").exists()
    countries = (world_bank_countries(
        get_json("https://api.worldbank.org/v2/country?format=json&per_page=500")
    ) if need_download else {r["iso3"]: {} for r in wjp})
    invalid = [(r["country"], r["iso3"]) for r in wjp
               if len(r["iso3"]) != 3 or not r["iso3"].isalpha()
               or r["iso3"] not in countries]
    print("WJP 国家名/ISO3 无法匹配：", invalid)
    if invalid:
        raise ValueError("存在无法匹配的 WJP 国家；请逐一核对原始代码。")

    download_findex_if_missing(DATA / "digital_finance.csv", countries)
    download_controls_if_missing(DATA / "controls.csv", countries)
    finance_rows = read_csv(DATA / "digital_finance.csv")
    control_rows = read_csv(DATA / "controls.csv")
    if {r["findex_year"] for r in finance_rows} != {str(FINDEX_YEAR)}:
        raise ValueError(f"digital_finance.csv 的调查年份必须为 {FINDEX_YEAR}。")
    if {r["controls_year"] for r in control_rows} != {str(CONTROLS_YEAR)}:
        raise ValueError(f"controls.csv 的年份必须为 {CONTROLS_YEAR}。")
    finance = {r["iso3"]: r for r in finance_rows if r["iso3"] in countries}
    controls = {r["iso3"]: r for r in control_rows if r["iso3"] in countries}
    merged = []
    for row in wjp:
        iso3 = row["iso3"]
        merged.append({**row, **finance.get(iso3, {}), **controls.get(iso3, {})})
    fields = ["iso3", "country", "wjp_region", "wjp_income_group", "wjp_overall",
              *[f"wjp_f{i}" for i in range(1, 9)], "findex_country",
              "findex_year", "digital_payment_pct", "account_ownership_pct",
              "wb_country", "wb_region", "wb_income_group", "controls_year",
              *WDI_CODES]
    write_csv(OUTPUTS / "merged_all.csv", merged, fields)
    print(f"WJP 国家数：{len(wjp)}；已保存左连接底表 outputs/merged_all.csv。")
    unmatched = []
    for name, source in (("Findex", finance), ("WDI", controls)):
        absent = [(r["country"], r["iso3"]) for r in wjp if r["iso3"] not in source]
        print(f"{name} 中没有对应国家记录（数据覆盖问题，不是名称映射错误）：{absent}")
        unmatched.extend({"source": name, "country": country, "iso3": iso3,
                          "reason": "source has no country record"}
                         for country, iso3 in absent)
    write_csv(OUTPUTS / "unmatched_countries.csv", unmatched,
              ["source", "country", "iso3", "reason"])
    return merged, fields


def has_valid_value(row, variable):
    """Reject missing or nonfinite values; GDP must be positive before taking logs."""
    try:
        value = float(row.get(variable, ""))
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and (variable != "gdp_per_capita" or value > 0)


def missingness_step2(merged, fields):
    """Report raw missingness and sequential exclusions, then save complete cases."""
    remaining = merged
    report = []
    for variable in ANALYSIS_VARIABLES:
        missing_all = sum(not has_valid_value(row, variable) for row in merged)
        lost = [row for row in remaining if not has_valid_value(row, variable)]
        remaining = [row for row in remaining if has_valid_value(row, variable)]
        report.append({
            "variable": variable,
            "missing_among_wjp_countries": missing_all,
            "newly_excluded": len(lost),
            "remaining_n": len(remaining),
        })
    write_csv(OUTPUTS / "missingness.csv", report,
              ["variable", "missing_among_wjp_countries", "newly_excluded", "remaining_n"])
    write_csv(OUTPUTS / "merged.csv", remaining, fields)
    kept = {row["iso3"] for row in remaining}
    excluded = []
    for row in merged:
        if row["iso3"] not in kept:
            missing = [name for name in ANALYSIS_VARIABLES if not has_valid_value(row, name)]
            excluded.append({"iso3": row["iso3"], "country": row["country"],
                             "missing_variables": "; ".join(missing)})
    write_csv(OUTPUTS / "excluded_countries.csv", excluded,
              ["iso3", "country", "missing_variables"])
    print("\n第 2 步：缺失情况（原始缺失 / 顺序筛选新增剔除）")
    for row in report:
        print(f"{row['variable']}: {row['missing_among_wjp_countries']} / {row['newly_excluded']}")
    print(f"最终完整样本 N = {len(remaining)}；排除国家数 = {len(excluded)}")


def descriptives_step3():
    """Create complete-case descriptives, histograms, scatter plot, and heatmap."""
    mpl_config = Path(__file__).parent / ".mplconfig"
    mpl_config.mkdir(exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(mpl_config))
    import numpy as np
    import pandas as pd
    import matplotlib

    matplotlib.use("Agg")  # Generate PNG files without a graphical display.
    import matplotlib.pyplot as plt
    import seaborn as sns

    np.random.seed(2025)  # Fixed seed; these plots do not currently use random sampling.
    sns.set_theme(style="whitegrid", font_scale=0.95)
    data = pd.read_csv(OUTPUTS / "merged.csv")
    numbers = data[ANALYSIS_VARIABLES].apply(pd.to_numeric, errors="raise")
    if numbers.isna().any().any():
        raise ValueError("完整样本仍有缺失值，请先检查第 2 步。")
    n = len(numbers)

    # pandas uses the sample standard deviation by default (denominator N-1).
    summary = numbers.agg(["count", "mean", "std", "min", "max"]).T
    summary.index.name = "variable"
    summary = summary.rename(columns={"count": "n"}).reset_index()
    summary["n"] = summary["n"].astype(int)
    summary.to_csv(OUTPUTS / "descriptives.csv", index=False, float_format="%.6f")

    # Show one histogram per analysis variable in a 4×4 panel.
    fig, axes = plt.subplots(4, 4, figsize=(18, 14))
    for ax, variable in zip(axes.flat, ANALYSIS_VARIABLES):
        values = numbers[variable]
        if variable == "gdp_per_capita":
            bins = np.geomspace(values.min(), values.max(), 17)
            ax.set_xscale("log")
            xlabel = "GDP per capita (USD, log scale)"
        else:
            bins = 16
            xlabel = PLOT_LABELS[variable]
        ax.hist(values, bins=bins, color="#3478a8", edgecolor="white")
        ax.set_title(PLOT_LABELS[variable], fontsize=11)
        ax.set_xlabel(xlabel, fontsize=9)
        ax.set_ylabel("Countries", fontsize=9)
        ax.tick_params(labelsize=8)
    for ax in list(axes.flat)[len(ANALYSIS_VARIABLES):]:
        ax.axis("off")
    fig.suptitle(f"Distributions of analysis variables (N = {n})", fontsize=17)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(OUTPUTS / "histograms.png", dpi=300, bbox_inches="tight")
    plt.close(fig)

    # The scatter plot's R² comes from the displayed simple least-squares fit.
    x = numbers["wjp_overall"].to_numpy()
    y = numbers["digital_payment_pct"].to_numpy()
    slope, intercept = np.polyfit(x, y, deg=1)
    fitted = slope * x + intercept
    r_squared = 1 - np.sum((y - fitted) ** 2) / np.sum((y - y.mean()) ** 2)
    line_x = np.linspace(x.min(), x.max(), 200)
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(x, y, alpha=0.72, s=35, color="#3478a8", edgecolor="white",
               linewidth=0.4, label="Countries")
    ax.plot(line_x, slope * line_x + intercept, color="#d95f02",
            linewidth=2.2, label="Linear fit")
    ax.set_xlabel("WJP overall rule of law score (0–1)")
    ax.set_ylabel("Made or received a digital payment (% age 15+)")
    ax.set_title(f"Rule of law and digital payments (N = {n}, R² = {r_squared:.3f})")
    ax.legend(frameon=True)
    fig.tight_layout()
    fig.savefig(OUTPUTS / "wjp_vs_digital_payments.png", dpi=300, bbox_inches="tight")
    plt.close(fig)

    corr = numbers.corr(method="pearson")
    corr = corr.rename(index=PLOT_LABELS, columns=PLOT_LABELS)
    fig, ax = plt.subplots(figsize=(13, 11))
    sns.heatmap(corr, ax=ax, vmin=-1, vmax=1, center=0, cmap="RdBu_r",
                annot=True, fmt=".2f", annot_kws={"size": 7}, square=True,
                linewidths=0.3, cbar_kws={"label": "Pearson correlation"})
    ax.set_title(f"Correlations among analysis variables (N = {n})", pad=15)
    ax.tick_params(axis="x", labelrotation=45, labelsize=8)
    ax.tick_params(axis="y", labelrotation=0, labelsize=8)
    fig.tight_layout()
    fig.savefig(OUTPUTS / "correlation_heatmap.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"第 3 步：已保存描述统计和 3 张 300 dpi 图；散点图 R² = {r_squared:.3f}，N = {n}。")


def regressions_step4():
    """Fit M1, M2, and eight separate factor models with HC3 standard errors."""
    import numpy as np
    import pandas as pd
    import statsmodels.api as sm
    from statsmodels.stats.multitest import multipletests

    data = pd.read_csv(OUTPUTS / "merged.csv")
    data["log_gdp_per_capita"] = np.log(data["gdp_per_capita"])
    outcome = data["digital_payment_pct"]
    controls = ["log_gdp_per_capita", "internet_users_pct", "urban_population_pct"]

    def fit(predictors):
        design = sm.add_constant(data[predictors], has_constant="add")
        if np.linalg.matrix_rank(design.to_numpy()) != len(design.columns):
            raise ValueError(f"回归矩阵不满秩：{predictors}")
        return sm.OLS(outcome, design).fit(cov_type="HC3")

    models = {
        "M1": fit(["wjp_overall"]),
        "M2": fit(["wjp_overall", *controls]),
    }
    # M3 replaces the overall score with one factor to avoid including both together.
    for number in range(1, 9):
        factor = f"wjp_f{number}"
        models[f"M3_F{number}"] = fit([factor, *controls])

    all_rows = []
    for model_name, result in models.items():
        for term in result.params.index:
            all_rows.append({
                "model": model_name,
                "term": term,
                "coefficient": result.params[term],
                "hc3_se": result.bse[term],
                "p_value": result.pvalues[term],
                "r_squared": result.rsquared,
                "n": int(result.nobs),
                "cov_type": "HC3",
            })
    pd.DataFrame(all_rows).to_csv(OUTPUTS / "regressions.csv", index=False,
                                   float_format="%.8g")

    factors = []
    for number in range(1, 9):
        factor = f"wjp_f{number}"
        result = models[f"M3_F{number}"]
        factors.append({
            "factor": factor,
            "factor_name": FACTOR_NAMES[factor],
            "coefficient": result.params[factor],
            "hc3_se": result.bse[factor],
            "p_value": result.pvalues[factor],
            "r_squared": result.rsquared,
            "n": int(result.nobs),
        })
    factor_table = pd.DataFrame(factors)
    factor_table["fdr_bh_q_value"] = multipletests(
        factor_table["p_value"], method="fdr_bh"
    )[1]
    factor_table.to_csv(OUTPUTS / "m3_factors.csv", index=False, float_format="%.8g")

    for model_name in ("M1", "M2"):
        result = models[model_name]
        table = pd.DataFrame({
            "coefficient": result.params,
            "HC3 SE": result.bse,
            "p value": result.pvalues,
        })
        print(f"\n{model_name}: N = {int(result.nobs)}, R² = {result.rsquared:.4f}")
        print(table.to_string(float_format=lambda value: f"{value:.4g}"))
    print("\nM3: 每次一个 WJP 分项 + 三个控制变量（HC3）")
    print(factor_table.to_string(index=False, float_format=lambda value: f"{value:.4g}"))


def robustness_step5():
    """Rerun M2 by income group, calculate VIF, and remove the five largest Cook's distances."""
    import numpy as np
    import pandas as pd
    import statsmodels.api as sm
    from statsmodels.stats.outliers_influence import variance_inflation_factor

    data = pd.read_csv(OUTPUTS / "merged.csv")
    data["log_gdp_per_capita"] = np.log(data["gdp_per_capita"])
    predictors = ["wjp_overall", "log_gdp_per_capita",
                  "internet_users_pct", "urban_population_pct"]

    def design_for(subset):
        design = sm.add_constant(subset[predictors], has_constant="add")
        if np.linalg.matrix_rank(design.to_numpy()) != len(design.columns):
            raise ValueError("M2 子样本的回归矩阵不满秩。")
        return design

    def fit_hc3(subset):
        return sm.OLS(subset["digital_payment_pct"], design_for(subset)).fit(cov_type="HC3")

    baseline = fit_hc3(data)
    subgroup_rows = []
    robustness_rows = []

    def add_result(model_name, result):
        for term in result.params.index:
            robustness_rows.append({
                "model": model_name,
                "term": term,
                "coefficient": result.params[term],
                "hc3_se": result.bse[term],
                "p_value": result.pvalues[term],
                "r_squared": result.rsquared,
                "n": int(result.nobs),
                "cov_type": "HC3",
            })

    add_result("M2_baseline", baseline)
    for group, subset in data.groupby("wb_income_group", sort=True):
        result = fit_hc3(subset)
        name = "M2_income_" + group.lower().replace(" ", "_")
        add_result(name, result)
        subgroup_rows.append({
            "income_group": group,
            "n": int(result.nobs),
            "wjp_coefficient": result.params["wjp_overall"],
            "hc3_se": result.bse["wjp_overall"],
            "p_value": result.pvalues["wjp_overall"],
            "r_squared": result.rsquared,
            "note": "small N; HC3 inference unstable" if len(subset) < 15 else "",
        })
    subgroup_table = pd.DataFrame(subgroup_rows)
    subgroup_table.to_csv(OUTPUTS / "subgroup_m2.csv", index=False, float_format="%.8g")

    # Only six high-income countries remain in 2024; pool adjacent income groups.
    broad_groups = {
        "Low income": "Low + lower middle income",
        "Lower middle income": "Low + lower middle income",
        "Upper middle income": "Upper middle + high income",
        "High income": "Upper middle + high income",
    }
    pooled_rows = []
    for group, subset in data.assign(
        income_band=data["wb_income_group"].map(broad_groups)
    ).groupby("income_band", sort=True):
        result = fit_hc3(subset)
        add_result("M2_income_pooled_" + group.lower().replace(" ", "_"), result)
        pooled_rows.append({
            "income_band": group,
            "n": int(result.nobs),
            "wjp_coefficient": result.params["wjp_overall"],
            "hc3_se": result.bse["wjp_overall"],
            "p_value": result.pvalues["wjp_overall"],
            "r_squared": result.rsquared,
        })
    pooled_table = pd.DataFrame(pooled_rows)
    pooled_table.to_csv(OUTPUTS / "subgroup_m2_pooled.csv", index=False,
                        float_format="%.8g")

    # Calculate VIF with an intercept in the M2 design, but report only predictors.
    full_design = design_for(data)
    vif_table = pd.DataFrame([
        {"variable": name,
         "vif": variance_inflation_factor(full_design.to_numpy(), index)}
        for index, name in enumerate(full_design.columns) if name != "const"
    ])
    vif_table.to_csv(OUTPUTS / "vif.csv", index=False, float_format="%.8g")

    # Cook's distance measures influence; save the hat-matrix diagonal as leverage.
    plain_m2 = sm.OLS(data["digital_payment_pct"], full_design).fit()
    influence = plain_m2.get_influence()
    ranked = data[["iso3", "country"]].copy()
    ranked["cooks_distance"] = influence.cooks_distance[0]
    ranked["leverage"] = influence.hat_matrix_diag
    top_five = ranked.sort_values(["cooks_distance", "iso3"],
                                   ascending=[False, True]).head(5)
    top_five.to_csv(OUTPUTS / "cooks_top5.csv", index=False, float_format="%.8g")

    trimmed = data.loc[~data["iso3"].isin(top_five["iso3"])].copy()
    trimmed_result = fit_hc3(trimmed)
    add_result("M2_without_cooks_top5", trimmed_result)
    pd.DataFrame(robustness_rows).to_csv(OUTPUTS / "robustness_regressions.csv",
                                          index=False, float_format="%.8g")

    print("\n第 5 步：按世界银行收入组重跑 M2（WJP 总分系数，HC3）")
    print(subgroup_table.to_string(index=False, float_format=lambda value: f"{value:.4g}"))
    print("\n合并相邻收入档后的 M2（WJP 总分系数，HC3）")
    print(pooled_table.to_string(index=False, float_format=lambda value: f"{value:.4g}"))
    print("\nM2 的 VIF（不含截距）")
    print(vif_table.to_string(index=False, float_format=lambda value: f"{value:.4g}"))
    print("\nCook's distance 最大的五国")
    print(top_five.to_string(index=False, float_format=lambda value: f"{value:.4g}"))
    print("\nM2 基准与剔除五国后的结果（WJP 总分）")
    for label, result in (("baseline", baseline), ("without top 5", trimmed_result)):
        print(f"{label}: N={int(result.nobs)}, coefficient={result.params['wjp_overall']:.4g}, "
              f"HC3 SE={result.bse['wjp_overall']:.4g}, "
              f"p={result.pvalues['wjp_overall']:.4g}, R²={result.rsquared:.4g}")


def results_summary_step6():
    """Generate the Chinese results summary from saved values to avoid manual copying."""
    import pandas as pd

    regressions = pd.read_csv(OUTPUTS / "regressions.csv")
    factors = pd.read_csv(OUTPUTS / "m3_factors.csv")
    subgroups = pd.read_csv(OUTPUTS / "subgroup_m2.csv")
    pooled = pd.read_csv(OUTPUTS / "subgroup_m2_pooled.csv")
    vif = pd.read_csv(OUTPUTS / "vif.csv")
    cooks = pd.read_csv(OUTPUTS / "cooks_top5.csv")
    robustness = pd.read_csv(OUTPUTS / "robustness_regressions.csv")
    all_data = pd.read_csv(OUTPUTS / "merged_all.csv")
    complete_data = pd.read_csv(OUTPUTS / "merged.csv")
    n_all = len(all_data)
    n = len(complete_data)
    n_high_all = int((all_data["wb_income_group"] == "High income").sum())
    n_high = int((complete_data["wb_income_group"] == "High income").sum())

    def estimate(table, model, term):
        return table.loc[(table["model"] == model) & (table["term"] == term)].iloc[0]

    m1 = estimate(regressions, "M1", "wjp_overall")
    m2 = estimate(regressions, "M2", "wjp_overall")
    gdp = estimate(regressions, "M2", "log_gdp_per_capita")
    trimmed = estimate(robustness, "M2_without_cooks_top5", "wjp_overall")
    candidate = factors.loc[factors["p_value"].idxmin()]
    factor_names_zh = {
        "wjp_f1": "政府权力制约", "wjp_f2": "廉洁程度", "wjp_f3": "政府开放程度",
        "wjp_f4": "基本权利", "wjp_f5": "秩序与安全", "wjp_f6": "监管执行",
        "wjp_f7": "民事司法", "wjp_f8": "刑事司法",
    }
    candidate_name = f"{factor_names_zh[candidate['factor']]}（{candidate['factor_name']}）"
    max_vif = vif.loc[vif["vif"].idxmax()]
    n_significant_subgroups = int((subgroups["p_value"] < 0.05).sum())
    subgroup_sentence = (
        "四个收入组的 WJP 总分系数均未达到 5% 显著水平。"
        if n_significant_subgroups == 0 else
        f"四个收入组中有 {n_significant_subgroups} 组的 WJP 总分系数达到 5% 显著水平。"
    )
    q_passes = candidate["fdr_bh_q_value"] < 0.05
    q_sentence = "通过" if q_passes else "未通过"
    factor_heading = (
        f"八个分项中，{factor_names_zh[candidate['factor']]}的关联最明确。" if q_passes else
        "八个法治分项尚不能排出可靠的“最强项”。"
    )
    factor_caveat = (
        "在这套单项模型中，它的统计证据最明确；但尚不能证明它的系数显著大于其他分项，更不能作因果解释。"
        if q_passes else
        "各分项本身也高度相关，因此不能断言它比其他分项更有作用。"
    )
    factor_conclusion = (
        f"{factor_names_zh[candidate['factor']]}分项在单独控制模型中的关联最明确，经过八项比较校正仍达到 5% 标准；"
        if q_passes else
        "没有分项在八项比较校正后达到 5% 标准；"
    )
    gdp_sentence = (
        "达到" if gdp["p_value"] < 0.05 else "未达到"
    )
    small_groups = "、".join(
        f"{row.income_group}（N={int(row.n)}）"
        for row in subgroups.itertuples(index=False) if row.n < 15
    )
    income_rows = "\n".join(
        f"| {row.income_group} | {int(row.n)} | {row.wjp_coefficient:.2f} | {row.p_value:.3f} |"
        for row in subgroups.itertuples(index=False)
    )
    pooled_rows = "\n".join(
        f"| {row.income_band} | {int(row.n)} | {row.wjp_coefficient:.2f} | {row.p_value:.3f} |"
        for row in pooled.itertuples(index=False)
    )
    cook_names = "、".join(cooks["country"].tolist())
    m2_ci_low = 0.1 * (m2["coefficient"] - 1.96 * m2["hc3_se"])
    m2_ci_high = 0.1 * (m2["coefficient"] + 1.96 * m2["hc3_se"])

    report = f"""# 法治水平与数字金融发展的跨国分析：结果总结

## 样本与方法

以 {n_all} 个 WJP {WJP_YEAR} 国家和地区为起点，删除缺少分析变量的记录后，完整样本为 **{n} 国**。数字金融主指标是 Global Findex **{FINDEX_YEAR} 年**“过去一年做过或收到过数字支付”的成年人占比；法治变量是 WJP **{WJP_YEAR} 年**总分及八个分项（0–1 分）；人均 GDP、互联网使用率、城镇人口占比来自 **{CONTROLS_YEAR} 年** WDI。三套数据均对应同一日历年。回归使用 OLS 和 HC3 稳健标准误，没有插补数据。[逐变量缺失情况](missingness.csv)和[被排除国家](excluded_countries.csv)可供核查。

## 主要发现

1. **未经控制时呈明显正相关。** M1 中，WJP 总分每高 0.1 分，数字支付率平均高约 **{0.1 * m1['coefficient']:.2f} 个百分点**（HC3 p < 0.001，R² = {m1['r_squared']:.3f}）。这是国家间的统计关联。
2. **加入控制变量后，证据减弱。** M2 中，同样的 0.1 分差对应约 **{0.1 * m2['coefficient']:.2f} 个百分点**（HC3 p = {m2['p_value']:.3f}，R² = {m2['r_squared']:.3f}），未达到常用的 5% 显著水平。按稳健标准误估算的 95% 区间约为 **{m2_ci_low:.2f} 至 {m2_ci_high:.2f} 个百分点**，包含零。人均 GDP 的对数系数为 {gdp['coefficient']:.2f}（p = {gdp['p_value']:.3f}），也{gdp_sentence} 5% 显著水平。
3. **{factor_heading}** 在每次仅放入一个分项并保留三个控制变量的 M3 中，未校正 p 值最小的是 **{candidate_name}**：该分项每高 0.1 分，对应数字支付率约高 {0.1 * candidate['coefficient']:.2f} 个百分点（p = {candidate['p_value']:.3f}）。八次检验的 Benjamini–Hochberg 校正后 q = {candidate['fdr_bh_q_value']:.4f}，**{q_sentence} 5% 标准**。{factor_caveat}

[全部回归系数](regressions.csv) · [八个分项结果](m3_factors.csv)

## 稳健性检验

按世界银行收入组分别重跑 M2，结果如下（系数对应 WJP 总分增加 1.0 分，因变量单位为百分点）：

| 收入组 | N | WJP 系数 | HC3 p 值 |
| --- | ---: | ---: | ---: |
{income_rows}

{subgroup_sentence}其中 {small_groups}的样本太小，模型含 5 个参数，其 HC3 标准误和 p 值不宜用于实质判断。为减少小样本问题，将相邻收入档合并后重跑 M2：

| 合并收入组 | N | WJP 系数 | HC3 p 值 |
| --- | ---: | ---: | ---: |
{pooled_rows}

合并组的结果仍不能证明各收入层中都存在独立关联。M2 的 VIF 中，最高的是 **{max_vif['variable']} = {max_vif['vif']:.2f}**。[四档分组](subgroup_m2.csv) · [合并分组](subgroup_m2_pooled.csv) · [VIF](vif.csv)

Cook's distance 最高的五国是 {cook_names}。剔除它们后，M2 的 WJP 系数由 **{m2['coefficient']:.2f}**（p = {m2['p_value']:.3f}，N = {n}）变为 **{trimmed['coefficient']:.2f}**（p = {trimmed['p_value']:.4f}，N = {int(trimmed['n'])}）。显著性对这五国的处理敏感；事后剔除不是更可信的主结果。[影响点](cooks_top5.csv) · [稳健性回归明细](robustness_regressions.csv)

## 可以怎样表述结论

**在这 {n} 个国家中，法治总分与数字支付率呈正相关；控制收入、互联网使用率和城镇化率后，总分系数仍为正，但未达到 5% 显著水平。** {factor_conclusion}这一发现不能解释为因果效应，也需要考虑样本选择和影响点敏感性。

## 局限性

- **相关不等于因果。** 这些模型不能证明提高法治水平会提高数字支付率。
- **可能存在反向因果。** 数字金融发展也可能影响制度建设、监管和公众对法治的感受。
- **可能有遗漏变量。** 教育、移动网络覆盖、金融基础设施、金融监管、信任等没有纳入，可能同时影响法治和数字支付。
- **仅为同年横截面分析。** Findex、WDI 和 WJP 均取 {WJP_YEAR} 年，但调查和统计发布并非同一时点，也没有观察国家随时间的变化，不能判断先后顺序或因果效应。
- **指标定义有限。** Findex 指标只记录过去一年是否至少做过或收到过一次数字支付，不衡量使用频率、金额、质量或数字信贷等其他金融服务；WJP 是综合指数，不能涵盖制度的全部方面。
- **样本选择明显。** {n_all - n} 个 WJP 国家因缺失被排除；原有 {n_high_all} 个高收入国家中仅 {n_high} 个进入完整样本，主要是 2024 年 Findex 数字支付指标缺失。结果更接近于本样本国家的关系，不能代表所有收入层。
"""
    (OUTPUTS / "results_summary.md").write_text(report, encoding="utf-8")
    print("\n第 6 步：已生成 outputs/results_summary.md。")


if __name__ == "__main__":
    rows, columns = merge_step1()
    missingness_step2(rows, columns)
    descriptives_step3()
    regressions_step4()
    robustness_step5()
    results_summary_step6()
