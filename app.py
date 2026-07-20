import os
import sys

# إضافة المجلد الحالي للمسارات لحل مشكلة استيراد core
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# تشغيل البوت الأساسي
if __name__ == "__main__":
    import bot
    bot.main()
