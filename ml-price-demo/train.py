"""Train an apartment-price model and export it for the static demo page.

The dataset is SYNTHETIC (generated below) and exists only to demonstrate the
workflow: data -> cleaning -> features -> model comparison -> export -> web app.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, r2_score
from sklearn.model_selection import KFold, cross_val_score, train_test_split

OUT = Path(__file__).parent
rng = np.random.default_rng(42)

AREAS = {  # base EGP per m2 (illustrative demo values)
    "التجمع الخامس": 72000, "الشيخ زايد": 68000, "مصر الجديدة": 55000,
    "المعادي": 58000, "العاصمة الإدارية": 52000, "مدينة نصر": 44000,
    "6 أكتوبر": 40000, "الهرم": 26000,
}
FINISH = {"بدون تشطيب": 0.78, "نصف تشطيب": 0.88, "تشطيب كامل": 1.0, "سوبر لوكس": 1.12}


def make_data(n=4000):
    area = rng.choice(list(AREAS), n, p=[.18, .14, .12, .1, .1, .14, .14, .08])
    size = np.clip(rng.normal(150, 45, n), 60, 400).round()
    beds = np.clip((size / 55).round() + rng.integers(-1, 2, n), 1, 5).astype(int)
    baths = np.clip(beds - rng.integers(0, 2, n), 1, 4).astype(int)
    floor = rng.integers(0, 13, n)
    finish = rng.choice(list(FINISH), n, p=[.2, .25, .4, .15])
    compound = rng.random(n) < np.where(np.isin(area, ["التجمع الخامس", "الشيخ زايد", "العاصمة الإدارية", "6 أكتوبر"]), .7, .25)
    age = np.clip(rng.exponential(7, n), 0, 40).round()
    garden = (floor == 0) & (rng.random(n) < .6)
    base = np.array([AREAS[a] for a in area])
    ppm = (base * np.array([FINISH[f] for f in finish]) * np.where(compound, 1.18, 1.0)
           * (1 - np.minimum(age, 30) * .009) * (1 + np.where(floor == 0, -.04, np.minimum(floor, 8) * .006))
           * np.where(garden, 1.12, 1.0) * (1 - (size - 150) / 3000) * rng.lognormal(0, .09, n))
    price = (ppm * size).round(-4)
    df = pd.DataFrame(dict(area=area, size=size, beds=beds, baths=baths, floor=floor, finish=finish,
                           compound=compound.astype(int), age=age, garden=garden.astype(int), price=price))
    # inject realistic dirt, then clean it (part of the demo story)
    dirty = df.sample(60, random_state=1).index
    df.loc[dirty[:30], "size"] = np.nan
    df.loc[dirty[30:], "price"] = df.loc[dirty[30:], "price"] * 10  # entry errors
    return df


raw = make_data()
n_raw = len(raw)
df = raw.dropna(subset=["size"]).copy()
ppm = df.price / df["size"]
q1, q3 = ppm.quantile([.25, .75])
df = df[(ppm > q1 - 3 * (q3 - q1)) & (ppm < q3 + 3 * (q3 - q1))]
n_clean = len(df)

CAT = {"area": list(AREAS), "finish": list(FINISH)}
NUM = ["size", "beds", "baths", "floor", "compound", "age", "garden"]
FEATS = NUM + [f"area={a}" for a in CAT["area"]] + [f"finish={f}" for f in CAT["finish"]]


def encode(d):
    X = d[NUM].astype(float).copy()
    for c, vals in CAT.items():
        for v in vals:
            X[f"{c}={v}"] = (d[c] == v).astype(float)
    return X[FEATS].values


X, y = encode(df), np.log(df.price.values)
Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=.2, random_state=7)

models = {
    "انحدار خطي (Ridge)": Ridge(alpha=1.0),
    "غابة عشوائية (Random Forest)": RandomForestRegressor(n_estimators=300, min_samples_leaf=3, n_jobs=-1, random_state=0),
    "Gradient Boosting": GradientBoostingRegressor(n_estimators=400, learning_rate=.05, max_depth=4, subsample=.8, random_state=0),
}
results = []
kf = KFold(5, shuffle=True, random_state=0)
for name, m in models.items():
    cv = cross_val_score(m, Xtr, ytr, cv=kf, scoring="r2").mean()
    m.fit(Xtr, ytr)
    p = np.exp(m.predict(Xte)); t = np.exp(yte)
    results.append(dict(name=name, cv_r2=round(cv, 3), r2=round(r2_score(t, p), 3),
                        mae=round(mean_absolute_error(t, p)), mape=round(mean_absolute_percentage_error(t, p) * 100, 1)))
    print(results[-1])

best = models["Gradient Boosting"]
pred = np.exp(best.predict(Xte)); true = np.exp(yte)
idx = rng.choice(len(true), 250, replace=False)

# group one-hot importances back into readable features
imp = dict(zip(FEATS, best.feature_importances_))
labels = {"size": "المساحة", "beds": "عدد الغرف", "baths": "الحمامات", "floor": "الدور", "compound": "داخل كمبوند",
          "age": "عمر المبنى", "garden": "حديقة خاصة", "area": "المنطقة", "finish": "التشطيب"}
grouped = {}
for k, v in imp.items():
    key = k.split("=")[0]
    grouped[labels[key]] = grouped.get(labels[key], 0) + v
importance = sorted(([k, round(v * 100, 1)] for k, v in grouped.items()), key=lambda x: -x[1])


def export_tree(t):
    t = t.tree_
    return dict(l=t.children_left.tolist(), r=t.children_right.tolist(), f=t.feature.tolist(),
                t=[round(x, 4) for x in t.threshold.tolist()], v=[round(x[0][0], 5) for x in t.value])


model_json = dict(features=FEATS, num=NUM, cat=CAT, init=float(best.init_.constant_[0][0]) if hasattr(best.init_, "constant_") else float(np.mean(ytr)),
                  lr=best.learning_rate, trees=[export_tree(e[0]) for e in best.estimators_])
# sanity check: re-implement prediction like the JS will
def js_like(x):
    s = model_json["init"]
    for tr in model_json["trees"]:
        n = 0
        while tr["l"][n] != -1:
            n = tr["l"][n] if x[tr["f"][n]] <= tr["t"][n] else tr["r"][n]
        s += model_json["lr"] * tr["v"][n]
    return s
chk = np.array([js_like(x) for x in Xte[:50]])
print("export max diff:", np.abs(chk - best.predict(Xte[:50])).max())

report = dict(n_raw=n_raw, n_clean=n_clean, n_train=len(Xtr), n_test=len(Xte), results=results, importance=importance,
              scatter=[[round(true[i] / 1e6, 2), round(pred[i] / 1e6, 2)] for i in idx],
              areas=list(AREAS), finishes=list(FINISH),
              area_ppm={a: round(float((df[df.area == a].price / df[df.area == a]["size"]).median())) for a in AREAS})
(OUT / "static").mkdir(exist_ok=True)
(OUT / "static" / "model.json").write_text(json.dumps(model_json, ensure_ascii=False, separators=(",", ":")))
(OUT / "static" / "report.json").write_text(json.dumps(report, ensure_ascii=False))
raw.head(400).to_csv(OUT / "data_sample.csv", index=False)
print("model.json KB:", (OUT / "static" / "model.json").stat().st_size // 1024)
