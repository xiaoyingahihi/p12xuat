import streamlit as st
import easyocr
import cv2
import numpy as np
import re
import os
import pandas as pd
from io import BytesIO

# --- 1. CẤU HÌNH GIAO DIỆN ---
st.set_page_config(page_title="P12 Trích Xuất Phiếu Cân", layout="wide")
st.title("🚛 Hệ Thống Trích Xuất Phiếu Cân")

# Session state
if 'data_history' not in st.session_state:
    st.session_state.data_history = []
if 'last_processed_file' not in st.session_state:
    st.session_state.last_processed_file = None
if 'current_results' not in st.session_state:
    st.session_state.current_results = None

# --- LOAD MODEL (CACHE) ---
@st.cache_resource
def load_ai_model():
    return easyocr.Reader(['vi', 'en'], gpu=False, verbose=False)

reader = load_ai_model()

# --- OCR CACHE ---
@st.cache_data(show_spinner=False)
def run_ocr_cached(img_array):
    return reader.readtext(img_array)

# --- LOGIC TRÍCH XUẤT ---
def intelligent_extract_logic(results):
    raw_texts = [res[1].strip() for res in results]
    full_content = " ".join(raw_texts).upper()

    data = {}

    dates = re.findall(r'\d{2}/\d{2}/\d{4}', full_content)

    data["COMPANY"] = raw_texts[0]
    data["ADDRESS"] = raw_texts[1] if len(raw_texts) > 1 else "N/A"
    #
    phones = re.findall(r'\(\+84\)\d+-\d+-\d+', full_content)
    data["TEL"] = phones[0] if len(phones) > 0 else "N/A"
    data["FAX"] = phones[1] if len(phones) > 1 else "N/A"
    #
    serial = re.search(r'CSVC[0-9OQ]{4,}', full_content)
    data["SERIAL_NO"] = serial.group(0).replace('O', '0').replace('Q', '0') if serial else "N/A"
    #
    truck = re.search(r'(\d{2}[A-Z]\d{5,6})', full_content)
    data["TRUCK_NO"] = truck.group(1) if truck else "N/A"
    #
    for i, txt in enumerate(raw_texts):
        txt_up = txt.upper()

        if "CARGO TYPE" in txt_up and i + 1 < len(raw_texts):
            data["CARGO_TYPE"] = raw_texts[i+1]

        if "PIC NAME" in txt_up and i + 1 < len(raw_texts):
            data["PIC_NAME"] = raw_texts[i+1].replace('l','1').replace('I','1')
    #
    data["WEIGHT DATE"] = dates[0] if dates else "N/A"

    full_content = full_content.replace('.', ':')
    times = re.findall(r'\d{2}:\d{2}:\d{2}', full_content)
    data["IN_TIME"] = times[0] if len(times) > 0 else "N/A"
    data["OUT_TIME"] = times[1] if len(times) > 1 else "N/A"
    #

    weights = re.findall(r'(\d{1,3}[,.]\d{3})', full_content)
    if len(weights) >= 3:
        data["IN_WEIGHT"] = weights[0]
        data["OUT_WEIGHT"] = weights[1]
        data["NET_WEIGHT"] = weights[2]
    else:
        data["IN_WEIGHT"] = data["OUT_WEIGHT"] = data["NET_WEIGHT"] = "N/A"

    for i, txt in enumerate(raw_texts):
        txt_up = txt.upper()
        if "WEIGH OPERATOR" in txt_up:

            candidates = []

            # lấy i-1 nếu có
            if i - 1 >= 0:
                candidates.append(raw_texts[i - 1])

            # lấy i+1 nếu có
            if i + 1 < len(raw_texts):
                candidates.append(raw_texts[i + 1])

            # chọn cái có độ dài lớn nhất
            if candidates:
                data["WEIGH OPERATOR"] = max(candidates, key=lambda x: len(x.strip())).strip()
            else:
                data["WEIGH OPERATOR"] = "N/A"

            break
    return data

# --- UI ---
uploaded_file = st.sidebar.file_uploader("Chọn ảnh phiếu cân", type=["jpg", "png", "jpeg"])

if uploaded_file is not None:
    file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
    img_bgr = cv2.imdecode(file_bytes, 1)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🖼️ Ảnh Đầu Vào")
        img_org = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(img_gray, (5,5),0)
        thresh = cv2.adaptiveThreshold(blur,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,11,2)
        st.image(img_org, width='stretch')

    with col2:
        st.subheader("📊 Kết quả trích xuất")

        with st.spinner('Hệ thống đang quét...'):

            # ⚡ Chỉ OCR khi file mới
            if st.session_state.last_processed_file != uploaded_file.name:
                results = run_ocr_cached(img_bgr.copy())
                st.session_state.current_results = results
                st.session_state.last_processed_file = uploaded_file.name
            else:
                results = st.session_state.current_results

            with st.expander("Nội Dung Quét (Thô)"):
                for res in results:
                    st.write(res[1])

            data = intelligent_extract_logic(results)

            for k, v in data.items():
                st.success(f"**{k}**: {v}")

            if st.button("➕ Thêm vào danh sách chờ xuất Excel"):
                st.session_state.data_history.append(data)
                st.toast("Đã thêm vào danh sách!", icon="✅")

# --- EXPORT EXCEL ---
st.divider()
st.subheader("📋 Danh sách phiếu đã quét")

if st.session_state.data_history:
    df = pd.DataFrame(st.session_state.data_history)
    st.dataframe(df, width='stretch')

    def to_excel(df):
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Sheet1')
        return output.getvalue()

    excel_data = to_excel(df)

    st.download_button(
        label="📥 TẢI FILE EXCEL (.xlsx)",
        data=excel_data,
        file_name='bao_cao_can_xe.xlsx',
        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

    if st.button("🗑️ Xóa hết danh sách"):
        st.session_state.data_history = []
        st.rerun()
else:
    st.write("Chưa có dữ liệu nào được lưu.")
                                     
