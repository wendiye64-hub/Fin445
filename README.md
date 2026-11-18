# Rule of Law and Digital Payments: A Cross-Country Analysis

This repository contains a reproducible 2024 cross-country analysis. Run [`analysis.py`](analysis.py) to regenerate the merged data, charts, regressions, robustness checks, and written results from the CSV files in `data/`.

## Five-minute presentation

[Download the current English PowerPoint](presentation/fin445_5min_english_revised.pptx). It has six speaking slides plus a final data-source reference slide, with English speaker notes. Slide 3 contains an editable scatter chart, slide 4 embeds the correlation heatmap, and slide 5 contains an editable regression summary table drawn from the output CSV files. The [earlier version](presentation/fin445_5min_english_heatmap.pptx) is still available.

## Run the project

Install Python 3.12 so that `python3.12` is available, then run:

```bash
git clone https://github.com/wendiye64-hub/Fin445.git
cd Fin445
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python analysis.py
```

In the existing local project, where the virtual environment is already installed, run `.venv/bin/python analysis.py`. The three analysis input CSV files are included, so a normal run does not need internet access. The script never imputes missing values.

## Data sources and years

| File | Source and indicator | Year | Unit |
| --- | --- | --- | --- |
| `data/wjp.csv` | [Official WJP Rule of Law Index CSV](https://worldjusticeproject.org/rule-of-law-index/data/2024.csv): overall score and Factors 1–8 | 2024 index | 0–1 score |
| `data/digital_finance.csv` | [World Bank Global Findex country data](https://www.worldbank.org/en/publication/globalfindex/download-data): `g20_any` means adults aged 15+ who made or received a digital payment in the past year; `account_t_d` means account ownership. The official source CSV is retained as `data/findex_raw_2025.csv`. | **2024 survey** | Converted to percentages (0–100) |
| `data/controls.csv` | [World Bank WDI API](https://api.worldbank.org/v2/): `NY.GDP.PCAP.CD` = GDP per capita, `IT.NET.USER.ZS` = internet use, `SP.URB.TOTL.IN.ZS` = urban population share | 2024 | USD, %, % |

The main digital-finance measure is `g20_any`, which directly records digital-payment use. “Global Findex 2025” is the report name; the latest survey observations used here are from **2024**. Account ownership is retained as a descriptive variable, not substituted for digital payments. The World Bank API indicator `FX.OWN.TOTL.ZS` was verified to exist, but this project uses `account_t_d` from the official Findex CSV so both Findex measures come from the same 2024 survey.

All three WDI controls use 2024 observations. World Bank regional and income-group aggregates are excluded using the country metadata. The WJP file already provides ISO3 codes, so the script does not infer them from country names.

## Code workflow

| Step | Code | Main outputs |
| --- | --- | --- |
| 1. Read, clean, and merge by ISO3 | [`merge_step1()`](analysis.py#L212) | `outputs/merged_all.csv`, `outputs/unmatched_countries.csv` |
| 2. Report missing data and select complete cases | [`missingness_step2()`](analysis.py#L272) | `outputs/missingness.csv`, `outputs/merged.csv` |
| 3. Descriptive statistics and charts | [`descriptives_step3()`](analysis.py#L304) | `outputs/descriptives.csv`, three PNG charts |
| 4. M1, M2, and eight M3 regressions | [`regressions_step4()`](analysis.py#L390) | `outputs/regressions.csv`, `outputs/m3_factors.csv` |
| 5. Income-group regressions, VIF, and Cook's distance | [`robustness_step5()`](analysis.py#L465) | `outputs/robustness_regressions.csv` and diagnostic tables |
| 6. Generate the written interpretation | [`results_summary_step6()`](analysis.py#L585) | `outputs/results_summary.md` |

The [main block](analysis.py#L708) calls these six functions in order. Steps 1–2 use the Python standard library; later steps use pandas, NumPy, Matplotlib, Seaborn, and statsmodels. The official WJP CSV is transposed; the script converts its ISO3 columns into country records.

## Regression code

The complete implementation is in [`analysis.py`, lines 390–463](analysis.py#L390-L463). The essential model setup is:

```python
from pathlib import Path
import numpy as np
import pandas as pd
import statsmodels.api as sm

OUTPUTS = Path("outputs")
data = pd.read_csv(OUTPUTS / "merged.csv")
data["log_gdp_per_capita"] = np.log(data["gdp_per_capita"])
outcome = data["digital_payment_pct"]
controls = ["log_gdp_per_capita", "internet_users_pct", "urban_population_pct"]

def fit(predictors):
    design = sm.add_constant(data[predictors], has_constant="add")
    return sm.OLS(outcome, design).fit(cov_type="HC3")

models = {
    "M1": fit(["wjp_overall"]),
    "M2": fit(["wjp_overall", *controls]),
}
for number in range(1, 9):
    factor = f"wjp_f{number}"
    models[f"M3_F{number}"] = fit([factor, *controls])

for name, result in models.items():
    print(name, "N =", int(result.nobs), "R² =", round(result.rsquared, 4))
    print(result.summary())
```

This excerpt runs on its own from the repository root after `outputs/merged.csv` exists. Run `analysis.py` to generate all files. The full script also checks matrix rank, saves the coefficients, and adjusts the eight factor tests for multiple comparisons.

## Sample and outputs

The analysis begins with 142 WJP countries and territories. The 2024 digital-payment measure overlaps with 85 of them. After excluding Kosovo for missing internet-use data, the complete sample is **N = 84**. All main models use the same 84 observations. Complete cases require digital payments, account ownership, WJP overall and all eight factors, three WDI controls, and positive GDP per capita. There is **no imputation**. Of the original 50 high-income WJP countries, only six are in the complete sample. See [missingness](outputs/missingness.csv) and [excluded countries](outputs/excluded_countries.csv).

The main deliverables are:

- [Descriptive statistics](outputs/descriptives.csv): N, mean, sample standard deviation, minimum, and maximum for 14 variables.
- [Histograms](outputs/histograms.png), [scatter plot with fitted line](outputs/wjp_vs_digital_payments.png), and [correlation heatmap](outputs/correlation_heatmap.png), all saved at 300 dpi.
- [Regression coefficients](outputs/regressions.csv) for M1, M2, and eight separate M3 factor models, with HC3 robust standard errors, p-values, R², and N.
- [Eight-factor summary](outputs/m3_factors.csv), including Benjamini–Hochberg adjusted q-values.
- [Income-group results](outputs/subgroup_m2.csv), [pooled income-group results](outputs/subgroup_m2_pooled.csv), [M2 VIF](outputs/vif.csv), [five highest Cook's distances](outputs/cooks_top5.csv), and [robustness regressions](outputs/robustness_regressions.csv).
- [Plain-language results and limitations](outputs/results_summary.md).

M1 regresses the digital-payment rate on the WJP overall score. M2 adds log GDP per capita, internet use, and urban population share. Each M3 model replaces the overall score with **one** WJP factor, keeping the same controls. The overall score and its factors never enter together. All models use OLS with HC3 robust standard errors. WJP scores range from 0 to 1; a coefficient divided by ten gives the percentage-point difference associated with a 0.1-point score difference.

The four original income-group M2 regressions use the same specification. The high-income group has only six observations and the low-income group 12, so their HC3 p-values are especially unstable. Two pooled income groups, each with 42 countries, are also reported. The script calculates VIF for the four M2 predictors and reruns M2 after excluding the five observations with the largest Cook's distance. This sensitivity check does not change the 84-country main sample.

## Interpretation

The simple M1 association is positive: a 0.1-point higher overall WJP score corresponds to about **10.33 percentage points** more digital-payment use (HC3 p < 0.001). With controls in M2, the estimate is about **6.02 percentage points** (p = 0.084) and does not meet the conventional 5% significance threshold. Among the separate M3 models, civil justice has the clearest adjusted association (about **9.00 percentage points** per 0.1-point score difference; p = 0.004; adjusted q = 0.034). This does not prove its coefficient exceeds every other factor's.

These are cross-sectional associations, not causal effects. Reverse causality, omitted variables, indicator definitions, missing high-income observations, and influential countries limit the conclusion. The script sets the NumPy random seed to 2025; it uses no random sampling or imputation.
