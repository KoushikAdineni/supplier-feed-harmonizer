# Supplier Feed Harmonizer - Reconciliation & Audit Report
**Generated:** 2026-10-29 19:01:26 UTC  
**Database:** `output/harmonizer.duckdb`

## 1. Row Reconciliation & Conservation Law
Verifies that every ingested row is accounted for: `rows_read = rows_valid + rows_rejected + rows_duplicate`.

| Metric | Value | Verification Formula | Status |
|---|---|---|---|
| **Rows Read** | 315 | Input file rows read | - |
| **Rows Valid** | 289 | Passed schema & business validation | - |
| **Rows Rejected** | 23 | Quarantined in rejected_records | - |
| **Rows Duplicate** | 3 | Dropped exact within-run duplicates | - |
| **Sum (Valid + Rejected + Duplicate)** | 315 | Must equal Rows Read | **PASS** |
| **Rows Published (Versions)** | 289 | Stored in fact_supplier_product_version | - |

## 2. Golden Catalog Entity Resolution Breakdown
| Metric | Count | Description |
|---|---|---|
| Total Golden Products | **52** | Unique unified products |
| Distinct GTINs | 45 | High-confidence primary keys |
| High Confidence Matches (GTIN) | 45 | Resolved via barcode matching |
| Low Confidence Matches (Fallback) | 7 | Brand / Name fallback matching |

## 3. Referential Integrity Assertions
| Integrity Assertion | Violation Count | Expected | Status |
|---|---|---|---|
| No Duplicate `product_id` in Golden | 0 | 0 | **PASS** |
| No Orphan Attribute Lineage Rows | 0 | 0 | **PASS** |
| No Unmapped `category_id` in Golden | 0 | 0 | **PASS** |

## 4. Price Distribution & Standardization Shift
Comparing raw staging prices against standardized USD version history.
| Dimension | Min Price | Avg Price | Max Price | Notes |
|---|---|---|---|---|
| **Standardized USD (Version Table)** | $0.01 | $562.04 | $99999.99 | Converted with static FX rates, excludes negative/malformed prices |
> **Explanation of Shift**: Supplier C feeds prices in EUR with comma decimals (e.g. 185,19 EUR). Standardizing multiplies EUR by 1.08 USD exchange rate. Malformed prices (e.g. negative prices and non-numeric strings) are routed to `rejected_records` and omitted from the valid price distribution.

## 5. Rejection Breakdown by Error Code
| Error Code | Count | Sample Error Reason |
|---|---|---|
| `REF_KEY_INVALID` | 16 | Category code 'INVALID-CAT-999' not found in category_map |
| `MALFORMED_RECORD` | 2 | Expected 10 columns but found 4 |
| `BAD_GTIN` | 1 | Invalid GTIN-13 checksum or format: '3482477109325' |
| `BAD_DATE` | 1 | Invalid date/time format: 'not-a-valid-date-32/13/2026' |
| `BAD_NUMERIC` | 1 | Non-numeric price value: 'INVALID_PRICE_ABC' |
| `NEGATIVE_PRICE` | 1 | Price must be strictly positive (> 0), got: -19.99 |
| `MISSING_REQUIRED` | 1 | Required field 'product_name' is empty |

## 6. Top 10 Cross-Supplier Attribute Conflicts
| Product ID | Attribute | Resolution Rule Applied | Conflicting Supplier Values |
|---|---|---|---|
| `prd_3f139eb02569acea` | `price_usd` | `latest_source_updated_at` | `{"SUP-B": 215.85, "SUP-A": 205.57}` |
| `prd_3f139eb02569acea` | `total_stock` | `latest_source_updated_at` | `{"SUP-B": 271, "SUP-A": 353}` |
| `prd_3f139eb02569acea` | `weight_kg` | `majority_vote_then_priority` | `{"SUP-A": 0.3311, "SUP-B": 0.333}` |
| `prd_fe597685e73c1918` | `price_usd` | `latest_source_updated_at` | `{"SUP-B": 78.78, "SUP-A": 75.03, "SUP-C": 75.03}` |
| `prd_fe597685e73c1918` | `total_stock` | `latest_source_updated_at` | `{"SUP-B": 176, "SUP-A": 425, "SUP-C": 59}` |
| `prd_fe597685e73c1918` | `weight_kg` | `majority_vote` | `{"SUP-A": 0.6486, "SUP-B": 0.65, "SUP-C": 0.65}` |
| `prd_fe597685e73c1918` | `name_std` | `supplier_priority` | `{"SUP-A": "UltraSound Bluetooth Portable Speaker", "SUP-B": "UltraSound Bluetooth Portable Speaker", "SUP-C": "UltraSound Bluetooth Portable Speaker Sonderedition"}` |
| `prd_0478ae9faee7c641` | `price_usd` | `latest_source_updated_at` | `{"SUP-B": 710.5, "SUP-A": 676.67, "SUP-C": 676.67}` |
| `prd_0478ae9faee7c641` | `total_stock` | `latest_source_updated_at` | `{"SUP-B": 217, "SUP-A": 321, "SUP-C": 67}` |
| `prd_0478ae9faee7c641` | `weight_kg` | `majority_vote` | `{"SUP-A": 0.1724, "SUP-B": 0.174, "SUP-C": 0.174}` |


## 7. Sample Analytical Queries & Results

### Query 1: Product Count & Average Price by Category
```sql
SELECT r.category_name, COUNT(*) AS product_count, ROUND(AVG(g.price_usd), 2) AS avg_price_usd
        FROM dim_product_golden g
        JOIN ref_category r ON g.category_id = r.category_id
        GROUP BY r.category_name
        ORDER BY product_count DESC;
```
| Category | Product Count | Avg Price (USD) |
|---|---|---|
| Audio Equipment | 14 | $146.41 |
| Electronics | 8 | $12698.09 |
| Phones & Accessories | 6 | $721.67 |
| Home & Kitchen | 6 | $95.00 |
| Sports & Outdoors | 6 | $134.43 |
| Home Appliances | 6 | $47.38 |
| Office Supplies | 6 | $191.14 |


### Query 2: Multi-Supplier Overlap Products (Top 5)
```sql
SELECT g.product_id, g.name_std, g.source_count, g.price_usd
        FROM dim_product_golden g
        WHERE g.source_count > 1
        ORDER BY g.source_count DESC, g.product_id
        LIMIT 5;
```
| Product ID | Name | Supplier Count | Golden Price (USD) |
|---|---|---|---|
| `prd_02c3403f1921fb17` | PixelGear 4K Ultra HD Action Camera Model-12 | 3 | $264.56 |
| `prd_0478ae9faee7c641` | SmartLife Pro Smartphone 128GB | 3 | $710.50 |
| `prd_0e0d33e500ab5e92` | PeakTrek Lightweight Camping Tent 2-Person Model-40 | 3 | $142.45 |
| `prd_0f88e32929db4114` | PixelGear 4K Ultra HD Action Camera Model-36 | 3 | $252.72 |
| `prd_0f93f051731e9f72` | UltraSound Bluetooth Portable Speaker Model-18 | 3 | $81.99 |


### Query 3: Cross-Supplier Price Spread on Shared Barcodes
```sql
SELECT
            v.gtin,
            MIN(v.name_std) AS product_name,
            ROUND(MIN(v.price_usd), 2) AS min_price,
            ROUND(MAX(v.price_usd), 2) AS max_price,
            ROUND(MAX(v.price_usd) - MIN(v.price_usd), 2) AS price_spread
        FROM fact_supplier_product_version v
        WHERE v.gtin IS NOT NULL
        GROUP BY v.gtin
        HAVING COUNT(DISTINCT v.supplier_id) > 1
        ORDER BY price_spread DESC
        LIMIT 5;
```
| GTIN | Product Name | Min Price (USD) | Max Price (USD) | Spread |
|---|---|---|---|---|
| `4332181960016` | UltraSound Bluetooth Portable Speaker | $75.03 | $999.00 | $923.97 |
| `0838637940266` | SmartLife Pro Smartphone 128GB | $676.67 | $999.00 | $322.33 |
| `8498084124118` | SmartLife Pro Smartphone 128GB Model-27 | $732.89 | $769.53 | $36.64 |
| `8895798687272` | SmartLife Pro Smartphone 128GB Model-43 | $692.02 | $726.62 | $34.60 |
| `0106513338729` | SmartLife Pro Smartphone 128GB Model-19 | $688.08 | $722.48 | $34.40 |


### Query 4: Total Inventory Stock by Country of Origin
```sql
SELECT c.country_name, SUM(g.total_stock) AS total_stock_units, COUNT(*) AS product_count
        FROM dim_product_golden g
        JOIN ref_country c ON g.country_code = c.country_code
        GROUP BY c.country_name
        ORDER BY total_stock_units DESC;
```
| Country | Total Stock Units | Product Count |
|---|---|---|
| Germany | 2,423 | 13 |
| United States | 2,132 | 15 |
| Canada | 1,038 | 6 |
| Japan | 1,006 | 6 |
| France | 957 | 6 |
| China | 854 | 6 |


### Query 5: Full Attribute Lineage Traceability (`prd_3f139eb02569acea`)
```sql
SELECT attribute_name, chosen_value, chosen_supplier_id, rule_applied, chosen_source_file, chosen_source_row_number
            FROM product_attribute_lineage
            WHERE product_id = 'prd_3f139eb02569acea'
            ORDER BY attribute_name;
```
| Attribute | Chosen Value | Winning Supplier | Applied Rule | Source File:Row |
|---|---|---|---|---|
| `category_id` | CAT_AUDIO | `SUP-A` | `supplier_priority` | supplier_a_feed.csv:52 |
| `color_id` | CLR_BLACK | `SUP-A` | `supplier_priority` | supplier_a_feed.csv:52 |
| `country_code` | US | `SUP-A` | `supplier_priority` | supplier_a_feed.csv:52 |
| `name_std` | TechCorp Wireless Noise Cancelling Headphones | `SUP-A` | `supplier_priority` | supplier_a_feed.csv:52 |
| `price_usd` | 215.85 | `SUP-B` | `latest_source_updated_at` | supplier_b_feed.jsonl:51 |
| `total_stock` | 271 | `SUP-B` | `latest_source_updated_at` | supplier_b_feed.jsonl:51 |
| `weight_kg` | 0.3311 | `SUP-A` | `majority_vote_then_priority` | supplier_a_feed.csv:52 |


