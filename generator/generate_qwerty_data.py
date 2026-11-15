"""
QWERTY Logistics - Demand Forecast Accuracy & S&OP project
Synthetic data generator (SIMULATED DATA - not a real company)

Author: Akshaynadh Ajithkumar

What this script does
---------------------
1. Builds a product catalogue of 80 beauty & personal-care SKUs in 6 families.
2. Simulates monthly demand (units) for 3 markets (FR, DE, UK) from Jan 2023
   to Oct 2026, using: base volume x market factor x trend x seasonality
   x promotions x random noise, plus two deliberate "real-life" events.
3. Produces three 1-month-ahead forecasts for every SKU-market-month from
   Jan 2024 onwards:
      NAIVE - seasonal naive (same month last year)
      STAT  - Holt-Winters exponential smoothing (written below in numpy),
              fitted on promo-cleansed history = baseline demand
      FINAL - the planners' consensus forecast = STAT + manual adjustments
   and a 6-month forward forecast (Nov 2026 - Apr 2027) made after the
   October 2026 close.
4. Creates an inventory snapshot at 31 Oct 2026.
5. Writes everything to CSV files in ./data

Run:  python generate_qwerty_data.py
Needs: pandas, numpy (no other libraries). Fixed random seed -> same output
every time.
"""

from pathlib import Path
import numpy as np
import pandas as pd

SEED = 2026
rng = np.random.default_rng(SEED)
OUT = Path(__file__).parent / "data"
OUT.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# 1. Calendar
# ---------------------------------------------------------------------------
HIST_START = pd.Timestamp("2023-01-01")
LAST_CLOSED = pd.Timestamp("2026-10-01")          # last month with actuals
FUTURE_MONTHS = 6                                  # Nov 2026 - Apr 2027
hist_months = pd.date_range(HIST_START, LAST_CLOSED, freq="MS")
future_months = pd.date_range(LAST_CLOSED + pd.DateOffset(months=1),
                              periods=FUTURE_MONTHS, freq="MS")
N_HIST = len(hist_months)                          # 46 months
FIRST_FC = 12                                      # forecasts start Jan 2024

# ---------------------------------------------------------------------------
# 2. Product families: seasonality (Jan..Dec), price range, lead time
# ---------------------------------------------------------------------------
FAMILIES = {
    #             n   seasonality Jan..Dec                                                 price      lead time (months)
    "Skincare":  (20, [0.95,0.90,0.95,1.00,1.00,0.95,0.90,0.90,1.00,1.05,1.15,1.25], (15, 60), [1.0, 1.5]),
    "Makeup":    (18, [0.90,0.95,1.00,1.00,1.00,0.95,0.90,0.90,1.00,1.05,1.15,1.30], (10, 40), [1.0, 1.5]),
    "Fragrance": (14, [0.60,0.90,0.70,0.70,1.00,1.00,0.60,0.60,0.80,1.00,1.70,2.40], (40, 120), [2.0, 3.0]),
    "Haircare":  (12, [1.00,0.98,1.00,1.00,1.02,1.03,1.02,1.00,1.00,0.98,0.98,1.00], (6, 25), [1.0]),
    "Suncare":   (8,  [0.20,0.25,0.50,1.00,1.80,2.60,2.80,1.90,0.60,0.20,0.10,0.15], (12, 30), [2.0]),
    "Gift Sets": (8,  [0.15,0.30,0.20,0.20,0.40,0.35,0.15,0.15,0.30,0.80,3.50,5.50], (35, 90), [3.0]),
}
NAME_PARTS = {
    "Skincare":  (["Hydra", "Pure", "Radiance", "Calm", "Vital", "Clear"],
                  ["Serum 30ml", "Day Cream 50ml", "Night Cream 50ml", "Cleanser 150ml",
                   "Eye Gel 15ml", "Toner 200ml", "Mask 75ml", "SPF Moisturiser 50ml"]),
    "Makeup":    (["Velvet", "Glow", "Studio", "Nude", "Bold"],
                  ["Foundation", "Lipstick", "Mascara", "Concealer", "Blush",
                   "Eyeliner", "Lip Gloss", "Primer"]),
    "Fragrance": (["Nuit", "Azur", "Ambre", "Fleur", "Cedre"],
                  ["EDP 50ml", "EDP 100ml", "EDT 50ml", "EDT 100ml", "Body Mist 150ml"]),
    "Haircare":  (["Silk", "Volume", "Repair", "Curl"],
                  ["Shampoo 250ml", "Conditioner 250ml", "Hair Mask 200ml", "Hair Oil 100ml"]),
    "Suncare":   (["Solaire", "Beach"],
                  ["SPF30 Lotion 200ml", "SPF50 Lotion 200ml", "SPF50 Spray 150ml",
                   "After-Sun 200ml", "Kids SPF50 150ml"]),
    "Gift Sets": (["Noel", "Prestige", "Discovery", "Signature"],
                  ["Fragrance Coffret", "Skincare Trio", "Makeup Box", "Mini Collection"]),
}
FAMILY_CODE = {"Skincare": "SK", "Makeup": "MU", "Fragrance": "FG",
               "Haircare": "HC", "Suncare": "SC", "Gift Sets": "GS"}

products = []
for fam, (n, season, (pmin, pmax), lead_opts) in FAMILIES.items():
    prefixes, suffixes = NAME_PARTS[fam]
    used = set()
    for i in range(n):
        while True:
            name = f"{rng.choice(prefixes)} {rng.choice(suffixes)}"
            if name not in used:
                used.add(name)
                break
        price = round(float(rng.uniform(pmin, pmax)), 2)
        products.append({
            "SKU_ID": f"{FAMILY_CODE[fam]}-{i + 1:03d}",
            "SKU_Name": name,
            "Product_Family": fam,
            "Wholesale_Price_EUR": price,
            "Unit_Cost_EUR": round(price * float(rng.uniform(0.35, 0.50)), 2),
            "Supplier_Lead_Time_Months": float(rng.choice(lead_opts)),
            "Target_Service_Level": 0.95,
        })
dim_product = pd.DataFrame(products)

MARKETS = pd.DataFrame({
    "Market_ID": ["FR", "DE", "UK"],
    "Market_Name": ["France", "Germany", "United Kingdom"],
    "Region": ["Western Europe", "Central Europe", "Northern Europe"],
    "Planning_Team": ["Paris", "Paris", "London"],
})

# ---------------------------------------------------------------------------
# 3. Demand simulation
# ---------------------------------------------------------------------------
VIRAL_SKU = "MU-004"              # goes viral on social media in March 2026
VIRAL_FROM = pd.Timestamp("2026-03-01")
DELIST_FAMILY, DELIST_MARKET = "Haircare", "DE"   # retailer delisting Jul 2025
DELIST_FROM = pd.Timestamp("2025-07-01")

sales_rows, series = [], {}
for _, p in dim_product.iterrows():
    fam = p["Product_Family"]
    season = np.array(FAMILIES[fam][1])
    season = season / season.mean()
    base = float(np.exp(rng.normal(6.0, 0.9)))      # skewed volumes -> Pareto/ABC
    growth = float(rng.uniform(-0.15, 0.25))         # annual trend
    noise_sd = float(rng.uniform(0.05, 0.28))        # forecastability differs by SKU
    for m in MARKETS["Market_ID"]:
        mfac = {"FR": 1.0, "DE": rng.uniform(0.6, 1.0), "UK": rng.uniform(0.4, 0.8)}[m]
        # promotions: 2-4 months per year (none for Gift Sets, 0-1 for Fragrance)
        promo = np.zeros(N_HIST, dtype=int)
        uplift = np.ones(N_HIST)
        if fam != "Gift Sets":
            for y in range(4):
                k = int(rng.integers(0, 2)) if fam == "Fragrance" else int(rng.integers(2, 5))
                months = rng.choice(12, size=k, replace=False)
                for mm in months:
                    t = y * 12 + mm
                    if t < N_HIST:
                        promo[t] = 1
                        uplift[t] = rng.uniform(1.3, 1.9)
        y_vals = np.zeros(N_HIST)
        for t, d in enumerate(hist_months):
            v = base * mfac * (1 + growth) ** (t / 12) * season[d.month - 1]
            v *= uplift[t]
            if t > 0 and promo[t - 1] and not promo[t]:
                v *= 0.85                              # post-promo dip (pull-forward)
            if p["SKU_ID"] == VIRAL_SKU and d >= VIRAL_FROM:
                v *= 1.8
            if fam == DELIST_FAMILY and m == DELIST_MARKET and d >= DELIST_FROM:
                v *= 0.70
            v *= np.exp(rng.normal(-noise_sd ** 2 / 2, noise_sd))
            y_vals[t] = max(0, round(v))
        series[(p["SKU_ID"], m)] = {"y": y_vals, "promo": promo, "uplift": uplift,
                                    "family": fam}
        mprice = {"FR": 1.00, "DE": 0.97, "UK": 1.05}[m]
        for t, d in enumerate(hist_months):
            sales_rows.append({
                "Month_Start": d.date(), "SKU_ID": p["SKU_ID"], "Market_ID": m,
                "Units_Sold": int(y_vals[t]),
                "Net_Revenue_EUR": round(y_vals[t] * p["Wholesale_Price_EUR"] * mprice, 2),
                "Promo_Flag": int(promo[t]),
            })
fact_sales = pd.DataFrame(sales_rows)

# Promotions are planned in advance, so the planners also know the promo
# calendar for the forward months. Simulate it the same way.
future_promo = {}
for key, s in series.items():
    fp = np.zeros(FUTURE_MONTHS, dtype=int)
    fu = np.ones(FUTURE_MONTHS)
    if s["family"] not in ("Gift Sets", "Fragrance"):
        for h in range(FUTURE_MONTHS):
            if rng.random() < 0.22:
                fp[h], fu[h] = 1, rng.uniform(1.3, 1.9)
    future_promo[key] = (fp, fu)

# ---------------------------------------------------------------------------
# 4. Forecasts
# ---------------------------------------------------------------------------
PHI = 0.9   # damped trend


def holt_winters(y, alpha, beta, gamma, horizon=0):
    """Multiplicative-season, damped additive-trend Holt-Winters.
    Returns one-step-ahead forecasts for t = 12..len(y)-1 (index-aligned,
    NaN before 12) and `horizon` forecasts after the last observation."""
    n = len(y)
    level = max(y[:12].mean(), 1.0)
    trend = 0.0
    seas = list(np.maximum(y[:12] / level, 0.05))
    fc = np.full(n, np.nan)
    for t in range(12, n):
        s = seas[t - 12]
        fc[t] = max(0.0, (level + PHI * trend) * s)
        new_level = alpha * (y[t] / s) + (1 - alpha) * (level + PHI * trend)
        new_level = max(new_level, 0.1)
        trend = beta * (new_level - level) + (1 - beta) * PHI * trend
        seas.append(max(gamma * (y[t] / new_level) + (1 - gamma) * s, 0.05))
        level = new_level
    future = []
    damp = 0.0
    for h in range(1, horizon + 1):
        damp += PHI ** h
        future.append(max(0.0, (level + damp * trend) * seas[n - 12 + (h - 1) % 12]))
    return fc, np.array(future)


GRID = [(a, b, g) for a in (0.1, 0.2, 0.3, 0.5)
        for b in (0.0, 0.05, 0.1) for g in (0.05, 0.1, 0.2, 0.3)]

# Planner behaviour (drives the FINAL forecast)
high_touch = set(rng.choice(dim_product["SKU_ID"], size=20, replace=False))

fc_rows = []
for (sku, m), s in series.items():
    y, fam = s["y"], s["family"]
    # Promo-cleansed history: remove promo uplift and post-promo dip so the
    # statistical model learns the BASELINE demand (standard planning practice).
    y_clean = y.copy()
    for t in range(N_HIST):
        if s["promo"][t]:
            y_clean[t] = y[t] / s["uplift"][t]
        elif t > 0 and s["promo"][t - 1]:
            y_clean[t] = y[t] / 0.85
    # tune parameters on 2024 errors only (t = 12..23)
    best = min(GRID, key=lambda prm: np.nansum(np.abs(
        holt_winters(y_clean[:24], *prm)[0][12:24] - y_clean[12:24])))
    stat_hist, stat_future = holt_winters(y_clean, *best, horizon=FUTURE_MONTHS)
    fp, fu = future_promo[(sku, m)]

    all_targets = list(hist_months[FIRST_FC:]) + list(future_months)
    for idx, target in enumerate(all_targets):
        is_future = target > LAST_CLOSED
        t = FIRST_FC + idx
        if is_future:
            h = t - N_HIST + 1
            created = LAST_CLOSED
            stat = stat_future[h - 1]
            naive = y[t - 12] if t - 12 < N_HIST else np.nan
            promo_flag, true_uplift = fp[h - 1], fu[h - 1]
        else:
            h = 1
            created = target - pd.DateOffset(months=1)
            stat = stat_hist[t]
            naive = y[t - 12]
            promo_flag, true_uplift = s["promo"][t], s["uplift"][t]

        adj = 1.0
        if promo_flag:                                   # planners add promo uplift
            adj *= true_uplift * rng.normal(1.0, 0.12)
        prev_promo = (s["promo"][t - 1] if t - 1 < N_HIST else fp[t - 1 - N_HIST])
        if prev_promo and not promo_flag and rng.random() < 0.5:
            adj *= 0.85                                  # post-promo dip (remembered half the time)
        if fam in ("Fragrance", "Gift Sets") and target.month in (10, 11, 12):
            adj *= rng.uniform(1.12, 1.28)               # sales-team optimism in Q4
        if sku in high_touch and rng.random() < 0.30:
            adj *= np.exp(rng.uniform(-0.2, 0.2))       # "gut-feel" overrides
        if sku == VIRAL_SKU and target >= pd.Timestamp("2026-05-01"):
            adj *= 1.40                                  # planners react to the trend
        final = stat * adj

        for ver, val in (("NAIVE", naive), ("STAT", stat), ("FINAL", final)):
            fc_rows.append({
                "Target_Month": target.date(),
                "Forecast_Created_Month": created.date(),
                "Lag_Months": h,
                "SKU_ID": sku, "Market_ID": m, "Version_ID": ver,
                "Forecast_Units": int(round(val)),
            })
fact_forecast = pd.DataFrame(fc_rows)

# ---------------------------------------------------------------------------
# 5. Inventory snapshot 31 Oct 2026
# ---------------------------------------------------------------------------
fut = fact_forecast[(fact_forecast["Version_ID"] == "FINAL")
                    & (fact_forecast["Lag_Months"].between(1, 3))
                    & (pd.to_datetime(fact_forecast["Target_Month"]) > LAST_CLOSED)]
avg3 = fut.groupby(["SKU_ID", "Market_ID"])["Forecast_Units"].mean()
lead = dim_product.set_index("SKU_ID")["Supplier_Lead_Time_Months"]
inv_rows = []
for (sku, m), a in avg3.items():
    # Policy: hold roughly lead time + 0.5-1.5 months of cover. Some SKU-markets
    # drift below (stock-out risk) or far above (excess) the policy.
    lt, r = lead[sku], rng.random()
    cover = (lt * rng.uniform(0.2, 0.9) if r < 0.12 else
             lt + rng.uniform(3.5, 7.0) if r > 0.88 else lt + rng.uniform(0.3, 1.5))
    inv_rows.append({"Snapshot_Date": "2026-10-31", "SKU_ID": sku, "Market_ID": m,
                     "On_Hand_Units": int(round(a * cover))})
fact_inventory = pd.DataFrame(inv_rows)

# ---------------------------------------------------------------------------
# 6. Dimensions: date and forecast version
# ---------------------------------------------------------------------------
dates = pd.date_range("2023-01-01", "2027-12-31", freq="D")
dim_date = pd.DataFrame({"Date": dates.date})
dim_date["Year"] = dates.year
dim_date["Quarter"] = "Q" + dates.quarter.astype(str)
dim_date["Month_Number"] = dates.month
dim_date["Month_Name"] = dates.strftime("%B")
dim_date["Month_Short"] = dates.strftime("%b")
dim_date["Year_Month"] = dates.strftime("%Y-%m")
dim_date["Year_Month_Sort"] = dates.year * 100 + dates.month
dim_date["Month_Start"] = dates.to_period("M").to_timestamp().date
month_start = dates.to_period("M").to_timestamp()
dim_date["Is_Closed_Month"] = (month_start <= LAST_CLOSED).astype(int)
dim_date["Is_Last_12_Closed_Months"] = ((month_start > LAST_CLOSED - pd.DateOffset(months=12))
                                        & (month_start <= LAST_CLOSED)).astype(int)
dim_date["Is_Forward_Month"] = ((month_start > LAST_CLOSED)
                                & (month_start <= future_months[-1])).astype(int)

dim_version = pd.DataFrame({
    "Version_ID": ["NAIVE", "STAT", "FINAL"],
    "Version_Name": ["Seasonal Naive", "Statistical (Holt-Winters)", "Final Consensus"],
    "Version_Sort": [1, 2, 3],
    "Description": [
        "Same month last year. Benchmark that any real forecast must beat.",
        "Damped Holt-Winters exponential smoothing, parameters tuned on 2024.",
        "Statistical forecast after planner / sales adjustments (S&OP consensus).",
    ],
})

# ---------------------------------------------------------------------------
# 7. Write CSVs
# ---------------------------------------------------------------------------
dim_product.to_csv(OUT / "dim_product.csv", index=False)
MARKETS.to_csv(OUT / "dim_market.csv", index=False)
dim_date.to_csv(OUT / "dim_date.csv", index=False)
dim_version.to_csv(OUT / "dim_forecast_version.csv", index=False)
fact_sales.to_csv(OUT / "fact_sales.csv", index=False)
fact_forecast.to_csv(OUT / "fact_forecast.csv", index=False)
fact_inventory.to_csv(OUT / "fact_inventory.csv", index=False)

for f in sorted(OUT.glob("*.csv")):
    print(f"{f.name:28s} {sum(1 for _ in open(f)) - 1:>7,d} rows")
