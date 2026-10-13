"""Cassandra, Spark and MongoDB - the storage half of the pipeline.

The route the data take in this project:

    ENTSO-E API  ->  Cassandra (local, raw 15-minute values)
                 ->  Spark     (pick columns, average to hourly)
                 ->  MongoDB   (small and curated, read by the Streamlit app)

Cassandra and Spark run on this machine, so the notebook can use them. The
deployed app cannot - Streamlit Cloud has no Docker container of mine running -
which is exactly why the finished data end up in MongoDB.
"""

import os
import pathlib
import tomllib

import pandas as pd

KEYSPACE = "ind320"
FLOW_TABLE = "crossborder_flows"

SECRETS_FILE = pathlib.Path(__file__).resolve().parents[1] / ".streamlit" / "secrets.toml"

# Pinned on purpose: the connector has to match the Spark version, and 3.5.1
# is what is installed here. A mismatch fails at run time, not at import.
CASSANDRA_CONNECTOR = "com.datastax.spark:spark-cassandra-connector_2.12:3.5.1"


def secrets() -> dict:
    """Read .streamlit/secrets.toml when running outside Streamlit.

    Inside the app st.secrets does this already. The notebook has no Streamlit
    runtime, so it reads the same file directly and nothing has to be typed
    twice. The file is in .gitignore, and on Streamlit Cloud the same keys are
    pasted into the app's own secrets page instead.
    """
    return tomllib.loads(SECRETS_FILE.read_text())


# --- Cassandra -------------------------------------------------------------

def cassandra_session():
    """Connect to the local Cassandra container and make sure the keyspace exists."""
    from cassandra.cluster import Cluster

    session = Cluster(["localhost"], port=9042).connect()
    session.execute(
        f"CREATE KEYSPACE IF NOT EXISTS {KEYSPACE} WITH replication = "
        "{'class': 'SimpleStrategy', 'replication_factor': 1}"
    )
    session.set_keyspace(KEYSPACE)
    return session


def create_flow_table(session, reset: bool = False) -> None:
    """Create the table the flow data go into.

    The partition key is (country, direction) and the rows inside a partition
    are ordered by time. That matches how the data are read later - always one
    cable and one direction over a period - and keeps the six partitions a
    sensible size.

    Every column name is lowercase. Cassandra folds unquoted names to lowercase
    while Spark is case sensitive, and mixing the two is a well-known way to
    get a column-not-found error that makes no sense when you read it.
    """
    if reset:
        session.execute(f"DROP TABLE IF EXISTS {FLOW_TABLE}")
    session.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {FLOW_TABLE} (
            country   text,
            direction text,
            ts        timestamp,
            mw        double,
            PRIMARY KEY ((country, direction), ts)
        )
        """
    )


# --- Spark -----------------------------------------------------------------

def spark_session(app_name: str = "ind320-part2"):
    """Build a local SparkSession wired up to Cassandra.

    spark.jars.packages downloads the connector from Maven the first time it
    runs, so the first call takes a while and needs a network connection.
    """
    import sys

    from pyspark.sql import SparkSession

    # PySpark starts a JVM, so it has to be told which Java to use.
    os.environ.setdefault(
        "JAVA_HOME",
        "/Users/moa/Library/Java/JavaVirtualMachines/jdk-17.0.20.1+1/Contents/Home",
    )

    # Spark launches its Python workers by running whatever "python3" is first
    # on PATH, which here is the system 3.9 while this notebook runs on 3.12.
    # Spark refuses to run with mismatched minor versions, so both ends are
    # pointed at the interpreter that is actually running.
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)

    return (
        SparkSession.builder.appName(app_name)
        .master("local[2]")
        .config("spark.jars.packages", CASSANDRA_CONNECTOR)
        .config("spark.sql.extensions", "com.datastax.spark.connector.CassandraSparkExtensions")
        .config("spark.cassandra.connection.host", "localhost")
        .config("spark.cassandra.connection.port", "9042")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )


# The schema is spelled out rather than inferred. Two reasons: the course book
# warns that PySpark is picky about data formats when writing to Cassandra, and
# handing Spark a pandas DataFrame goes through pyspark.sql.pandas, which still
# imports distutils - removed from the standard library in Python 3.12. Building
# the rows directly sidesteps that entirely.
FLOW_SCHEMA = "country string, direction string, ts timestamp, mw double"


def write_flows(spark, flows: pd.DataFrame) -> int:
    """Push the downloaded flows into Cassandra using Spark.

    The task asks for the insert to go through Spark rather than the plain
    driver, so the rows become a Spark DataFrame first and are written in
    append mode.

    Cassandra overwrites a row when the primary key already exists, so running
    this twice is harmless - no duplicates, just the same values written again.
    """
    frame = flows.rename(columns={"timestamp": "ts"})

    # The timestamps are handed over as timezone-aware UTC, not naive. A naive
    # datetime is converted using the driver's local time zone, and in Oslo the
    # hour 02:00-03:00 happens twice on the night the clocks go back. Two
    # different UTC instants then land on the same value, and since ts is part
    # of the primary key the second one silently overwrites the first - 42 rows
    # went missing this way before the tz_localize was added.
    rows = list(
        zip(
            frame["country"].astype(str),
            frame["direction"].astype(str),
            frame["ts"].dt.tz_localize("UTC").dt.to_pydatetime(),
            frame["mw"].astype(float),
        )
    )

    (
        spark.createDataFrame(rows, schema=FLOW_SCHEMA)
        .write.format("org.apache.spark.sql.cassandra")
        .options(table=FLOW_TABLE, keyspace=KEYSPACE)
        .mode("append")
        .save()
    )
    return len(rows)


def read_flows(spark):
    """Read the flow table back out of Cassandra as a Spark DataFrame.

    Only the four columns that matter are selected. The point of doing this in
    Spark is that the filtering and aggregating happen on the cluster side, and
    only the small result is pulled back with toPandas().
    """
    return (
        spark.read.format("org.apache.spark.sql.cassandra")
        .options(table=FLOW_TABLE, keyspace=KEYSPACE)
        .load()
        .select("country", "direction", "ts", "mw")
    )


def hourly_from_spark(spark) -> pd.DataFrame:
    """Average the 15-minute values to hourly, in Spark, and bring the result home.

    date_trunc cuts every timestamp back to the start of its hour, so grouping
    on it gives one row per cable, direction and hour. That is a quarter of the
    rows, which is what makes the result small enough to keep in MongoDB.
    """
    from pyspark.sql import functions as F

    hourly = (
        read_flows(spark)
        .withColumn("hour", F.date_trunc("hour", F.col("ts")))
        .groupBy("country", "direction", "hour")
        .agg(F.avg("mw").alias("mw"))
        .orderBy("country", "direction", "hour")
    )

    # collect() instead of toPandas() for the same reason the schema above is
    # written out by hand: toPandas() goes through pyspark.sql.pandas and that
    # module needs distutils. The result is small - about 105 000 rows - so
    # pulling it as plain Row objects costs nothing.
    frame = pd.DataFrame(
        [row.asDict() for row in hourly.collect()]
    ).rename(columns={"hour": "timestamp"})

    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame["year"] = frame["timestamp"].dt.year
    frame["month"] = frame["timestamp"].dt.month
    return frame


# --- MongoDB ---------------------------------------------------------------

MONGO_DB = "ind320"
MONGO_COLLECTION = "crossborder_hourly"


def mongo_collection(uri: str | None = None):
    """Open the collection the app reads from."""
    from pymongo import MongoClient

    uri = uri or secrets()["mongo_uri"]
    return MongoClient(uri, serverSelectionTimeoutMS=20000)[MONGO_DB][MONGO_COLLECTION]


def write_hourly_to_mongo(hourly: pd.DataFrame, uri: str | None = None) -> int:
    """Replace the contents of the MongoDB collection with the hourly data.

    The collection is emptied first so that re-running the notebook does not
    stack several copies of the same hours on top of each other - the free tier
    only has 512 MB, and the app would double-count everything.

    An index on (year, country, direction) keeps the app's queries quick; it
    only ever asks for one year at a time.
    """
    collection = mongo_collection(uri)
    collection.delete_many({})

    records = hourly.to_dict("records")
    # insert_many in batches: one call with 100 000 documents is a good way to
    # hit the request size limit.
    for start in range(0, len(records), 10_000):
        collection.insert_many(records[start : start + 10_000])

    collection.create_index([("year", 1), ("country", 1), ("direction", 1)])
    return collection.count_documents({})
