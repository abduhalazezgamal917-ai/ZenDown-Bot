# ZenDown Bot — دليل التشغيل والإعداد

بوت تيليجرام لتحميل الفيديوهات من أبرز المنصات مع دعم استخراج الصوت والدفع عبر Telegram Stars.

---

## المنصات المدعومة
| المنصة | الاستراتيجية الأولى | الاحتياط |
|---|---|---|
| 🎵 تيك توك | tikwm API | yt-dlp |
| 📸 إنستغرام | fastdl.to API | yt-dlp |
| ▶️ يوتيوب | yt-dlp مباشرة | — |
| 𝕏 تويتر/X | vxtwitter API | yt-dlp |
| 👻 سناب شات | yt-dlp | snapsave.app |
| 📌 بينترست | yt-dlp مباشرة | — |

---

## المتغيرات البيئية المطلوبة (Replit Secrets)

| المتغير | الوصف | مطلوب |
|---|---|---|
| `BOT_TOKEN` | رمز بوت تيليجرام من @BotFather | ✅ ضروري |
| `ADMIN_ID` | رقم معرف المشرف (Telegram user ID) | ✅ ضروري |
| `BOT_USERNAME` | اسم المستخدم بدون @ | اختياري |
| `PORT` | منفذ خادم الصحة (افتراضي: 8080) | اختياري |

---

## التشغيل

### عبر Replit Workflow
اضغط زر **▶️ Run** أو شغّل workflow **"ZenDown Bot"**

### من سطر الأوامر
```bash
cd zendown-bot
python3 bot.py
```

---

## نظام الـ Uptime (ثلاث طبقات)

### Layer 1 — Watchdog داخلي
- إعادة تشغيل تلقائية عند الانهيار (حتى 100 محاولة)
- تأخير 5 ثوانٍ بين كل محاولة

### Layer 2 — خادم HTTP
- `GET /health` — معلومات تفصيلية (JSON)
- `GET /ping`   — رد سريع لـ UptimeRobot

### Layer 3 — UptimeRobot
1. سجّل في https://uptimerobot.com (مجاناً)
2. أضف Monitor جديد:
   - **النوع**: HTTP(S)
   - **الرابط**: `https://<نطاق-replit>/ping`
   - **الفترة**: 5 دقائق
3. فعّل التنبيهات عبر تيليجرام أو البريد الإلكتروني

---

## نظام الدفع — Telegram Stars (XTR)

| الخطة | السعر | المدة |
|---|---|---|
| تحميل واحد 💳 | 75 ⭐ | 24 ساعة |
| أسبوعي 📅 | 200 ⭐ | 7 أيام |
| شهري 🗓️ | 500 ⭐ | 30 يوم |

### إعداد الدفع
1. افتح @BotFather وأرسل `/mybots`
2. اختر البوت ← **Payments**
3. فعّل **Telegram Stars**
4. البوت جاهز للدفع تلقائياً

---

## البنية الهيكلية

```
zendown-bot/
├── bot.py                        # نقطة الدخول + watchdog + تسجيل المعالجات
├── settings.py                   # إعدادات مستمرة (قناة + force_join)
├── ui.py                         # نصوص وأزرار واجهة المستخدم
├── requirements.txt
├── core/
│   ├── config.py                 # ثوابت + متغيرات البيئة
│   └── exceptions.py             # استثناءات مخصصة
├── handlers/
│   ├── callbacks.py              # تحميل + دفع + أزرار inline
│   ├── commands.py               # /start /stats /setchannel /forcejoin
│   ├── errors.py                 # معالج الأخطاء العام
│   ├── messages.py               # عرض أزرار الاختيار عند استلام رابط
│   └── middleware.py             # فحص الاشتراك الإجباري
├── services/
│   ├── audio_service.py          # تحويل MP4→MP3 عبر ffmpeg
│   ├── cache.py                  # كاش TTL في الذاكرة
│   ├── download_service.py       # تحميل من المنصات (multi-strategy)
│   ├── payment_service.py        # Telegram Stars + اشتراكات
│   ├── queue_manager.py          # Semaphore + حد لكل مستخدم
│   ├── rate_limiter.py           # Sliding Window Rate Limiter
│   ├── stats.py                  # إحصائيات مستمرة (JSON)
│   └── uptime_server.py          # خادم HTTP /health /ping
└── utils/
    ├── logging_setup.py          # إعداد السجلات الهيكلي
    ├── retry.py                  # async_retry + Exponential Backoff
    └── validators.py             # فحص الروابط + منع SSRF
```

---

## تدفق المستخدم الجديد

```
المستخدم يرسل رابط
       ↓
بوابة الاشتراك الإجباري
       ↓
فحص Rate Limit
       ↓
التحقق من الرابط وتعقيمه
       ↓
تخزين الرابط في bot_data
       ↓
عرض: [ 🎧 موسيقى ]  [ 📺 فيديو ]
       ↓              ↓
  تحميل MP4      تحميل MP4
  تحويل MP3      إرسال مباشر
       ↓              ↓
     فحص حجم الملف (50MB)
       ↓
  ≤50MB → إرسال مجاني
  >50MB + اشتراك → إرسال
  >50MB + لا اشتراك → عرض خيارات الدفع
```
