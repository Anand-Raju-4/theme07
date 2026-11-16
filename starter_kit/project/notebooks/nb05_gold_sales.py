# Databricks notebook source
# MAGIC %md
# MAGIC # nb05_gold_sales  (silver.orders + silver.order_lines + bronze.erp_products → gold.fact_sales, gold.dim_product)

# COMMAND ----------
from pyspark.sql import functions as F
o = spark.table("silver.orders")
l = spark.table("silver.order_lines")
p = spark.table("bronze.erp_products").select("product_id", "product_name", "category", "cost_price")

# allocate order-level discount to lines by share of order value
order_tot = l.groupBy("order_id").agg(F.sum("line_amount").alias("order_lines_total"))
fact = (l.join(o, "order_id").join(order_tot, "order_id").join(p, "product_id")
         .withColumn("net_amount", F.col("line_amount") - F.col("discount_amount") * F.col("line_amount") / F.col("order_lines_total"))
         .withColumn("cost_amount", F.col("quantity") * F.col("cost_price"))
         .select("order_id", "line_no", "order_date", "customer_id", "product_id", "quantity", "net_amount", "cost_amount", "status"))
fact.write.format("delta").mode("overwrite").saveAsTable("gold.fact_sales")

dim_product = spark.table("bronze.erp_products").select("product_id", "product_name", "category", "subcategory", "list_price")
dim_product.write.format("delta").mode("overwrite").saveAsTable("gold.dim_product")
