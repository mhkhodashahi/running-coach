import os
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
app = FastAPI()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
engine = create_engine(f"sqlite:///{PROJECT_ROOT / 'garmin_data.db'}")
Session = sessionmaker(bind=engine)

@app.get("/", response_class=HTMLResponse)
async def show_vo2max(request: Request):
    session = Session()
    query = "SELECT date, value FROM vo2max ORDER BY date ASC"  # Changed to ASC for chronological order
    df = pd.read_sql(query, engine)

    # Convert dates to string format for JSON serialization
    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')

    vo2max_data = df.to_dict('records')

    weekly_runs = []
    inspector = inspect(engine)

    if inspector.has_table("activities"):
        activities_df = pd.read_sql(
            "SELECT start_time, distance, activity_type FROM activities",
            engine
        )

        if not activities_df.empty:
            activities_df["start_time"] = pd.to_datetime(activities_df["start_time"])
            cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=90)
            activities_df = activities_df[activities_df["start_time"] >= cutoff]

            runs_df = activities_df[
                activities_df["activity_type"].str.contains("run", case=False, na=False)
            ].copy()

            if not runs_df.empty:
                runs_df["distance_km"] = runs_df["distance"].fillna(0) / 1000
                runs_df["week"] = runs_df["start_time"].dt.to_period("W").apply(
                    lambda r: r.start_time.date()
                )

                weekly_runs_df = (
                    runs_df.groupby("week", as_index=False)["distance_km"].sum()
                    .sort_values("week")
                )
                weekly_runs_df["week"] = weekly_runs_df["week"].astype(str)
                weekly_runs = weekly_runs_df.to_dict("records")

    session.close()
    
    return templates.TemplateResponse(
        "vo2max.html",
        {
            "request": request,
            "vo2max_data": vo2max_data,
            "weekly_runs": weekly_runs
        }
    )

def main() -> None:
    import uvicorn

    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
