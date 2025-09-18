import streamlit as st
import sqlite3
from datetime import datetime
from fpdf import FPDF
from io import BytesIO
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
    site_type TEXT,
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
    crop_id INTEGER,
    item_name TEXT,
    qty REAL,
    discount REAL,
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
        if password_input == st.secrets["FARM_PASSWORD"]:
            st.session_state.logged_in = True
        else:
            st.error("Incorrect password")
else:
    # -------------------------
    # SIDEBAR
    # -------------------------
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to", ["Dashboard", "Farm Management", "POS", "Add Site/Crop", "Inventory Adjustment", "Export Data"])

    # Quick Stats
    st.sidebar.subheader("Quick Stats")
    c.execute("SELECT COUNT(*) FROM crops")
    total_crops = c.fetchone()[0]
    st.sidebar.write(f"Total crops: {total_crops}")

    c.execute("SELECT SUM(yield_amount) FROM crops WHERE actual_harvest IS NOT NULL")
    total_stock = c.fetchone()[0] or 0
    st.sidebar.write(f"Total stock: {total_stock}")

    # -------------------------
    # PAGE CONTENT
    # -------------------------
    if page == "Dashboard":
        st.header("Dashboard")
        # Harvest Alerts
        st.subheader("Harvest Alerts")
        today = datetime.now().date()
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

        # Harvest Crops
        st.subheader("Harvest Crops")
        c.execute("SELECT id, item_name, site_id, expected_harvest FROM crops WHERE actual_harvest IS NULL")
        active_crops = c.fetchall()
        if active_crops:
            crop_options = [f"{c[1]} at site {c[2]} (Expected: {c[3]})" for c in active_crops]
            selected_crop_str = st.selectbox("Select Crop to Harvest", crop_options)
            selected_index = crop_options.index(selected_crop_str)
            selected_crop = active_crops[selected_index]

            actual_harvest_date = st.date_input("Actual Harvest Date", datetime.today())
            yield_amount = st.number_input("Yield Amount", min_value=0.0, value=0.0)
            if st.button("Record Harvest"):
                c.execute(
                    "UPDATE crops SET actual_harvest=?, yield_amount=? WHERE id=?",
                    (actual_harvest_date.strftime("%Y-%m-%d"), yield_amount, selected_crop[0])
                )
                conn.commit()
                st.success(f"Harvest recorded for {selected_crop[1]}!")
        else:
            st.info("No active crops to harvest.")

    elif page == "POS":
        st.header("Point of Sale")
        c.execute("SELECT id, site_name FROM sites WHERE site_type='Market'")
        sites = c.fetchall()
        if not sites:
            st.warning("No market sites found. Add at least one market site first.")
        else:
            site_dict = {s[1]: s[0] for s in sites}
            selected_site_name = st.selectbox("Select Sale Site", list(site_dict.keys()))
            selected_site_id = site_dict[selected_site_name]

            if "cart" not in st.session_state:
                st.session_state.cart = []

            # Add items
            st.subheader("Add Items to Cart")
            c.execute("SELECT id, item_name, yield_amount FROM crops WHERE actual_harvest IS NOT NULL AND yield_amount>0")
            harvested_items = c.fetchall()
            item_dict = {f"{i[1]} (Stock: {i[2]})": i for i in harvested_items}
            selected_item_str = st.selectbox("Select Item", list(item_dict.keys()))
            selected_item = item_dict[selected_item_str]
            qty = st.number_input("Quantity", min_value=1, value=1)
            price_per_unit = st.number_input("Price per Unit", min_value=0.0, value=0.0)
            discount = st.number_input("Discount ($)", min_value=0.0, value=0.0)
            if st.button("Add to Cart"):
                if qty > selected_item[2]:
                    st.error("Not enough stock!")
                else:
                    st.session_state.cart.append({
                        "crop_id": selected_item[0],
                        "item_name": selected_item[1],
                        "qty": qty,
                        "price_per_unit": price_per_unit,
                        "discount": discount
                    })

            st.write("Cart:", st.session_state.cart)

            # Payment
            payment_type = st.selectbox("Payment Type", ["Cash", "Card"])
            subtotal = sum([(it["qty"]*it["price_per_unit"])-it["discount"] for it in st.session_state.cart])
            tax = subtotal * 0.07
            total = subtotal + tax
            cash_given = 0.0
            change_due = 0.0
            if payment_type=="Cash":
                cash_given = st.number_input("Cash Given", min_value=0.0, value=total)
                change_due = cash_given - total

            receipt_notes = st.text_area("Notes")

            if st.button("Complete Sale"):
                if not st.session_state.cart:
                    st.error("Cart is empty!")
                else:
                    # Save sale
                    c.execute("INSERT INTO sales (site_id, date, payment_type, cash_given, change_due, total, notes) VALUES (?,?,?,?,?,?,?)",
                              (selected_site_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), payment_type, cash_given, change_due, total, receipt_notes))
                    sale_id = c.lastrowid

                    for it in st.session_state.cart:
                        c.execute("INSERT INTO sale_items (sale_id, crop_id, item_name, qty, price_per_unit, discount) VALUES (?,?,?,?,?,?)",
                                  (sale_id, it["crop_id"], it["item_name"], it["qty"], it["price_per_unit"], it["discount"]))
                        # Decrease inventory
                        c.execute("UPDATE crops SET yield_amount = yield_amount - ? WHERE id=?", (it["qty"], it["crop_id"]))
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
                        pdf.cell(0,6,f"{item_name_safe} - {it['qty']} @ ${it['price_per_unit']:.2f} - Discount ${it['discount']:.2f}", ln=1)
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
                    st.session_state.cart = []  # Reset cart after sale

    elif page == "Add Site/Crop":
        st.header("Add New Site or Crop")

        # Add Site
        st.subheader("Add Site")
        with st.form("add_site_form"):
            site_name = st.text_input("Site Name")
            site_type = st.selectbox("Site Type", ["Field", "Greenhouse", "Market"])
            site_address = st.text_area("Address")
            site_phone = st.text_input("Phone")
            submit_site = st.form_submit_button("Add Site")
            if submit_site:
                c.execute("INSERT INTO sites (site_name, site_type, address, phone) VALUES (?, ?, ?, ?)",
                          (site_name, site_type, site_address, site_phone))
                conn.commit()
                st.success("Site added successfully!")

        # Add Crop
        st.subheader("Add Crop")
        c.execute("SELECT id, site_name FROM sites")
        sites = c.fetchall()
        if sites:
            with st.form("add_crop_form"):
                site_id = st.selectbox("Select Site", [site[1] for site in sites])
                item_name = st.text_input("Crop Name")
                date_planted = st.date_input("Planting Date", datetime.today())
                expected_harvest = st.date_input("Expected Harvest Date", datetime.today())
                notes = st.text_area("Notes")
                submit_crop = st.form_submit_button("Add Crop")
                if submit_crop:
                    site_id_val = [site[0] for site in sites if site[1] == site_id][0]
                    c.execute("INSERT INTO crops (site_id, item_name, date_planted, expected_harvest, notes) VALUES (?, ?, ?, ?, ?)",
                              (site_id_val, item_name, date_planted.strftime("%Y-%m-%d"), expected_harvest.strftime("%Y-%m-%d"), notes))
                    conn.commit()
                    st.success("Crop added successfully!")
        else:
            st.info("Add a site first.")

    elif page == "Inventory Adjustment":
        st.header("Manual Inventory Adjustment")
        c.execute("SELECT id, item_name FROM crops WHERE actual_harvest IS NOT NULL")
        crops = c.fetchall()
        crop_dict = {crop[1]: crop[0] for crop in crops}
        if crops:
            selected_crop = st.selectbox("Select Crop", list(crop_dict.keys()))
            adjustment = st.number_input("Adjustment Amount", min_value=-1000.0, max_value=1000.0, step=0.1)
            if st.button("Apply Adjustment"):
                crop_id = crop_dict[selected_crop]
                c.execute("UPDATE crops SET yield_amount = yield_amount + ? WHERE id = ?", (adjustment, crop_id))
                conn.commit()
                st.success(f"Inventory adjusted for {selected_crop} by {adjustment} units.")
        else:
            st.info("No harvested crops available.")

    elif page == "Export Data":
        st.header("Export Data")
        # Crops
        st.subheader("Export Crops")
        crops_df = pd.read_sql_query("SELECT * FROM crops", conn)
        csv_crops = crops_df.to_csv(index=False).encode('utf-8')
        st.download_button("Download Crops CSV", csv_crops, "crops.csv", "text/csv")
        # Sales
        st.subheader("Export Sales")
        sales_df = pd.read_sql_query("SELECT * FROM sales", conn)
        csv_sales = sales_df.to_csv(index=False).encode('utf-8')
        st.download_button("Download Sales CSV", csv_sales, "sales.csv", "text/csv")
