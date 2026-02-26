import plotly.express as px
import streamlit as st
import sqlite3
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from datetime import date, datetime, timedelta
import os
import psycopg2 # YENİ BULUT KÜTÜPHANEMİZ
from supabase import create_client
import numpy as np
import requests
import xml.etree.ElementTree as ET

# --- KULLANICI DOĞRULAMA (AUTH) AYARLARI ---
# Bu satır kodun en üstünde olmalı!
st.set_page_config(page_title="Portföyüm Pro", layout="wide", initial_sidebar_state="expanded")

# Secrets'tan bilgileri çekiyoruz
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)

# Kullanıcı oturumunu kontrol etme
if "user" not in st.session_state:
    st.session_state.user = None

def login_page():
    st.title("💎 Portföyüm Pro'ya Hoş Geldiniz")
    tab1, tab2 = st.tabs(["Giriş Yap", "Hesap Oluştur"])
    
    with tab1:
        email = st.text_input("E-posta", key="login_email")
        password = st.text_input("Şifre", type="password", key="login_pass")
        if st.button("Giriş"):
            try:
                res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                st.session_state.user = res.user
                st.rerun()
            except Exception:
                st.error("Giriş başarısız: E-posta veya şifre hatalı.")

    with tab2:
        new_email = st.text_input("Yeni E-posta", key="reg_email")
        new_password = st.text_input("Şifre (En az 6 karakter)", type="password", key="reg_pass")
        if st.button("Kayıt Ol"):
            try:
                supabase.auth.sign_up({"email": new_email, "password": new_password})
                st.success("Hesap oluşturuldu! Şimdi 'Giriş Yap' sekmesinden girebilirsiniz.")
            except Exception:
                st.error("Kayıt hatası: Bu e-posta zaten kullanımda olabilir.")

# --- ANA KONTROL MEKANİZMASI ---
if st.session_state.user is None:
    login_page()
    st.stop() # Giriş yapılmadıysa kodun geri kalanını çalıştırma!

user_id = st.session_state.user.id # Artık her yerde bu ID'yi kullanacağız

# =============================================================================
# BULUT VERİTABANI BAĞLANTISI (SUPABASE)
# =============================================================================
def get_db_connection():
    return psycopg2.connect(st.secrets["DB_URL"])

@st.cache_resource # EKLENEN SİHİRLİ KOD: Bu işlem sadece 1 kere çalışır, hızı artırır!
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("CREATE TABLE IF NOT EXISTS varliklar (id SERIAL PRIMARY KEY, tur TEXT, sembol TEXT, miktar REAL, ort_maliyet REAL, guncel_fiyat REAL, user_id UUID)")
    cursor.execute("CREATE TABLE IF NOT EXISTS islemler (id SERIAL PRIMARY KEY, sembol TEXT, islem_tipi TEXT, miktar REAL, fiyat REAL, tarih TEXT, user_id UUID)")
    cursor.execute("CREATE TABLE IF NOT EXISTS hedefler (id SERIAL PRIMARY KEY, ad TEXT, tutar REAL, user_id UUID)")
    cursor.execute("CREATE TABLE IF NOT EXISTS takip_listesi (sembol TEXT, isim TEXT, kisa_kod TEXT)")
    
    cursor.execute("SELECT count(*) FROM takip_listesi")
    if cursor.fetchone()[0] == 0:
        d = [
            ("USDTRY=X", "DOLAR/TL", "USD"), 
            ("EURTRY=X", "EURO/TL", "EUR"), 
            ("GRAM-ALTIN", "GRAM ALTIN", "GAU"), 
            ("GRAM-GUMUS", "GRAM GÜMÜŞ", "GÜMÜŞ"),
            ("GRAM-PLATIN", "GRAM PLATİN", "PLATİN"),
            ("GC=F", "ONS ALTIN", "ONS-ALTIN"),
            ("SI=F", "ONS GÜMÜŞ", "ONS-GÜMÜŞ"),
            ("PL=F", "ONS PLATİN", "ONS-PLATİN"),
            ("XU100.IS", "BIST 100", "BIST"), 
            ("BTC-USD", "BITCOIN", "BTC")
        ]
        cursor.executemany("INSERT INTO takip_listesi VALUES (%s,%s,%s)", d)
    
    conn.commit()
    conn.close()
    
init_db()

# =============================================================================
# VERİ ÇEKME VE HESAPLAMA MOTORU (FİZİKİ ALTIN DAHİL)
# =============================================================================
@st.cache_data(ttl=60)
def veri_getir(sembol):
    try:
        data = yf.Ticker(sembol).history(period="5d")
        if not data.empty:
            return float(data['Close'].iloc[-1])
        return 0.0
    except:
        return 0.0

def fiyatlari_hesapla(serbest_altin_girdisi):
    usd = veri_getir("USDTRY=X")
    if usd == 0: usd = 1.0 
    
    ons_altin = veri_getir("GC=F")
    ons_gumus = veri_getir("SI=F")
    ons_platin = veri_getir("PL=F")

    has_altin_banka = (ons_altin * usd) / 31.1035
    gumus_tl = (ons_gumus * usd) / 31.1035
    platin_tl = (ons_platin * usd) / 31.1035

    try:
        has_altin_serbest = float(str(serbest_altin_girdisi).replace(".", "").replace(",", "."))
        if has_altin_serbest <= 0: has_altin_serbest = has_altin_banka
    except:
        has_altin_serbest = has_altin_banka

    return usd, has_altin_banka, has_altin_serbest, gumus_tl, platin_tl

def guncel_fiyat_bul(sembol, fiyatlar):
    usd, has_altin_banka, has_altin_serbest, gumus_tl, platin_tl = fiyatlar
    
    if sembol == "GRAM-ALTIN": return has_altin_banka
    elif sembol == "GRAM-ALTIN-S": return has_altin_serbest
    elif sembol == "GRAM-ALTIN-22": return has_altin_serbest * 0.916
    elif sembol == "CEYREK-ALTIN": return has_altin_serbest * 1.6065
    elif sembol == "YARIM-ALTIN": return has_altin_serbest * 3.2130
    elif sembol == "TAM-ALTIN": return has_altin_serbest * 6.4260
    elif sembol == "ATA-ALTIN": return has_altin_serbest * 6.6080
    elif sembol == "GRAM-GUMUS": return gumus_tl
    elif sembol == "GRAM-PLATIN": return platin_tl 
    else: return veri_getir(sembol)

# =============================================================================
# MODERNİZE EDİLMİŞ SOL MENÜ (SIDEBAR) TASARIMI
# =============================================================================

# Menüye özel canlandırıcı CSS dokunuşları
st.sidebar.markdown("""
<style>
    /* Sidebar içeriğini en yukarı çekme */
    [data-testid="stSidebarContent"] {
        padding-top: 0rem !important;
    }
    
    /* Menü Başlığı Tasarımı */
    .sidebar-title {
        font-size: 22px !important;
        font-weight: 800 !important;
        color: #ffffff !important;
        text-align: center;
        margin-top: -20px; /* Başlığı daha da yukarı çeker */
        margin-bottom: 20px;
        padding: 12px;
        background: linear-gradient(90deg, #1e3a8a, #3b82f6);
        border-radius: 0px 0px 15px 15px; /* Sadece alt köşeleri yuvarlatır */
        box-shadow: 0 4px 15px rgba(0,0,0,0.3);
    }
    
    /* Menü Seçenekleri Animasyonu */
    div[class*="stRadio"] label {
        transition: all 0.3s ease-in-out;
        padding: 8px 12px !important;
        border-radius: 10px !important;
        margin-bottom: 5px;
    }
    
    div[class*="stRadio"] label:hover {
        transform: translateX(10px); /* Sağa kayma animasyonu */
        background-color: rgba(59, 130, 246, 0.15) !important;
        color: #3b82f6 !important;
    }

    /* Çıkış Butonu Tasarımı */
    .stButton>button[kind="secondary"] {
        width: 100%;
        border-radius: 15px;
        border: 1px solid #ef4444;
        color: #ef4444;
        transition: 0.3s;
        font-weight: bold;
    }
    .stButton>button[kind="secondary"]:hover {
        background-color: #ef4444;
        color: white;
        box-shadow: 0 4px 12px rgba(239, 68, 68, 0.4);
    }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    # 1. En Tepe: Sade Başlık
    st.markdown('<div class="sidebar-title">💎 PORTFÖYÜM</div>', unsafe_allow_html=True)
    
    # 2. Orta: Sayfa Gezinme Menüsü
    menu = st.radio(
        "📍 Hızlı Erişim",
        ["📊 Genel Özet", "🔥 Isı Haritası", "💵 Varlıklar & İşlemler", "📈 Piyasa Analizi", "🧮 Hesap Araçları", "📅 Piyasa Takvimi"],
        index=0,
        label_visibility="collapsed" # Gereksiz 'Hızlı Erişim' yazısını gizler
    )
    
    st.markdown("---")
    
    # 3. Alt Kısım: Ayarlar ve Fiyat Girişi
    st.subheader("⚙️ Sistem Ayarları")
    serbest_altin = st.text_input("Serbest Piyasa Gr Altın (₺):", placeholder="Örn: 3150")
    fiyatlar = fiyatlari_hesapla(serbest_altin)

    if st.button("🔄 Fiyatları Güncelle", use_container_width=True):
        with st.spinner("Güncelleniyor..."):
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT sembol FROM varliklar WHERE user_id=%s", (user_id,))
            for (s,) in cursor.fetchall():
                yeni_f = guncel_fiyat_bul(s, fiyatlar)
                if yeni_f > 0:
                    cursor.execute("UPDATE varliklar SET guncel_fiyat=%s WHERE sembol=%s AND user_id=%s", (float(yeni_f), s, user_id))
            conn.commit()
            conn.close()
        st.success("Veriler yenilendi!")

    # 4. En Alt: Güvenli Çıkış
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🚪 Güvenli Çıkış", type="secondary", use_container_width=True):
        st.session_state.user = None
        st.rerun()

# =============================================================================
# HABER BANDI (MARQUEE) VE CSS TASARIMLARI
# =============================================================================
@st.cache_data(ttl=300)
def haberleri_getir_marquee():
    try:
        url = "https://www.bloomberght.com/rss"
        resp = requests.get(url, timeout=5)
        resp.encoding = 'utf-8'
        root = ET.fromstring(resp.content)
        
        haberler_html = ""
        for item in root.findall('./channel/item')[:15]:
            title = item.find('title').text
            link = item.find('link').text
            haberler_html += f"<a href='{link}' class='news-link' target='_blank'> 🔴 {title}</a>"
        return haberler_html
    except:
        return "<span class='news-link'>Haberler alınamadı...</span>"

haber_metni = haberleri_getir_marquee()

footer_css = f"""
<style>
    .block-container {{ padding-bottom: 80px !important; padding-top: 2rem; }}
    .news-footer {{ position: fixed; left: 0; bottom: 0; width: 100%; background-color: #ffffff; border-top: 4px solid #e60000; display: flex; align-items: center; z-index: 99999; font-family: 'Segoe UI', Tahoma, sans-serif; box-shadow: 0 -2px 10px rgba(0,0,0,0.1); }}
    .news-label {{ background-color: #e60000; color: white; padding: 12px 20px; font-weight: bold; font-size: 15px; white-space: nowrap; z-index: 100000; box-shadow: 2px 0 5px rgba(0,0,0,0.1); text-transform: uppercase; }}
    .marquee-container {{ overflow: hidden; white-space: nowrap; width: 100%; padding-left: 10px; }}
    .marquee-content {{ display: inline-block; animation: marquee 80s linear infinite; }}
    .marquee-content:hover {{ animation-play-state: paused; }}
    @keyframes marquee {{ 0% {{ transform: translateX(100%); }} 100% {{ transform: translateX(-100%); }} }}
    .news-link {{ color: #1a1a1a; text-decoration: none; margin-right: 50px; font-size: 16px; font-weight: 600; transition: color 0.3s; }}
    .news-link:hover {{ color: #e60000; }}
</style>
<div class="news-footer">
    <div class="news-label">📰 SON DAKİKA</div>
    <div class="marquee-container">
        <div class="marquee-content">{haber_metni}</div>
    </div>
</div>
"""
st.markdown(footer_css, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# SAYFA 1: GENEL ÖZET
# -----------------------------------------------------------------------------
if menu == "📊 Genel Özet":
    st.title("Portföy Analizi")

    # --- HAFIZA KORUMASI (Hata Almamak İçin) ---
    if 'takip_listesi_bant' not in st.session_state:
        st.session_state.takip_listesi_bant = {
            "Dolar/TL": "USDTRY=X", "Euro/TL": "EURTRY=X", 
            "Gram Altın": "GRAM_ALTIN", "Bitcoin": "BTC-USD"
        }
    if 'sag_panel_listesi' not in st.session_state:
        st.session_state.sag_panel_listesi = {
            "BIST 100": "XU100.IS", "S&P 500": "^GSPC",
            "Gram Altın": "GRAM_ALTIN", "Dolar/TL": "USDTRY=X", "Bitcoin": "BTC-USD"
        }

    # 1. YAHOO FİNANS CANLI ARAMA MOTORU
    @st.cache_data(ttl=3600)
    def yahoo_arama(kelime):
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={kelime}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        try:
            res = requests.get(url, headers=headers, timeout=5)
            quotes = res.json().get('quotes', [])
            sonuclar = {}
            for q in quotes:
                sembol = q.get('symbol')
                isim = q.get('shortname', '')
                borsa = q.get('exchDisp', '')
                if sembol: sonuclar[f"{sembol} - {isim} ({borsa})"] = sembol
            return sonuclar
        except:
            return {}

    # 2. VERİ ÇEKME MOTORU (KAYAN BANT İÇİN)
    @st.cache_data(ttl=300) 
    def dinamik_bant_verisi_cek(takip_sozlugu):
        sonuclar = []
        try: usd_fiyat = float(yf.Ticker("USDTRY=X").history(period="1d")['Close'].iloc[-1])
        except: usd_fiyat = 1.0 

        for ad, kod in takip_sozlugu.items():
            try:
                if kod == "GRAM_ALTIN":
                    f = (float(yf.Ticker("GC=F").history(period="1d")['Close'].iloc[-1]) / 31.1035) * usd_fiyat
                    sonuclar.append(f"🟡 GR ALTIN: {f:,.2f} ₺")
                elif kod == "GRAM_GUMUS":
                    f = (float(yf.Ticker("SI=F").history(period="1d")['Close'].iloc[-1]) / 31.1035) * usd_fiyat
                    sonuclar.append(f"🥈 GR GÜMÜŞ: {f:,.2f} ₺")
                elif kod == "GRAM_PLATIN":
                    f = (float(yf.Ticker("PL=F").history(period="1d")['Close'].iloc[-1]) / 31.1035) * usd_fiyat
                    sonuclar.append(f"💍 GR PLATİN: {f:,.2f} ₺")
                else:
                    f = float(yf.Ticker(kod).history(period="1d")['Close'].iloc[-1])
                    birim = "₺" if (".IS" in kod or "TRY" in kod) else "$"
                    if kod == "GC=F": ikon = "🏆"
                    elif kod == "SI=F": ikon = "⚙️"
                    elif kod == "PL=F": ikon = "💎"
                    elif "TRY" in kod: ikon = "💵"
                    elif "-USD" in kod: ikon = "🪙"
                    else: ikon = "📈"
                    kisa_ad = ad.split('-')[0].strip()[:15]
                    sonuclar.append(f"{ikon} {kisa_ad}: {f:,.2f} {birim}")
            except:
                sonuclar.append(f"⚠️ {ad[:10]}: Hata")
        return sonuclar

    # 3. KAYAN BANT ARAYÜZÜ (DİŞLİ ÇARK)
    col_bant, col_ayar = st.columns([12, 1])
    with col_ayar:
        with st.popover("⚙️"):
            st.markdown("### 🛠️ Bant Ayarları")
            
            st.markdown("**1. Gösterilenleri Çıkar**")
            aktif_secimler = st.multiselect(
                "Kaldırmak için çarpıya basın:",
                options=list(st.session_state.takip_listesi_bant.keys()),
                default=list(st.session_state.takip_listesi_bant.keys()),
                label_visibility="collapsed"
            )
            if len(aktif_secimler) != len(st.session_state.takip_listesi_bant):
                st.session_state.takip_listesi_bant = {k: st.session_state.takip_listesi_bant[k] for k in aktif_secimler}
                st.rerun()

            st.markdown("---")
            st.markdown("**2. Hızlı Ekle (Maden & Döviz)**")
            hazir_varliklar = {
                "Gram Altın": "GRAM_ALTIN", "Gram Gümüş": "GRAM_GUMUS", "Gram Platin": "GRAM_PLATIN",
                "Ons Altın": "GC=F", "Ons Gümüş": "SI=F", "Ons Platin": "PL=F",
                "Dolar/TL": "USDTRY=X", "Euro/TL": "EURTRY=X", "Sterlin/TL": "GBPTRY=X"
            }
            secili_hazir = st.selectbox("Listeden Seçin:", ["Seçiniz..."] + list(hazir_varliklar.keys()), key="sec_maden", label_visibility="collapsed")
            if secili_hazir != "Seçiniz...":
                if st.button("➕ Band'a Ekle", key="hizli_ekle_maden", use_container_width=True):
                    st.session_state.takip_listesi_bant[secili_hazir] = hazir_varliklar[secili_hazir]
                    st.rerun()

            st.markdown("---")
            st.markdown("**3. Hızlı Ekle (Kripto Para)**")
            kripto_varliklar = {
                "Bitcoin": "BTC-USD", "Ethereum": "ETH-USD", "Solana": "SOL-USD", "Avalanche": "AVAX-USD"
            }
            secili_kripto = st.selectbox("Kripto Seçin:", ["Seçiniz..."] + list(kripto_varliklar.keys()), key="sec_kripto", label_visibility="collapsed")
            if secili_kripto != "Seçiniz...":
                if st.button("➕ Kripto Ekle", key="hizli_ekle_kripto", use_container_width=True):
                    st.session_state.takip_listesi_bant[secili_kripto] = kripto_varliklar[secili_kripto]
                    st.rerun()

            st.markdown("---")
            st.markdown("**4. Hisse/Fon Ara**")
            arama_kelimesi = st.text_input("Şirket veya Fon Kodu:", placeholder="Örn: Tesla, AKBNK")
            if arama_kelimesi:
                bulunanlar = yahoo_arama(arama_kelimesi)
                if bulunanlar:
                    secilen = st.selectbox("Sonuçlar:", ["Lütfen Seçin..."] + list(bulunanlar.keys()))
                    if secilen != "Lütfen Seçin...":
                        if st.button("➕ Band'a Ekle", key="arama_ekle", use_container_width=True):
                            st.session_state.takip_listesi_bant[secilen.split('-')[0].strip()] = bulunanlar[secilen]
                            st.rerun()

    with col_bant:
        ticker_data = dinamik_bant_verisi_cek(st.session_state.takip_listesi_bant)
        if not ticker_data: ticker_data = ["Gösterilecek veri yok."]

        ticker_html = f"""
        <div style="background-color: #0e1117; padding: 0px 10px; border-radius: 5px; border: 1px solid #30333d; overflow: hidden; white-space: nowrap; height: 42px; display: flex; align-items: center;">
            <div style="display: inline-block; padding-left: 100%; animation: marquee 100s linear infinite; font-family: monospace; font-size: 16px; color: #00ffcc;">
                {" &nbsp;&nbsp;&nbsp;&nbsp; | &nbsp;&nbsp;&nbsp;&nbsp; ".join(ticker_data)}
            </div>
        </div>
        """
        st.markdown(ticker_html, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        
    # =========================================================================
    # ANA EKRAN: SOL KOLON (PORTFÖY) VE SAĞ KOLON (CANLI TABLO)
    # =========================================================================
    ana_kolon, sag_kolon = st.columns([3, 1], gap="large")

    with ana_kolon:
        conn = get_db_connection()
        query = "SELECT sembol, miktar, ort_maliyet, guncel_fiyat FROM varliklar WHERE miktar > 0 AND user_id = %s"
        df_varlik = pd.read_sql_query(query, conn, params=(user_id,))

        if df_varlik.empty:
            st.info("Portföyünüzde henüz varlık bulunmuyor. Yan menüden işlem ekleyerek başlayabilirsiniz!")
        else:
            df_varlik['Yatirim'] = df_varlik['miktar'] * df_varlik['ort_maliyet']
            df_varlik['Guncel'] = df_varlik['miktar'] * df_varlik['guncel_fiyat']
            df_varlik['Kar_Zarar'] = df_varlik['Guncel'] - df_varlik['Yatirim']
            df_varlik['Degisim_%'] = (df_varlik['Kar_Zarar'] / df_varlik['Yatirim']) * 100
            
            top_yatirim = df_varlik['Yatirim'].sum()
            top_guncel = df_varlik['Guncel'].sum()
            net_kz = top_guncel - top_yatirim
            yuzde_kz = (net_kz / top_yatirim * 100) if top_yatirim > 0 else 0 
              
            cc1, cc2, cc3 = st.columns(3)
            cc1.metric("💼 Yatırım", f"{top_yatirim:,.0f} ₺")
            cc2.metric("💎 Güncel", f"{top_guncel:,.0f} ₺")
            cc3.metric("🚀 Net K/Z", f"{net_kz:+,.0f} ₺", f"%{yuzde_kz:.2f}")
            
            st.write("---")
            df_gosterim = df_varlik.rename(columns={
                'sembol': 'Varlık',
                'miktar': 'Adet',
                'ort_maliyet': 'Maliyet',
                'guncel_fiyat': 'Fiyat',
                'Kar_Zarar': 'K/Z (₺)',
                'Degisim_%': 'Değişim (%)'
            })

            st.dataframe(df_gosterim.style.format({
                'Adet': '{:.2f}', 'Maliyet': '{:.2f} ₺', 
                'Fiyat': '{:.2f} ₺', 'Yatirim': '{:,.2f} ₺', 
                'Guncel': '{:,.2f} ₺', 'K/Z (₺)': '{:+,.2f} ₺', 'Değişim (%)': '%{:.2f}'
            }), use_container_width=True, hide_index=True)

            col_grafik, col_hedef = st.columns([2, 1])
            
            with col_grafik:
                st.subheader("Varlık Dağılımı")
                if 'Guncel' in df_varlik.columns:
                    df_pie = df_varlik.sort_values(by="Guncel", ascending=False).head(10)
                    fig = px.pie(
                        df_pie, values='Guncel', names='sembol', hole=0.4,
                        color_discrete_sequence=px.colors.qualitative.Pastel
                    )
                    fig.update_traces(textposition='inside', textinfo='percent', insidetextorientation='radial')
                    fig.update_layout(
                        margin=dict(t=10, b=10, l=10, r=10),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.0) 
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("Grafik için veri yok.")
                
            with col_hedef:
                st.subheader("🎯 Hedef")
                cursor = conn.cursor()
                cursor.execute("SELECT ad, tutar FROM hedefler WHERE user_id=%s LIMIT 1", (user_id,))
                hedef = cursor.fetchone()
                
                h_ad = hedef[0] if hedef else "Finansal Özgürlük"
                h_tutar = hedef[1] if hedef else 1000000
                
                ilerleme = (top_guncel / h_tutar) * 100
                if ilerleme > 100: ilerleme = 100 
                
                st.write(f"**{h_ad}** ({h_tutar:,.0f} ₺)")
                st.progress(int(ilerleme))
                st.write(f"%{ilerleme:.1f} Tamamlandı")
                
                with st.expander("✏️ Düzenle"):
                    with st.form("hedef_form"):
                        yeni_ad = st.text_input("Hedef Adı", value=h_ad)
                        yeni_tutar = st.number_input("Hedef Tutar", value=float(h_tutar), step=1000.0)
                        if st.form_submit_button("Kaydet"):
                            cursor.execute("DELETE FROM hedefler WHERE user_id=%s", (user_id,))
                            cursor.execute("INSERT INTO hedefler (ad, tutar, user_id) VALUES (%s, %s, %s)", (yeni_ad, yeni_tutar, user_id))
                            conn.commit()
                            st.rerun()
                            
        conn.close()

    # --- SAĞ PANEL KAPANMA SORUNUNU ÇÖZEN POPUP ---
    @st.dialog("⚙️ Sağ Tablo Ayarları")
    def tablo_ayarlari_popup():
        st.markdown("**1. Gösterilenler & Sıralama**")
        st.caption("💡 *İpucu: Bir varlığı en alta almak için önce çarpıya (X) basıp listeden silin, ardından alttaki menülerden tekrar ekleyin.*")
        
        aktif_tablo_secimleri = st.multiselect(
            "Kaldırmak için çarpıya basın:",
            options=list(st.session_state.sag_panel_listesi.keys()),
            default=list(st.session_state.sag_panel_listesi.keys()),
            key="tablo_sil_popup",
            label_visibility="collapsed"
        )
        
        # Sıralama veya silme işlemi yapıldıysa hafızayı güncelleyip tabloyu yeniler
        if list(aktif_tablo_secimleri) != list(st.session_state.sag_panel_listesi.keys()):
            st.session_state.sag_panel_listesi = {k: st.session_state.sag_panel_listesi[k] for k in aktif_tablo_secimleri}
            st.rerun()
            
        st.markdown("---")
        st.markdown("**2. Hızlı Ekle (Maden, Döviz, Kripto)**")
        hazir_tablo_varliklar = {
            "Gram Altın": "GRAM_ALTIN", "Gram Gümüş": "GRAM_GUMUS", "Gram Platin": "GRAM_PLATIN",
            "Ons Altın": "GC=F", "Ons Gümüş": "SI=F", "Ons Platin": "PL=F",
            "Dolar/TL": "USDTRY=X", "Euro/TL": "EURTRY=X", "Sterlin/TL": "GBPTRY=X", 
            "İsviçre Frangı": "CHFTRY=X", "Japon Yeni": "JPYTRY=X",
            "Bitcoin": "BTC-USD", "Ethereum": "ETH-USD", "Solana": "SOL-USD", 
            "Avalanche": "AVAX-USD", "Binance Coin": "BNB-USD", "Ripple (XRP)": "XRP-USD"
        }
        secili_hazir_t = st.selectbox("Listeden Seçin:", ["Seçiniz..."] + list(hazir_tablo_varliklar.keys()), key="tablo_hizli_popup", label_visibility="collapsed")
        if secili_hazir_t != "Seçiniz...":
            if st.button("➕ Tabloya Ekle", key="btn_tablo_hizli_popup", use_container_width=True):
                # Yeni eklenen her zaman en alta (sona) eklenir
                st.session_state.sag_panel_listesi[secili_hazir_t] = hazir_tablo_varliklar[secili_hazir_t]
                st.rerun()

        st.markdown("---")
        st.markdown("**3. Hisse/Fon Ara**")
        arama_tablo = st.text_input("Hisse/Fon Ara:", placeholder="Örn: AAPL, THYAO", key="tablo_ara_popup")
        if arama_tablo:
            bulunanlar_tablo = yahoo_arama(arama_tablo) 
            if bulunanlar_tablo:
                secilen_t = st.selectbox("Sonuçlar:", ["Lütfen Seçin..."] + list(bulunanlar_tablo.keys()), key="tablo_sonuc_popup")
                if secilen_t != "Lütfen Seçin...":
                    if st.button("➕ Tabloya Ekle", key="btn_tablo_ara_popup", use_container_width=True):
                        st.session_state.sag_panel_listesi[secilen_t.split('-')[0].strip()] = bulunanlar_tablo[secilen_t]
                        st.rerun()

    # --- SAĞ KOLON (TAM KOYU TASARIM - KÜÇÜLTÜLMÜŞ KOMPAKT FONT) ---
    with sag_kolon:
        # Başlık ve Çark
        baslik_alani, ayar_alani = st.columns([0.85, 0.15], gap="small", vertical_alignment="center")
        baslik_alani.markdown("<h3 style='margin:0; white-space:nowrap; font-size:20px;'>📊 Canlı Piyasa</h3>", unsafe_allow_html=True)
        
        if ayar_alani.button("⚙️", key="tablo_ayar_buton", help="Düzenle"):
            tablo_ayarlari_popup()

        @st.cache_data(ttl=300)
        def tablo_verisi_hazirla_html(sozluk):
            satirlar_html = ""
            try:
                usd_hist = yf.Ticker("USDTRY=X").history(period="5d")['Close']
            except:
                usd_hist = None
            
            for ad, kod in sozluk.items():
                try:
                    if kod in ["GRAM_ALTIN", "GRAM_GUMUS", "GRAM_PLATIN"]:
                        ons_kod = "GC=F" if kod == "GRAM_ALTIN" else ("SI=F" if kod == "GRAM_GUMUS" else "PL=F")
                        ons_data = yf.Ticker(ons_kod).history(period="5d")['Close']
                        df_ortak = pd.concat([ons_data, usd_hist], axis=1, keys=['ONS', 'USD']).ffill().dropna()
                        
                        if not df_ortak.empty:
                            bugun = (float(df_ortak['ONS'].iloc[-1]) * float(df_ortak['USD'].iloc[-1])) / 31.1035
                            if len(df_ortak) > 1:
                                dun = (float(df_ortak['ONS'].iloc[-2]) * float(df_ortak['USD'].iloc[-2])) / 31.1035
                            else:
                                dun = bugun
                        else:
                            bugun, dun = 0.0, 0.0
                    else:
                        fiyatlar = yf.Ticker(kod).history(period="5d")['Close'].dropna()
                        if not fiyatlar.empty:
                            bugun = float(fiyatlar.iloc[-1])
                            dun = float(fiyatlar.iloc[-2]) if len(fiyatlar) > 1 else bugun
                        else:
                            bugun, dun = 0.0, 0.0
                    
                    degisim_yuzde = ((bugun - dun) / dun) * 100 if dun > 0 else 0.0
                    renk = "#10b981" if degisim_yuzde > 0 else "#ef4444"
                    ok = "▲" if degisim_yuzde > 0 else "▼"

                    # DİKKAT: Fontlar 13px yapıldı. Padding'ler daraltıldı. white-space: nowrap eklendi.
                    satirlar_html += f'<tr style="border-bottom: 1px solid #2d3748;">'
                    satirlar_html += f'<td style="padding: 10px 5px; color: #e2e8f0; font-size: 13px; font-weight: 500; vertical-align: middle; white-space: nowrap;">{ad}</td>'
                    satirlar_html += f'<td style="padding: 10px 5px; color: #ffffff; font-weight: 600; text-align: right; font-size: 13px; vertical-align: middle; white-space: nowrap;">{bugun:,.2f}</td>'
                    satirlar_html += f'<td style="padding: 10px 5px; color: {renk}; font-weight: 600; text-align: right; font-size: 13px; vertical-align: middle; white-space: nowrap;">{ok} {abs(degisim_yuzde):.2f}%</td>'
                    satirlar_html += f'</tr>'
                except Exception as e:
                    satirlar_html += f'<tr style="border-bottom: 1px solid #2d3748;">'
                    satirlar_html += f'<td style="padding: 10px 5px; color: #e2e8f0; font-size: 13px; font-weight: 500; vertical-align: middle; white-space: nowrap;">{ad[:15]}</td>'
                    satirlar_html += f'<td style="padding: 10px 5px; color: #ffffff; font-weight: 600; text-align: right; font-size: 13px; vertical-align: middle; white-space: nowrap;">0.00</td>'
                    satirlar_html += f'<td style="padding: 10px 5px; color: #888888; font-weight: 600; text-align: right; font-size: 13px; vertical-align: middle; white-space: nowrap;">0.00%</td>'
                    satirlar_html += f'</tr>'
            return satirlar_html

        html_govde = tablo_verisi_hazirla_html(st.session_state.sag_panel_listesi)
        
        if html_govde:
            # Container padding 20'den 12'ye, başlıklar 13px'ten 11px'e düşürüldü.
            st.markdown(f"""<div style="background-color: #111827; padding: 12px; border-radius: 12px; border: 1px solid #1f2937; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.5); margin-top: 10px;">
<table style="width: 100%; border-collapse: collapse; font-family: inherit;">
<thead>
<tr style="border-bottom: 2px solid #374151; text-align: left;">
<th style="padding: 0px 5px 8px 5px; color: #a0aec0; font-size: 11px; font-weight: 600; text-transform: uppercase; white-space: nowrap;">Varlık</th>
<th style="padding: 0px 5px 8px 5px; color: #a0aec0; font-size: 11px; font-weight: 600; text-transform: uppercase; text-align: right; white-space: nowrap;">Fiyat</th>
<th style="padding: 0px 5px 8px 5px; color: #a0aec0; font-size: 11px; font-weight: 600; text-transform: uppercase; text-align: right; white-space: nowrap;">Değişim</th>
</tr>
</thead>
<tbody>
{html_govde}
</tbody>
</table>
</div>""", unsafe_allow_html=True)
        else:
            st.info("Tablo boş. Dişli çarktan veri ekleyin.")

# -----------------------------------------------------------------------------
# SAYFA 2: ISI HARİTASI
# -----------------------------------------------------------------------------
elif menu == "🔥 Isı Haritası":
    st.title("Portföy Isı Haritası")
    st.write("Varlıklarınızın anlık kar/zarar durumunu renklerle analiz edin.")
    
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT sembol, miktar, ort_maliyet, guncel_fiyat FROM varliklar WHERE miktar > 0", conn)
    conn.close()
    
    if df.empty:
        st.warning("Görüntülenecek veri bulunamadı.")
    else:
        df['Tutar'] = df['miktar'] * df['guncel_fiyat']
        df['KZ_TL'] = (df['guncel_fiyat'] - df['ort_maliyet']) * df['miktar']
        df['Yuzde'] = np.where(df['ort_maliyet'] > 0, ((df['guncel_fiyat'] - df['ort_maliyet']) / df['ort_maliyet']) * 100, 0.0)
        df = df.sort_values(by="Tutar", ascending=False)
        
        legend_html = """
        <div style='display: flex; justify-content: flex-end; align-items: center; margin-bottom: 20px;'>
            <span style='color: #ef4444; font-weight: bold; font-size: 12px; margin-right: 5px;'>ZARAR</span>
            <span style='color: #be123c; font-size: 18px;'>⬛</span>
            <span style='color: #059669; font-size: 18px;'>⬛</span>
            <span style='color: #10b981; font-weight: bold; font-size: 12px; margin-left: 5px;'>KAR</span>
        </div>
        """
        st.markdown(legend_html, unsafe_allow_html=True)
        
        sutun_sayisi = 4
        satirlar = df.to_dict('records')
        
        for i in range(0, len(satirlar), sutun_sayisi):
            grup = satirlar[i:i+sutun_sayisi]
            cols = st.columns(sutun_sayisi)
            
            for col, row in zip(cols, grup):
                y = row['Yuzde']
                if y >= 0:
                    ok = "▲"
                    if y >= 10: bg = "#059669"
                    elif y >= 3: bg = "#10b981"
                    else: bg = "#34d399"
                else:
                    ok = "▼"
                    if y <= -10: bg = "#be123c"
                    elif y <= -3: bg = "#e11d48"
                    else: bg = "#fb7185"
                
                isim = row['sembol']
                f_size = "14px" if len(isim) > 12 else "18px"
                
                kutu_html = f"""
                <div style="background-color: {bg}; padding: 20px; border-radius: 10px; color: white; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 15px;">
                    <div style="font-size: {f_size}; font-weight: bold; margin-bottom: 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="{isim}">{isim}</div>
                    <div style="font-size: 26px; font-weight: bold; margin-bottom: 10px;">{ok} %{abs(y):.2f}</div>
                    <div style="font-size: 16px; margin-top: 10px; font-weight: 500;">{row['Tutar']:,.0f} ₺</div>
                    <div style="font-size: 13px; opacity: 0.9; margin-top: 5px;">({row['KZ_TL']:+,.0f} ₺)</div>
                </div>
                """
                col.markdown(kutu_html, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# SAYFA 3: VARLIKLAR & İŞLEMLER
# -----------------------------------------------------------------------------
elif menu == "💵 Varlıklar & İşlemler":
    # 3 PANELLİ ANA EKRAN DÜZENİ İÇİN CSS
    st.markdown("""
    <style>
        [data-testid="column"]:nth-of-type(2) {
            background-color: #1a1a1a;
            border-left: 2px solid #333;
            padding: 0px 15px 15px 15px;
            border-radius: 5px;
            height: 85vh;
            overflow-y: auto;
            position: sticky;
            top: 3rem;
        }
        [data-testid="column"]:nth-of-type(2)::-webkit-scrollbar { display: none; }
        [data-baseweb="tab-list"] { background-color: #1a1a1a; gap: 5px; }
        [data-baseweb="tab"] { color: #aaaaaa !important; font-weight: bold; }
        [aria-selected="true"] { background-color: #dc2626 !important; color: white !important; border-radius: 3px; }
    </style>
    """, unsafe_allow_html=True)
    
    col_orta, col_sag = st.columns([3, 1.2], gap="large")
    
    with col_orta:
        st.title("Varlık & İşlem Yönetimi")
        
        hizli_varliklar = {
            "Manuel Giriş (Aşağıya Yazın)": "",
            "GRAM ALTIN (Serbest/Kuyumcu)": "GRAM-ALTIN-S",
            "ÇEYREK ALTIN": "CEYREK-ALTIN",
            "YARIM ALTIN": "YARIM-ALTIN",
            "TAM ALTIN": "TAM-ALTIN",
            "ATA (CUMHURİYET) ALTIN": "ATA-ALTIN",
            "22 AYAR BİLEZİK (Gr)": "GRAM-ALTIN-22-B",
            "14 AYAR BİLEZİK (Gr)": "GRAM-ALTIN-14",
            "22 AYAR GRAM (Gr)": "GRAM-ALTIN-22",
            "GRAM ALTIN (Banka/Ekran)": "GRAM-ALTIN",
            "GRAM GÜMÜŞ": "GRAM-GUMUS",
            "GRAM PLATİN": "GRAM-PLATIN",
            "ONS ALTIN ($)": "GC=F",
            "ONS GÜMÜŞ ($)": "SI=F",
            "ONS PLATİN ($)": "PL=F",
            "DOLAR (USD/TRY)": "USDTRY=X", 
            "EURO (EUR/TRY)": "EURTRY=X",
            "STERLİN (GBP/TRY)": "GBPTRY=X",
            "BITCOIN ($)": "BTC-USD",
            "ETHEREUM ($)": "ETH-USD"
        }

        with st.expander("➕ YENİ İŞLEM EKLE (Alış / Satış)", expanded=True):
            with st.form("islem_formu", clear_on_submit=True):
                c1, c2, c3 = st.columns([1, 2, 2])
                tip = c1.selectbox("İşlem Tipi", ["ALIS", "SATIS"])
                secilen_isim = c2.selectbox("Hızlı Seçim (Döviz/Maden)", list(hizli_varliklar.keys()))
                elle_giris = c3.text_input("Veya Hisse Kodu (Örn: AAPL, THYAO.IS)")
                
                c4, c5, c6 = st.columns([1, 2, 2])
                miktar = c5.number_input("Adet / Miktar", min_value=0.0000, format="%f", step=1.0)
                fiyat = c6.number_input("Birim Fiyat (₺)", min_value=0.00, format="%f", step=10.0)
                
                if st.form_submit_button("İşlemi Kaydet"):
                    # Sembol belirleme
                    if elle_giris.strip(): 
                        sembol = elle_giris.strip().upper()
                    else: 
                        sembol = hizli_varliklar[secilen_isim]
                        
                    # Hata kontrolleri
                    if not sembol: 
                        st.error("Lütfen listeden bir varlık seçin veya bir sembol yazın!")
                    elif miktar <= 0: 
                        st.error("Miktar 0'dan büyük olmalıdır.")
                    else:
                        # === BOŞLUKLARIN DÜZELTİLDİĞİ KISIM BURASI ===
                        maden_doviz_anahtarlar = ["USD", "EUR", "GBP", "CHF", "TRY", "JPY", "GRAM", "ALTIN", "CEYREK", "GUMUS", "PLATIN", "GC=F", "SI=F", "PL=F"]
                        tur = "Döviz/Emtia" if any(x in sembol for x in maden_doviz_anahtarlar) else "Hisse/Fon"
                        
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute("SELECT id, miktar, ort_maliyet FROM varliklar WHERE sembol=%s AND user_id=%s", (sembol, user_id))
                        mevcut = cursor.fetchone()
                        
                        if tip == "SATIS" and (not mevcut or mevcut[1] < miktar):
                            st.error("Hata: Yetersiz Bakiye! Portföyünüzde bu kadar varlık yok.")
                        else:
                            if tip == "ALIS":
                                if mevcut:
                                    v_id, esk_m, esk_mal = mevcut
                                    yeni_m = esk_m + miktar
                                    yeni_mal = ((esk_m * esk_mal) + (miktar * fiyat)) / yeni_m
                                    cursor.execute("UPDATE varliklar SET miktar=%s, ort_maliyet=%s, guncel_fiyat=%s, tur=%s WHERE id=%s", (yeni_m, yeni_mal, fiyat, tur, v_id))
                                else:
                                    cursor.execute("INSERT INTO varliklar (tur, sembol, miktar, ort_maliyet, guncel_fiyat, user_id) VALUES (%s,%s,%s,%s,%s,%s)", (tur, sembol, miktar, fiyat, fiyat, user_id))
                            else:
                                v_id, esk_m, esk_mal = mevcut
                                yeni_m = esk_m - miktar
                                cursor.execute("UPDATE varliklar SET miktar=%s, guncel_fiyat=%s WHERE id=%s", (yeni_m, fiyat, v_id))
                                
                            cursor.execute("INSERT INTO islemler (sembol, islem_tipi, miktar, fiyat, tarih, user_id) VALUES (%s,%s,%s,%s,%s,%s)", (sembol, tip, miktar, fiyat, date.today().strftime("%Y-%m-%d"), user_id))
                            conn.commit()
                            st.success(f"{sembol} işlemi başarıyla kaydedildi!")
                        
                        conn.close()
        tab1, tab2 = st.tabs(["💼 Mevcut Varlıklarım", "📜 İşlem Geçmişi (Silme)"])
        
        with tab1:
            conn = get_db_connection()
            df_varlik = pd.read_sql_query("SELECT tur, sembol, miktar, ort_maliyet, guncel_fiyat FROM varliklar WHERE miktar > 0 AND user_id=%s", conn, params=(user_id,))
            conn.close()
            if not df_varlik.empty:
                df_varlik['Toplam_Tutar'] = df_varlik['miktar'] * df_varlik['guncel_fiyat']
                df_varlik['Kar_Zarar'] = df_varlik['Toplam_Tutar'] - (df_varlik['miktar'] * df_varlik['ort_maliyet'])
                st.dataframe(df_varlik, use_container_width=True, hide_index=True)
            else:
                st.info("Kayıtlı varlık yok.")
                
        with tab2:
            conn = get_db_connection()
            df_islem = pd.read_sql_query("SELECT id, tarih, sembol, islem_tipi, miktar, fiyat FROM islemler WHERE user_id=%s ORDER BY id DESC", conn, params=(user_id,))
            
            if not df_islem.empty:
                st.dataframe(df_islem, use_container_width=True, hide_index=True)
                st.markdown("---")
                st.subheader("🗑️ İşlem Sil")
                sil_id = st.selectbox("Silmek istediğiniz işlemin ID numarasını seçin:", df_islem['id'].tolist())
                if st.button("Seçili İşlemi Sil (Geri Alınamaz)"):
                    cursor = conn.cursor()
                    cursor.execute("SELECT sembol FROM islemler WHERE id=%s AND user_id=%s", (sil_id, user_id))
                    sembol_sil = cursor.fetchone()[0]
                    
                    cursor.execute("DELETE FROM islemler WHERE id=%s", (sil_id,))
                    
                    cursor.execute("SELECT islem_tipi, miktar, fiyat FROM islemler WHERE sembol=%s AND user_id=%s ORDER BY id ASC", (sembol_sil, user_id))
                    kalan_islemler = cursor.fetchall()
                    
                    toplam_adet = 0.0
                    toplam_maliyet_tutari = 0.0
                    
                    for t, m, f in kalan_islemler:
                        if t == "ALIS":
                            toplam_maliyet_tutari += (m * f)
                            toplam_adet += m
                        elif t == "SATIS" and toplam_adet > 0:
                            ort_birim = toplam_maliyet_tutari / toplam_adet
                            toplam_adet -= m
                            toplam_maliyet_tutari -= (m * ort_birim)
                    
                    yeni_ort = (toplam_maliyet_tutari / toplam_adet) if toplam_adet > 0 else 0
                    
                    if toplam_adet <= 0:
                        cursor.execute("UPDATE varliklar SET miktar=0, ort_maliyet=0 WHERE sembol=%s AND user_id=%s", (sembol_sil, user_id))
                    else:
                        cursor.execute("UPDATE varliklar SET miktar=%s, ort_maliyet=%s WHERE sembol=%s AND user_id=%s", (toplam_adet, yeni_ort, sembol_sil, user_id))
                    
                    conn.commit()
                    st.success("İşlem silindi ve maliyetler yeniden hesaplandı!")
                    st.rerun()
            else:
                st.info("İşlem geçmişi boş.")
            conn.close()

    with col_sag:
        st.write("### Sabit Piyasa Verileri")
        st.write("Buraya canlı piyasa takip grafikleri eklenebilir...")

# -----------------------------------------------------------------------------
# SAYFA 4: HESAP ARAÇLARI (SİMÜLASYON)
# -----------------------------------------------------------------------------
elif menu == "🧮 Hesap Araçları":
    st.title("Hesap Araçları & Simülasyon")
    
    tab_mal, tab_kredi, tab_cevir = st.tabs(["📉 Maliyet Düşürme", "🏦 Kredi Hesapla", "💱 Hızlı Çevirici"])
    
    # MALİYET DÜŞÜRME
    with tab_mal:
        st.subheader("Ortalama Maliyet Hesaplayıcı")
        col1, col2 = st.columns(2)
        with col1:
            mevcut_adet = st.number_input("Mevcut Adet", min_value=0.0, format="%f")
            mevcut_maliyet = st.number_input("Mevcut Maliyet (₺)", min_value=0.0, format="%f")
        with col2:
            yeni_adet = st.number_input("Yeni Alınacak Adet", min_value=0.0, format="%f")
            yeni_fiyat = st.number_input("Yeni Alış Fiyatı (₺)", min_value=0.0, format="%f")
            
        if mevcut_adet + yeni_adet > 0:
            yeni_ortalama = ((mevcut_adet * mevcut_maliyet) + (yeni_adet * yeni_fiyat)) / (mevcut_adet + yeni_adet)
            st.success(f"**Yeni Ortalama Maliyetiniz:** {yeni_ortalama:,.2f} ₺")

    # KREDİ HESAPLAYICI
    with tab_kredi:
        st.subheader("Gelişmiş Kredi Hesaplama Aracı")
        
        kredi_veriler = {
            "İhtiyaç Kredisi": {"oran": 4.29, "vergi_carpani": 1.30},
            "Taşıt Kredisi": {"oran": 3.49, "vergi_carpani": 1.30},
            "Konut Kredisi": {"oran": 3.05, "vergi_carpani": 1.00},
            "Ticari Kredi": {"oran": 3.59, "vergi_carpani": 1.05}
        }
        
        c_tur, c_mod = st.columns(2)
        kredi_turu = c_tur.selectbox("Kredi Türü Seçin:", list(kredi_veriler.keys()))
        hesap_modu = c_mod.radio("Hesaplama Yöntemi:", ["Çekilecek Tutara Göre (Taksit Hesapla)", "Aylık Taksite Göre (Çekilebilir Tutar Hesapla)"])
        
        varsayilan_oran = kredi_veriler[kredi_turu]["oran"]
        vergi_carpani = kredi_veriler[kredi_turu]["vergi_carpani"]
        
        st.markdown("---")
        
        col1, col2 = st.columns([1, 1])
        
        # 1. MOD: TUTARA GÖRE TAKSİT HESAPLAMA
        if hesap_modu == "Çekilecek Tutara Göre (Taksit Hesapla)":
            with col1:
                k_tutar = st.number_input("Çekmek İstediğiniz Tutar (₺)", min_value=0.0, step=10000.0, value=100000.0)
                k_vade = st.selectbox("Vade (Ay)", [12, 24, 36, 48, 60, 120])
                k_faiz = st.number_input("Aylık Faiz Oranı (%)", min_value=0.0, format="%f", value=float(varsayilan_oran))
                
            with col2:
                st.markdown("### Hesaplama Sonucu")
                if k_tutar > 0 and k_faiz > 0:
                    r = (k_faiz / 100.0) * vergi_carpani
                    n = k_vade
                    taksit = k_tutar * (r * (1 + r)**n) / ((1 + r)**n - 1)
                    toplam_odeme = taksit * n
                    toplam_faiz = toplam_odeme - k_tutar
                    
                    st.metric("Aylık Taksitiniz", f"{taksit:,.2f} ₺")
                    st.metric("Toplam Geri Ödeme", f"{toplam_odeme:,.2f} ₺")
                    st.metric("Toplam Faiz ve Vergi Yükü", f"{toplam_faiz:,.2f} ₺")
                    st.caption(f"*Seçilen tür için hesaplamaya {vergi_carpani}x vergi çarpanı dahil edilmiştir.*")

        # 2. MOD: TAKSİTE GÖRE ÇEKİLEBİLİR TUTAR HESAPLAMA
        else:
            with col1:
                k_taksit = st.number_input("Aylık Ödeyebileceğiniz Taksit (₺)", min_value=0.0, step=1000.0, value=5000.0)
                k_vade = st.selectbox("Vade (Ay) ", [12, 24, 36, 48, 60, 120])
                k_faiz = st.number_input("Aylık Faiz Oranı (%) ", min_value=0.0, format="%f", value=float(varsayilan_oran))
                
            with col2:
                st.markdown("### Hesaplama Sonucu")
                if k_taksit > 0 and k_faiz > 0:
                    r = (k_faiz / 100.0) * vergi_carpani
                    n = k_vade
                    P = k_taksit * ((1 + r)**n - 1) / (r * (1 + r)**n)
                    toplam_odeme = k_taksit * n
                    toplam_faiz = toplam_odeme - P
                    
                    st.metric("Çekebileceğiniz Maksimum Kredi", f"{P:,.2f} ₺")
                    st.metric("Toplam Geri Ödeme", f"{toplam_odeme:,.2f} ₺")
                    st.metric("Toplam Faiz ve Vergi Yükü", f"{toplam_faiz:,.2f} ₺")
                    st.caption(f"*Seçilen tür için hesaplamaya {vergi_carpani}x vergi çarpanı dahil edilmiştir.*")

# -----------------------------------------------------------------------------
# SAYFA 5: TAKVİM VE TEMETTÜ 
# -----------------------------------------------------------------------------
elif menu == "📅 Piyasa Takvimi":
    st.title("Önemli Tarihler & Temettü Beklentileri")
    
    tab_takvim, tab_temettu = st.tabs(["🗓️ Ekonomik Takvim", "💰 Temettü (Kâr Payı) Tarayıcı"])
    
    with tab_takvim:
        st.subheader("Kritik Veri Takvimi (Otomatik Hesaplanan)")
        
        bugun = date.today()
        if bugun.month == 12:
            yil = bugun.year + 1
            ay = 1
        else:
            yil = bugun.year
            ay = bugun.month + 1
            
        ilk_gun = date(yil, ay, 1)
        fark = (4 - ilk_gun.weekday() + 7) % 7
        t_nfp = ilk_gun + timedelta(days=fark)
        t_cpi = date(yil, ay, 13)
        t_tcmb = date(yil, ay, 21) 
        t_fed = date(yil, ay, 18) 

        olaylar = [
            {"Tarih": t_nfp.strftime("%d.%m.%Y"), "Olay": "ABD Tarım Dışı İstihdam (NFP)", "Önem": "🔴 Yüksek"},
            {"Tarih": t_cpi.strftime("%d.%m.%Y"), "Olay": "ABD Enflasyon (TÜFE)", "Önem": "🔴 Yüksek"},
            {"Tarih": t_tcmb.strftime("%d.%m.%Y"), "Olay": "TCMB Faiz Kararı", "Önem": "🟠 Orta"},
            {"Tarih": t_fed.strftime("%d.%m.%Y"), "Olay": "FED Faiz Beklentisi", "Önem": "🔴 Yüksek"},
            {"Tarih": date(yil, ay, 1).strftime("%d.%m.%Y"), "Olay": "TR İmalat PMI", "Önem": "🟢 Düşük"},
            {"Tarih": date(yil, ay, 3).strftime("%d.%m.%Y"), "Olay": "TR Enflasyon (TÜFE)", "Önem": "🔴 Yüksek"}
        ]
        
        df_olaylar = pd.DataFrame(olaylar).sort_values(by="Tarih")
        st.dataframe(df_olaylar, hide_index=True, use_container_width=True)
        
    with tab_temettu:
        st.subheader("Hisse Temettü Tarayıcı")
        st.write("Portföyünüzdeki hisselerin temettü (kâr payı) verimleri Yahoo Finance üzerinden taranıyor...")
        
        conn = get_db_connection()
        hisseler = pd.read_sql_query("SELECT sembol, miktar FROM varliklar WHERE miktar > 0 AND user_id=%s", conn, params=(user_id,))
        conn.close()
        
        yoksay = ["TRY=X", "GRAM", "=F", "BTC", "ETH", "ALTIN", "GUMUS", "PLATIN", "USD", "EUR"]
        temettu_listesi = []
        
        with st.spinner('Geçmiş ve gelecek temettü verileri hesaplanıyor... Lütfen bekleyin.'):
            for _, row in hisseler.iterrows():
                sembol = row['sembol']
                miktar = row['miktar']
                
                if any(x in sembol for x in yoksay): 
                    continue
                    
                try:
                    info = yf.Ticker(sembol).info
                    tarih = "-"
                    tahmini_tutar_str = "-"
                    
                    ex_date = info.get('exDividendDate', None)
                    if ex_date:
                        dt_object = datetime.fromtimestamp(ex_date)
                        if dt_object.date() >= date.today():
                            tarih = dt_object.strftime("%d.%m.%Y")

                    div_rate = info.get('dividendRate', 0)
                    if div_rate and div_rate > 0:
                        toplam_tahmini = div_rate * miktar
                        tahmini_tutar_str = f"{toplam_tahmini:,.2f} ₺"
                        if tarih == "-": tarih = "Tarih Bekleniyor" 
                    
                    if tarih != "-" or tahmini_tutar_str != "-":
                        sade_sembol = sembol.replace(".IS", "")
                        temettu_listesi.append({"Hisse": sade_sembol, "Beklenen Tarih": tarih, "Tahmini Tutar": tahmini_tutar_str})
                except:
                    continue
                    
        if temettu_listesi:
            st.dataframe(pd.DataFrame(temettu_listesi), hide_index=True, use_container_width=True)
        else:
            st.info("Portföyünüzdeki hisselerde yakın zamanda bir temettü ödemesi bulunamadı.")

# -----------------------------------------------------------------------------
# SAYFA 6: PRO PİYASA ANALİZİ
# -----------------------------------------------------------------------------
elif menu == "📈 Piyasa Analizi":
    st.title("📈 Pro Piyasa Analizi")
    st.markdown("⚠️ **YASAL UYARI:** Veriler 10-15 dk gecikmeli gelebilir. Sadece takip amaçlıdır, yatırım tavsiyesi içermez.")
    
    c1, c2, c3 = st.columns([2, 1, 1])
    hizli_semboller = ["USDTRY=X", "GRAM-ALTIN", "GRAM-GUMUS", "GRAM-PLATIN", "GC=F", "SI=F", "XU100.IS", "BTC-USD", "AAPL"]
    secilen_sembol = c1.selectbox("🔍 Analiz Edilecek Sembolü Seçin veya Yazın:", hizli_semboller, index=0)
    
    periyotlar = {"1 AY": "1mo", "3 AY": "3mo", "6 AY": "6mo", "1 YIL": "1y", "3 YIL": "3y", "5 YIL": "5y"}
    secilen_periyot = c2.selectbox("📅 Zaman Aralığı:", list(periyotlar.keys()), index=3)
    
    @st.cache_data(ttl=300)
    def analiz_verisi_getir(sembol, periyot_kodu):
        try:
            if sembol in ["GRAM-ALTIN", "CEYREK-ALTIN", "GRAM-GUMUS", "GRAM-PLATIN"]:
                ons_kod = "GC=F"
                if "GUMUS" in sembol: ons_kod = "SI=F"
                elif "PLATIN" in sembol: ons_kod = "PL=F"
                
                ons = yf.Ticker(ons_kod).history(period="5y")['Close']
                usd = yf.Ticker("USDTRY=X").history(period="5y")['Close']
                
                df = pd.concat([ons, usd], axis=1, keys=['O','U']).ffill().dropna()
                fac = 1.6065 if sembol == "CEYREK-ALTIN" else 1
                data = (df['O'] * df['U']) / 31.1035 * fac
            else:
                t = "XU100.IS" if sembol == "BIST" else sembol
                data = yf.Ticker(t).history(period="5y")['Close'].dropna()
            
            return data
        except:
            return None

    p_kod = periyotlar[secilen_periyot]
    ham_veri = analiz_verisi_getir(secilen_sembol, p_kod)
    
    if ham_veri is None or ham_veri.empty:
        st.error("Bu sembol için veri bulunamadı. Lütfen geçerli bir kod girin (Örn: AAPL, THYAO.IS)")
    else:
        days_map = {"1mo":30, "3mo":90, "6mo":180, "1y":365, "3y":1095, "5y":1825}
        grafik_verisi = ham_veri.tail(days_map.get(p_kod, 365))
        son_fiyat = ham_veri.iloc[-1]
        
        c3.metric(label="Güncel Fiyat", value=f"{son_fiyat:,.2f} ₺/$")
        st.markdown("---")
        
        col_grafik, col_rapor = st.columns([7, 3])
        
        with col_grafik:
            st.subheader(f"📊 {secilen_sembol} Fiyat Grafiği")
            st.area_chart(grafik_verisi, use_container_width=True, color="#3b82f6")
            
            st.write("⏱️ **Geçmiş Performans**")
            p_cols = st.columns(6)
            araliklar = [("1 Ay", 30), ("3 Ay", 90), ("6 Ay", 180), ("1 Yıl", 365), ("3 Yıl", 1095), ("5 Yıl", 1825)]
            
            for i, (ad, gun) in enumerate(araliklar):
                try:
                    hedef_tarih = ham_veri.index[-1] - pd.Timedelta(days=gun)
                    idx = ham_veri.index.get_indexer([hedef_tarih], method='nearest')[0]
                    eski_fiyat = ham_veri.iloc[idx]
                    yuzde_degisim = ((son_fiyat - eski_fiyat) / eski_fiyat) * 100
                    p_cols[i].metric(label=ad, value=f"%{yuzde_degisim:+.1f}", delta=f"{yuzde_degisim:.1f}%")
                except:
                    p_cols[i].metric(label=ad, value="--")

        with col_rapor:
            st.subheader("🤖 Teknik AI Raporu")
            with st.container(border=True):
                sma200 = ham_veri.rolling(200).mean().iloc[-1]
                delta = ham_veri.diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                
                trend = "YÜKSELİŞ 🟢" if son_fiyat > sma200 else "DÜŞÜŞ 🔴"
                rsi_durum = "Aşırı Pahalı 🔴" if rsi > 70 else ("Aşırı Ucuz 🟢" if rsi < 30 else "Dengeli 🟡")
                
                st.markdown(f"**Uzun Vadeli Trend:** {trend}")
                st.write(f"Fiyat, 200 günlük hareketli ortalamanın ({sma200:,.2f}) {'üzerinde.' if son_fiyat > sma200 else 'altında.'}")
                
                st.markdown(f"**Momentum (RSI):** {rsi_durum}")
                st.write(f"RSI değeri şu an **{rsi:.1f}** seviyesinde.")
                
                st.markdown("---")
                st.markdown("**📐 Fibonacci Seviyeleri (1 Yıllık)**")
                son1y = ham_veri.tail(252)
                tepe, dip = son1y.max(), son1y.min()
                fark = tepe - dip
                
                fibs = {
                    "Tepe": tepe,
                    "0.236": tepe - fark * 0.236,
                    "0.382": tepe - fark * 0.382,
                    "0.500": tepe - fark * 0.5,
                    "0.618 (Altın)": tepe - fark * 0.618,
                    "Dip": dip
                }
                
                for k, v in fibs.items():
                    if abs(son_fiyat - v) / son_fiyat < 0.015:
                        st.markdown(f"📍 **{k}: {v:,.2f} (Şu an burada)**")
                    else:
                        st.write(f"• {k}: {v:,.2f}")
                
                st.markdown("---")
                vol = ham_veri.pct_change().std() * 100
                st.write(f"**Volatilite (Günlük Risk):** %{vol:.2f}")
