Temperature Simulator - BKViewer-FastAPI - 

A small FastAPI + Cesium app that
	1.	Loads an IFC model of the BK building,
	2.	Lets you pick a room in the browser (or via URL),
	3.	Extracts geometry + weather data,
	4.	Feeds those inputs to an XGBoost pipeline to predict the room’s internal temperature.

PREREQUISITES
	•	Python 3.11+
	•	IfcOpenShell installed so that import ifcopenshell works
	•	Git
    •	downloaded IFC file from - https://drive.google.com/file/d/1ZXrI8kJfnkPilKgl4p4mBvxf7cqVyY5u/view?usp=drive_link


*NOTE - We use uv as our package manager throughout.

SETUP AND RUN 
1. Set up your environment with uv sync to install everything into a fresh venv (emulating my setup)
2. (OPTIONAL) (Re-)train the XGBoost model
	•	Run standalone python xgboost_training.py if you want to build a brand-new model.
	•	Otherwise, the app will automatically load the latest .joblib file in xgboost_models/
3. Start FastAPI server (uv run main:app --reload --host 127.0.0.1 --port 8000)
4. Select room by either of these two ways: 
    a. Go to http://127.0.0.1:8000/ and pick from the dropdown
    b. Or hit http://127.0.0.1:8000/api/simulate/BG.West.010 (direct URL)

What happens under the hood
	•	Both UI and /api/simulate/... endpoint call simulator.py
	•	simulator.py extracts the 3 inputs (room volume, solar inflow, external temp),
	•	then loads the latest XGBoost pipeline and returns the predicted internal temperature.
About the XGBoost model
	•	Instead of native .json or .model formats, the pipeline is saved as a joblib file
	•	This preserves all preprocessing steps (via an sklearn.Pipeline) alongside the trained regressor.

project-root/
├── static/
│   ├── index.html
│   ├── main.js
│   ├── style.css
│   ├── bk_rooms.csv
│   └── IFC/
│       └── BK_v2_vb_updated.ifc      ← download from Drive link
├── xgboost_training.py               ← train/save XGB pipeline
├── xgboost_models/                   ← saved .joblib pipelines
├── ifc_parsers.py                    ← IFC→Site/Room/Window data
├── ifc_calculators.py                ← solar-inflow helper
├── simulator.py                      ← mediator: parsers→weather→model
├── main.py                           ← FastAPI app, mounts static + /api
├── pyproject.toml                    ← uv-managed dependencies
└── README.md                         ← you are here
