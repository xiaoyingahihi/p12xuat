import streamlit as st
import easyocr
import cv2
import numpy as np
import re
import pandas as pd
from io import BytesIO
import requests

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

#giam phan giai
def preprocess_image(img):
    h, w = img.shape[:2]

    # 1. Resize nhỏ lại (giảm tải)
    max_w = 960
    if w > max_w:
        ratio = max_w / w
        img = cv2.resize(img, (int(w * ratio), int(h * ratio)))

    # 2. Grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 3. Tăng contrast mạnh hơn (CLAHE)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8,8))
    gray = clahe.apply(gray)

    # 4. Blur nhẹ
    blur = cv2.GaussianBlur(gray, (3, 3), 0)

    # 5. Adaptive threshold (giữ chữ tốt hơn)
    thresh = cv2.adaptiveThreshold(
        blur,
        255,
        cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY,
        11, 2
    )

    # 6. Làm chữ đậm hơn
    kernel = np.ones((1,1), np.uint8)
    dilate = cv2.dilate(thresh, kernel, iterations=1)

    return dilate

# --- OCR CACHE ---
@st.cache_data(show_spinner=False)
def run_ocr_cached(img_array):
    return reader.readtext(
        img_array,
        detail=1,
        paragraph=False,
        batch_size=1
    )

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

    # giới hạn size
    if uploaded_file.size > 5 * 1024 * 1024:
        st.error("Ảnh quá nặng (>5MB)")
        st.stop()

    file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
    img_bgr = cv2.imdecode(file_bytes, 1)

    img_processed = preprocess_image(img_bgr.copy())

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🖼️ Ảnh gốc")
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        st.image(img_rgb, width='stretch')

    with col2:
        st.subheader("📊 Kết quả AI")

        with st.spinner('Đang quét dữ liệu...'):

            if st.session_state.last_processed_file != uploaded_file.name:
                results = run_ocr_cached(img_processed)
                st.session_state.current_results = results
                st.session_state.last_processed_file = uploaded_file.name
            else:
                results = st.session_state.current_results

            with st.expander("OCR Raw"):
                for res in results:
                    st.write(res[1])

            data = intelligent_extract_logic(results)

            for k, v in data.items():
                st.success(f"**{k}**: {v}")

            # --- API GOOGLE SHEET ---
            API_URL = "YOUR_WEB_APP_URL"

            if st.button("➕ Lưu + Đẩy lên Cloud"):
                st.session_state.data_history.append(data)

                try:
                    res = requests.post(API_URL, json=data, timeout=5)
                    if res.status_code == 200:
                        st.toast("Đã lưu + gửi cloud!", icon="🚀")
                    else:
                        st.warning("Gửi API lỗi")
                except:
                    st.warning("Không kết nối được API")

# --- EXPORT ---
st.divider()
st.subheader("📋 Danh sách phiếu")

if st.session_state.data_history:
    df = pd.DataFrame(st.session_state.data_history)
    st.dataframe(df, width='stretch')

    def to_excel(df):
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        return output.getvalue()

    st.download_button(
        label="📥 Tải Excel",
        data=to_excel(df),
        file_name='bao_cao_can_xe.xlsx'
    )

    if st.button("🗑️ Xóa hết"):
        st.session_state.data_history = []
        st.rerun()
else:
    st.write("Chưa có dữ liệu")
