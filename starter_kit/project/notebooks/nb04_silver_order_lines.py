# Databricks notebook source
# MAGIC %md
# MAGIC # nb04_silver_order_lines  (bronze.erp_order_lines → silver.order_lines)

# COMMAND ----------
from pyspark.sql import functions as F
silver = (spark.table("bronze.erp_order_lines")
          .select("order_id", "line_no", "product_id", "quantity", "unit_price")
          .withColumn("line_amount", F.col("quantity") * F.col("unit_price")))   # recomputed; source line_amount not used
silver.write.format("delta").mode("overwrite").saveAsTable("silver.order_lines")
