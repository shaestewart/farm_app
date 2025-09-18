import streamlit as st
import sqlite3
from datetime import datetime, timedelta
from fpdf import FPDF
from io import BytesIO
import qrcode
import pandas as pd

# -------------------------
# DATABASE SETUP
# -------------------------
conn = sqlite3.connect("farm_manager.db", check_same_thread=False)
c = conn.cursor()

# Sites Table
c.execute('''
CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name TEXT,
    site_type TEXT,  -- "field" or "market"
    address TEXT,
    phone TEXT
)
''')

# Crops/Items Table
c.execute('''
CREATE TABLE IF NOT EXISTS crops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER,
    item_name TEXT,
    date_planted TEXT,
    expected_harvest TEXT,
    actual_harvest TEXT,
    yield_amount REAL,
    notes TEXT,
    FOREIGN KEY(site_id) REFERENCES sites(id)
)
''')

# Sales Table
c.execute('''
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER,
    date TEXT,
    payment_type TEXT,
    cash_given REAL,
    change_due REAL,
    total REAL,
    notes TEXT,
    FOREIGN KEY(site_id) REFERENCES sites(id)
)
''')

# Sale Items Table
c.execute('''
CREATE TABLE IF NOT EXISTS sale_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER,
    item_name TEXT,
    qty REAL,
    unit TEXT,
    price_per_unit REAL,
    FOREIGN KEY(sale_id) REFERENCES sales(id)
)
''')
conn.commit()

# -------------------------
# LOGIN
# -------------------------
st.title("Farm Manager App")
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    password_input = st.text_input("Enter Password", type="password")
    if st.button("Login"):
        if password_input == st.secrets.get("FARM_PASSWORD", "admin123"):
            st.session_state.logged_in = True
        else:
            st.error("Incorrect password")
else:
    # -------------------------
    # SIDEBAR
    # -------------------------
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to", ["Dashboard", "Farm Management", "POS", "Export Data", "Add Site/Crop"])

    # Quick Stats
    st.sidebar.subheader("Quick Stats")
    c.execute("SELECT COUNT(*) FROM crops")
    total_crops = c.fetchone()[0]
    st.sidebar.write(f"Total crops: {total_crops}")

    c.execute("SELECT SUM(yield_amount) FROM crops WHERE actual_harvest IS NOT NULL")
    total_stock = c.fetchone()[0] or 0
    st.sidebar.write(f"Total stock: {total_stock}")

    today = datetime.now().date()
    c.execute("SELECT COUNT(*) FROM crops WHERE actual_harvest IS NULL")
    crops_due_soon = 0
    for row in c.fetchall():
        # For simplicity, check expected_harvest
        c.execute("SELECT expected_harvest FROM crops WHERE actual_harvest IS NULL")
        for e in c.fetchall():
            if e[0]:
                harvest_date = datetime.strptime(e[0], "%Y-%m-%d").date()
                if 0 <= (harvest_date - today).days <= 5:
                    crops_due_soon += 1
    st.sidebar.write(f"Harvest due soon (<5 days): {crops_due_soon}")

    # -------------------------
    # PAGE CONTENT
    # -------------------------
    if page == "Dashboard":
        st.header("Dashboard")
        # Harvest Alerts
        st.subheader("Harvest Alerts")
        c.execute("SELECT c.item_name, s.site_name, c.expected_harvest FROM crops c JOIN sites s ON c.site_id=s.id WHERE c.actual_harvest IS NULL")
        crops_due = c.fetchall()
        for crop in crops_due:
            if crop[2]:
                harvest_date = datetime.strptime(crop[2], "%Y-%m-%d").date()
                days_left = (harvest_date - today).days
                if days_left <= 5:
                    st.warning(f"{crop[0]} at {crop[1]} ready for harvest in {days_left} days (Expected {harvest_date})")

        # Stock Summary
        st.subheader("Current Stock / Inventory")
        c.execute("SELECT item_name, SUM(yield_amount) FROM crops WHERE actual_harvest IS NOT NULL GROUP BY item_name")
        stock = c.fetchall()
        for s_item in stock:
            st.write(f"{s_item[0]}: {s_item[1]} units available for sale")

        # Revenue Summary
        st.subheader("Revenue Summary")
        c.execute("SELECT s.site_name, SUM(sa.total) FROM sales sa JOIN sites s ON sa.site_id=s.id GROUP BY s.site_name")
        revenues = c.fetchall()
        for rev in revenues:
            st.write(f"{rev[0]}: ${rev[1] or 0:.2f}")

    elif page == "Farm Management":
        st.header("Farm Management")
        # List Sites
        st.subheader("Sites")
        c.execute("SELECT id, site_name, site_type FROM sites")
        sites = c.fetchall()
        for s in sites:
            st.write(f"{s[1]} ({s[2]})")
        # List Crops
        st.subheader("Crops / Items")
        c.execute("SELECT c.id, c.item_name, s.site_name, c.date_planted, c.expected_harvest, c.actual_harvest, c.yield_amount FROM crops c JOIN sites s ON c.site_id=s.id")
        crops = c.fetchall()
        for crop in crops:
            st.write(f"{crop[1]} at {crop[2]}: Planted {crop[3]}, Expected Harvest {crop[4]}, Actual {crop[5]}, Yield {crop[6]}")

    elif page == "POS":
        st.header("Point of Sale")
        c.execute("SELECT id, site_name FROM sites WHERE site_type='market'")
        sites = c.fetchall()
        if not sites:
            st.warning("No market sites found. Add at least one market site first.")
        else:
            site_dict = {s[1]: s[0] for s in sites}
            selected_site_name = st.selectbox("Select Sale Site", list(site_dict.keys()))
            selected_site_id = site_dict[selected_site_name]

            if "cart" not in st.session_state:
                st.session_state.cart = []

            with st.expander("Add Item to Cart"):
                item_name = st.text_input("Item Name", key="item_name")
                qty = st.number_input("Quantity", min_value=1, value=1, key="qty")
                unit = st.text_input("Unit", value="pcs", key="unit")
                price = st.number_input("Price per Unit", min_value=0.0, value=0.0, format="%.2f", key="price")
                if st.button("Add to Cart"):
                    st.session_state.cart.append({"item_name": item_name, "qty": qty, "unit": unit, "price_per_unit": price})

            st.write("Cart:", st.session_state.cart)

            payment_type = st.selectbox("Payment Type", ["Cash", "Card"], key="payment_type")
            subtotal = sum([it["qty"]*it["price_per_unit"] for it in st.session_state.cart])
            tax = subtotal * 0.07
            total = subtotal + tax
            cash_given = 0.0
            change_due = 0.0
            if payment_type == "Cash":
                cash_given = st.number_input("Cash Given", min_value=0.0, value=total, format="%.2f", key="cash_given")
                change_due = cash_given - total

            receipt_notes = st.text_area("Notes", key="notes")

            if st.button("Complete Sale"):
                if not st.session_state.cart:
                    st.error("Cart is empty!")
                else:
                    c.execute("INSERT INTO sales (site_id, date, payment_type, cash_given, change_due, total, notes) VALUES (?,?,?,?,?,?,?)",
                              (selected_site_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), payment_type, cash_given, change_due, total, receipt_notes))
                    sale_id = c.lastrowid

                    for it in st.session_state.cart:
                        c.execute("INSERT INTO sale_items (sale_id, item_name, qty, unit, price_per_unit) VALUES (?,?,?,?,?)",
                                  (sale_id, it["item_name"], it["qty"], it["unit"], it["price_per_unit"]))
                    conn.commit()

                    # Generate PDF
                    pdf_bytes = BytesIO()
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.set_font("Arial", "B", 16)
                    pdf.cell(0, 10, f"{selected_site_name} - Receipt #{sale_id}", ln=1, align="C")
                    pdf.set_font("Arial", "", 12)
                    for it in st.session_state.cart:
                        item_name_safe = it["item_name"].encode('latin-1', 'replace').decode('latin-1')
                        pdf.cell(0, 6, f"{item_name_safe} - {it['qty']} {it['unit']} @ ${it['price_per_unit']:.2f}", ln=1)
                    pdf.cell(0,6,f"Subtotal: ${subtotal:.2f}", ln=1)
                    pdf.cell(0,6,f"Tax: ${tax:.2f}", ln=1)
                    pdf.cell(0,6,f"Total: ${total:.2f}", ln=1)
                    if payment_type=="Cash":
                        pdf.cell(0,6,f"Cash given: ${cash_given:.2f}", ln=1)
                        pdf.cell(0,6,f"Change due: ${change_due:.2f}", ln=1)
                    pdf_bytes.seek(0)
                    pdf.output(pdf_bytes)
                    pdf_bytes.seek(0)
                    st.download_button("Download Receipt (PDF)", pdf_bytes, file_name=f"receipt_{sale_id}.pdf")
                    st.success(f"Sale completed (ID {sale_id})")

                    st.session_state.cart = []

    elif page == "Export Data":
        st.header("Export Data")
        c.execute("SELECT * FROM crops")
        crops_df = pd.DataFrame(c.fetchall(), columns=[desc[0] for desc in c.description])
        c.execute("SELECT * FROM sales")
        sales_df = pd.DataFrame(c.fetchall(), columns=[desc[0] for desc in c.description])
        st.download_button("Download Crops CSV", crops_df.to_csv(index=False).encode('utf-8'), "crops.csv", "text/csv")
        st.download_button("Download Sales CSV", sales_df.to_csv(index=False).encode('utf-8'), "sales.csv", "text/csv")

    elif page == "Add Site/Crop":
        st.header("Add Site / Crop")
        with st.expander("Add New Site"):
            site_name = st.text_input("Site Name")
            site_type = st.selectbox("Site Type", ["field", "market"])
            address = st.text_input("Address")
            phone = st.text_input("Phone")
            if st.button("Add Site"):
                c.execute("INSERT INTO sites (site_name, site_type, address, phone) VALUES (?,?,?,?)", (site_name, site_type, address, phone))
                conn.commit()
                st.success("Site added successfully!")

        with st.expander("Add New Crop"):
            c.execute("SELECT id, site_name FROM sites WHERE site_type='field'")
            fields = c.fetchall()
            if fields:
                field_dict = {f[1]: f[0] for f in fields}
                selected_field = st.selectbox("Select Field", list(field_dict.keys()))
                item_name = st.text_input("Crop / Item Name")
                date_planted = st.date_input("Date Planted")
                expected_harvest = st.date_input("Expected Harvest")
                yield_amount = st.number_input("Yield Amount", min_value=0.0, value=0.0)
                notes = st.text_area("Notes")
                if st.button("Add Crop"):
                    c.execute("INSERT INTO crops (site_id, item_name, date_planted, expected_harvest, yield_amount, notes) VALUES (?,?,?,?,?,?)",
                              (field_dict[selected_field], item_name, date_planted.strftime("%Y-%m-%d"), expected_harvest.strftime("%Y-%m-%d"), yield_amount, notes))
                    conn.commit()
                    st.success("Crop added successfully!")
            else:
                st.warning("Add at least one field site first.")
