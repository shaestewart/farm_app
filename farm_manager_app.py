"""
Farm Management + POS Streamlit App
Single-file deployable app.

Usage:
    streamlit run farm_manager_app.py

CSV files created (if not exist):
 - sites.csv
 - crops.csv
 - sales.csv

Dependencies: see requirements.txt below.
"""
import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime, date, timedelta
from io import BytesIO
from fpdf import FPDF
import qrcode
import base64

# ---------------------------
# Config & Storage paths
# ---------------------------
st.set_page_config(page_title="Farm Management & POS", layout="wide")

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

SITES_CSV = DATA_DIR / "sites.csv"
CROPS_CSV = DATA_DIR / "crops.csv"
SALES_CSV = DATA_DIR / "sales.csv"

# ---------------------------
# Default CSV creation
# ---------------------------
def ensure_csv(path: Path, cols):
    if not path.exists():
        df = pd.DataFrame(columns=cols)
        df.to_csv(path, index=False)

ensure_csv(SITES_CSV, ["site_id", "site_name", "address", "phone", "notes"])
ensure_csv(CROPS_CSV, [
    "crop_id", "site_id", "item_name", "date_planted", "expected_harvest_date",
    "actual_harvest_date", "yield_qty", "unit", "price_per_unit", "notes", "available_qty"
])
ensure_csv(SALES_CSV, [
    "sale_id", "date", "site_id", "items_json", "subtotal", "tax", "total", "notes"
])

# ---------------------------
# Utilities
# ---------------------------
def load_sites():
    return pd.read_csv(SITES_CSV).fillna("")

def load_crops():
    df = pd.read_csv(CROPS_CSV).fillna("")
    # parse date fields safely
    for col in ["date_planted", "expected_harvest_date", "actual_harvest_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    return df

def load_sales():
    return pd.read_csv(SALES_CSV).fillna("")

def save_sites(df):
    df.to_csv(SITES_CSV, index=False)

def save_crops(df):
    # for date columns, convert to isoformat strings
    df2 = df.copy()
    for col in ["date_planted", "expected_harvest_date", "actual_harvest_date"]:
        if col in df2.columns:
            df2[col] = df2[col].apply(lambda x: x.isoformat() if pd.notna(x) and isinstance(x, (date,)) else (x if x=="" else str(x)))
    df2.to_csv(CROPS_CSV, index=False)

def save_sales(df):
    df.to_csv(SALES_CSV, index=False)

def next_id(df, id_col):
    if df.empty:
        return 1
    return int(df[id_col].max()) + 1

# Simple JSON/pickle-like convert: we store items_json as plain stringified dicts
import json

# ---------------------------
# Auth: single password
# ---------------------------
def check_password():
    pw_secret = None
    try:
        pw_secret = st.secrets["FARM_PASSWORD"]
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
                st.experimental_rerun()
            else:
                st.error("Incorrect password")
        st.stop()

check_password()

# ---------------------------
# Small UI/CSS polish
# ---------------------------
st.markdown("""
<style>
h1 {text-align:center;}
.sidebar .block-container {padding-top:1rem;}
.card {background:#ffffff; border-radius:8px; padding:12px; box-shadow:0 2px 6px rgba(0,0,0,0.07);}
.small {font-size:0.9rem; color:#666;}
</style>
""", unsafe_allow_html=True)

st.title("🚜 Farm Management & POS")

# ---------------------------
# Sidebar: quick actions
# ---------------------------
st.sidebar.header("Quick Actions")
if st.sidebar.button("Add Site"):
    st.session_state.show_add_site = True
if st.sidebar.button("Add Crop/Item"):
    st.session_state.show_add_crop = True
if st.sidebar.button("Open POS"):
    st.session_state.show_pos = True
if st.sidebar.button("Export All CSVs"):
    # bundle CSVs in a zip in memory and provide download as one file
    import zipfile, io
    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, mode="w") as zf:
        zf.write(SITES_CSV, arcname="sites.csv")
        zf.write(CROPS_CSV, arcname="crops.csv")
        zf.write(SALES_CSV, arcname="sales.csv")
    mem_zip.seek(0)
    st.sidebar.download_button("Download data.zip", mem_zip, file_name="farm_data.zip")

st.sidebar.markdown("---")
st.sidebar.markdown("**Persistence:** CSVs are stored in `/data` in the app folder.")
st.sidebar.markdown("Hint: override password via `st.secrets['FARM_PASSWORD']`.")

# ---------------------------
# Tabs: Farm, POS, Reports
# ---------------------------
tabs = st.tabs(["Farm Management", "Point of Sale (POS)", "Dashboard & Reports", "Data Export / Admin"])

# ---------------------------
# Tab 1: Farm Management
# ---------------------------
with tabs[0]:
    st.header("🌾 Farm Management")
    sites_df = load_sites()
    crops_df = load_crops()

    st.subheader("Sites")
    cols = st.columns([3,1])
    with cols[0]:
        st.dataframe(sites_df[["site_id","site_name","address","phone","notes"]], use_container_width=True)
    with cols[1]:
        st.markdown("### Add Site")
        with st.form("add_site_form", clear_on_submit=True):
            site_name = st.text_input("Site name")
            address = st.text_input("Address")
            phone = st.text_input("Phone")
            notes = st.text_area("Notes", height=80)
            if st.form_submit_button("Add Site"):
                sid = next_id(sites_df, "site_id") if "site_id" in sites_df.columns else 1
                new = {"site_id": sid, "site_name": site_name, "address": address, "phone": phone, "notes": notes}
                sites_df = pd.concat([sites_df, pd.DataFrame([new])], ignore_index=True)
                save_sites(sites_df)
                st.success(f"Site '{site_name}' added")
                st.experimental_rerun()

    st.markdown("---")
    st.subheader("Crops & Items")
    st.dataframe(crops_df[["crop_id","site_id","item_name","date_planted","expected_harvest_date","yield_qty","available_qty","unit","price_per_unit"]], use_container_width=True)

    st.markdown("### Add Crop / Item")
    with st.form("add_crop_form", clear_on_submit=True):
        # choose site id from existing sites
        if sites_df.empty:
            st.warning("Please add a site first.")
        else:
            site_options = sites_df["site_id"].astype(int).tolist()
            site_choice = st.selectbox("Site (ID)", site_options)
            item_name = st.text_input("Crop / Item name")
            date_planted = st.date_input("Date planted", value=date.today())
            expected_harvest_date = st.date_input("Expected harvest date", value=date.today() + timedelta(days=90))
            actual_harvest_date = st.date_input("Actual harvest date (if harvested)", value=None)
            yield_qty = st.number_input("Yield (numeric)", min_value=0.0, value=0.0, step=0.1)
            unit = st.text_input("Unit (e.g., kg, bunch, tray)", value="kg")
            price_per_unit = st.number_input("Price per unit (for POS)", min_value=0.0, value=0.0, step=0.01)
            notes = st.text_area("Notes", height=80)
            if st.form_submit_button("Add Crop / Item"):
                cid = next_id(crops_df, "crop_id") if "crop_id" in crops_df.columns else 1
                new = {
                    "crop_id": cid,
                    "site_id": int(site_choice),
                    "item_name": item_name,
                    "date_planted": date_planted.isoformat(),
                    "expected_harvest_date": expected_harvest_date.isoformat(),
                    "actual_harvest_date": "" if actual_harvest_date is None else actual_harvest_date.isoformat(),
                    "yield_qty": float(yield_qty),
                    "unit": unit,
                    "price_per_unit": float(price_per_unit),
                    "notes": notes,
                    "available_qty": float(yield_qty)  # initial available equal yield
                }
                crops_df = pd.concat([crops_df, pd.DataFrame([new])], ignore_index=True)
                save_crops(crops_df)
                st.success(f"Added item '{item_name}'")
                st.experimental_rerun()

    st.markdown("---")
    st.subheader("Edit Crop / Update Inventory")
    if not crops_df.empty:
        sel = st.selectbox("Select crop to edit (by crop_id)", crops_df["crop_id"].tolist())
        crop_row = crops_df[crops_df["crop_id"] == sel].iloc[0]
        with st.form("edit_crop_form"):
            st.write(f"Editing crop id {sel} — {crop_row['item_name']}")
            new_avail = st.number_input("Available quantity", min_value=0.0, value=float(crop_row.get("available_qty", 0)), step=0.1)
            new_actual = st.date_input("Actual harvest date (blank if not)", value=(crop_row['actual_harvest_date'] if pd.notna(crop_row['actual_harvest_date']) else None))
            submit = st.form_submit_button("Save")
            if submit:
                idx = crops_df.index[crops_df["crop_id"]==sel][0]
                crops_df.at[idx, "available_qty"] = float(new_avail)
                crops_df.at[idx, "actual_harvest_date"] = "" if new_actual is None else new_actual.isoformat()
                save_crops(crops_df)
                st.success("Crop updated")
                st.experimental_rerun()
    else:
        st.info("No crops yet.")

# ---------------------------
# Tab 2: POS
# ---------------------------
with tabs[1]:
    st.header("💵 Point of Sale (POS)")
    sites_df = load_sites()
    crops_df = load_crops()
    sales_df = load_sales()

    st.subheader("Sale Settings")
    if sites_df.empty:
        st.warning("Add a site first to configure sale info.")
    else:
        sale_site = st.selectbox("Sale site (for receipt)", sites_df["site_id"].astype(int).tolist())
        sale_site_info = sites_df[sites_df["site_id"]==int(sale_site)].iloc[0]
        st.markdown(f"**Site:** {sale_site_info['site_name']} — {sale_site_info['address']}  \nPhone: {sale_site_info['phone']}")

    st.markdown("### Build Cart")
    # initialize cart in session state
    if "cart" not in st.session_state:
        st.session_state.cart = []

    # product selection
    available_products = crops_df[crops_df["available_qty"].astype(float) > 0] if not crops_df.empty else pd.DataFrame()
    prod_map = {}
    if not available_products.empty:
        for _, r in available_products.iterrows():
            key = f"{int(r['crop_id'])} | {r['item_name']} ({r['available_qty']} {r['unit']}) - ${r['price_per_unit']:.2f}"
            prod_map[key] = r
        product_choice = st.selectbox("Select product to add", list(prod_map.keys()))
        qty = st.number_input("Quantity", min_value=0.0, step=0.1, value=1.0)
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

    st.markdown("#### Cart")
    if st.session_state.cart:
        cart_df = pd.DataFrame(st.session_state.cart)
        st.dataframe(cart_df, use_container_width=True)
        # subtotal
        subtotal = (cart_df["qty"] * cart_df["price_per_unit"]).sum()
        tax = subtotal * 0.0  # placeholder; VAT if needed
        total = subtotal + tax
        st.markdown(f"**Subtotal:** ${subtotal:.2f}  \n**Tax:** ${tax:.2f}  \n**Total:** ${total:.2f}")

        # finalize sale
        receipt_notes = st.text_area("Receipt notes (optional)", height=80)
        if st.button("Finalize Sale & Generate Receipt"):
            # reduce inventory
            for item in st.session_state.cart:
                idx = crops_df.index[crops_df["crop_id"]==item["crop_id"]][0]
                crops_df.at[idx, "available_qty"] = float(crops_df.at[idx, "available_qty"]) - item["qty"]
                if crops_df.at[idx, "available_qty"] < 0:
                    crops_df.at[idx, "available_qty"] = 0.0
            save_crops(crops_df)

            # create sale record
            sale_id = next_id(sales_df, "sale_id") if "sale_id" in sales_df.columns and not sales_df.empty else 1
            sale_row = {
                "sale_id": sale_id,
                "date": datetime.now().isoformat(),
                "site_id": int(sale_site),
                "items_json": json.dumps(st.session_state.cart),
                "subtotal": float(subtotal),
                "tax": float(tax),
                "total": float(total),
                "notes": receipt_notes
            }
            sales_df = pd.concat([sales_df, pd.DataFrame([sale_row])], ignore_index=True)
            save_sales(sales_df)

            # generate PDF receipt (in memory) and provide download
            pdf_bytes = BytesIO()
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=12)
            # header
            pdf.cell(0, 8, txt=f"{sale_site_info['site_name']}", ln=1)
            pdf.cell(0, 6, txt=f"{sale_site_info['address']}", ln=1)
            pdf.cell(0, 6, txt=f"Phone: {sale_site_info['phone']}", ln=1)
            pdf.ln(4)
            pdf.cell(0, 6, txt=f"Receipt #{sale_id} — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=1)
            pdf.ln(4)
            pdf.cell(100, 6, txt="Item", border=1)
            pdf.cell(30, 6, txt="Qty", border=1)
            pdf.cell(30, 6, txt="Unit", border=1)
            pdf.cell(30, 6, txt="Price", border=1, ln=1)
            for it in st.session_state.cart:
                pdf.cell(100, 6, txt=str(it["item_name"]), border=1)
                pdf.cell(30, 6, txt=str(it["qty"]), border=1)
                pdf.cell(30, 6, txt=str(it["unit"]), border=1)
                pdf.cell(30, 6, txt=f"${it['price_per_unit']:.2f}", border=1, ln=1)
            pdf.ln(2)
            pdf.cell(0, 6, txt=f"Subtotal: ${subtotal:.2f}", ln=1)
            pdf.cell(0, 6, txt=f"Tax: ${tax:.2f}", ln=1)
            pdf.cell(0, 6, txt=f"Total: ${total:.2f}", ln=1)
            pdf.ln(6)
            if receipt_notes:
                pdf.multi_cell(0, 6, txt=f"Notes: {receipt_notes}")
            pdf.output(pdf_bytes)
            pdf_bytes.seek(0)

            # QR code of sale link or ID (optional)
            qr_img = qrcode.make(f"sale:{sale_id}")
            qr_buf = BytesIO()
            qr_img.save(qr_buf, format="PNG")
            qr_buf.seek(0)

            st.success(f"Sale recorded (ID {sale_id}).")
            st.download_button("Download Receipt (PDF)", pdf_bytes, file_name=f"receipt_{sale_id}.pdf", mime="application/pdf")

            # clear cart
            st.session_state.cart = []
    else:
        st.info("Cart is empty")

# ---------------------------
# Tab 3: Dashboard & Reports
# ---------------------------
with tabs[2]:
    st.header("📈 Dashboard & Reports")
    crops_df = load_crops()
    sales_df = load_sales()
    sites_df = load_sites()

    # Active crops (not harvested)
    st.subheader("Active Crops (not harvested)")
    if not crops_df.empty:
        active = crops_df[crops_df["actual_harvest_date"].isnull() | (crops_df["actual_harvest_date"]=="")]
        # compute days until expected harvest
        def days_until(d):
            try:
                dd = pd.to_datetime(d).date()
                return (dd - date.today()).days
            except Exception:
                return None
        active = active.copy()
        active["days_until_harvest"] = active["expected_harvest_date"].apply(days_until)
        st.dataframe(active[["crop_id","item_name","site_id","expected_harvest_date","days_until_harvest","available_qty"]], use_container_width=True)

        # Alerts: ready within 7 days
        soon = active[active["days_until_harvest"].between(0,7)]
        if not soon.empty:
            st.warning("Crops ready for harvest within 7 days:")
            for _, r in soon.iterrows():
                st.write(f"- {r['item_name']} (site {r['site_id']}) — expected in {int(r['days_until_harvest'])} days")
        else:
            st.success("No crops ready within 7 days.")
    else:
        st.info("No crop data yet.")

    st.markdown("---")
    st.subheader("Sales Summary")
    if not sales_df.empty:
        sales_df["date_parsed"] = pd.to_datetime(sales_df["date"], errors="coerce")
        sales_summary = sales_df.groupby(sales_df["date_parsed"].dt.to_period("M"))["total"].sum().reset_index()
        st.dataframe(sales_summary.rename(columns={"date_parsed":"month","total":"revenue"}))
        st.markdown(f"**Total revenue:** ${sales_df['total'].sum():.2f}")
    else:
        st.info("No sales yet.")

    st.markdown("---")
    st.subheader("Inventory Snapshot")
    if not crops_df.empty:
        inv = crops_df[["crop_id","item_name","site_id","available_qty","unit"]]
        st.dataframe(inv, use_container_width=True)
    else:
        st.info("No inventory data yet.")

# ---------------------------
# Tab 4: Data Export / Admin
# ---------------------------
with tabs[3]:
    st.header("🛠️ Data Export & Admin")
    st.markdown("Download CSVs or clear demo data (careful!).")
    st.download_button("Download sites.csv", SITES_CSV.read_bytes(), "sites.csv", "text/csv")
    st.download_button("Download crops.csv", CROPS_CSV.read_bytes(), "crops.csv", "text/csv")
    st.download_button("Download sales.csv", SALES_CSV.read_bytes(), "sales.csv", "text/csv")

    st.markdown("---")
    if st.button("Reset ALL DATA (wipe CSVs)"):
        # destructive — warn
        if st.confirm("Are you sure? This will clear all saved data."):
            ensure_csv(SITES_CSV, ["site_id", "site_name", "address", "phone", "notes"])
            ensure_csv(CROPS_CSV, ["crop_id", "site_id", "item_name", "date_planted", "expected_harvest_date", "actual_harvest_date", "yield_qty", "unit", "price_per_unit", "notes", "available_qty"])
            ensure_csv(SALES_CSV, ["sale_id", "date", "site_id", "items_json", "subtotal", "tax", "total", "notes"])
            st.success("Data reset.")
            st.experimental_rerun()

    st.markdown("Admin tips: add sites first, then crops. Use the POS tab to take sales and generate receipts.")
