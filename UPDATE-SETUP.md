# راه‌اندازی آپدیت خودکار پنل — v17

## چرا دو Token لازم است؟

Railway account token فقط می‌تواند Deployment را مدیریت کند و اجازه تغییر GitHub Fork را ندارد. برای آپدیت واقعی، پنل ابتدا Fork کاربر را با Upstream همگام می‌کند؛ بنابراین یک GitHub fine-grained token نیز لازم است. Redeploy ساده Railway همان Commit قبلی را دوباره اجرا می‌کند و نسخه را تغییر نمی‌دهد.

## مراحل اولین ورود

بعد از اولین ورود به Dashboard، پنجره **Secure version updates** خودکار باز می‌شود:

1. **Your connected fork**: ریپازیتوری متصل به Railway با قالب `owner/repository`.
2. **Publisher repository**: اختیاری؛ اگر خالی باشد از parent همان Fork تشخیص داده می‌شود.
3. **Fork branch**: معمولاً `main`.
4. **Railway account token**: از `https://railway.com/account/tokens`.
5. **GitHub fine-grained token**: فقط برای همان Fork، با دسترسی `Contents: Read and write`.
6. روی **Save and verify** بزنید.

Railway باید متغیرهای داخلی `RAILWAY_SERVICE_ID` و `RAILWAY_ENVIRONMENT_ID` را در Runtime ارائه کند؛ برنامه آن‌ها را خودکار استفاده می‌کند.

## انتشار نسخه توسط مالک

1. مقدار `CURRENT_VERSION` در `updater.py` را افزایش دهید.
2. تغییرات را در branch اصلی Publisher منتشر کنید.
3. در همان ریپازیتوری یک GitHub Release با Tag استاندارد مانند `v17.1.0` بسازید.
4. کاربران در ورود بعدی به پنل، دکمه **Update to v17.1.0** را خواهند دید. پنل هر ۱۵ دقیقه نیز دوباره بررسی می‌کند.

## روند امن Update

1. دریافت آخرین GitHub Release.
2. اعتبارسنجی مجدد اینکه Repository کاربر واقعاً Fork همان Publisher است.
3. اجرای GitHub `merge-upstream` بدون Force push.
4. توقف با خطای قابل‌نمایش در صورت Merge conflict.
5. دریافت SHA شاخه Fork بعد از Sync.
6. اجرای Railway `serviceInstanceDeployV2` با همان SHA در Service و Environment فعلی.

## نگهداری Token

- Tokenها با Fernet و کلیدی مشتق‌شده از `SECRET_KEY` رمزگذاری می‌شوند.
- هیچ API مقدار Token را به Browser برنمی‌گرداند.
- Tokenها در Log نوشته نمی‌شوند.
- فایل رمز‌شده `lumen_update.json` در `DATA_DIR` قرار می‌گیرد؛ برای ماندگاری حتماً Railway Volume را روی `/data` متصل کنید.
- Account token دسترسی گسترده دارد؛ یک Token اختصاصی بسازید، آن را در جای دیگری استفاده نکنید و در صورت افشا فوراً Rotate کنید.
- از Settings می‌توانید Setup ذخیره‌شده را حذف کنید.

## نکته مهم

اگر Fork تغییرات محلی متعارض داشته باشد، پنل آن را بازنویسی نمی‌کند. Update متوقف می‌شود تا Conflict به‌صورت دستی حل شود. این رفتار عمداً برای جلوگیری از حذف کد یا تنظیمات کاربر است.
