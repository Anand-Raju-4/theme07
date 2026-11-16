# Databricks notebook source
# MAGIC %md
# MAGIC # nb03_silver_orders  (bronze.erp_orders → silver.orders)

# COMMAND ----------
from pyspark.sql import functions as F
silver = (spark.table("bronze.erp_orders")
          .select("order_id", "customer_id", "order_date", "status", "currency", "total_amount", "discount_amount")
          .where(F.col("status") != "Cancelled")
          .dropDuplicates(["order_id"]))
silver.write.format("delta").mode("overwrite").saveAsTable("silver.orders")
