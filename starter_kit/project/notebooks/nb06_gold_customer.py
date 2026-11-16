# Databricks notebook source
# MAGIC %md
# MAGIC # nb06_gold_customer  (silver.customers → gold.dim_customer)

# COMMAND ----------
from pyspark.sql import functions as F
regions = spark.createDataFrame([("N", "North"), ("S", "South"), ("E", "East"), ("W", "West")], ["region_code", "region_name"])
dim = (spark.table("silver.customers")
         .join(regions, "region_code", "left")
         .select("customer_id", "full_name", "segment", "region_name", "is_active"))
dim.write.format("delta").mode("overwrite").saveAsTable("gold.dim_customer")
