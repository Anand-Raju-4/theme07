# Databricks notebook source
# MAGIC %md
# MAGIC # nb01_bronze_ingest
# MAGIC Generic, config-driven ingestion into bronze. One run per entry in config/ingest_config.json.

# COMMAND ----------
import json
from pyspark.sql import functions as F
from pyspark.sql.types import StructType

source_name = dbutils.widgets.get("source")
cfg = next(s for s in json.load(open("/Workspace/Repos/data-platform/config/ingest_config.json"))["sources"] if s["source"] == source_name)

if cfg["reader"] == "json":
    # Explicit schema: fields not in the schema are ignored; schema fields missing in the file become NULL (PERMISSIVE mode)
    schema = StructType.fromJson(json.load(open("/Workspace/Repos/data-platform/" + cfg["schema_file"])))
    df = spark.read.schema(schema).option("mode", cfg["mode"]).json(cfg["path"])
else:
    df = (spark.read.format("jdbc").option("url", dbutils.secrets.get("kv-contoso", "erp-jdbc-url"))
          .option("query", cfg["query"].replace("?", "'" + dbutils.widgets.get("watermark") + "'")).load())

df = df.withColumn("_ingested_at", F.current_timestamp())
writer = df.write.format("delta").mode(cfg["write_mode"])
if cfg.get("overwrite_schema"):
    writer = writer.option("overwriteSchema", "true")
writer.saveAsTable(cfg["target"])
