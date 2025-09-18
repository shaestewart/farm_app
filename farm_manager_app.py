import streamlit as st
import sqlite3
from datetime import datetime, timedelta
from fpdf import FPDF
from io import BytesIO
import qrcode

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
    # MAIN DASHBOARD
    # -------------------------
    st.header("Dashboard")
    
    # Show alerts for harvest due soon
    st.subheader("Harvest Alerts")
    today = datetime.now().date()
    c.execute("SELECT c.item_name, s.site_name, c.expected_harvest FROM crops c JOIN sites s ON c.site_id=s.id WHERE c.actual_harvest IS NULL")
    crops_due = c.fetchall()
    for crop in crops_due:
        harvest_date = datetime.strptime(crop[2], "%Y-%m-%d").date()
        days_left = (harvest_date - today).days
        if days_left <= 5:
            st.warning(f"{crop[0]} at {crop[1]} ready for harvest in {days_left} days (Expected {harvest_date})")

    # Stock / Inventory summary
    st.subheader("Current Stock / Inventory")
    c.execute("SELECT item_name, SUM(yield_amount) FROM crops WHERE actual_harvest IS NOT NULL GROUP BY item_name")
    stock = c.fetchall()
    for s_item in stock:
        st.write(f"{s_item[0]}: {s_item[1]} units available for sale")

    # Revenue summary
    st.subheader("Revenue Summary")
    c.execute("SELECT s.site_name, SUM(sa.total) FROM sales sa JOIN sites s ON sa.site_id=s.id GROUP BY s.site_name")
    revenues = c.fetchall()
    for rev in revenues:
        st.write(f"{rev[0]}: ${rev[1] or 0:.2f}")

    # -------------------------
    # POS - Sell Items
    # -------------------------
    st.subheader("POS - Sell Items")

    # Load sites for POS (only markets)
    c.execute("SELECT id, site_name, site_type FROM sites WHERE site_type='market'")
    sites = c.fetchall()
    if not sites:
        st.warning("No market sites found. Add at least one site of type 'market' first.")
    else:
        site_dict = {f"{s[1]} ({s[2]})": s[0] for s in sites}
        selected_site_name = st.selectbox("Select Sale Site", list(site_dict.keys()))
        selected_site_id = site_dict[selected_site_name]

        # Cart
        if "cart" not in st.session_state:
            st.session_state.cart = []

        with st.expander("Add Item to Cart"):
            item_name = st.text_input("Item Name", key="item_name")
            qty = st.number_input("Quantity", min_value=1, value=1, key="qty")
            unit = st.text_input("Unit", value="pcs", key="unit")
            price = st.number_input("Price per Unit", min_value=0.0, value=0.0, format="%.2f", key="price")
            if st.button("Add to Cart"):
                st.session_state.cart.append({
                    "item_name": item_name,
                    "qty": qty,
                    "unit": unit,
                    "price_per_unit": price
                })

        st.write("Cart:", st.session_state.cart)

        # Payment
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
                # Save sale
                c.execute("INSERT INTO sales (site_id, date, payment_type, cash_given, change_due, total, notes) VALUES (?,?,?,?,?,?,?)",
                          (selected_site_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), payment_type, cash_given, change_due, total, receipt_notes))
                sale_id = c.lastrowid

                for it in st.session_state.cart:
                    c.execute("INSERT INTO sale_items (sale_id, item_name, qty, unit, price_per_unit) VALUES (?,?,?,?,?)",
                              (sale_id, it["item_name"], it["qty"], it["unit"], it["price_per_unit"]))
                conn.commit()

                # -------------------------
                # Modern PDF Receipt
                # -------------------------
                pdf_bytes = BytesIO()
                pdf = FPDF(orientation='P', unit='mm', format='A4')
                pdf.add_page()
                pdf.set_auto_page_break(auto=True, margin=15)

                # Branding Header
                pdf.set_font("Arial", "B", 18)
                pdf.set_text_color(34, 139, 34)
                pdf.cell(0, 10, f"{selected_site_name}", ln=1, align="C")
                pdf.set_font("Arial", "", 12)
                pdf.set_text_color(0, 0, 0)
                pdf.ln(5)

                # Receipt Info
                pdf.set_font("Arial", "B", 14)
                pdf.cell(0, 6, f"Receipt #{sale_id} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=1)
                pdf.ln(3)

                # Table Header
                pdf.set_font("Arial", "B", 12)
                pdf.set_fill_color(34, 139, 34)
                pdf.set_text_color(255, 255, 255)
                pdf.cell(100, 8, "Item", 1, 0, "C", fill=True)
                pdf.cell(30, 8, "Qty", 1, 0, "C", fill=True)
                pdf.cell(30, 8, "Unit", 1, 0, "C", fill=True)
                pdf.cell(30, 8, "Price", 1, 1, "C", fill=True)

                # Table Rows
                pdf.set_font("Arial", "", 12)
                pdf.set_text_color(0, 0, 0)
                fill = False
                for it in st.session_state.cart:
                    item_name_safe = it["item_name"].encode('latin-1', 'replace').decode('latin-1')
                    pdf.set_fill_color(240, 248, 255)
                    pdf.cell(100, 6, item_name_safe, 1, 0, "L", fill=fill)
                    pdf.cell(30, 6, str(it["qty"]), 1, 0, "C", fill=fill)
                    pdf.cell(30, 6, it["unit"], 1, 0, "C", fill=fill)
                    pdf.cell(30, 6, f"${it['price_per_unit']:.2f}", 1, 1, "R", fill=fill)
                    fill = not fill

                # Totals
                pdf.ln(2)
                pdf.set_font("Arial", "B", 12)
                pdf.cell(0, 6, f"Subtotal: ${subtotal:.2f}", ln=1)
                pdf.cell(0, 6, f"Tax: ${tax:.2f}", ln=1)
                pdf.cell(0, 6, f"Total: ${total:.2f}", ln=1)
                pdf.cell(0, 6, f"Payment type: {payment_type}", ln=1)
                if payment_type == "Cash":
                    pdf.cell(0, 6, f"Cash given: ${cash_given:.2f}", ln=1)
                    pdf.cell(0, 6, f"Change due: ${change_due:.2f}", ln=1)

                # Notes
                if receipt_notes:
                    notes_safe = receipt_notes.encode('latin-1', 'replace').decode('latin-1')
                    pdf.multi_cell(0, 6, f"Notes: {notes_safe}")

                # QR Code
                qr = qrcode.QRCode(version=1, box_size=2, border=1)
                qr.add_data(f"Receipt#{sale_id}")
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                qr_bytes = BytesIO()
                img.save(qr_bytes, format='PNG')
                qr_bytes.seek(0)
                pdf.image(qr_bytes, x=160, y=10, w=30)

                pdf.output(pdf_bytes)
                pdf_bytes.seek(0)
                st.download_button("Download Receipt (PDF)", pdf_bytes, file_name=f"receipt_{sale_id}.pdf")
                st.success(f"Sale completed (ID {sale_id})")

                # Reset cart after sale
                st.session_state.cart = []

    # -------------------------
    # Optional: CSV export of crops / sales
    # -------------------------
    st.subheader("Export Data")
    if st.button("Export Crops to CSV"):
        c.execute("SELECT * FROM crops")
        data = c.fetchall()
        import pandas as pd
        df = pd.DataFrame(data, columns=[desc[0] for desc in c.description])
        csv_bytes = df.to_csv(index=False).encode('utf-8')
        st.download_button("Download Crops CSV", csv_bytes, "crops.csv", "text/csv")

    if st.button("Export Sales to CSV"):
        c.execute("SELECT * FROM sales")
        data = c.fetchall()
        df = pd.DataFrame(data, columns=[desc[0] for desc in c.description])
        csv_bytes = df.to_csv(index=False).encode('utf-8')
        st.download_button("Download Sales CSV", csv_bytes, "sales.csv", "text/csv")
