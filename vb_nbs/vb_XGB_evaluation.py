# This sript is a standalone test script (not part of the final application)
# for training an XGBoost model using a CSV file with preprocessed data
# goal is to test the change in prediction accuracy by using 
# 1. different hyperparameters 2. additional input parameters and 3. additional training data
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor
import joblib
from pathlib import Path
import numpy as np
from datetime import datetime

# === Step 1: Load CSV ===
csv_path = Path("output/combined_training_data_20250707.csv")  # <-- Update date as needed
df = pd.read_csv(csv_path)

# === 🧹 Step 2: Prepare Features & Target ===
X = df[['external_temp', 'volume', 'solar_inflow']]
y = df['internal_temp']

# === 🧪 Step 3: Train/Test Split ===
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# === 🧠 Step 4: Define XGBoost Pipeline ===
pipeline = Pipeline([
    ('scaler', StandardScaler()),
    ('xgb', XGBRegressor(n_estimators=100, learning_rate=0.1, max_depth=3, random_state=42))
])

# === 🔁 Step 5: Fit the Model ===
pipeline.fit(X_train, y_train)

# === 🔍 Step 6: Predict & Evaluate ===
y_pred = pipeline.predict(X_test)

rmse = np.sqrt(mean_squared_error(y_test, y_pred))
mae = mean_absolute_error(y_test, y_pred)
r2 = r2_score(y_test, y_pred)

print(f"✅ Model Evaluation")
print(f"  • RMSE: {rmse:.2f} °C")
print(f"  • MAE:  {mae:.2f} °C")
print(f"  • R²:   {r2:.4f}")

# === 💾 Step 7: Save Model ===
model_dir = Path("xgboost_models")
model_dir.mkdir(exist_ok=True)
model_path = model_dir / f"xgb_pipeline_{datetime.now().strftime('%Y%m%d')}.joblib"
joblib.dump(pipeline, model_path)
print(f"📦 Model saved to: {model_path}")