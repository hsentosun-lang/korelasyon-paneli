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
    print("⏳ Aktif varlık listesi getiriliyor...")
    symbol_map = get_active_assets()
    tickers = list(symbol_map.keys())
    
    if not tickers:
        print("⚠️ Aktif enstrüman bulunamadı!")
        return

    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime('%Y-%m-%d')
    
    # 1. Son 35 Günün Günlük Kapanış Fiyatlarını İndir
    print("📊 Günlük geçmiş veriler indiriliyor...")
    daily_data = yf.download(tickers, period='35d', interval='1d')['Close'].ffill().bfill()
    past_daily_data = daily_data[daily_data.index < today_str].tail(30)
    
    # 2. Bugüne (31. Gün) Ait En Son Saatlik Fiyatı Çek
    print("⏱️ Bugüne ait en son saatlik veri indiriliyor...")
    hourly_data = yf.download(tickers, period='2d', interval='1h')['Close'].ffill().bfill()
    latest_hourly_prices = hourly_data.iloc[-1:]
    
    # Bugünü 31. günün geçici fiyatı olarak günlük serinin altına ekle
    combined_prices = pd.concat([past_daily_data, latest_hourly_prices])
    
    # 3. Günlük Getirileri Hesapla (Daily Returns)
    returns = combined_prices.pct_change().dropna()
    returns = returns.rename(columns=symbol_map)
    
    # 4. Getiri Bazlı Rolling 30 Gün Korelasyon Matrisi
    corr_matrix = returns.corr().round(3)
    corr_json = corr_matrix.to_json()
    now_iso = now_utc.isoformat()
    
    # 5. Anlık Saatlik Güncelleme (Geçici saatlik matrisleri temizleyip yenisini yazma)
    supabase.table('correlation_matrix')\
        .delete()\
        .eq('window_type', 'INTRADAY_HOURLY')\
        .execute()
        
    supabase.table('correlation_matrix').insert({
        'calculated_at': now_iso,
        'window_type': 'INTRADAY_HOURLY',
        'data': json.loads(corr_json)
    }).execute()
    
    print(f"⚡ [{now_iso}] 31. Gün Saatlik Güncellemesi Yapıldı.")
    
    # 6. Gün Sonu (EOD - 23:00 UTC) Kesinleştirme ve Temizlik
    if now_utc.hour == 23:
        print("🔒 Gün sonu donduruluyor...")
        supabase.table('correlation_matrix').insert({
            'calculated_at': now_iso,
            'window_type': 'DAILY_EOD',
            'data': json.loads(corr_json)
        }).execute()
        
        for ticker in tickers:
            last_price = float(latest_hourly_prices[ticker].iloc[-1])
            supabase.table('daily_prices').upsert({
                'price_date': today_str,
                'symbol': ticker,
                'close_price': last_price
            }).execute()
            
        print(f"✅ [{today_str}] Gün sonu kapanışı kesinleştirildi.")

if __name__ == "__main__":
    run_pipeline()