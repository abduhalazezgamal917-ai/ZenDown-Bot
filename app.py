import os
import sys

# الخدعة: إيهام النظام بأن الواجهة الرئيسية هي نفسها مجلد core
base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base_dir)

# صنع مجلد وهمي في الذاكرة باسم core لتوجيه الاستدعاءات إليه
import types
core_module = types.ModuleType('core')
sys.modules['core'] = core_module

# ربط ملفات الإعدادات والوظائف المبعثرة بالمجلد الوهمي
try:
    import config
    core_module.config = config
except ImportError:
    pass

try:
    import exceptions
    core_module.exceptions = exceptions
except ImportError:
    pass

if __name__ == "__main__":
    print("...جاري تشغيل البوت الأساسي بالخطة البديلة")
    import bot
