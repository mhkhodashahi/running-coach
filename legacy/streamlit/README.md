# Legacy Streamlit UI

This is a reversible back-office copy of the old UI. It will be removed before the first public release. The FastAPI site in `web/` is the default interface.

From the repository root, install the optional extra and run:

```sh
pip install -e '.[legacy-streamlit]'
PYTHONPATH=.:legacy/streamlit streamlit run legacy/streamlit/app/main.py
```

The legacy UI uses the same configured database. Upgrade it with `python -m scripts.upgrade_db --db <path>` before starting either UI. Map rendering may still require the legacy Google Maps configuration.
