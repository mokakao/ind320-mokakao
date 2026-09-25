"""Page 4 of the app.

The assignment only asks for a fourth page with a dummy header and test
content for now. Later parts of the project will replace the CSV file with a
MongoDB connection and add analysis pages, so this page is kept as a place to
document the data source and what is planned next.
"""

import streamlit as st

from utils import COLUMN_NAMES, load_data

st.set_page_config(page_title="About - IND320", page_icon="ℹ️", layout="wide")

st.title("ℹ️ About the data and the project")

st.markdown(
    """
### The data

The file `data/reservoirs.csv` holds the weekly reservoir statistics published
by **NVE** (the Norwegian Water Resources and Energy Directorate). It covers
1995 up to the present and describes how full the Norwegian hydropower
reservoirs are.

The raw file is in *long* format, with one row per area per week, and with
Norwegian column names. The app keeps the rows for **Norway as a whole** and
renames the columns to English, so that every remaining column is one series
over time.

### Areas in the raw file

| Code | Meaning |
| --- | --- |
| `EL1`-`EL5` | The five electricity price areas (NO1-NO5) |
| `VASS1`-`VASS3` | The three watercourse areas |
| `NO` | Norway as a whole (used in this app) |

### Column names
"""
)

# Show the renaming as a table, so the reader can check the translation.
st.dataframe(
    {
        "Original (Norwegian)": list(COLUMN_NAMES.keys()),
        "Renamed (English)": list(COLUMN_NAMES.values()),
    },
    hide_index=True,
    width="stretch",
)

st.markdown(
    """
### Planned for the next parts of the project

* **Part 2:** replace the local CSV file with data fetched from an API and
  stored in a database (MongoDB and Cassandra).
* **Part 3:** clean the data and look for outliers and anomalies.
* **Part 4:** add forecasting and finished visualisations.

### Test content

Everything below is placeholder content for this first hand-in.
"""
)

data = load_data()
st.write("Last five weeks in the data set:")
st.dataframe(data.tail(), width="stretch")
