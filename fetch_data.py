import os
import json
from datetime import datetime, timezone
import pandas as pd
import yfinance as yf
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase bağlantı bilgileri eksik!")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_active_assets():
    response = supabase.table('assets').select('symbol, display_name').eq('is_active', True).execute()
    return {item['symbol']: item['display_name'] for item in response.data}

def run_pipeline():
    print("⏳ Aktif varlık listesi Supabase'den çekiliyor...")
    symbol_map = get_active_assets()
    tickers = list(symbol_map.keys())
    
    if not tickers:
        print("⚠️ HATA: Assets tablosunda aktif varlık bulunamadı!")
        return

    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime('%Y-%m-%d')
    now_iso = now_utc.isoformat()
    
    print(f"📊 Takip edilen varlıklar ({len(tickers)} adet): {tickers}")
    
    # 1. Günlük Geçmiş Verileri İndir (35 Günlük)
    raw_daily = yf.download(tickers, period='35d', interval='1d', progress=False)
    
    # Pandas MultiIndex kolon yapısını düzelt
    if isinstance(raw_daily.columns, pd.MultiIndex):
        daily_prices = raw_daily['Close']
    else:
        daily_prices = raw_daily['Close'] if 'Close' in raw_daily else raw_daily

    # Boş verileri doldur ve bugünden önceki son 30 günü al
    daily_prices = daily_prices.ffill().bfill()
    past_daily = daily_prices[daily_prices.index < today_str].tail(30)
    
    # 2. Bugüne Ait Saatlik Verileri İndir
    raw_hourly = yf.download(tickers, period='2d', interval='1h', progress=False)
    if isinstance(raw_hourly.columns, pd.MultiIndex):
        hourly_prices = raw_hourly['Close']
    else:
        hourly_prices = raw_hourly['Close'] if 'Close' in raw_hourly else raw_hourly
        
    hourly_prices = hourly_prices.ffill().bfill()
    latest_hourly = hourly_prices.iloc[-1:] # En son saatlik bar
    
    # 3. 30 Günlük Geçmiş + 31. Gün Anlık Verisini Birleştir
    combined_prices = pd.concat([past_daily, latest_hourly])
    
    # 4. Yüzdesel Getirileri Hesapla (Returns)
    returns = combined_prices.pct_change().dropna(how='all').fillna(0)
    
    # Kolon isimlerini görünen isimlerle değiştir
    returns = returns.rename(columns=symbol_map)
    
    # 5. Getiri Korelasyon Matrisini Hesapla
    corr_matrix = returns.corr().round(3)
    corr_json = json.loads(corr_matrix.to_json())
    
    print("💾 Supabase veritabanına yazılıyor...")
    
    # --- A) CORRELATION_MATRIX TABLOSUNU GÜNCELLE ---
    # Geçici saatlik veriyi temizle
    supabase.table('correlation_matrix').delete().eq('window_type', 'INTRADAY_HOURLY').execute()
    
    # Yeni korelasyonu ekle
    res_corr = supabase.table('correlation_matrix').insert({
        'calculated_at': now_iso,
        'window_type': 'INTRADAY_HOURLY',
        'data': corr_json
    }).execute()
    print(f"✅ Correlation Matrix başarıyla güncellendi: {len(res_corr.data)} kayıt eklendi.")
    
    # --- B) DAILY_PRICES TABLOSUNU GÜNCELLE ---
    # Test aşamasında tablonun boş kalmaması için en son fiyatları daily_prices tablosuna da işliyoruz
    for ticker in tickers:
        try:
            if ticker in latest_hourly.columns:
                val = latest_hourly[ticker].dropna().iloc[-1]
                price_val = float(val)
                supabase.table('daily_prices').upsert({
                    'price_date': today_str,
                    'symbol': ticker,
                    'close_price': price_val
                }).execute()
        except Exception as e:
            print(f"⚠️ {ticker} fiyatı daily_prices'a yazılamadı: {e}")
            
    print("✅ Daily Prices tablosuna en son fiyatlar başarıyla işlendi.")

if __name__ == "__main__":
    run_pipeline()
