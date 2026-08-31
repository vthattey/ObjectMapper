"""
Auto-generated mapping code.
Source: complex_source.json
Target: complex_target.json
"""


# Helper functions — implement these for your environment
def country_name(code: str) -> str:
    _MAP = {"US": "United States", "GB": "United Kingdom", "DE": "Germany"}
    return _MAP.get(code.upper(), code)

def format_date(iso_str: str, fmt: str) -> str:
    from datetime import datetime
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return dt.strftime(fmt.replace('YYYY','%Y').replace('MM','%m').replace('DD','%d'))

def pretty_phone(e164: str) -> str:
    return e164  # implement formatting as needed



def map_source_to_target(source: dict) -> dict:
    """
    Auto-generated mapping: complex_source.json -> complex_target.json
    Mappings: 23
    """

    result = {}

    result["invoiceNumber"] = source["order_id"]
    result["issuedOn"] = format_date(source["created_at"], 'YYYY-MM-DD')
    result["customer"] = {}
    result["customer"]["fullName"] = source["customer"]["first_name"] + " " + source["customer"]["last_name"]
    result["customer"]["email"] = source["customer"]["email_lc"]
    result["customer"]["phone"] = pretty_phone(source["customer"]["phone_e164"])
    result["customer"]["tier"] = source["customer"]["loyalty_tier"].title()
    result["shipTo"] = {}
    result["shipTo"]["street"] = source["shipping_address"]["line_1"]
    result["shipTo"]["city"] = source["shipping_address"]["city"]
    result["shipTo"]["country"] = country_name(source["shipping_address"]["country_code"])
    result["shipTo"]["zip"] = source["shipping_address"]["postal_code"]
    result["summary"] = {}
    result["summary"]["subtotal"] = source["totals"]["subtotal_cents"] / 100.0
    result["summary"]["tax"] = source["totals"]["tax_cents"] / 100.0
    result["summary"]["shipping"] = source["totals"]["shipping_cents"] / 100.0
    result["summary"]["total"] = source["totals"]["grand_total_cents"] / 100.0
    result["summary"]["currency"] = source["totals"]["currency"]
    result["paymentSummary"] = {}
    result["paymentSummary"]["method"] = source["payment"]["method"]
    result["paymentSummary"]["maskedCard"] = source["payment"]["card_brand"].upper() + " ••••" + source["payment"]["card_last4"]
    result["status"] = {"PAID": "Paid", "PENDING": "Pending", "REFUNDED": "Refunded"}.get(source["status_code"], source["status_code"])
    result["lineItems"] = [
        {
            "sku": item["sku"],
            "description": item["name"],
            "quantity": item["qty"],
            "unitPrice": item["unit_price_cents"] / 100.0,
            "lineTotal": (item["unit_price_cents"] * item["qty"]) / 100.0,
        }
        for item in source["items"]
    ]

    return result


if __name__ == '__main__':
    import json, sys
    if len(sys.argv) < 2:
        print("Usage: python {sys.argv[0]} <source.json>")
        sys.exit(1)
    with open(sys.argv[1]) as f:
        source = json.load(f)
    result = map_source_to_target(source)
    print(json.dumps(result, indent=2))