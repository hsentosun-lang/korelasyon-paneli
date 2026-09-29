import streamlit as st
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from supabase import create_client

st.set_page_config(page_title="Finansal Korelasyon Paneli", layout="wide")

@st.cache_resource
def init_supabase():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_supabase()

st.title("📈 30 Günlük Günlük Getiri Korelasyon Paneli")

# YAN MENÜ: ENSTRÜMAN YÖNETİMİ
st.sidebar.header("⚙️ Enstrüman Yönetimi")
with st.sidebar.expander("➕ Yeni Enstrüman Ekle"):
    new_symbol = st.text_input("Yahoo Symbol (Örn: GARAN.IS)", "").strip().upper()
    new_name = st.text_input("Görünen İsim (Örn: Garanti)", "").strip()
    new_cat = st.selectbox("Kategori", ["BIST", "ABD", "Kripto", "Emtia", "Diğer"])
    
    if st.button("Sisteme Ekle"):
        if new_symbol and new_name:
            try:
                supabase.table('assets').insert({
                    'symbol': new_symbol, 'display_name': new_name, 'category': new_cat, 'is_active': True
                }).execute()
                st.sidebar.success(f"{new_name} eklendi! Sonraki saatlik çalıştırmada matrise girecek.")
            except:
                st.sidebar.error("Ekleme başarısız.")

# GÖRÜNÜM SEÇİMİ
st.sidebar.header("📊 Görünüm")
view_mode = st.sidebar.radio("Matris Tipi:", ["Gün İçi Anlık Rolling (31. Gün)", "Geçmiş Gün Sonu (EOD) Kapanışları"])

if view_mode == "Gün İçi Anlık Rolling (31. Gün)":
    resp = supabase.table('correlation_matrix').select('*').eq('window_type', 'INTRADAY_HOURLY').order('calculated_at', desc=True).limit(1).execute()
else:
    resp = supabase.table('correlation_matrix').select('*').eq('window_type', 'DAILY_EOD').order('calculated_at', desc=True).limit(30).execute()

if resp.data:
    if view_mode == "Gün İçi Anlık Rolling (31. Gün)":
        latest = resp.data[0]
        st.caption(f"🕐 Son Anlık Güncelleme (UTC): **{latest['calculated_at']}**")
        corr_df = pd.DataFrame(latest['data'])
    else:
        eod_dates = [item['calculated_at'][:10] for item in resp.data]
        selected_date = st.sidebar.selectbox("Tarih Seçin:", eod_dates)
        selected_data = next(item for item in resp.data if item['calculated_at'].startswith(selected_date))
        st.caption(f"🔒 **{selected_date}** Gün Sonu Matrisi")
        corr_df = pd.DataFrame(selected_data['data'])

    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader("🔥 Getiri Korelasyon Isı Haritası")
        fig, ax = plt.subplots(figsize=(10, 7))
        sns.heatmap(corr_df, annot=True, cmap='vlag', vmin=-1, vmax=1, fmt=".2f", linewidths=.5, ax=ax)
        plt.xticks(rotation=45, ha='right')
        st.pyplot(fig)
    with col2:
        st.subheader("📋 Matris Verileri")
        st.dataframe(corr_df, use_container_width=True, height=450)
else:
    st.info("Veri bekleniyor... Zamanlayıcının ilk çalışmasını bekleyin.")