import os
import sys

# إجبار بايثون على قراءة المجلد الحالي كمسار رئيسي
base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base_dir)

if __name__ == "__main__":
    print("جاري تشغيل البوت الأساسي...")
    import bot

