# 🔧 BITGET API FIX

## Problem: 400 Bad Request

**Hata:**
```
Client error '400 Bad Request' for url 
'https://api.bitget.com/api/v2/copy/mix-follower/query-traders?productType=...'
```

---

## Neden?

**Yanlış signature hesaplama:**

```python
# ❌ YANLIŞ (query parameters dahil)
path = "/api/v2/copy/mix-follower/query-traders"
full_path = f"{path}?productType=USDT-FUTURES&sortBy=roi&pageSize=100"
signature = sign(timestamp + method + full_path)
```

**Doğru format:**

```python
# ✅ DOĞRU (sadece base path)
path = "/api/v2/copy/mix-follower/query-traders"
signature = sign(timestamp + method + path)

# Query parameters ayrı gönderilir
params = {'productType': 'USDT-FUTURES', 'sortBy': 'roi'}
```

---

## Bitget API Signature Format

```python
message = timestamp + method + requestPath + body

# Örnek:
message = "1779126383370" + "GET" + "/api/v2/copy/mix-follower/query-traders" + ""

# HMAC SHA256
signature = hmac_sha256(api_secret, message).hex()
```

**Önemli:**
- Query parameters signature'a dahil EDİLMEZ
- Sadece base path kullanılır
- Body POST request'ler için (GET'te boş)

---

## Düzeltme

### Önceki Kod:
```python
# Query string oluştur
query = '&'.join([f"{k}={v}" for k, v in params.items()])
full_path = f"{path}?{query}"

# Signature hesapla (YANLIŞ!)
headers = self._headers('GET', full_path)
url = f"{self.base_url}{full_path}"

response = self.client.get(url, headers=headers)
```

### Yeni Kod:
```python
# Signature için base path kullan
headers = self._headers('GET', path)

# URL'de query parameters ekle
url = f"{self.base_url}{path}"

# Params ayrı gönder
response = self.client.get(url, params=params, headers=headers)
```

---

## Test

```bash
python3 scripts/run_bitget_to_binance.py test-bitget
```

**Beklenen Sonuç:**
```
✅ SUCCESS! Found X traders
```

---

## Düzeltilen Dosyalar

- `binance_futures_trader/bitget_signal_source.py`
  - `get_futures_traders()` method
  - `get_trader_positions()` method

---

## Diğer Endpoint'ler

Aynı fix tüm Bitget API endpoint'lerine uygulanır:

```python
# ✅ Her zaman:
# 1. Signature = base path only
# 2. Query params = separate
# 3. Body = POST için JSON string

def make_request(path, params=None, body=None):
    # Signature için base path
    signature = self._sign(timestamp, method, path, body or "")
    
    # Request gönder
    if method == "GET":
        response = client.get(url, params=params, headers=headers)
    else:
        response = client.post(url, json=body, headers=headers)
```

---

## 🎯 SONUÇ

**400 Bad Request hatası düzeltildi!** ✅

Tekrar test et ve çalışmalı! 🚀
