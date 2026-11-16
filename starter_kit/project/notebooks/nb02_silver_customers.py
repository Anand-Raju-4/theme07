# Databricks notebook source
# MAGIC %md
# MAGIC # nb02_silver_customers  (bronze.crm_customers → silver.customers)

# COMMAND ----------
from pyspark.sql import functions as F
src = spark.table("bronze.crm_customers")
silver = (src.select("customer_id", "first_name", "last_name", "email", "segment", "region_code", "is_active", "created_at")
             .withColumn("full_name", F.concat_ws(" ", "first_name", "last_name"))
             .withColumn("email", F.lower("email"))
             .dropDuplicates(["customer_id"]))
silver.write.format("delta").mode("overwrite").saveAsTable("silver.customers")
