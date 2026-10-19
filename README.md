# IND320 – Project work

Mohammad el Meziani · IND320 Data to decision, autumn 2026

A small dashboard about Norwegian hydropower: how full the reservoirs are, and
how much power is flowing across the cables to Denmark, Germany and England.

## ▶ Screencasts

**Part 2:** https://www.youtube.com/watch?v=VRHKimh_U80

**Part 1:** https://nmbu.cloud.panopto.eu/Panopto/Pages/Viewer.aspx?id=0da9ddba-20d8-4a0b-8e05-b4d301405fce

## 💧 Live app

**https://ind320-mokakaoo.streamlit.app**

---

## Part 2 – data sources

The CSV file is gone. Everything now comes from two live sources:

| Source | What it gives | Where the app reads it |
| --- | --- | --- |
| [NVE Magasinstatistikk API](https://biapi.nve.no/magasinstatistikk/swagger/index.html) | weekly reservoir levels per area | directly, on every page load |
| [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/) | cross-border physical flow, 15 min | via MongoDB |

The ENTSO-E data take a detour, because Streamlit Cloud cannot reach a database
on my laptop:

```
ENTSO-E API  ->  Cassandra (local, raw 15-min)  ->  Spark (hourly average)  ->  MongoDB  ->  the app
```

## Layout

| Path | What it is |
| --- | --- |
| [`notebooks/project_work_part2.ipynb`](notebooks/project_work_part2.ipynb) | The hand-in notebook for part 2 |
| [`notebooks/project_work_part1.ipynb`](notebooks/project_work_part1.ipynb) | Part 1, kept for the record |
| `Home.py` | Front page of the app |
| `pages/` | Reservoir table, reservoir plots, power flow, about |
| `modules/nve.py` | The NVE API |
| `modules/entsoe_flows.py` | The ENTSO-E API |
| `modules/storage.py` | Cassandra, Spark and MongoDB |
| `utils.py` | Cached loading and the shared sidebar controls |

## Running it locally

```bash
pip install -r requirements.txt
streamlit run Home.py
```

The app needs `.streamlit/secrets.toml` with a `mongo_uri`. That file is not in
the repository, and on Streamlit Cloud the same key is pasted into the app's
own secrets page instead.

To refill the databases, run the notebook. It also needs `entsoe_token`, plus a
local Cassandra container, Java 17 and PySpark:

```bash
docker start cassie
```
