import streamlit as st
import pandas as pd
import sqlite3
from pathlib import Path
from datetime import date, datetime, timedelta
from io import BytesIO
from fpdf import FPDF
import json

# ---------------------------
# Config & DB setup
# ---------------------------
st.set_page_config(page_title="Farm Manager", layout="wide")
DB_PATH = Path("farm.db")

# Connect to SQLite
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# ---------------------------
# Tables creation (enhanced)
# ---------------------------
c.execute("""
CREATE TABLE IF NOT EXISTS sites (
    site_id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name TEXT,
    site_type TEXT DEFAULT 'farm',  -- 'farm' or 'market'
    address TEXT,
    phone TEXT,
    notes TEXT
)
""")
c.execute("""
CREATE TABLE IF NOT EXISTS crops (
    crop_id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER,
    item_name TEXT,
    date_planted TEXT,
    expected_harvest_date TEXT,
    actual_harvest_date TEXT,
    yield_qty REAL,
    unit TEXT,
    price_per_unit REAL,
    available_qty REAL,
    notes TEXT,
    FOREIGN KEY(site_id) REFERENCES sites(site_id)
)
""")
c.execute("""
CREATE TABLE IF NOT EXISTS sales (
    sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    site_id INTEGER,
    items_json TEXT,
    subtotal REAL,
    tax REAL,
    total REAL,
    payment_type TEXT,
    cash_given REAL DEFAULT 0,
    change_due REAL DEFAULT 0,
    notes TEXT,
    FOREIGN KEY(site_id) REFERENCES sites(site_id)
)
""")
conn.commit()

# ---------------------------
# Authentication
# ---------------------------
def check_password():
    pw_secret = None
    try:
        pw_secret = st.secrets["FARM"]["FARM_PASSWORD"]
    except Exception:
        pw_secret = None
    expected = pw_secret if pw_secret else "admin123"

    if "auth_ok" not in st.session_state:
        st.session_state.auth_ok = False

    if not st.session_state.auth_ok:
        st.markdown("<h3 style='text-align:center;'>🔒 Enter Password to Access Farm Manager</h3>", unsafe_allow_html=True)
        pw = st.text_input("Password", type="password")
        if st.button("Enter"):
            if pw == expected:
                st.session_state.auth_ok = True
            else:
                st.error("Incorrect password")
        st.stop()

check_password()

# ---------------------------
# UI polish
# ---------------------------
st.markdown("""
<style>
h1 {text-align:center;}
.sidebar .block-container {padding-top:1rem;}
</style>
""", unsafe_allow_html=True)

st.title("🚜 Farm Manager (Enhanced)")

# ---------------------------
# Sidebar
# ---------------------------
st.sidebar.header("Quick Actions")
st.sidebar.button("Add Site", on_click=lambda: st.session_state.update({"show_add_site": True}))
st.sidebar.button("Add Crop/Item", on_click=lambda: st.session_state.update({"show_add_crop": True}))
st.sidebar.button("Open POS", on_click=lambda: st.session_state.update({"show_pos": True}))
st.sidebar.button("Export All CSVs", on_click=lambda: st.session_state.update({"export_all": True}))

# ---------------------------
# Tabs
# ---------------------------
tabs = st.tabs(["Dashboard", "Farm Management", "POS", "Reports & Export"])

# ---------------------------
# Tab 1: Dashboard
# ---------------------------
with tabs[0]:
    st.header("📊 Main Dashboard")
    crops_df = pd.read_sql("SELECT * FROM crops", conn)
    sites_df = pd.read_sql("SELECT * FROM sites WHERE site_type='farm'", conn)
    sales_df = pd.read_sql("SELECT * FROM sales", conn)

    if not crops_df.empty:
        crops_df["expected_harvest_date"] = pd.to_datetime(crops_df["expected_harvest_date"])
        crops_df["days_until_harvest"] = (crops_df["expected_harvest_date"] - pd.Timestamp.today()).dt.days

        st.subheader("Active Crops / Items")
        st.dataframe(crops_df[["item_name","site_id","available_qty","unit"]], use_container_width=True)

        st.subheader("Harvest Due Soon (7 days)")
        due_soon = crops_df[crops_df["days_until_harvest"] <= 7]
        st.dataframe(due_soon[["item_name","site_id","expected_harvest_date","days_until_harvest"]], use_container_width=True)

    else:
        st.info("No crops yet")

    if not sales_df.empty:
        st.subheader("Total Sales")
        st.write(f"Total sales records: {len(sales_df)}")
        st.write(f"Total revenue: ${sales_df['total'].sum():.2f}")
    else:
        st.info("No sales yet")

# ---------------------------
# Tab 2: Farm Management
# ---------------------------
with tabs[1]:
    st.header("🌾 Farm Management")
    sites_df = pd.read_sql("SELECT * FROM sites", conn)
    st.subheader("Sites")
    st.dataframe(sites_df, use_container_width=True)

    st.markdown("### Add Site")
    with st.form("add_site_form", clear_on_submit=True):
        site_name = st.text_input("Site name")
        site_type = st.selectbox("Site type", ["farm","market"])
        address = st.text_input("Address")
        phone = st.text_input("Phone")
        notes = st.text_area("Notes", height=80)
        if st.form_submit_button("Add Site"):
            c.execute("INSERT INTO sites (site_name,site_type,address,phone,notes) VALUES (?,?,?,?,?)",
                      (site_name, site_type, address, phone, notes))
            conn.commit()
            st.success(f"Site '{site_name}' added")

    # Crops / Items
    st.markdown("---")
    st.subheader("Crops / Items")
    crops_df = pd.read_sql("SELECT * FROM crops", conn)
    st.dataframe(crops_df, use_container_width=True)

    st.markdown("### Add Crop / Item")
    farm_sites = sites_df[sites_df["site_type"]=="farm"]
    if farm_sites.empty:
        st.warning("Please add a farm site first.")
    else:
        with st.form("add_crop_form", clear_on_submit=True):
            site_choice = st.selectbox("Farm Site", farm_sites["site_id"].tolist())
            item_name = st.text_input("Crop / Item name")
            date_planted = st.date_input("Date planted", value=date.today())
            expected_harvest_date = st.date_input("Expected harvest date", value=date.today()+timedelta(days=90))
            actual_harvest_date = st.date_input("Actual harvest date (optional)", value=None)
            yield_qty = st.number_input("Yield", min_value=0.0, value=0.0, step=0.1)
            unit = st.text_input("Unit (kg, tray, etc.)", value="kg")
            price_per_unit = st.number_input("Price per unit", min_value=0.0, value=0.0, step=0.01)
            notes = st.text_area("Notes", height=80)
            if st.form_submit_button("Add Crop / Item"):
                c.execute("""
                    INSERT INTO crops (site_id,item_name,date_planted,expected_harvest_date,actual_harvest_date,yield_qty,unit,price_per_unit,available_qty,notes)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                          (site_choice,item_name,date_planted.isoformat(),expected_harvest_date.isoformat(),
                           actual_harvest_date.isoformat() if actual_harvest_date else None,
                           yield_qty,unit,price_per_unit,yield_qty,notes))
                conn.commit()
                st.success(f"Added item '{item_name}'")

# ---------------------------
# Tab 3: POS
# ---------------------------
with tabs[2]:
    st.header("💵 Point of Sale (POS)")
    sites_df = pd.read_sql("SELECT * FROM sites WHERE site_type='market'", conn)
    crops_df = pd.read_sql("SELECT * FROM crops WHERE available_qty>0", conn)

    if "cart" not in st.session_state:
        st.session_state.cart = []

    if sites_df.empty:
        st.warning("Add a market site first to start POS")
    else:
        sale_site = st.selectbox("Sale site (market)", sites_df["site_id"].tolist())
        sale_site_info = sites_df[sites_df["site_id"]==sale_site].iloc[0]

        st.markdown(f"**Site:** {sale_site_info['site_name']} - {sale_site_info['address']}")

        available_products = crops_df
        prod_map = {f"{row['crop_id']} | {row['item_name']} ({row['available_qty']} {row['unit']}) - ${row['price_per_unit']:.2f}":row for idx,row in available_products.iterrows()}

        if prod_map:
            product_choice = st.selectbox("Select product", list(prod_map.keys()))
            qty = st.number_input("Quantity", min_value=0.0, value=1.0, step=0.1)
            if st.button("Add to cart"):
                r = prod_map[product_choice]
                st.session_state.cart.append({
                    "crop_id": int(r["crop_id"]),
                    "item_name": r["item_name"],
                    "qty": float(qty),
                    "unit": r["unit"],
                    "price_per_unit": float(r["price_per_unit"])
                })
                st.success("Added to cart")

        st.subheader("Cart")
        if st.session_state.cart:
            cart_df = pd.DataFrame(st.session_state.cart)
            st.dataframe(cart_df, use_container_width=True)
            subtotal = (cart_df["qty"]*cart_df["price_per_unit"]).sum()
            tax = 0.0
            total = subtotal+tax
            st.markdown(f"**Subtotal:** ${subtotal:.2f}  **Tax:** ${tax:.2f}  **Total:** ${total:.2f}")

            payment_type = st.selectbox("Payment Type", ["Cash","Card"])
            cash_given = 0
            change_due = 0
            if payment_type=="Cash":
                cash_given = st.number_input("Cash given", min_value=0.0, value=total, step=0.01)
                change_due = cash_given - total
                st.markdown(f"**Change due:** ${change_due:.2f}")

            receipt_notes = st.text_area("Receipt notes")
            if st.button("Finalize Sale & Generate Receipt"):
                # reduce inventory
                for item in st.session_state.cart:
                    c.execute("UPDATE crops SET available_qty=available_qty-? WHERE crop_id=?",
                              (item["qty"], item["crop_id"]))
                conn.commit()
                # create sale
                c.execute("INSERT INTO sales (date,site_id,items_json,subtotal,tax,total,payment_type,cash_given,change_due,notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (datetime.now().isoformat(), sale_site, json.dumps(st.session_state.cart), subtotal, tax, total,
                           payment_type, cash_given, change_due, receipt_notes))
                conn.commit()
                sale_id = c.lastrowid

                # generate PDF
                pdf_bytes = BytesIO()
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Arial","B",14)
                pdf.cell(0,8, f"{sale_site_info['site_name']}", ln=1)
                pdf.set_font("Arial","",12)
                pdf.cell(0,6, f"{sale_site_info['address']}", ln=1)
                pdf.cell(0,6, f"Phone: {sale_site_info['phone']}", ln=1)
                pdf.ln(4)
                pdf.cell(0,6, f"Receipt #{sale_id} — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=1)
                pdf.ln(4)
                pdf.cell(100,6,"Item",1)
                pdf.cell(30,6,"Qty",1)
                pdf.cell(30,6,"Unit",1)
                pdf.cell(30,6,"Price",1,ln=1)
                for it in st.session_state.cart:
                    pdf.cell(100,6,it["item_name"],1)
                    pdf.cell(30,6,str(it["qty"]),1)
                    pdf.cell(30,6,it["unit"],1)
                    pdf.cell(30,6,f"${it['price_per_unit']:.2f}",1,ln=1)
                pdf.ln(2)
                pdf.cell(0,6,f"Subtotal: ${subtotal:.2f}",ln=1)
                pdf.cell(0,6,f"Tax: ${tax:.2f}",ln=1)
                pdf.cell(0,6,f"Total: ${total:.2f}",ln=1)
                pdf.cell(0,6,f"Payment type: {payment_type}",ln=1)
                if payment_type=="Cash":
                    pdf.cell(0,6,f"Cash given: ${cash_given:.2f}",ln=1)
                    pdf.cell(0,6,f"Change due: ${change_due:.2f}",ln=1)
                if receipt_notes:
                    pdf.multi_cell(0,6,f"Notes: {receipt_notes}")
                pdf.output(pdf_bytes)
                pdf_bytes.seek(0)
                st.download_button("Download Receipt (PDF)", pdf_bytes, file_name=f"receipt_{sale_id}.pdf")
                st.success(f"Sale completed (ID {sale_id})")
                st.session_state.cart = []

# ---------------------------
# Tab 4: Reports & Export
# ---------------------------
with tabs[3]:
    st.header("📁 Reports & Data Export")
    for tbl in ["sites","crops","sales"]:
        df = pd.read_sql(f"SELECT * FROM {tbl}", conn)
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button(f"Download {tbl}.csv", csv_bytes, file_name=f"{tbl}.csv")
