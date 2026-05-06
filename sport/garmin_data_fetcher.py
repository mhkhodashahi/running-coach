import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import Column, DateTime, Float, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from config import get_settings
from services.garmin_client import GarminAPIClient

try:
    from paper_crawler.services.OllamaClient import GeminiClient
except ImportError:
    GeminiClient = None

Base = declarative_base()
PROJECT_ROOT = Path(__file__).resolve().parent.parent
engine = create_engine(f"sqlite:///{PROJECT_ROOT / 'garmin_data.db'}")
Session = sessionmaker(bind=engine)


class HeartRate(Base):
    __tablename__ = 'heart_rates'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime)
    value = Column(Integer)


class VO2Max(Base):
    __tablename__ = 'vo2max'
    id = Column(Integer, primary_key=True)
    date = Column(DateTime)
    value = Column(String)


class Activity(Base):
    __tablename__ = 'activities'
    id = Column(Integer, primary_key=True)
    activity_id = Column(Integer, unique=True, index=True)
    name = Column(String)
    activity_type = Column(String)
    start_time = Column(DateTime)
    distance = Column(Float)
    duration = Column(Float)


Base.metadata.create_all(engine)

logger = logging.getLogger(__name__)


class GarminFetcher:
    """Class for fetching data from Garmin Connect."""

    def __init__(
        self,
        email: str,
        password: str,
        output_dir: str | Path = PROJECT_ROOT / "garmin_data",
        token_dir: str | Path | None = None,
        rate_limit_cooldown_minutes: int = 30,
    ):
        """
        Initialize Garmin Connect client.

        Args:
            email: Garmin Connect account email
            password: Garmin Connect account password
            output_dir: Directory to save downloaded data
        """
        self.api_client = GarminAPIClient(
            email=email,
            password=password,
            token_dir=token_dir,
            rate_limit_cooldown_minutes=rate_limit_cooldown_minutes,
        )
        self.client = None
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def connect(self) -> bool:
        """
        Establish connection to Garmin Connect.

        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            self.client = self.api_client.get_authenticated_client()
            return True
        except (RuntimeError, ValueError) as exc:
            logger.error(str(exc))
            return False
        except Exception as e:
            logger.error(f"Connection failed: {str(e)}")
            return False

    def get_activities(self, 
                      start_date: str | datetime,
                      end_date: str | datetime | None = None,
                      save: bool = True) -> pd.DataFrame | None:
        """
        Fetch activities between dates.
        
        Args:
            start_date: Start date (YYYY-MM-DD or datetime)
            end_date: End date (YYYY-MM-DD or datetime), defaults to today
            save: Whether to save data to file
            
        Returns:
            DataFrame with activities data or None if failed
        """
        try:
            # Convert dates if needed
            if isinstance(start_date, str):
                start_date = datetime.strptime(start_date, "%Y-%m-%d")
            if isinstance(end_date, str):
                end_date = datetime.strptime(end_date, "%Y-%m-%d")
            if end_date is None:
                end_date = datetime.now()

            # Fetch activities
            activities = self.client.get_activities_by_date(
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d")
            )

            if not activities:
                logger.info("No activities found for the specified period")
                return None

            # Convert to DataFrame
            df = pd.DataFrame(activities)
            
            # Save activities to database
            session = Session()
            for _, row in df.iterrows():
                try:
                    activity_id = int(row.get("activityId"))
                except (TypeError, ValueError):
                    continue

                existing = session.query(Activity).filter_by(activity_id=activity_id).first()
                if existing:
                    continue

                activity_type = row.get("activityType")
                if isinstance(activity_type, dict):
                    activity_type = activity_type.get("typeKey")

                start_time_raw = row.get("startTimeLocal") or row.get("startTimeGMT")
                start_time = pd.to_datetime(start_time_raw, errors="coerce")
                distance = row.get("distance")
                duration = row.get("duration")

                activity = Activity(
                    activity_id=activity_id,
                    name=row.get("activityName"),
                    activity_type=str(activity_type) if activity_type is not None else None,
                    start_time=start_time.to_pydatetime() if not pd.isnull(start_time) else None,
                    distance=float(distance) if pd.notnull(distance) else None,
                    duration=float(duration) if pd.notnull(duration) else None
                )
                session.add(activity)
            session.commit()
            session.close()

            # Save to CSV if requested
            if save:
                filename = f"activities_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.csv"
                filepath = self.output_dir / filename
                df.to_csv(filepath, index=False)
                logger.info(f"Saved activities to {filepath}")

            return df

        except Exception as e:
            logger.error(f"Failed to fetch activities: {str(e)}")
            return None

    def get_heart_rate(self, 
                      date: str | datetime,
                      save: bool = True) -> pd.DataFrame | None:
        """
        Fetch heart rate data for specific date.
        
        Args:
            date: Date to fetch data for (YYYY-MM-DD or datetime)
            save: Whether to save data to file
            
        Returns:
            DataFrame with heart rate data or None if failed
        """
        try:
            # Convert date if needed
            if isinstance(date, str):
                date = datetime.strptime(date, "%Y-%m-%d")

            # Fetch heart rate data
            heart_data = self.client.get_heart_rates(date.strftime("%Y-%m-%d"))
            
            if not heart_data:
                logger.info(f"No heart rate data found for {date.strftime('%Y-%m-%d')}")
                return None

            # Convert to DataFrame
            df = pd.DataFrame(heart_data)

            # Save to database
            session = Session()
            for _, row in df.iterrows():
                hr = HeartRate(
                    timestamp=datetime.fromtimestamp(row['timestamp'] / 1000),
                    value=row['value']
                )
                session.add(hr)
            session.commit()
            session.close()

            # Save to file if requested
            if save:
                filename = f"heart_rate_{date.strftime('%Y%m%d')}.csv"
                filepath = self.output_dir / filename
                df.to_csv(filepath, index=False)
                logger.info(f"Saved heart rate data to {filepath}")

            return df

        except Exception as e:
            logger.error(f"Failed to fetch heart rate data: {str(e)}")
            return None

    def get_summary_metrics(self, date: str | datetime) -> pd.DataFrame | None:
        """
        Fetch summary metrics between dates.

        Args:
            date: date (YYYY-MM-DD or datetime)
        """

        summary = self.client.get_stats(date)  # includes HR, VO2max
        activities = self.client.get_activities(0, 3)
        #sleep = self.client.get_sleep_data(date)
        hrv = self.client.get_heart_rates(date)
        body_battery = self.client.get_body_battery(date)

        # Combine into a summary dictionary
        user_data = {
            "summary": summary,
            "activities": activities,
            #"sleep": sleep,
            "hrv": hrv,
            "body_battery": body_battery
        }

        prompt = f"""
        You are a personalized AI assistant for my Garmin data.
        Here is my Garmin data from the last few days:

        {json.dumps(user_data, indent=2)}

        Based on this, please:
        - Analyze my training load and VO2max trend
        - Suggest any adjustments for fat loss and performance
        - Recommend weekly changes to improve HRV and sleep
        """

        if GeminiClient is None:
            logger.error(
                "Summary metrics require the local 'paper_crawler' project to be importable."
            )
            return None

        # Send prompt to Gemini for AI-driven recommendations
        client = GeminiClient()
        return client.ask_question(prompt)


def main() -> None:
    load_dotenv()
    settings = get_settings()

    fetcher = GarminFetcher(
        email=settings.garmin_email,
        password=settings.garmin_password,
        token_dir=settings.garmin_token_dir,
        rate_limit_cooldown_minutes=settings.garmin_rate_limit_cooldown_minutes,
    )

    if not fetcher.connect():
        print("Failed to connect to Garmin Connect")
        return

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = today - timedelta(days=90)
    fetcher.get_activities(start_date=start_date, end_date=today)

    for offset in range(1, 10):
        target_date = today - timedelta(days=10 - offset)

        heart_rate = fetcher.get_heart_rate(date=target_date)
        print(f"Heart rate data for {target_date.strftime('%Y-%m-%d')}:")
        print(heart_rate)

        vo2max = fetcher.client.get_max_metrics(
            cdate=target_date.strftime("%Y-%m-%d")
        )
        print(f"VO2max data for {target_date.strftime('%Y-%m-%d')}:")
        print(vo2max)

        if len(vo2max) > 0 and vo2max[0].get("generic"):
            session = Session()
            vo2max_entry = VO2Max(
                date=target_date,
                value=str(vo2max[0].get("generic")),
            )
            session.add(vo2max_entry)
            session.commit()
            session.close()


if __name__ == "__main__":
    main()
