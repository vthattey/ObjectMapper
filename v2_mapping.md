# JSON Attribute Mapping Specification

This document describes how to transform a **source** JSON object into a **target** JSON object.

- **Source:** `complex_source.json`
- **Target:** `complex_target.json`
- **Mappings:** 23

## Path notation

- `$` — root.  `.field` — property.  `[*]` — every array element.

## Mapping table

| # | Source | Type | Target | Type | Functoids | Kind |
|---|--------|------|--------|------|-----------|------|
| 1 | `$.order_id` | string | `$.invoiceNumber` | string | — | direct |
| 2 | `$.created_at` | string | `$.issuedOn` | string | Conversion 1 | transform |
| 3 | `$.customer.first_name`, `$.customer.last_name` | string, string | `$.customer.fullName` | string | String | transform |
| 4 | `$.customer.email_lc` | string | `$.customer.email` | string | — | direct |
| 5 | `$.customer.phone_e164` | string | `$.customer.phone` | string | Conversion | transform |
| 6 | `$.customer.loyalty_tier` | string | `$.customer.tier` | string | String 1 | transform |
| 7 | `$.shipping_address.line_1` | string | `$.shipTo.street` | string | — | direct |
| 8 | `$.shipping_address.city` | string | `$.shipTo.city` | string | — | direct |
| 9 | `$.shipping_address.country_code` | string | `$.shipTo.country` | string | Conversion 2 | transform |
| 10 | `$.shipping_address.postal_code` | string | `$.shipTo.zip` | string | — | direct |
| 11 | `$.items[*].sku` | string | `$.lineItems[*].sku` | string | — | direct |
| 12 | `$.items[*].name` | string | `$.lineItems[*].description` | string | — | direct |
| 13 | `$.items[*].qty` | integer | `$.lineItems[*].quantity` | integer | — | direct |
| 14 | `$.items[*].unit_price_cents` | integer | `$.lineItems[*].unitPrice` | number | Math 4 | transform |
| 15 | `$.items[*].unit_price_cents`, `$.items[*].qty` | integer, integer | `$.lineItems[*].lineTotal` | number | Math 5 | transform |
| 16 | `$.totals.subtotal_cents` | integer | `$.summary.subtotal` | number | Math | transform |
| 17 | `$.totals.tax_cents` | integer | `$.summary.tax` | number | Math 1 | transform |
| 18 | `$.totals.shipping_cents` | integer | `$.summary.shipping` | number | Math 2 | transform |
| 19 | `$.totals.grand_total_cents` | integer | `$.summary.total` | number | Math 3 | transform |
| 20 | `$.totals.currency` | string | `$.summary.currency` | string | — | direct |
| 21 | `$.payment.method` | string | `$.paymentSummary.method` | string | — | direct |
| 22 | `$.payment.card_brand`, `$.payment.card_last4` | string, string | `$.paymentSummary.maskedCard` | string | Custom | transform |
| 23 | `$.status_code` | string | `$.status` | string | Logic | transform |

## Mapping details

### 1. `$.order_id` → `$.invoiceNumber`

- **Transformation:** direct copy.

### 2. `$.created_at` → `$.issuedOn`

- **Functoid:** Conversion 1 (ISO date reformat)

```text
format_date(input_a, 'YYYY-MM-DD')
```

### 3. `$.customer.first_name` + `$.customer.last_name` → `$.customer.fullName`

- **Functoid:** String (Concatenate)

```text
input_a + " " + input_b
```

### 4. `$.customer.email_lc` → `$.customer.email`

- **Transformation:** direct copy.

### 5. `$.customer.phone_e164` → `$.customer.phone`

- **Functoid:** Conversion (Phone format)

```text
pretty_phone(input_a)
```

### 6. `$.customer.loyalty_tier` → `$.customer.tier`

- **Functoid:** String 1 (Uppercase)

```text
input_a.title()
```

### 7. `$.shipping_address.line_1` → `$.shipTo.street`

- **Transformation:** direct copy.

### 8. `$.shipping_address.city` → `$.shipTo.city`

- **Transformation:** direct copy.

### 9. `$.shipping_address.country_code` → `$.shipTo.country`

- **Functoid:** Conversion 2 (Country code to name)

```text
country_name(input_a)
```

### 10. `$.shipping_address.postal_code` → `$.shipTo.zip`

- **Transformation:** direct copy.

### 11. `$.items[*].sku` → `$.lineItems[*].sku`

- **Transformation:** direct copy.

### 12. `$.items[*].name` → `$.lineItems[*].description`

- **Transformation:** direct copy.

### 13. `$.items[*].qty` → `$.lineItems[*].quantity`

- **Transformation:** direct copy.

### 14. `$.items[*].unit_price_cents` → `$.lineItems[*].unitPrice`

- **Functoid:** Math 4 (Divide by 100)

```text
input_a / 100.0
```

### 15. `$.items[*].unit_price_cents` + `$.items[*].qty` → `$.lineItems[*].lineTotal`

- **Functoid:** Math 5 (Multiply)

```text
(input_a * input_b) / 100.0
```

### 16. `$.totals.subtotal_cents` → `$.summary.subtotal`

- **Functoid:** Math (Divide by 100)

```text
input_a / 100.0
```

### 17. `$.totals.tax_cents` → `$.summary.tax`

- **Functoid:** Math 1 (Divide by 100)

```text
input_a / 100.0
```

### 18. `$.totals.shipping_cents` → `$.summary.shipping`

- **Functoid:** Math 2 (Divide by 100)

```text
input_a / 100.0
```

### 19. `$.totals.grand_total_cents` → `$.summary.total`

- **Functoid:** Math 3 (Divide by 100)

```text
input_a / 100.0
```

### 20. `$.totals.currency` → `$.summary.currency`

- **Transformation:** direct copy.

### 21. `$.payment.method` → `$.paymentSummary.method`

- **Transformation:** direct copy.

### 22. `$.payment.card_brand` + `$.payment.card_last4` → `$.paymentSummary.maskedCard`

- **Functoid:** Custom

```text
input_a.upper() + " ••••" + input_b
```

### 23. `$.status_code` → `$.status`

- **Functoid:** Logic (Lookup map)

```text
{"PAID": "Paid", "PENDING": "Pending", "REFUNDED": "Refunded"}.get(input_a, input_a)
```

## Agent instructions

1. Read source JSON, produce target JSON satisfying every mapping.
2. Direct-copy rows: assign unchanged.
3. Functoid rows: implement the expression faithfully.
4. `[*]` paths: iterate and produce corresponding arrays.
5. Preserve types unless the expression says to coerce.
