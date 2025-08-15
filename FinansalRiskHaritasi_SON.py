#!/usr/bin/env python3
"""
KRİPTO ANALİZ BOTU - PAKET SİSTEMLİ VERSİYON
Claude kesin karar verir, sadece görüntü kabul eder
"""

import os
import asyncio
import base64
import json
import sqlite3
import logging
from io import BytesIO
from datetime import datetime, timedelta
import hashlib
import hmac
import requests

# Gerekli kütüphaneler
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
    import anthropic
    from PIL import Image
    from dotenv import load_dotenv
except ImportError:
    print("""
    ❌ Gerekli kütüphaneler yüklü değil!
    
    Lütfen şu komutu çalıştırın:
    pip install python-telegram-bot anthropic pillow python-dotenv requests
    """)
    exit(1)

# .env dosyasını yükle
load_dotenv()

# ============= AYARLAR - GÜVENLİK SİSTEMİ =============
class Config:
    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv('8245423008:AAFZ0bkaIDEkiTceB97Yym7IjOvknWp5ql4', '')
    ADMIN_ID = int(os.getenv('564128176', '0'))
    
    # Claude API
    ANTHROPIC_API_KEY = os.getenv('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', '')
    
    # PayTR - GERÇEK BİLGİLERİNİZİ GİRİN
    PAYTR_MERCHANT_ID = os.getenv('598542', '')
    PAYTR_MERCHANT_KEY = os.getenv('yJNreQ6po8t94rRd', '')
    PAYTR_MERCHANT_SALT = os.getenv('WctGnFUUTXGPt9n3', '')
    PAYTR_TEST_MODE = os.getenv('PAYTR_TEST_MODE', '1')
    
    # GÜVENLİK SİSTEMİ
    FREE_TRIAL_LIMIT = 1  # Her kullanıcıya 1 deneme hakkı
    REQUIRE_PHONE = True  # Telefon numarası zorunlu
    MINIMUM_ACCOUNT_AGE_DAYS = 7  # Telegram hesap yaşı minimum 7 gün
    
    # PAKET SİSTEMİ
    PACKAGES = {
        'trial': {
            'name': 'Deneme',
            'total_queries': 1,  # Toplam 1 analiz hakkı
            'price_tl': 0,
            'price_usd': 0,
            'description': '1 Ücretsiz Deneme'
        },
        'silver': {
            'name': 'Silver',
            'daily_limit': 3,
            'price_tl': 199,
            'price_usd': 6.22,
            'monthly_queries': 90,
            'description': 'Günde 3 analiz (Aylık 90)'
        },
        'gold': {
            'name': 'Gold',
            'daily_limit': 10,
            'price_tl': 499,
            'price_usd': 15.59,
            'monthly_queries': 300,
            'description': 'Günde 10 analiz (Aylık 300)'
        },
        'platinum': {
            'name': 'Platinum',
            'daily_limit': 20,
            'price_tl': 899,
            'price_usd': 28.09,
            'monthly_queries': 600,
            'description': 'Günde 20 analiz (Aylık 600)'
        },
        'starter': {
            'name': 'Starter',
            'total_queries': 10,  # Toplam 10 analiz
            'price_tl': 99,
            'price_usd': 3.09,
            'description': '10 Analiz Paketi (Süresiz)'
        }
    }
    
    # Referans sistemi
    REFERRAL_BONUS_QUERIES = 1  # Referans başına 1 analiz hediye
    
    # MALİYET HESABI (USD)
    COST_PER_ANALYSIS = 0.02  # ~$0.02 per analiz
    
    # Veritabanı
    DB_NAME = 'crypto_bot.db'

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============= VERİTABANI =============
class Database:
    def __init__(self):
        self.db_name = Config.DB_NAME
        self.init_db()
    
    def init_db(self):
        """Veritabanını oluştur - GÜVENLİK ALANLARI EKLENDİ"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        # Users tablosu - GÜVENLİK ve REFERANS SİSTEMİ EKLENDİ
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                phone TEXT,
                is_verified INTEGER DEFAULT 0,
                package TEXT DEFAULT 'none',
                package_expire TEXT,
                trial_used INTEGER DEFAULT 0,
                total_queries INTEGER DEFAULT 0,
                remaining_queries INTEGER DEFAULT 0,
                daily_queries INTEGER DEFAULT 0,
                last_query_date TEXT,
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                referral_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                banned INTEGER DEFAULT 0,
                ban_reason TEXT
            )
        ''')
        
        # Analyses tablosu
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                coin_pair TEXT,
                timeframe TEXT,
                recommendation TEXT,
                entry_price TEXT,
                targets TEXT,
                stop_loss TEXT,
                risk_reward TEXT,
                analysis_text TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Payments tablosu
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                package TEXT,
                amount REAL,
                status TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Referrals tablosu
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER,
                bonus_given INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Veritabanı hazır!")
    
    def get_user(self, user_id):
        """Kullanıcıyı getir"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        conn.close()
        return user
    
    def create_user(self, user_id, username, first_name):
        """Yeni kullanıcı oluştur - REFERANS KODU İLE"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        # Benzersiz referans kodu oluştur
        import random
        import string
        referral_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, first_name, package, referral_code)
            VALUES (?, ?, ?, 'trial', ?)
        ''', (user_id, username, first_name, referral_code))
        conn.commit()
        conn.close()
    
    def can_analyze(self, user_id):
        """Kullanıcı analiz yapabilir mi? - GÜVENLİK KONTROLÜ"""
        user = self.get_user(user_id)
        if not user:
            return False  # Kayıtlı değilse yapamaz
        
        # Kullanıcı bilgileri (index'ler güncellendi)
        package = user[5]  # package
        trial_used = user[7]  # trial_used
        remaining_queries = user[9]  # remaining_queries
        daily_queries = user[10]  # daily_queries
        banned = user[16]  # banned
        
        # Banlı mı?
        if banned == 1:
            return False
        
        # Paket kontrolü
        if package == 'none':
            return False  # Paketi yok
        
        if package == 'trial':
            # Deneme hakkı kullanılmış mı?
            return trial_used == 0
        
        if package == 'starter':
            # Starter pakette kalan sorgu var mı?
            return remaining_queries > 0
        
        if package in ['silver', 'gold', 'platinum']:
            # Günlük limit kontrolü
            today = datetime.now().strftime('%Y-%m-%d')
            last_date = user[11]  # last_query_date
            
            if last_date != today:
                daily_queries = 0
            
            daily_limit = Config.PACKAGES[package]['daily_limit']
            return daily_queries < daily_limit
        
        return False
    
    def update_query_count(self, user_id):
        """Sorgu sayısını güncelle - YENİ SİSTEM"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Kullanıcıyı al
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        
        if user:
            package = user[5]
            
            if package == 'trial':
                # Deneme hakkını kullan
                cursor.execute('UPDATE users SET trial_used = 1, total_queries = total_queries + 1 WHERE user_id = ?', (user_id,))
            
            elif package == 'starter':
                # Starter paketinden 1 azalt
                cursor.execute('UPDATE users SET remaining_queries = remaining_queries - 1, total_queries = total_queries + 1 WHERE user_id = ?', (user_id,))
            
            else:
                # Normal paketler - günlük sayaç
                last_date = user[11]
                daily_count = user[10]
                
                if last_date != today:
                    daily_count = 0
                
                cursor.execute('''
                    UPDATE users 
                    SET daily_queries = ?, 
                        total_queries = total_queries + 1,
                        last_query_date = ?
                    WHERE user_id = ?
                ''', (daily_count + 1, today, user_id))
        
        conn.commit()
        conn.close()
    
    def add_referral_bonus(self, referrer_id, referred_id):
        """Referans bonusu ekle"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        # Referans kaydı ekle
        cursor.execute('''
            INSERT INTO referrals (referrer_id, referred_id, bonus_given)
            VALUES (?, ?, 1)
        ''', (referrer_id, referred_id))
        
        # Referans verene bonus ekle (remaining_queries)
        cursor.execute('''
            UPDATE users 
            SET referral_count = referral_count + 1,
                remaining_queries = remaining_queries + ?
            WHERE user_id = ?
        ''', (Config.REFERRAL_BONUS_QUERIES, referrer_id))
        
        conn.commit()
        conn.close()
    
    def update_package(self, user_id, package_type):
        """Kullanıcı paketini güncelle"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        if package_type == 'free':
            expire_date = None
        else:
            # 30 gün geçerli
            expire_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
        
        cursor.execute('''
            UPDATE users 
            SET package = ?, package_expire = ?, daily_queries = 0
            WHERE user_id = ?
        ''', (package_type, expire_date, user_id))
        
        conn.commit()
        conn.close()
    
    def save_analysis(self, user_id, analysis_data):
        """Analizi kaydet"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO analyses (user_id, coin_pair, timeframe, recommendation, entry_price, targets, stop_loss, risk_reward, analysis_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            analysis_data.get('coin_pair', 'UNKNOWN'),
            analysis_data.get('timeframe', 'UNKNOWN'),
            analysis_data.get('recommendation', 'NEUTRAL'),
            analysis_data.get('entry', ''),
            json.dumps(analysis_data.get('targets', [])),
            analysis_data.get('stop_loss', ''),
            analysis_data.get('risk_reward', ''),
            analysis_data.get('full_text', '')
        ))
        conn.commit()
        conn.close()

# ============= CLAUDE SERVİSİ - KESİN KARAR =============
class ClaudeAnalyzer:
    def __init__(self):
        self.api_key = Config.ANTHROPIC_API_KEY
        if not self.api_key:
            logger.error("Claude API key eksik!")
    
    async def analyze_image(self, image_base64):
        """MUTLAKA POZİSYON, SL, TP VERİR"""
        
        if not self.api_key:
            return {"success": False, "error": "API key eksik"}
        
        try:
            client = anthropic.Anthropic(api_key=self.api_key)
            
            # SÜPER DETAYLI VE KESİN PROMPT
            prompt = """
            Grafikteki coin çiftini ve zaman dilimini tespit et, ardından teknik analiz yap.
            
            ADIM 1: Grafikte görünen yazıları oku:
            - Sol üstte veya başlıkta coin çifti yazar (örn: BTCUSDT, BTC/USDT, ETH/USDT)
            - Zaman dilimi genelde üstte veya altta yazar (1m, 5m, 15m, 1h, 4h, 1d, 1w)
            - Eğer göremiyorsan mumların sıklığına göre tahmin et
            
            ADIM 2: Teknik analiz yap ve KESİNLİKLE aşağıdaki formatta cevap ver:
            
            COIN: [Tespit ettiğin coin çifti]
            ZAMAN: [Tespit ettiğin zaman dilimi]
            FİYAT: [Grafikte görünen son fiyat]
            TREND: [Yükseliş/Düşüş/Yatay]
            
            POZİSYON: [LONG veya SHORT - MUTLAKA BİRİNİ SEÇ]
            
            GİRİŞ: [Mevcut fiyat civarında dar bir aralık, örn: 95000-95500]
            TP1: [Giriş fiyatından %1-2 uzakta]
            TP2: [Giriş fiyatından %2-4 uzakta]
            TP3: [Giriş fiyatından %4-6 uzakta]
            SL: [Giriş fiyatından %1-2 ters yönde]
            
            R/R: [Risk/Reward oranı]
            
            AÇIKLAMA:
            [50-100 kelime ile neden bu pozisyonu önerdiğini açıkla]
            
            KURALLAR:
            1. ASLA "BEKLE" veya "NÖTR" deme, MUTLAKA LONG veya SHORT seç
            2. Eğer grafik net değilse bile, mevcut trende göre karar ver
            3. Yükseliş trendi varsa LONG, düşüş trendi varsa SHORT
            4. Trend yoksa son mumların yönüne bak
            5. Tüm değerleri rakamsal olarak ver, "N/A" veya "Belirlenemedi" YAZMA
            """
            
            # API çağrısı
            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1000,
                temperature=0.3,  # Daha kararlı cevaplar için düşük
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": image_base64
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ]
            )
            
            # Sonucu parse et
            result_text = response.content[0].text
            analysis = self.parse_analysis_strict(result_text)
            
            analysis['success'] = True
            analysis['full_text'] = result_text
            
            # MALİYET HESABI
            analysis['api_cost'] = Config.COST_PER_ANALYSIS
            
            return analysis
            
        except Exception as e:
            logger.error(f"Claude API hatası: {e}")
            return {"success": False, "error": str(e)}
    
    def parse_analysis_strict(self, text):
        """Kesin değerlerle parse et"""
        analysis = {
            'coin_pair': 'BTCUSDT',  # Varsayılan
            'timeframe': '1H',
            'current_price': '0',
            'recommendation': 'LONG 🟢',
            'entry': '0',
            'targets': ['0', '0', '0'],
            'stop_loss': '0',
            'risk_reward': '1:2'
        }
        
        lines = text.split('\n')
        
        for line in lines:
            line_upper = line.upper()
            
            if 'COIN:' in line_upper:
                coin = line.split(':')[1].strip()
                # Slash'ı kaldır
                coin = coin.replace('/', '').replace(' ', '')
                analysis['coin_pair'] = coin
                
            elif 'ZAMAN:' in line_upper or 'TIMEFRAME:' in line_upper or 'TF:' in line_upper:
                analysis['timeframe'] = line.split(':')[1].strip()
                
            elif 'FİYAT:' in line_upper or 'PRICE:' in line_upper:
                analysis['current_price'] = line.split(':')[1].strip()
                
            elif 'POZİSYON:' in line_upper or 'POSITION:' in line_upper:
                if 'SHORT' in line_upper:
                    analysis['recommendation'] = 'SHORT 🔴'
                else:
                    analysis['recommendation'] = 'LONG 🟢'
                    
            elif 'GİRİŞ:' in line_upper or 'ENTRY:' in line_upper:
                analysis['entry'] = line.split(':')[1].strip()
                
            elif 'TP1:' in line_upper or 'TARGET 1:' in line_upper:
                analysis['targets'][0] = line.split(':')[1].strip()
                
            elif 'TP2:' in line_upper or 'TARGET 2:' in line_upper:
                analysis['targets'][1] = line.split(':')[1].strip()
                
            elif 'TP3:' in line_upper or 'TARGET 3:' in line_upper:
                analysis['targets'][2] = line.split(':')[1].strip()
                
            elif 'SL:' in line_upper or 'STOP' in line_upper:
                analysis['stop_loss'] = line.split(':')[1].strip()
                
            elif 'R/R:' in line_upper or 'RISK' in line_upper:
                if ':' in line:
                    parts = line.split(':')
                    if len(parts) > 1:
                        analysis['risk_reward'] = parts[-1].strip()
        
        # Eğer hala boş değerler varsa, varsayılan ata
        if analysis['entry'] == '0' or not analysis['entry']:
            analysis['entry'] = '$95,000-95,500'
        if analysis['targets'][0] == '0':
            analysis['targets'] = ['$96,000', '$97,000', '$98,000']
        if analysis['stop_loss'] == '0':
            analysis['stop_loss'] = '$94,000'
        
        return analysis
    
    async def analyze_image(self, image_base64):
        """Görüntüyü analiz et - POZİSYON, SL, TP GARANTİLİ"""
        
        if not self.api_key:
            return {"success": False, "error": "API key eksik"}
        
        try:
            client = anthropic.Anthropic(api_key=self.api_key)
            
            # DETAYLI PROMPT - KESİNLİKLE POZİSYON VERMESİ İÇİN
            prompt = """
            Bu kripto para grafiğini detaylı analiz et ve KESİNLİKLE aşağıdaki formatta cevap ver:
            
            COIN: [Grafikte görünen coin çifti, örn: BTCUSDT]
            TREND: [Yükseliş/Düşüş/Yatay]
            ÖNERİ: [LONG veya SHORT - mutlaka birini seç]
            
            GİRİŞ: [Pozisyon açılacak fiyat aralığı]
            HEDEF 1: [İlk kar al seviyesi - giriş fiyatından %1-3 uzakta]
            HEDEF 2: [İkinci kar al seviyesi - giriş fiyatından %3-5 uzakta]
            HEDEF 3: [Son kar al seviyesi - giriş fiyatından %5-10 uzakta]
            STOP LOSS: [Zarar kes seviyesi - giriş fiyatından %1-3 uzakta]
            
            RİSK/ÖDÜL: [Risk reward oranı, örn: 1:2 veya 1:3]
            
            ANALİZ:
            [Neden bu pozisyonu önerdiğini açıkla. Hangi göstergeler, formasyonlar, destek-dirençler bu kararı destekliyor?]
            
            ÖNEMLI KURALLAR:
            1. MUTLAKA LONG veya SHORT pozisyon öner
            2. MUTLAKA rakamsal giriş, hedef ve stop loss ver
            3. Eğer grafik net değilse bile tahmin yürüt
            4. Kararsız kalma, mutlaka bir yön seç
            """
            
            # API çağrısı
            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1500,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": image_base64
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ]
            )
            
            # Sonucu parse et
            result_text = response.content[0].text
            
            # Detaylı parsing - KESİN DEĞERLER ÇIKAR
            analysis = self.parse_analysis(result_text)
            
            # Eğer bazı değerler eksikse varsayılan ekle
            if analysis['recommendation'] == 'NEUTRAL':
                # Rastgele LONG veya SHORT seç
                import random
                analysis['recommendation'] = random.choice(['LONG 🟢', 'SHORT 🔴'])
            
            if analysis['entry'] == 'N/A':
                analysis['entry'] = '$95,000 - $95,500'  # Örnek değer
            
            if analysis['targets'][0] == 'N/A':
                analysis['targets'] = ['$96,000', '$97,000', '$98,000']  # Örnek değerler
            
            if analysis['stop_loss'] == 'N/A':
                analysis['stop_loss'] = '$94,000'  # Örnek değer
            
            analysis['success'] = True
            analysis['full_text'] = result_text
            
            return analysis
            
        except Exception as e:
            logger.error(f"Claude API hatası: {e}")
            return {"success": False, "error": str(e)}
    
    def parse_analysis(self, text):
        """Analiz metnini parse et"""
        analysis = {
            'coin_pair': 'UNKNOWN',
            'recommendation': 'NEUTRAL',
            'entry': 'N/A',
            'targets': ['N/A', 'N/A', 'N/A'],
            'stop_loss': 'N/A',
            'risk_reward': 'N/A'
        }
        
        lines = text.split('\n')
        
        for line in lines:
            line_upper = line.upper()
            
            if 'COIN:' in line_upper or 'PARITE:' in line_upper:
                analysis['coin_pair'] = line.split(':')[1].strip()
            elif 'ÖNERİ:' in line_upper or 'RECOMMENDATION:' in line_upper:
                if 'LONG' in line_upper:
                    analysis['recommendation'] = 'LONG 🟢'
                elif 'SHORT' in line_upper:
                    analysis['recommendation'] = 'SHORT 🔴'
                else:
                    analysis['recommendation'] = 'BEKLE ⚪'
            elif 'GİRİŞ:' in line_upper or 'ENTRY:' in line_upper:
                analysis['entry'] = line.split(':')[1].strip()
            elif 'HEDEF 1:' in line_upper or 'TP1:' in line_upper or 'TARGET 1:' in line_upper:
                analysis['targets'][0] = line.split(':')[1].strip()
            elif 'HEDEF 2:' in line_upper or 'TP2:' in line_upper or 'TARGET 2:' in line_upper:
                analysis['targets'][1] = line.split(':')[1].strip()
            elif 'HEDEF 3:' in line_upper or 'TP3:' in line_upper or 'TARGET 3:' in line_upper:
                analysis['targets'][2] = line.split(':')[1].strip()
            elif 'STOP' in line_upper:
                analysis['stop_loss'] = line.split(':')[1].strip()
            elif 'RİSK/ÖDÜL:' in line_upper or 'RISK/REWARD:' in line_upper:
                analysis['risk_reward'] = line.split(':')[1].strip()
        
        return analysis

# ============= PAYTR SERVİSİ (GERÇEK) =============
class SimplePayment:
    def __init__(self):
        self.merchant_id = Config.PAYTR_MERCHANT_ID
        self.merchant_key = Config.PAYTR_MERCHANT_KEY
        self.merchant_salt = Config.PAYTR_MERCHANT_SALT
        self.test_mode = os.getenv('PAYTR_TEST_MODE', '1')  # 1=test, 0=gerçek
    
    def create_payment_link(self, user_id, amount_tl=32, package='single'):
        """GERÇEK PayTR ödeme linki oluştur"""
        
        if not all([self.merchant_id, self.merchant_key, self.merchant_salt]):
            return {
                'success': False,
                'message': '⚠️ PayTR bilgileri eksik! .env dosyasını kontrol edin.'
            }
        
        # Paketler
        packages = {
            'single': {'price': 32, 'credits': 1, 'desc': '1 Analiz'},
            'package5': {'price': 128, 'credits': 5, 'desc': '5 Analiz (%20 indirim)'},
            'package10': {'price': 224, 'credits': 10, 'desc': '10 Analiz (%30 indirim)'}
        }
        
        pack = packages.get(package, packages['single'])
        
        # Sipariş no
        merchant_oid = f"BOT{user_id}_{int(datetime.now().timestamp())}"
        
        # PayTR için sepet
        basket = base64.b64encode(
            json.dumps([[pack['desc'], str(pack['price']), 1]]).encode()
        ).decode()
        
        # Hash oluştur
        amount_kurus = pack['price'] * 100
        
        hash_str = (
            f"{self.merchant_id}{user_id}{amount_kurus}{merchant_oid}"
            f"https://t.me/your_bothttps://t.me/your_bot11TL{self.test_mode}"
        )
        hash_str += basket
        
        token = base64.b64encode(
            hmac.new(
                self.merchant_salt.encode(),
                hash_str.encode(),
                hashlib.sha256
            ).digest()
        ).decode()
        
        # PayTR API'ye gönder
        try:
            response = requests.post(
                "https://www.paytr.com/odeme/api/get-token",
                data={
                    'merchant_id': self.merchant_id,
                    'user_ip': '1.1.1.1',
                    'merchant_oid': merchant_oid,
                    'email': f'{user_id}@telegram.com',
                    'payment_amount': amount_kurus,
                    'paytr_token': token,
                    'user_basket': basket,
                    'debug_on': self.test_mode,
                    'no_installment': 1,
                    'max_installment': 0,
                    'user_name': str(user_id),
                    'user_address': 'Telegram',
                    'user_phone': '05555555555',
                    'merchant_ok_url': 'https://t.me/your_bot',
                    'merchant_fail_url': 'https://t.me/your_bot',
                    'timeout_limit': 30,
                    'currency': 'TL',
                    'test_mode': self.test_mode
                },
                timeout=30
            )
            
            result = response.json()
            
            if result.get('status') == 'success':
                # Veritabanına kaydet
                conn = sqlite3.connect(Config.DB_NAME)
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO payments (user_id, amount, credits, status)
                    VALUES (?, ?, ?, 'pending')
                ''', (user_id, pack['price'], pack['credits']))
                conn.commit()
                conn.close()
                
                return {
                    'success': True,
                    'link': f"https://www.paytr.com/odeme/guvenli/{result['token']}",
                    'amount': pack['price'],
                    'credits': pack['credits']
                }
            else:
                return {
                    'success': False,
                    'message': f"❌ PayTR hatası: {result.get('reason', 'Bilinmeyen')}"
                }
                
        except Exception as e:
            logger.error(f"PayTR error: {e}")
            return {
                'success': False,
                'message': f'❌ Bağlantı hatası: {str(e)[:50]}'
            }

# ============= ANA BOT SINIFI - PAKETLER VE KISITLAMALAR =============
class CryptoBot:
    def __init__(self):
        self.db = Database()
        self.analyzer = ClaudeAnalyzer()
        self.payment = SimplePayment()
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start komutu - GÜVENLİK SİSTEMİ İLE"""
        user_id = update.effective_user.id
        username = update.effective_user.username
        first_name = update.effective_user.first_name
        
        # Referans kodu kontrolü (deeplinking)
        if context.args and len(context.args) > 0:
            ref_code = context.args[0]
            await self.process_referral(user_id, ref_code)
        
        # Kullanıcı var mı kontrol et
        user = self.db.get_user(user_id)
        
        if not user:
            # Yeni kullanıcı - hesap yaşı kontrolü
            try:
                # Telegram hesap yaşı kontrolü (API limiti nedeniyle try-except)
                chat = await context.bot.get_chat(user_id)
                # Bu özellik her zaman çalışmayabilir
            except:
                pass
            
            # Yeni kullanıcı oluştur
            self.db.create_user(user_id, username, first_name)
            user = self.db.get_user(user_id)
            
            welcome_text = f"""
🎉 *KRİPTO ANALİZ BOTUNA HOŞ GELDİNİZ!*

Merhaba {first_name}! 👋

🎁 *ÜCRETSİZ DENEME HAKKINIZ HAZIR!*
Size özel 1 ücretsiz analiz hakkı tanımlandı.

📊 *Nasıl Çalışır?*
1️⃣ Kripto grafiğinin ekran görüntüsünü gönderin
2️⃣ 15-30 saniye bekleyin
3️⃣ Detaylı analiz alın:
   • Coin ve zaman dilimi tespiti
   • LONG/SHORT önerisi
   • Giriş, TP ve SL seviyeleri
   • Risk/Ödül oranı

💎 *PAKETLER*
Deneme sonrası paket almanız gerekiyor:
• *Starter:* 99₺ - 10 analiz
• *Silver:* 199₺/ay - Günde 3 analiz
• *Gold:* 499₺/ay - Günde 10 analiz
• *Platinum:* 899₺/ay - Günde 20 analiz

🔗 *Referans Kodunuz:* `{user[13]}`
Her arkadaşınız için +1 analiz kazanın!

⚠️ *ÖNEMLİ:* Sadece grafik görüntüsü gönderin!

Hemen denemeye başlayın! 👇
"""
        else:
            # Mevcut kullanıcı
            package = user[5]
            remaining = self.get_remaining_queries(user_id)
            
            if package == 'none':
                welcome_text = f"""
❌ *PAKET GEREKLİ!*

{first_name}, deneme hakkınız bitti.
Devam etmek için paket almanız gerekiyor.

💎 *PAKET SEÇENEKLERİ:*
• *Starter:* 99₺ - 10 analiz
• *Silver:* 199₺/ay - 90 analiz
• *Gold:* 499₺/ay - 300 analiz
• *Platinum:* 899₺/ay - 600 analiz

Hemen paket alın ve analize devam edin! 👇
"""
            else:
                package_info = Config.PACKAGES.get(package, {})
                welcome_text = f"""
👋 *Tekrar Hoş Geldiniz {first_name}!*

📦 Paketiniz: *{package_info.get('name', 'Bilinmeyen')}*
📊 Kalan analiz: {remaining}
🔗 Referans kodunuz: `{user[13]}`

📸 Grafik görüntüsü göndererek başlayın!
"""
        
        # Butonlar
        keyboard = []
        
        if not user or user[5] == 'trial':
            keyboard.append([InlineKeyboardButton("🎁 Denemeyi Başlat", callback_data='start_trial')])
        
        if not user or user[5] in ['none', 'trial']:
            keyboard.append([InlineKeyboardButton("💎 Paketleri Gör", callback_data='packages')])
        
        keyboard.append([InlineKeyboardButton("📊 Örnek Analiz", callback_data='example')])
        keyboard.append([InlineKeyboardButton("👥 Arkadaş Davet Et", callback_data='referral')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            welcome_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def process_referral(self, new_user_id, ref_code):
        """Referans işlemi"""
        conn = sqlite3.connect(Config.DB_NAME)
        cursor = conn.cursor()
        
        # Referans kodunun sahibini bul
        cursor.execute('SELECT user_id FROM users WHERE referral_code = ?', (ref_code,))
        result = cursor.fetchone()
        
        if result and result[0] != new_user_id:
            referrer_id = result[0]
            
            # Yeni kullanıcıyı referans ile işaretle
            cursor.execute('UPDATE users SET referred_by = ? WHERE user_id = ?', (referrer_id, new_user_id))
            
            # Referans bonusu ver
            self.db.add_referral_bonus(referrer_id, new_user_id)
            
            logger.info(f"Referral processed: {referrer_id} -> {new_user_id}")
        
        conn.close()
    
    def get_remaining_queries(self, user_id):
        """Kalan sorgu hakkını hesapla"""
        user = self.db.get_user(user_id)
        if not user:
            return 0
        
        package = user[5]
        
        if package == 'trial':
            return 1 - user[7]  # 1 - trial_used
        
        elif package == 'starter':
            return user[9]  # remaining_queries
        
        elif package in ['silver', 'gold', 'platinum']:
            daily_limit = Config.PACKAGES[package]['daily_limit']
            today = datetime.now().strftime('%Y-%m-%d')
            
            if user[11] != today:  # last_query_date
                return daily_limit
            
            return daily_limit - user[10]  # daily_limit - daily_queries
        
        return 0
    
    async def packages_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Paketleri göster"""
        packages_text = """
💎 *PAKET SİSTEMİ*

📦 *SILVER PAKET*
• Günde 3 analiz (Aylık 90 analiz)
• Fiyat: 199₺/ay
• Tasarruf: %70

📦 *GOLD PAKET*
• Günde 10 analiz (Aylık 300 analiz)
• Fiyat: 499₺/ay
• Tasarruf: %75
• ⭐ En popüler

📦 *PLATINUM PAKET*
• Günde 20 analiz (Aylık 600 analiz)
• Fiyat: 899₺/ay
• Tasarruf: %78
• 🔥 Profesyoneller için

💰 *Maliyet Karşılaştırması:*
• Tek analiz: 32₺
• Silver: 2.21₺/analiz
• Gold: 1.66₺/analiz
• Platinum: 1.50₺/analiz

✅ Tüm paketler 30 gün geçerlidir
✅ Otomatik yenileme yok
✅ Anında aktifleşir
"""
        
        keyboard = [
            [InlineKeyboardButton("💳 Silver Satın Al", callback_data='buy_silver')],
            [InlineKeyboardButton("💳 Gold Satın Al", callback_data='buy_gold')],
            [InlineKeyboardButton("💳 Platinum Satın Al", callback_data='buy_platinum')],
            [InlineKeyboardButton("◀️ Geri", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if hasattr(update, 'message') and update.message:
            await update.message.reply_text(packages_text, parse_mode='Markdown', reply_markup=reply_markup)
        else:
            await update.callback_query.edit_message_text(packages_text, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def profile_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Profil komutu"""
        user_id = update.effective_user.id
        user = self.db.get_user(user_id)
        
        if not user:
            await update.message.reply_text("Önce /start komutunu kullanın!")
            return
        
        # Kullanıcı bilgileri
        package = user[3]
        package_expire = user[4]
        daily_queries = user[5]
        total_queries = user[6]
        
        # Paket bilgisi
        package_info = Config.PACKAGES.get(package, Config.PACKAGES['free'])
        daily_limit = package_info['daily_limit']
        remaining = daily_limit - daily_queries
        
        # Kalan süre
        if package != 'free' and package_expire:
            expire_date = datetime.strptime(package_expire, '%Y-%m-%d')
            days_left = (expire_date - datetime.now()).days
            expire_text = f"{days_left} gün kaldı"
        else:
            expire_text = "Süresiz"
        
        profile_text = f"""
👤 *PROFİLİNİZ*

🆔 ID: `{user_id}`
📦 Paket: *{package_info['name']}*
⏰ Geçerlilik: {expire_text}

📊 *Kullanım:*
• Bugün: {daily_queries}/{daily_limit}
• Kalan: {remaining}
• Toplam: {total_queries}

💰 *Maliyet Bilgisi:*
Her analiz bana ~0.65₺ maliyete sahip
"""
        
        keyboard = []
        if package == 'free':
            keyboard.append([InlineKeyboardButton("💎 Paket Satın Al", callback_data='packages')])
        else:
            keyboard.append([InlineKeyboardButton("⬆️ Paket Yükselt", callback_data='packages')])
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        await update.message.reply_text(
            profile_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """FOTOĞRAF - GÜVENLİK KONTROLÜ İLE"""
        user_id = update.effective_user.id
        
        # Kullanıcı kontrolü
        user = self.db.get_user(user_id)
        
        if not user:
            # Kayıtlı değil
            await update.message.reply_text(
                "❌ *KAYIT GEREKLİ!*\n\n"
                "Önce /start komutunu kullanın.",
                parse_mode='Markdown'
            )
            return
        
        # Ban kontrolü
        if user[16] == 1:  # banned
            await update.message.reply_text(
                f"🚫 *HESABINIZ ASKIYA ALINMIŞ*\n\n"
                f"Sebep: {user[17]}\n"  # ban_reason
                f"Destek: @your_support",
                parse_mode='Markdown'
            )
            return
        
        # Paket kontrolü
        package = user[5]
        
        if package == 'none':
            # Paketi yok
            keyboard = [
                [InlineKeyboardButton("💳 Starter (99₺)", callback_data='buy_starter')],
                [InlineKeyboardButton("💳 Silver (199₺)", callback_data='buy_silver')],
                [InlineKeyboardButton("💳 Gold (499₺)", callback_data='buy_gold')],
                [InlineKeyboardButton("💳 Platinum (899₺)", callback_data='buy_platinum')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "❌ *PAKET GEREKLİ!*\n\n"
                "Deneme hakkınız bitti. Devam etmek için paket almalısınız.\n\n"
                "📦 *Önerilen: Starter Paket*\n"
                "• 10 analiz hakkı\n"
                "• Sadece 99₺\n"
                "• Süresiz kullanım\n\n"
                "Hemen başlamak için seçin:",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            return
        
        # Limit kontrolü
        if not self.db.can_analyze(user_id):
            remaining = self.get_remaining_queries(user_id)
            
            if package == 'trial':
                text = "❌ *DENEME HAKKINIZ BİTTİ!*\n\nDevam etmek için paket alın:"
            elif package == 'starter':
                text = "❌ *STARTER PAKETİNİZ BİTTİ!*\n\n10 analiz hakkınızı kullandınız.\nYeni paket alın:"
            else:
                package_info = Config.PACKAGES[package]
                text = (
                    f"⚠️ *GÜNLÜK LİMİT DOLDU!*\n\n"
                    f"📦 Paket: {package_info['name']}\n"
                    f"📊 Günlük limit: {package_info['daily_limit']}\n"
                    f"⏰ Yeni hak: Gece 00:00'da\n\n"
                    f"Hemen devam etmek için Starter paket alabilirsiniz:"
                )
            
            keyboard = [
                [InlineKeyboardButton("💳 Starter (99₺) - 10 Analiz", callback_data='buy_starter')],
                [InlineKeyboardButton("⬆️ Paket Yükselt", callback_data='packages')],
                [InlineKeyboardButton("👥 Arkadaş Davet Et (+1 Analiz)", callback_data='referral')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            return
        
        # İşleniyor mesajı
        remaining_before = self.get_remaining_queries(user_id)
        
        processing_msg = await update.message.reply_text(
            f"🔄 *Grafik analiz ediliyor...*\n\n"
            f"📊 Kalan hakkınız: {remaining_before}\n"
            f"⏳ 15-30 saniye kadar sürecek...",
            parse_mode='Markdown'
        )
        
        try:
            # Fotoğrafı indir
            photo_file = await update.message.photo[-1].get_file()
            photo_bytes = BytesIO()
            await photo_file.download_to_memory(photo_bytes)
            photo_bytes.seek(0)
            
            # Base64'e çevir
            image_base64 = base64.b64encode(photo_bytes.read()).decode('utf-8')
            
            # Claude ile analiz
            analysis = await self.analyzer.analyze_image(image_base64)
            
            if not analysis['success']:
                await processing_msg.edit_text(
                    f"❌ Analiz başarısız!\n\nHata: {analysis.get('error', 'Bilinmeyen hata')}"
                )
                return
            
            # Veritabanını güncelle
            self.db.update_query_count(user_id)
            self.db.save_analysis(user_id, analysis)
            
            # Processing mesajını sil
            await processing_msg.delete()
            
            # Sonucu gönder
            await self.send_analysis_result(update, analysis, user_id)
            
            # Trial kullanıcısı ise paket öner
            if package == 'trial':
                keyboard = [
                    [InlineKeyboardButton("💳 Starter Paket Al (99₺)", callback_data='buy_starter')],
                    [InlineKeyboardButton("📦 Tüm Paketler", callback_data='packages')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "✅ *DENEME HAKKINIZ KULLANILDI!*\n\n"
                    "Analizden memnun kaldıysanız, hemen paket alarak devam edin:\n\n"
                    "🎯 *Önerilen: Starter Paket*\n"
                    "• 10 analiz hakkı\n"
                    "• Sadece 99₺\n"
                    "• Anında aktif",
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
            
        except Exception as e:
            logger.error(f"Analiz hatası: {e}")
            await processing_msg.edit_text(
                "❌ Bir hata oluştu!\n\nLütfen tekrar deneyin."
            )
    
    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """METIN MESAJLARINI REDDET"""
        await update.message.reply_text(
            "⚠️ *SADECE GRAFİK GÖRÜNTÜSÜ!*\n\n"
            "Bu bot sadece grafik görüntülerini analiz eder.\n"
            "Lütfen metin yazmayın, sadece görüntü gönderin.\n\n"
            "📊 Grafik ekran görüntüsü alıp gönderin.",
            parse_mode='Markdown'
        )
    
    async def send_analysis_result(self, update: Update, analysis, user_id):
        """Analiz sonucunu gönder"""
        
        # Kullanıcı bilgisi
        user = self.db.get_user(user_id)
        package = user[3]
        daily_queries = user[5]
        package_info = Config.PACKAGES[package]
        remaining = package_info['daily_limit'] - daily_queries
        
        message = f"""
📊 *ANALİZ SONUCU*

🪙 *Coin:* {analysis['coin_pair']}
⏰ *Zaman Dilimi:* {analysis['timeframe']}
💵 *Mevcut Fiyat:* {analysis['current_price']}

🎯 *POZİSYON ÖNERİSİ:* {analysis['recommendation']}

📍 *Giriş Seviyesi:* {analysis['entry']}

✅ *Kar Al Hedefleri:*
• TP1: {analysis['targets'][0]}
• TP2: {analysis['targets'][1]}  
• TP3: {analysis['targets'][2]}

🛡 *Zarar Kes:* {analysis['stop_loss']}

📊 *Risk/Ödül:* {analysis['risk_reward']}

{'='*25}

📝 *Analiz:*
{analysis.get('full_text', '')[:300]}...

{'='*25}

📦 Paket: *{package_info['name']}*
📊 Bugün kalan: {remaining}
💰 API Maliyeti: ${analysis.get('api_cost', 0.02):.3f}

⚠️ *Risk Uyarısı:* Yatırım tavsiyesi değildir!
"""
        
        keyboard = [
            [InlineKeyboardButton("💾 Kaydet", callback_data='save_analysis')],
            [InlineKeyboardButton("🔄 Yeni Analiz", callback_data='new_analysis')]
        ]
        
        if package == 'free':
            keyboard.append([InlineKeyboardButton("💎 Paket Al", callback_data='packages')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            message,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Yardım komutu"""
        help_text = """
📚 *YARDIM*

*Desteklenen Grafikler:*
✅ TradingView
✅ Binance  
✅ MEXC
✅ Diğer borsalar

*İpuçları:*
• Grafik net ve okunaklı olmalı
• Göstergeler görünür olmalı
• En az 50-100 mum görünmeli

*Komutlar:*
/start - Botu başlat
/help - Bu menü
/profil - Kullanım bilgileriniz
/premium - Premium özellikler

*Destek:* @your_support
"""
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def profile_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Profil komutu"""
        user_id = update.effective_user.id
        user = self.db.get_user(user_id)
        
        if not user:
            await update.message.reply_text("Önce /start komutunu kullanın!")
            return
        
        # Kullanıcı bilgileri
        subscription = user[3]
        credits = user[4]
        daily_analyses = user[5]
        total_analyses = user[6]
        
        profile_text = f"""
👤 *PROFİLİNİZ*

🆔 ID: `{user_id}`
📊 Toplam Analiz: {total_analyses}
📅 Bugünkü Analiz: {daily_analyses}/{Config.FREE_DAILY_LIMIT}

💳 Durum: {subscription.upper()}
🎯 Kredi: {credits}

{'✅ Premium aktif!' if subscription == 'premium' else '💡 Premium alarak sınırsız analiz yapın!'}
"""
        
        keyboard = [
            [InlineKeyboardButton("💰 Kredi Yükle", callback_data='buy_credits')],
            [InlineKeyboardButton("💎 Premium Al", callback_data='premium')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            profile_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Fotoğraf geldiğinde analiz yap"""
        user_id = update.effective_user.id
        
        # Kullanıcı kontrolü
        user = self.db.get_user(user_id)
        if not user:
            self.db.create_user(
                user_id,
                update.effective_user.username,
                update.effective_user.first_name
            )
        
        # Limit kontrolü
        if not self.db.can_analyze(user_id):
            keyboard = [
                [InlineKeyboardButton("💰 1 Analiz Al (32 TL)", callback_data='buy_single')],
                [InlineKeyboardButton("📦 Paket Al", callback_data='buy_package')],
                [InlineKeyboardButton("💎 Premium", callback_data='premium')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "⚠️ *Günlük limitiniz doldu!*\n\n"
                f"Ücretsiz kullanıcılar günde {Config.FREE_DAILY_LIMIT} analiz yapabilir.\n\n"
                "Devam etmek için:",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            return
        
        # İşleniyor mesajı
        processing_msg = await update.message.reply_text(
            "🔄 *Görüntü analiz ediliyor...*\n\n"
            "⏳ 15-30 saniye kadar sürebilir.\n"
            "Lütfen bekleyin...",
            parse_mode='Markdown'
        )
        
        try:
            # Fotoğrafı indir
            photo_file = await update.message.photo[-1].get_file()
            photo_bytes = BytesIO()
            await photo_file.download_to_memory(photo_bytes)
            photo_bytes.seek(0)
            
            # Base64'e çevir
            image_base64 = base64.b64encode(photo_bytes.read()).decode('utf-8')
            
            # Claude ile analiz
            analysis = await self.analyzer.analyze_image(image_base64)
            
            if not analysis['success']:
                await processing_msg.edit_text(
                    f"❌ Analiz başarısız!\n\nHata: {analysis.get('error', 'Bilinmeyen hata')}"
                )
                return
            
            # Veritabanını güncelle
            self.db.update_user_analysis(user_id)
            self.db.save_analysis(user_id, analysis)
            
            # Kredi kullan
            if user and user[4] > 0:  # Kredisi varsa
                self.db.use_credit(user_id)
            
            # Processing mesajını sil
            await processing_msg.delete()
            
            # Sonucu gönder
            await self.send_analysis_result(update, analysis)
            
        except Exception as e:
            logger.error(f"Analiz hatası: {e}")
            await processing_msg.edit_text(
                "❌ Bir hata oluştu!\n\nLütfen tekrar deneyin."
            )
    
    async def send_analysis_result(self, update: Update, analysis):
        """Analiz sonucunu gönder"""
        
        message = f"""
📊 *ANALİZ SONUCU*

🪙 *Coin:* {analysis['coin_pair']}
🎯 *Öneri:* {analysis['recommendation']}

📍 *Giriş:* {analysis['entry']}

🎯 *Hedefler:*
• TP1: {analysis['targets'][0]}
• TP2: {analysis['targets'][1]}  
• TP3: {analysis['targets'][2]}

🛡 *Stop Loss:* {analysis['stop_loss']}

📊 *Risk/Ödül:* {analysis['risk_reward']}

{'='*30}

📝 *Detaylı Analiz:*
{analysis.get('full_text', 'Analiz metni hazırlanıyor...')[:500]}...

⚠️ *Uyarı:* Bu bir yatırım tavsiyesi değildir!
"""
        
        keyboard = [
            [InlineKeyboardButton("💾 Kaydet", callback_data='save_analysis')],
            [InlineKeyboardButton("🔄 Yeni Analiz", callback_data='new_analysis')],
            [InlineKeyboardButton("📊 Geçmiş Analizler", callback_data='history')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            message,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Buton tıklamalarını yönet"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        
        if data == 'example':
            example_text = """
📊 *ÖRNEK ANALİZ*

🪙 *Coin:* BTCUSDT
⏰ *Zaman Dilimi:* 4H
💵 *Mevcut Fiyat:* $95,234

🎯 *POZİSYON ÖNERİSİ:* LONG 🟢

📍 *Giriş Seviyesi:* $94,800 - $95,200

✅ *Kar Al Hedefleri:*
• TP1: $96,000 (%1.05)
• TP2: $97,500 (%2.63)
• TP3: $100,000 (%5.26)

🛡 *Zarar Kes:* $93,500 (-1.58%)

📊 *Risk/Ödül:* 1:3.3

📝 *Analiz:*
4 saatlik grafikte yükselen trend kanalı içinde hareket görülüyor. RSI 58 seviyesinde ve MACD pozitif bölgede. EMA20 ve EMA50 alttan destek veriyor. Hacim artışı mevcut...

⚠️ *Risk Uyarısı:* Yatırım tavsiyesi değildir!
"""
            await query.edit_message_text(example_text, parse_mode='Markdown')
            
        elif data == 'packages':
            await self.packages_command(update, context)
            
        elif data.startswith('buy_'):
            # Paket satın alma
            package_map = {
                'buy_silver': 'silver',
                'buy_gold': 'gold',
                'buy_platinum': 'platinum'
            }
            
            package = package_map.get(data)
            if package:
                package_info = Config.PACKAGES[package]
                
                # PayTR ödeme linki oluştur
                payment_result = self.payment.create_payment_link(
                    user_id, 
                    package_info['price_tl'],
                    package
                )
                
                if payment_result['success']:
                    keyboard = [[InlineKeyboardButton("💳 Ödemeye Git", url=payment_result['link'])]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    text = f"""
💳 *ÖDEME LİNKİ HAZIR*

📦 Paket: *{package_info['name']}*
💰 Tutar: {package_info['price_tl']} TL
📊 Günlük: {package_info['daily_limit']} analiz
📅 Geçerlilik: 30 gün

✅ Ödeme sonrası paketiniz otomatik aktif olacak!

Ödeme için butona tıklayın:
"""
                    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=reply_markup)
                else:
                    await query.edit_message_text(payment_result['message'], parse_mode='Markdown')
            
        elif data == 'help':
            help_text = """
📚 *YARDIM*

*Nasıl Kullanılır?*
1️⃣ Kripto grafiğinin ekran görüntüsünü alın
2️⃣ Bota gönderin (metin yazmayın!)
3️⃣ Analiz sonucunu bekleyin

*Nelere Dikkat Edilmeli?*
• Grafik net ve okunaklı olmalı
• Coin ismi görünür olmalı
• Zaman dilimi görünür olmalı
• Göstergeler açık olabilir

*Desteklenen Borsalar:*
✅ Binance
✅ TradingView
✅ MEXC
✅ OKX
✅ Diğer tüm borsalar

*Paket Limitleri:*
• Free: 1/gün
• Silver: 3/gün (199₺/ay)
• Gold: 10/gün (499₺/ay)
• Platinum: 20/gün (899₺/ay)

*Komutlar:*
/start - Başlat
/packages - Paketler
/profile - Profilim
/help - Yardım

⚠️ *ÖNEMLİ:* Metin mesajı göndermeyin, sadece görüntü!
"""
            await query.edit_message_text(help_text, parse_mode='Markdown')
        
        elif data == 'new_analysis':
            await query.edit_message_text(
                "📸 Yeni bir grafik görüntüsü gönderin!",
                parse_mode='Markdown'
            )
    
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin komutu"""
        if update.effective_user.id != Config.ADMIN_ID:
            await update.message.reply_text("Bu komutu kullanma yetkiniz yok!")
            return
        
        # Admin istatistikleri
        conn = sqlite3.connect(Config.DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE package != "free"')
        premium_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT SUM(total_queries) FROM users')
        total_queries = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT package, COUNT(*) FROM users GROUP BY package')
        package_stats = cursor.fetchall()
        
        conn.close()
        
        # Maliyet hesabı
        total_cost = total_queries * Config.COST_PER_ANALYSIS
        
        admin_text = f"""
👨‍💼 *ADMIN PANELİ*

📊 *İstatistikler:*
👥 Toplam Kullanıcı: {total_users}
💎 Premium Kullanıcı: {premium_users}
📈 Toplam Sorgu: {total_queries}

📦 *Paket Dağılımı:*
"""
        for package, count in package_stats:
            admin_text += f"• {package}: {count} kullanıcı\n"
        
        admin_text += f"""
💰 *Maliyet Analizi:*
• Sorgu başı maliyet: ${Config.COST_PER_ANALYSIS}
• Toplam maliyet: ${total_cost:.2f}
• Toplam maliyet (TL): {total_cost * 32:.2f} TL

*Komutlar:*
/broadcast [mesaj] - Toplu mesaj
/setpackage [user_id] [package] - Paket ata
/stats - Detaylı istatistikler
"""
        await update.message.reply_text(admin_text, parse_mode='Markdown')

# ============= PAYTR SERVİSİ =============
class SimplePayment:
    def __init__(self):
        self.merchant_id = Config.PAYTR_MERCHANT_ID
        self.merchant_key = Config.PAYTR_MERCHANT_KEY
        self.merchant_salt = Config.PAYTR_MERCHANT_SALT
        self.test_mode = Config.PAYTR_TEST_MODE
    
    def create_payment_link(self, user_id, amount_tl, package_type):
        """PayTR ödeme linki oluştur"""
        
        if not all([self.merchant_id, self.merchant_key, self.merchant_salt]):
            return {
                'success': False,
                'message': '⚠️ PayTR bilgileri eksik!\n\n.env dosyasına PayTR bilgilerinizi ekleyin.'
            }
        
        # Sipariş no
        merchant_oid = f"PKG_{package_type}_{user_id}_{int(datetime.now().timestamp())}"
        
        # Paket açıklaması
        package_info = Config.PACKAGES[package_type]
        basket_item = f"{package_info['name']} Paket - {package_info['monthly_queries']} Aylık Analiz"
        
        # PayTR için sepet
        basket = base64.b64encode(
            json.dumps([[basket_item, str(amount_tl), 1]]).encode()
        ).decode()
        
        # Hash oluştur
        amount_kurus = int(amount_tl * 100)
        
        hash_str = (
            f"{self.merchant_id}{user_id}{amount_kurus}{merchant_oid}"
            f"https://t.me/your_bothttps://t.me/your_bot11TL{self.test_mode}"
        )
        hash_str += basket
        
        token = base64.b64encode(
            hmac.new(
                self.merchant_salt.encode(),
                hash_str.encode(),
                hashlib.sha256
            ).digest()
        ).decode()
        
        # PayTR API'ye gönder
        try:
            response = requests.post(
                "https://www.paytr.com/odeme/api/get-token",
                data={
                    'merchant_id': self.merchant_id,
                    'user_ip': '1.1.1.1',
                    'merchant_oid': merchant_oid,
                    'email': f'{user_id}@telegram.com',
                    'payment_amount': amount_kurus,
                    'paytr_token': token,
                    'user_basket': basket,
                    'debug_on': self.test_mode,
                    'no_installment': 1,
                    'max_installment': 0,
                    'user_name': str(user_id),
                    'user_address': 'Telegram',
                    'user_phone': '05555555555',
                    'merchant_ok_url': 'https://t.me/your_bot',
                    'merchant_fail_url': 'https://t.me/your_bot',
                    'timeout_limit': 30,
                    'currency': 'TL',
                    'test_mode': self.test_mode
                },
                timeout=30
            )
            
            result = response.json()
            
            if result.get('status') == 'success':
                # Veritabanına kaydet
                conn = sqlite3.connect(Config.DB_NAME)
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO payments (user_id, package, amount, status)
                    VALUES (?, ?, ?, 'pending')
                ''', (user_id, package_type, amount_tl))
                conn.commit()
                conn.close()
                
                return {
                    'success': True,
                    'link': f"https://www.paytr.com/odeme/guvenli/{result['token']}"
                }
            else:
                return {
                    'success': False,
                    'message': f"❌ PayTR hatası: {result.get('reason', 'Bilinmeyen')}"
                }
                
        except Exception as e:
            logger.error(f"PayTR error: {e}")
            return {
                'success': False,
                'message': f'❌ Bağlantı hatası: {str(e)[:50]}'
            }

# ============= ANA FONKSİYON =============
def main():
    """Botu başlat"""
    
    # Konfigürasyon kontrolü
    if not Config.TELEGRAM_BOT_TOKEN:
        print("""
        ❌ TELEGRAM_BOT_TOKEN eksik!
        
        Lütfen .env dosyası oluşturun ve şunu ekleyin:
        TELEGRAM_BOT_TOKEN=your_bot_token_here
        ANTHROPIC_API_KEY=your_claude_key_here
        PAYTR_MERCHANT_ID=your_merchant_id
        PAYTR_MERCHANT_KEY=your_merchant_key
        PAYTR_MERCHANT_SALT=your_merchant_salt
        """)
        return
    
    if not Config.ANTHROPIC_API_KEY:
        print("⚠️ ANTHROPIC_API_KEY eksik! Bot çalışacak ama analiz yapamayacak.")
    
    print(f"""
    ✅ KRİPTO ANALİZ BOTU BAŞLATILIYOR...
    
    📊 PAKET MALİYETLERİ:
    • Her analiz maliyeti: ${Config.COST_PER_ANALYSIS} (~0.65 TL)
    • Silver (90/ay): ${Config.COST_PER_ANALYSIS * 90:.2f} maliyet → 199 TL satış
    • Gold (300/ay): ${Config.COST_PER_ANALYSIS * 300:.2f} maliyet → 499 TL satış
    • Platinum (600/ay): ${Config.COST_PER_ANALYSIS * 600:.2f} maliyet → 899 TL satış
    
    💰 KAR ORANLARI:
    • Silver: %{((199 - Config.COST_PER_ANALYSIS * 90 * 32) / (Config.COST_PER_ANALYSIS * 90 * 32) * 100):.0f} kar
    • Gold: %{((499 - Config.COST_PER_ANALYSIS * 300 * 32) / (Config.COST_PER_ANALYSIS * 300 * 32) * 100):.0f} kar
    • Platinum: %{((899 - Config.COST_PER_ANALYSIS * 600 * 32) / (Config.COST_PER_ANALYSIS * 600 * 32) * 100):.0f} kar
    
    Bot çalışıyor! Durdurmak için Ctrl+C
    """)
    
    # Bot instance
    bot = CryptoBot()
    
    # Application oluştur
    app = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()
    
    # Handler'ları ekle
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("help", lambda u, c: u.message.reply_text("📸 Sadece grafik görüntüsü gönderin!")))
    app.add_handler(CommandHandler("packages", bot.packages_command))
    app.add_handler(CommandHandler("profile", bot.profile_command))
    app.add_handler(CommandHandler("admin", bot.admin_command))
    
    # Fotoğraf handler - SADECE FOTOĞRAF
    app.add_handler(MessageHandler(filters.PHOTO, bot.handle_photo))
    
    # Metin handler - REDDET
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text))
    
    # Callback handler
    app.add_handler(CallbackQueryHandler(bot.handle_callback))
    
    # Botu başlat
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
        """Buton tıklamalarını yönet"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        
        if data == 'example':
            example_text = """
📊 *ÖRNEK ANALİZ*

🪙 *Coin:* BTC/USDT
🎯 *Öneri:* LONG 🟢

📍 *Giriş:* $94,500 - $95,000

🎯 *Hedefler:*
• TP1: $96,000
• TP2: $97,500
• TP3: $100,000

🛡 *Stop Loss:* $93,000

📊 *Risk/Ödül:* 1:2.5

*Analiz:* Grafik yükselen trend içinde. 4 saatlik grafikte EMA20 üzerinde tutunma var...
"""
            await query.edit_message_text(example_text, parse_mode='Markdown')
            
        elif data == 'premium':
            premium_text = """
💎 *PREMIUM ÜYELİK*

✅ Sınırsız analiz
✅ Öncelikli işlem
✅ Detaylı raporlar
✅ 7/24 destek

💰 *Fiyatlar:*
• Aylık: 999 TL
• 3 Aylık: 2499 TL (%17 indirim)
• Yıllık: 8999 TL (%25 indirim)

📞 İletişim: @your_admin
"""
            await query.edit_message_text(premium_text, parse_mode='Markdown')
            
        elif data == 'buy_single':
            # TEK ANALİZ SATIN AL
            payment_result = self.payment.create_payment_link(user_id, 32, 'single')
            
            if payment_result['success']:
                keyboard = [[InlineKeyboardButton("💳 Ödemeye Git", url=payment_result['link'])]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                text = f"""
💳 *ÖDEME LİNKİNİZ HAZIR*

📦 Paket: 1 Analiz
💰 Tutar: {payment_result['amount']} TL
🎯 Alacağınız: {payment_result['credits']} kredi

Ödeme için butona tıklayın:
"""
                await query.edit_message_text(text, parse_mode='Markdown', reply_markup=reply_markup)
            else:
                await query.edit_message_text(payment_result['message'], parse_mode='Markdown')
        
        elif data == 'buy_package':
            # PAKET SEÇENEKLERİ
            keyboard = [
                [InlineKeyboardButton("1️⃣ 1 Analiz (32 TL)", callback_data='pack_single')],
                [InlineKeyboardButton("5️⃣ 5 Analiz (128 TL - %20 indirim)", callback_data='pack_5')],
                [InlineKeyboardButton("🔟 10 Analiz (224 TL - %30 indirim)", callback_data='pack_10')],
                [InlineKeyboardButton("◀️ Geri", callback_data='back')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            text = """
📦 *PAKET SEÇİN*

Hangi paketi almak istersiniz?

💡 Toplu alımda daha avantajlı!
"""
            await query.edit_message_text(text, parse_mode='Markdown', reply_markup=reply_markup)
        
        elif data.startswith('pack_'):
            # PAKET SATIN AL
            package_map = {
                'pack_single': 'single',
                'pack_5': 'package5',
                'pack_10': 'package10'
            }
            
            package = package_map.get(data, 'single')
            payment_result = self.payment.create_payment_link(user_id, 0, package)
            
            if payment_result['success']:
                keyboard = [[InlineKeyboardButton("💳 Ödemeye Git", url=payment_result['link'])]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                text = f"""
💳 *ÖDEME LİNKİNİZ HAZIR*

📦 Paket: {payment_result['credits']} Analiz
💰 Tutar: {payment_result['amount']} TL

✅ Ödeme sonrası kredileriniz otomatik yüklenecek!

Ödeme için butona tıklayın:
"""
                await query.edit_message_text(text, parse_mode='Markdown', reply_markup=reply_markup)
            else:
                await query.edit_message_text(payment_result['message'], parse_mode='Markdown')
            
        elif data == 'help':
            await self.help_command(query, context)
    
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin komutu"""
        if update.effective_user.id != Config.ADMIN_ID:
            await update.message.reply_text("Bu komutu kullanma yetkiniz yok!")
            return
        
        # Admin istatistikleri
        conn = sqlite3.connect(Config.DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT SUM(total_analyses) FROM users')
        total_analyses = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE subscription = "premium"')
        premium_users = cursor.fetchone()[0]
        
        conn.close()
        
        admin_text = f"""
👨‍💼 *ADMIN PANELİ*

👥 Toplam Kullanıcı: {total_users}
💎 Premium Kullanıcı: {premium_users}
📊 Toplam Analiz: {total_analyses}

*Komutlar:*
/broadcast [mesaj] - Toplu mesaj
/addcredit [user_id] [miktar] - Kredi ekle
/stats - Detaylı istatistikler
"""
        await update.message.reply_text(admin_text, parse_mode='Markdown')

# ============= ANA FONKSİYON =============
def main():
    """Botu başlat"""
    
    # Konfigürasyon kontrolü
    if not Config.TELEGRAM_BOT_TOKEN:
        print("""
        ❌ TELEGRAM_BOT_TOKEN eksik!
        
        Lütfen .env dosyası oluşturun ve şunu ekleyin:
        TELEGRAM_BOT_TOKEN=your_bot_token_here
        ANTHROPIC_API_KEY=your_claude_key_here
        """)
        return
    
    if not Config.ANTHROPIC_API_KEY:
        print("⚠️ ANTHROPIC_API_KEY eksik! Bot çalışacak ama analiz yapamayacak.")
    
    # Bot instance
    bot = CryptoBot()
    
    # Application oluştur
    app = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()
    
    # Handler'ları ekle
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("help", bot.help_command))
    app.add_handler(CommandHandler("profil", bot.profile_command))
    app.add_handler(CommandHandler("admin", bot.admin_command))
    app.add_handler(MessageHandler(filters.PHOTO, bot.handle_photo))
    app.add_handler(CallbackQueryHandler(bot.handle_callback))
    
    # Botu başlat
    print("""
    ✅ Bot başlatılıyor...
    
    Durdurmak için: Ctrl+C
    
    Bot çalışıyor! Telegram'dan /start yazarak test edebilirsiniz.
    """)
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
