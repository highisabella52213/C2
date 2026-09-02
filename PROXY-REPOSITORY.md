# مخزن خصوصی پروکسی — v15

مخزن با AWS Signature Version 4 مستقیماً از S3-compatible خوانده می‌شود. هیچ اطلاعات اتصال باکت یا endpoint پروکسی به مرورگر ارسال نمی‌شود.

## تنظیم iDrive E2 در کد

فایل `proxy_repository.py` را باز و بخش `PRIVATE S3 CONFIGURATION` را پیدا کنید. Endpoint، Region، Bucket و Object Key از قبل تنظیم شده‌اند:

```python
S3_ENDPOINT = "https://s3.us-west-2.idrivee2.com"
S3_REGION = "us-west-2"
S3_BUCKET = "bt2"
S3_OBJECT_KEY = "www-32k-ort-org-021/proxy.txt"
```

فقط این دو placeholder را با مقادیر واقعی عوض کنید:

```python
S3_ACCESS_KEY_ID = "KEY_ID"
S3_SECRET_ACCESS_KEY = "SECRET_ACCESS"
```

برای امنیت انتقال، Endpoint عمداً از HTTPS استفاده می‌کند. کلید باید فقط مجوز `GetObject` برای همین شیء را داشته باشد و مجوز نوشتن/حذف نداشته باشد.

## قالب proxy.txt

```text
http://1.2.3.4:8080#Finland - 75%
socks5://user:pass@1.2.3.4:8181#DE|Germany - 32%
https://proxy.example.com:443#US - 91%
```

بررسی خودکار هنگام startup و سپس هر ۲ ساعت انجام می‌شود. اگر fetch جدید شکست بخورد، آخرین لیست سالم در حافظه حفظ می‌شود.

## فعال‌کردن دکمه «بررسی جدید»

نام Variable در Railway:

```text
PROXY_REPOSITORY_MANUAL_REFRESH_KEY
```

یک مقدار تصادفی طولانی انتخاب کنید و SHA-256 آن را بسازید:

```bash
python tools/hash_manual_refresh_key.py 'YOUR-LONG-RANDOM-SECRET'
```

خروجی را در `proxy_repository.py` جایگزین این مقدار کنید:

```python
MANUAL_REFRESH_TOKEN_SHA256 = "PASTE_SHA256_OF_RAILWAY_SECRET_HERE"
```

سپس مقدار خام `YOUR-LONG-RANDOM-SECRET` را به Variable بالا در Railway بدهید. فقط در صورت تطابق امن هش‌ها، دکمه **بررسی جدید** در پنل ظاهر می‌شود. خود endpoint بررسی دستی نیز سمت سرور 403 می‌دهد؛ مخفی‌کردن دکمه تنها کنترل امنیتی نیست.

> چون برنامه برای امضای S3 به Access Key و Secret Key نیاز دارد، اگر آن‌ها مستقیم داخل سورس باشند از دارنده کامل سورس قابل مخفی‌کردن نیستند. برای کاهش ریسک، کلید read-only و محدود به همان object بسازید.
