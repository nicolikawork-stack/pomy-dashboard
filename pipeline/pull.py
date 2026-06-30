#!/usr/bin/env python3
"""POMY profit dashboard pipeline — CLOUD version (GitHub Actions).
Same logic as Business Manager/scripts/profit_dashboard_pull.py, but reads credentials
from environment variables (GitHub Secrets) and writes profit_data.js to the repo root.
Stateless: pulls a long rolling window each run (no committed history). KEEP IN SYNC with the local script."""
import os, json, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_JS = os.path.join(ROOT, "profit_data.js")
COGS_PATH = os.path.join(HERE, "cogs_rules.json")
TZ = ZoneInfo("Asia/Jerusalem")
SHOP_API = "2025-07"
GADS_API = "v21"
DAYS_BACK = int(os.environ.get("DAYS_BACK", "180"))

env = os.environ   # credentials come from GitHub Secrets

FEE_PAYPAL, FEE_MANUAL, FEE_DEFAULT = 0.02, 0.0, 0.0119
def fee_rate(names):
    n = [x.lower() for x in (names or [])]
    if any("paypal" in x for x in n):
        return FEE_PAYPAL
    if n and all(x == "manual" for x in n):
        return FEE_MANUAL
    return FEE_DEFAULT

COGS_RULES = json.load(open(COGS_PATH, encoding="utf-8"))

def cogs_classify(name):
    n = (name or "").lower()
    for key, p in COGS_RULES["products"].items():
        if any(m.lower() in n for m in p["match"]):
            return key
    return None

def cogs_method(node):
    t = ((node.get("shippingLine") or {}).get("title") or "").lower()
    if any(x in t for x in ("pick", "איסוף", "עצמי")):
        return "self"
    if any(x in t for x in ("d2d", "door", "בית", "דלת", "שליח")):
        return "d2d"
    return COGS_RULES.get("default_method", "d2d")

def cogs_full_ils(method, prod_units):
    rate = COGS_RULES["rate"]; total = 0.0
    for key, qty in prod_units.items():
        p = COGS_RULES["products"][key]; qty = int(qty)
        if "full_ils" in p:
            tiers = p["full_ils"].get(method) or p["full_ils"].get("d2d")
            t = str(min(qty, max(int(k) for k in tiers)))
            total += tiers[t]
        elif "full_usd" in p:
            tiers = p["full_usd"].get(method) or p["full_usd"].get("d2d")
            t = str(min(qty, max(int(k) for k in tiers)))
            total += tiers[t] * rate
        elif "shipping_usd" in p:
            sh = p["shipping_usd"].get(method) or p["shipping_usd"]["d2d"]
            t = str(min(qty, max(int(k) for k in sh)))
            total += (p["product_per_unit_usd"] * qty + sh[t]) * rate
        elif "ship_ils_flat" in p:
            total += p["product_per_unit_usd"] * qty * rate + p["ship_ils_flat"]
    return round(total, 2)

def platform_of(node):
    cj = (node.get("customerJourneySummary") or {}).get("lastVisit") or {}
    u = ((cj.get("utmParameters") or {}).get("source") or "").lower()
    s = (cj.get("source") or "").lower()
    if any(x in u for x in ("facebook", "fb", "instagram", "meta")) or "facebook" in s or "instagram" in s:
        return "facebook"
    if u == "google" or (not u and "google" in s and "android-app" not in s and ".gm" not in s):
        return "google"
    return "other"

today = datetime.now(TZ).date()
since = today - timedelta(days=DAYS_BACK)
SINCE, UNTIL = since.isoformat(), today.isoformat()

def http(url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {},
                                 method=method or ("POST" if data else "GET"))
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)

def shopify_daily():
    store = env.get("SHOPIFY_STORE", "pomy-sport.myshopify.com")
    token = env["SHOPIFY_ADMIN_TOKEN"]
    url = f"https://{store}/admin/api/{SHOP_API}/graphql.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    q = """
    query($cursor:String,$q:String){
      orders(first:60, after:$cursor, query:$q, sortKey:CREATED_AT){
        pageInfo{hasNextPage endCursor}
        edges{node{
          name
          createdAt
          paymentGatewayNames
          currentTotalPriceSet{shopMoney{amount}}
          currentSubtotalPriceSet{shopMoney{amount}}
          totalDiscountsSet{shopMoney{amount}}
          customerJourneySummary{ lastVisit{ source utmParameters{ source } } }
          shippingLine{ title }
          lineItems(first:50){edges{node{quantity name
            discountedTotalSet{shopMoney{amount}}
            product{title}
            variant{inventoryItem{unitCost{amount}}}}}}
        }}
      }
    }"""
    qstr = f"created_at:>={SINCE} created_at:<={UNTIL} test:false"
    days = {}; prod = {}; plat = {}; order_rows = []; cursor = None
    while True:
        body = json.dumps({"query": q, "variables": {"cursor": cursor, "q": qstr}}).encode()
        for attempt in range(6):
            res = http(url, data=body, headers=headers)
            if "errors" in res:
                msg = json.dumps(res["errors"])
                if "THROTTLED" in msg.upper():
                    time.sleep(2 + attempt); continue
                raise RuntimeError("Shopify GraphQL: " + msg[:300])
            break
        conn = res["data"]["orders"]
        for e in conn["edges"]:
            n = e["node"]
            d = datetime.fromisoformat(n["createdAt"]).astimezone(TZ).date().isoformat()
            total = float(n["currentTotalPriceSet"]["shopMoney"]["amount"])
            net = float(n["currentSubtotalPriceSet"]["shopMoney"]["amount"])
            disc = float(n["totalDiscountsSet"]["shopMoney"]["amount"])
            fees = total * fee_rate(n.get("paymentGatewayNames"))
            gross_o = net + disc
            net_ratio = (net / gross_o) if gross_o else 1.0
            cogs = 0.0; seen_products = set(); prod_units = {}
            for li in (n.get("lineItems", {}).get("edges") or []):
                ln = li["node"]; qty = ln.get("quantity", 0) or 0
                uc = ((ln.get("variant") or {}).get("inventoryItem") or {}).get("unitCost") or {}
                line_cost = qty * float(uc["amount"]) if uc.get("amount") else 0.0
                cogs += line_cost
                title = ((ln.get("product") or {}).get("title")) or "(לא ידוע)"
                ckey = cogs_classify(title) or cogs_classify(ln.get("name"))
                if ckey:
                    prod_units[ckey] = prod_units.get(ckey, 0) + qty
                dts = ((ln.get("discountedTotalSet") or {}).get("shopMoney") or {}).get("amount")
                line_sales = float(dts) if dts else 0.0
                p = prod.setdefault((d, title), {"units": 0, "sales": 0.0, "cogs": 0.0, "orders": 0})
                p["units"] += qty; p["sales"] += line_sales * net_ratio; p["cogs"] += line_cost
                if title not in seen_products:
                    p["orders"] += 1; seen_products.add(title)
            method = cogs_method(n)
            order_cogs = cogs_full_ils(method, prod_units) if prod_units else round(cogs, 2)
            b = days.setdefault(d, {"orders": 0, "gross_sales": 0.0, "discounts": 0.0,
                                    "net_sales": 0.0, "total_sales": 0.0, "cogs": 0.0, "fees": 0.0})
            b["orders"] += 1; b["net_sales"] += net; b["total_sales"] += total
            b["discounts"] += disc; b["gross_sales"] += net + disc
            b["cogs"] += order_cogs; b["fees"] += fees
            pf = platform_of(n)
            pb = plat.setdefault((d, pf), {"sales": 0.0, "orders": 0})
            pb["sales"] += total; pb["orders"] += 1
            order_rows.append({"date": d, "name": n.get("name", ""), "platform": pf,
                               "total": round(total, 2), "net": round(net, 2), "cogs": order_cogs,
                               "fees": round(fees, 2), "method": method,
                               "profit": round(net - order_cogs - fees, 2)})
        ts = ((res.get("extensions") or {}).get("cost") or {}).get("throttleStatus") or {}
        avail, restore = ts.get("currentlyAvailable"), ts.get("restoreRate") or 50
        if avail is not None and avail < 300:
            time.sleep(min(5, (300 - avail) / restore + 0.3))
        if conn["pageInfo"]["hasNextPage"]:
            cursor = conn["pageInfo"]["endCursor"]
        else:
            break
    for d in days:
        for k in days[d]:
            if k != "orders":
                days[d][k] = round(days[d][k], 2)
    product_days = [{"date": d, "title": t, "units": v["units"], "orders": v.get("orders", 0),
                     "sales": round(v["sales"], 2), "cogs": round(v["cogs"], 2)} for (d, t), v in prod.items()]
    platform_days = [{"date": d, "platform": pf, "sales": round(v["sales"], 2), "orders": v["orders"]}
                     for (d, pf), v in plat.items()]
    return days, product_days, platform_days, order_rows

def _meta_purchase_value(row):
    vals = {a.get("action_type"): a.get("value") for a in (row.get("action_values") or [])}
    for k in ("omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase"):
        if vals.get(k):
            return round(float(vals[k]), 2)
    return 0.0

def meta_daily():
    tok = env["Meta_Access_Token"]; acct = env["Ad_Account_Id"]
    tr = json.dumps({"since": SINCE, "until": UNTIL})
    url = f"https://graph.facebook.com/v21.0/act_{acct}/insights?" + urllib.parse.urlencode({
        "access_token": tok, "fields": "spend,action_values", "level": "account",
        "time_increment": "1", "time_range": tr})
    out = {}; res = http(url)
    def take(r):
        for row in r.get("data", []):
            out[row["date_start"]] = {"spend": round(float(row.get("spend", 0)), 2), "rev": _meta_purchase_value(row)}
    take(res)
    while "paging" in res and "next" in res["paging"]:
        res = http(res["paging"]["next"]); take(res)
    return out

def google_daily():
    data = urllib.parse.urlencode({
        "client_id": env["GOOGLE_ADS_CLIENT_ID"], "client_secret": env["GOOGLE_ADS_CLIENT_SECRET"],
        "refresh_token": env["GOOGLE_ADS_REFRESH_TOKEN"], "grant_type": "refresh_token"}).encode()
    at = http("https://oauth2.googleapis.com/token", data=data)["access_token"]
    cid = env["GOOGLE_ADS_CUSTOMER_ID"]
    url = f"https://googleads.googleapis.com/{GADS_API}/customers/{cid}/googleAds:searchStream"
    headers = {"Authorization": f"Bearer {at}", "developer-token": env["GOOGLE_ADS_DEVELOPER_TOKEN"],
               "Content-Type": "application/json"}
    q = (f"SELECT segments.date, metrics.cost_micros, metrics.conversions_value FROM campaign "
         f"WHERE segments.date BETWEEN '{SINCE}' AND '{UNTIL}'")
    res = http(url, data=json.dumps({"query": q}).encode(), headers=headers)
    out = {}
    for chunk in res:
        for row in chunk.get("results", []):
            d = row["segments"]["date"]; mt = row["metrics"]
            o = out.setdefault(d, {"spend": 0.0, "rev": 0.0})
            o["spend"] += int(mt.get("costMicros", 0)) / 1_000_000
            o["rev"] += float(mt.get("conversionsValue", 0) or 0)
    return {k: {"spend": round(v["spend"], 2), "rev": round(v["rev"], 2)} for k, v in out.items()}

def main():
    print(f"Pulling {SINCE} .. {UNTIL}")
    shop, products, platforms, orders = shopify_daily()
    print(f"  Shopify days: {len(shop)}  products: {len(products)}  platforms: {len(platforms)}  orders: {len(orders)}")
    meta = meta_daily(); print(f"  Meta days: {len(meta)}")
    goog = google_daily(); print(f"  Google days: {len(goog)}")
    existing = {}
    for d in sorted(set(shop) | set(meta) | set(goog)):
        rec = {"date": d}
        s = shop.get(d)
        if s:
            rec.update(s)
        else:
            for k, dv in (("orders", 0), ("gross_sales", 0.0), ("discounts", 0.0), ("net_sales", 0.0),
                          ("total_sales", 0.0), ("cogs", 0.0), ("fees", 0.0)):
                rec.setdefault(k, dv)
        md = meta.get(d); gd = goog.get(d)
        rec["meta_spend"] = md["spend"] if md else 0.0
        rec["google_spend"] = gd["spend"] if gd else 0.0
        rec["meta_reported"] = md["rev"] if md else 0.0
        rec["google_reported"] = gd["rev"] if gd else 0.0
        existing[d] = rec
    days = [existing[d] for d in sorted(existing)]
    payload = {"updated": today.isoformat(), "currency": "ILS", "days": days,
               "product_days": sorted(products, key=lambda p: (p["date"], p["title"])),
               "platform_days": sorted(platforms, key=lambda p: (p["date"], p["platform"])),
               "orders": sorted(orders, key=lambda o: o["date"])}
    header = ("// Auto-generated (cloud) by pipeline/pull.py — do not edit by hand.\n"
              "window.PROFIT_DATA = ")
    with open(DATA_JS, "w", encoding="utf-8") as f:
        f.write(header); json.dump(payload, f, ensure_ascii=False, indent=2); f.write(";\n")
    print(f"Wrote {len(days)} days -> {DATA_JS}")

if __name__ == "__main__":
    main()
