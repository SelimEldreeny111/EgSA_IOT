// English / Arabic interface. Pages render English; when Arabic is active, a MutationObserver
// translates interface text in place (exact phrases, then patterns for dynamic phrases) and the
// document switches to right-to-left. Data (names, IDs, values, logs) is never translated.
// Elements can opt out with data-i18n-skip. Add a language by adding a dictionary below.

const KEY = "wiot.lang";
export const I18N = { lang: "en" };
export const LANGS = { en: "English", ar: "العربية" };

const AR = {
  // ---- shell
  "WIOT Control Center": "مركز تحكم WIOT", "Smart farm": "المزرعة الذكية", "World operations": "العمليات العالمية",
  "Fleet overview": "نظرة عامة على الأسطول", "Command center": "مركز الأوامر", "Data science": "علم البيانات",
  "Message history": "سجل الرسائل", "Organization": "المؤسسة", "Administration": "الإدارة",
  "API documentation": "توثيق واجهة البرمجة", "Sign out": "تسجيل الخروج",
  "Smart agriculture & irrigation · soil, flow & valve control · LoRa → cellular / satellite": "الزراعة والري الذكي · التحكم في التربة والتدفق والمحابس · من LoRa إلى الشبكة الخلوية والأقمار الصناعية",
  "Fleet status": "حالة الأسطول", "MQTT broker": "وسيط MQTT", "Tenant": "الشركة", "Company": "الشركة", "Region": "المنطقة",
  "Local time": "الوقت المحلي", "View": "العرض", "Language": "اللغة", "Night": "ليلي", "Day": "نهاري",
  "Night / Day view": "العرض الليلي / النهاري", "Switch between night and day view": "التبديل بين العرض الليلي والنهاري",
  "supervisor": "مشرف عام", "admin": "مسؤول", "monitor": "مراقب", "user": "مستخدم",
  "READY": "جاهز", "DISCONNECTED": "غير متصل", "CONNECTING": "جارٍ الاتصال", "UNKNOWN": "غير معروف",
  "Loading…": "جارٍ التحميل…", "Session expired": "انتهت الجلسة",
  "Operations": "العمليات", "Insights": "التحليلات", "Settings": "الإعدادات", "Collapse": "طي القائمة", "Control Center": "مركز التحكم",
  "online": "متصل", "MQTT": "MQTT", "Ready": "جاهز", "Disconnected": "غير متصل", "Connecting": "جارٍ الاتصال", "Reconnecting": "إعادة الاتصال",
  "Nodes online in this region": "العقد المتصلة في هذه المنطقة", "Local time of the selected company": "الوقت المحلي للشركة المحددة",
  "Collapse sidebar": "طي الشريط الجانبي",
  "Monitoring node": "عقدة مراقبة", "Control node": "عقدة تحكم", "Monitoring": "مراقبة", "Control": "تحكم", "Unregistered": "غير مسجلة",
  "Node type": "نوع العقدة", "Type": "النوع", "Sensors": "المستشعرات", "Sensors fitted": "المستشعرات المركبة", "Sensors detected": "المستشعرات المكتشفة",
  "All types": "جميع الأنواع", "No valve": "لا يوجد محبس", "Target moisture band": "نطاق الرطوبة المستهدف",
  "Sensors only — reports soil, flow and salinity readings. Cannot receive valve commands.": "مستشعرات فقط — ترسل قراءات التربة والتدفق والملوحة. لا تستقبل أوامر المحبس.",
  "Sensors + valve — reports readings and opens / closes its valve (manual commands and automatic irrigation).": "مستشعرات + محبس — ترسل القراءات وتفتح محبسها وتغلقه (أوامر يدوية وري تلقائي).",
  "HNDA soil moisture & temperature": "مجس HNDA لرطوبة التربة وحرارتها", "Sondas EC (salinity) probe": "مجس Sondas للموصلية (الملوحة)",
  "TUF-2000B ultrasonic flow meter": "عداد تدفق فوق صوتي TUF-2000B", "Supmea electromagnetic flow meter": "عداد تدفق كهرومغناطيسي Supmea",
  "HNDA soil": "تربة HNDA", "Sondas EC": "Sondas EC", "TUF flow": "تدفق TUF", "Supmea flow": "تدفق Supmea",
  "Detected automatically from the node's sensor mask when it has reported.": "تُكتشف تلقائيًا من قناع المستشعرات عند إرسال العقدة لبياناتها.",
  "Used for irrigation advice and alerts on this monitored field.": "يُستخدم لتوصيات الري والتنبيهات في هذا الحقل المراقَب.",
  "monitoring node · sensors only": "عقدة مراقبة · مستشعرات فقط",
  "Sensors only — this field's node has no valve. Irrigation for it is not controlled from WIOT; use a control node to automate it.": "مستشعرات فقط — لا يوجد محبس على عقدة هذا الحقل. لا يتم التحكم في ريّه من WIOT؛ استخدم عقدة تحكم لأتمتته.",
  // ---- sign-in
  "WIOT Sign In": "تسجيل الدخول إلى WIOT", "Sign in": "تسجيل الدخول", "Username": "اسم المستخدم", "Password": "كلمة المرور",
  "Smart agriculture & irrigation · water-IoT operations": "الزراعة والري الذكي · عمليات إنترنت الأشياء للمياه",
  "Sessions are signed tokens · repeated failures are rate-limited": "الجلسات موقّعة رقميًا · تُقيَّد المحاولات المتكررة الفاشلة",
  "Sign-in failed": "فشل تسجيل الدخول", "Invalid username or password": "اسم المستخدم أو كلمة المرور غير صحيحة",
  // ---- status words / badges
  "Online": "متصل", "Late": "متأخر", "Offline": "غير متصل", "ONLINE": "متصل", "OFFLINE": "غير متصل", "LATE": "متأخر", "LIVE": "مباشر", "ALL": "الكل",
  "Acknowledged": "تم التأكيد", "Rejected": "مرفوض", "No reply": "لا رد", "Superseded": "استُبدل", "Pending": "قيد الانتظار",
  "Dispatched": "أُرسل", "Retry queued": "إعادة المحاولة مجدولة", "Expired": "منتهي الصلاحية", "Partial": "جزئي",
  "Active": "نشط", "Archived": "مؤرشف", "Strict": "صارم", "Paused": "متوقف مؤقتًا", "Revoked": "ملغى",
  "Read only": "قراءة فقط", "Read & write": "قراءة وكتابة", "Primary": "أساسي", "Standby": "احتياطي", "Ready · roadmap": "جاهز · ضمن الخطة",
  "not fitted": "غير مركّب", "n/a": "غير متاح", "Fits": "مناسب", "Auto": "تلقائي", "Manual": "يدوي", "Idle": "خامل",
  "Open": "مفتوح", "Closed": "مغلق", "Fault": "عطل", "Unknown": "غير معروف", "OPEN": "فتح", "CLOSE": "إغلاق", "CLOSED": "مغلق",
  "NORMAL": "عادي", "never": "أبدًا", "Awaiting first uplink": "بانتظار أول إرسال", "No nodes": "لا توجد عقد",
  "Strict provisioning": "تسجيل صارم", "Open provisioning": "تسجيل مفتوح",
  // ---- farm
  "Avg soil moisture": "متوسط رطوبة التربة", "Irrigating now": "يُروى الآن", "Need attention": "تحتاج انتباهًا",
  "Water applied today": "المياه المستخدمة اليوم", "Reference ET₀ today": "البخر-نتح المرجعي اليوم", "Weather now": "الطقس الآن",
  "FAO-56 Penman–Monteith": "معادلة FAO-56 بنمان-مونتيث", "weather offline": "الطقس غير متاح", "Weather unavailable": "الطقس غير متاح",
  "Soil moisture": "رطوبة التربة", "Salinity (EC)": "الملوحة (EC)", "Soil temp": "حرارة التربة", "Irrigation": "الري",
  "Edit positions": "تعديل المواقع", "Save positions": "حفظ المواقع", "Cancel": "إلغاء",
  "Below target": "أقل من المستهدف", "In target band": "ضمن النطاق المستهدف", "Above target": "أعلى من المستهدف",
  "Node offline": "العقدة غير متصلة", "No data": "لا توجد بيانات", "Probe fault": "عطل في المجس", "Soil probe ·": "مجس التربة ·",
  "Soil probe": "مجس التربة", "Gateway": "البوابة", "Probes": "المجسات", "LoRa GW": "بوابة LoRa", "WIOT": "WIOT",
  "Cellular": "خلوي", "Satellite IoT": "إنترنت الأشياء عبر الأقمار الصناعية", "Satellite": "قمر صناعي", "Wi-Fi": "واي فاي", "Ethernet": "إيثرنت", "LoRa": "LoRa",
  "Irrigation plan · all fields": "خطة الري · جميع الحقول", "Weather & evapotranspiration · 7 days": "الطقس والبخر-نتح · 7 أيام",
  "Connectivity & satellite backhaul readiness": "الاتصال وجاهزية الربط عبر الأقمار الصناعية",
  "Field": "الحقل", "Crop": "المحصول", "Soil moisture vs target": "رطوبة التربة مقابل المستهدف", "Status": "الحالة",
  "Valve": "المحبس", "Flow m³/h": "التدفق م³/س", "Today m³": "اليوم م³", "Advice": "التوصية",
  "Select a field on the map": "اختر حقلًا على الخريطة", "Soil moisture · 24 h": "رطوبة التربة · 24 ساعة", "Irrigation flow · 24 h": "تدفق الري · 24 ساعة",
  "No moisture samples in 24 h": "لا توجد قراءات رطوبة خلال 24 ساعة", "No flow in 24 h": "لا يوجد تدفق خلال 24 ساعة",
  "Soil temp ": "حرارة التربة", "Flow now": "التدفق الآن", "Water today": "مياه اليوم", "Crop ET today": "بخر-نتح المحصول اليوم",
  "Battery · probe": "البطارية · المجس", "Start irrigation": "بدء الري", "Stop": "إيقاف", "Automatic irrigation": "الري التلقائي",
  "Opens the valve below the band, closes it above — through the audited command journal.": "يفتح المحبس تحت النطاق ويغلقه فوقه — عبر سجل الأوامر المدقق.",
  "Min %": "الحد الأدنى %", "Max %": "الحد الأقصى %", "Save": "حفظ", "Read-only role": "دور للقراءة فقط", "Irrigating": "جارٍ الري",
  "Irrigating (pivot arm turning)": "جارٍ الري (ذراع الري المحوري يدور)", "Satellite budget": "ميزانية القمر الصناعي", "msgs/node/day": "رسالة/عقدة/يوم",
  "Readiness checklist": "قائمة الجاهزية", "Node": "العقدة", "Path": "المسار", "Link": "الاتصال", "Reports/day": "تقارير/يوم",
  "Avg payload B": "متوسط الحمولة (بايت)", "Avg frame B": "متوسط الإطار (بايت)", "Bytes/day": "بايت/يوم",
  "LoRa 433 MHz · WOR": "LoRa 433 ميجاهرتز · WOR", "WIOT Platform": "منصة WIOT", "MQTT · journal · analytics": "MQTT · السجل · التحليلات",
  "STM32 · AES-128": "STM32 · AES-128",
  "Satellite IoT links deliver small messages with minutes of latency and a daily message budget. WIOT already stores and forwards samples, queues commands for sleeping nodes and reconciles late ACKs — so the same firmware and server can switch backhaul without redesign.":
    "تنقل روابط إنترنت الأشياء عبر الأقمار الصناعية رسائل صغيرة بتأخير دقائق وبميزانية يومية من الرسائل. يقوم WIOT بالفعل بتخزين العينات وتمريرها، وجدولة الأوامر للعقد النائمة، ومطابقة الإقرارات المتأخرة — لذا يمكن للبرنامج الثابت والخادم نفسيهما تبديل وسيلة الربط دون إعادة تصميم.",
  "Store-and-forward on the node": "التخزين والتمرير على العقدة", "Sleep-aware command delivery": "تسليم الأوامر مع مراعاة السكون",
  "Compact encrypted frames": "إطارات مشفرة مدمجة", "Latency-tolerant acknowledgements": "إقرارات تتحمل التأخير",
  "Delivery-risk scoring before send": "تقييم مخاطر التسليم قبل الإرسال",
  "Clear": "صافٍ", "Mainly clear": "صافٍ غالبًا", "Partly cloudy": "غائم جزئيًا", "Overcast": "غائم", "Fog": "ضباب", "Rime fog": "ضباب متجمد",
  "Light drizzle": "رذاذ خفيف", "Drizzle": "رذاذ", "Dense drizzle": "رذاذ كثيف", "Light rain": "مطر خفيف", "Rain": "مطر", "Heavy rain": "مطر غزير",
  "Light snow": "ثلج خفيف", "Rain showers": "زخات مطر", "Violent showers": "زخات عنيفة", "Thunderstorm": "عاصفة رعدية",
  "Rain mm": "المطر مم", "ET₀ mm": "البخر-نتح مم", "Rain (mm/day)": "المطر (مم/يوم)", "Reference ET₀ (mm/day)": "البخر-نتح المرجعي (مم/يوم)",
  "Rain in": "المطر بوصة", "ET₀ in": "البخر-نتح بوصة", "Rain (in/day)": "المطر (بوصة/يوم)", "Reference ET₀ (in/day)": "البخر-نتح المرجعي (بوصة/يوم)",
  "Temperature °F": "الحرارة °ف",
  "Wheat": "قمح", "Maize": "ذرة", "Alfalfa": "برسيم", "Potato": "بطاطس", "Sugar beet": "بنجر السكر", "Tomato": "طماطم",
  "Vegetables": "خضروات", "Olive": "زيتون", "Date palm": "نخيل", "Citrus": "موالح", "Other": "أخرى",
  "Above target band — no irrigation needed.": "فوق النطاق المستهدف — لا حاجة للري.", "Within target band — no action.": "ضمن النطاق المستهدف — لا يلزم إجراء.",
  "Node offline — last reading may be stale; verify the link before acting.": "العقدة غير متصلة — قد تكون آخر قراءة قديمة؛ تحقق من الاتصال قبل اتخاذ أي إجراء.",
  "Soil probe reports no valid moisture value — inspect the sensor.": "مجس التربة لا يرسل قيمة رطوبة صالحة — افحص المستشعر.",
  "Above target band while irrigating — stop to avoid leaching and waterlogging.": "فوق النطاق المستهدف أثناء الري — أوقف الري لتجنب الغسل والتشبع بالمياه.",
  "No uplink from this zone's node yet.": "لم ترسل عقدة هذا الحقل أي بيانات بعد.",
  // farm set-up
  "Farm details": "تفاصيل المزرعة", "Farm name": "اسم المزرعة", "Location": "الموقع", "Gateway position · latitude, longitude": "موقع البوابة · خط العرض، خط الطول",
  "Place": "تحديد", "Field radius · m": "نصف قطر الحقل · م", "Moisture target · %": "الرطوبة المستهدفة · %", "Fields · one per node": "الحقول · حقل لكل عقدة",
  "Gateway backhaul": "وسيلة ربط البوابة", "Satellite-ready": "جاهز للأقمار الصناعية", "Save farm layout": "حفظ مخطط المزرعة",
  "Advanced · paste a layout JSON": "متقدم · لصق مخطط بصيغة JSON", "Validate & save JSON": "تحقق واحفظ JSON", "Open the demo farm": "فتح المزرعة التجريبية",
  "Open overview": "فتح النظرة العامة", "Farm layout saved": "تم حفظ مخطط المزرعة", "Layout saved": "تم حفظ المخطط", "Step 1": "الخطوة 1", "Step 2": "الخطوة 2",
  "e.g. East Owainat, New Valley, Egypt": "مثال: شرق العوينات، الوادي الجديد، مصر", "Farm gateway": "بوابة المزرعة", "to": "إلى",
  "Drag probes and gateways, then save": "اسحب المجسات والبوابات ثم احفظ", "Enter latitude and longitude in decimal degrees": "أدخل خط العرض وخط الطول بالدرجات العشرية",
  "The moisture target needs a lower value on the left": "يجب أن تكون القيمة اليسرى للرطوبة المستهدفة أقل",
  // ---- overview
  "Fleet Tracking & Status": "تتبع الأسطول وحالته", "Fleet uplinks · last 48 h": "إرسالات الأسطول · آخر 48 ساعة", "Live event stream": "بث الأحداث المباشر",
  "Nodes online": "العقد المتصلة", "Uplinks · 24 h": "الإرسالات · 24 ساعة", "Uplinks 24 h": "الإرسالات 24 ساعة", "Command delivery · 7 d": "تسليم الأوامر · 7 أيام",
  "Mean battery": "متوسط البطارية", "Watchdog resets": "إعادات تشغيل المراقب", "watchdog · power-on": "المراقب · التشغيل",
  "Flow rate": "معدل التدفق", "Battery": "البطارية", "Soil (HNDA)": "التربة (HNDA)", "Sondas EC": "مجسات EC", "Moisture %": "الرطوبة %",
  "Temperature °C": "الحرارة °م", "Conductivity": "الموصلية", "Flow": "التدفق", "Today": "اليوم", "Resets": "إعادات التشغيل",
  "Report interval": "فترة الإرسال", "Time source": "مصدر الوقت", "Sensors": "المستشعرات", "Uplinks": "الإرسالات",
  "P(command delivered now)": "احتمال تسليم الأمر الآن", "Delivery model": "نموذج التسليم", "Select a node": "اختر عقدة", "commanded state": "الحالة المأمورة",
  "No uplinks in the last 48 hours — historical data is on the Data science page": "لا إرسالات خلال آخر 48 ساعة — البيانات التاريخية في صفحة علم البيانات",
  // ---- commands
  "Compose command": "إنشاء أمر", "Command journal": "سجل الأوامر", "Target node": "العقدة المستهدفة", "Command": "الأمر", "Value": "القيمة",
  "Delivery": "التسليم", "Send now": "إرسال الآن", "Next wake": "الاستيقاظ التالي", "Send command": "إرسال الأمر", "Pre-send delivery risk": "مخاطر التسليم قبل الإرسال",
  "Request": "الطلب", "Created": "أُنشئ", "Operator": "المشغّل", "ACK latency": "زمن الإقرار", "State": "الحالة", "Command detail": "تفاصيل الأمر",
  "Event journal": "سجل الأحداث", "Receipts": "الإيصالات", "Close": "إغلاق", "Node ID": "معرّف العقدة", "Other node ID…": "معرّف عقدة آخر…",
  "Use next wake": "استخدم الاستيقاظ التالي", "Node is very likely listening — send now.": "العقدة على الأرجح في وضع الاستماع — أرسل الآن.",
  "Node is probably asleep. Queue for its next wake window to avoid a lost command.": "العقدة على الأرجح نائمة. ضع الأمر في قائمة الانتظار لنافذة الاستيقاظ التالية لتجنب فقدانه.",
  "Read-only role — commands disabled": "دور للقراءة فقط — الأوامر معطلة", "No commands yet": "لا توجد أوامر بعد",
  "Risk is scored per node; broadcasts are not scored": "تُقيَّم المخاطر لكل عقدة؛ لا تُقيَّم أوامر البث",
  "LIKELY": "مرجح", "UNCERTAIN": "غير مؤكد", "UNLIKELY": "غير مرجح", "Accepted": "مقبول", "Published": "نُشر", "Broker PUBACK": "إقرار الوسيط", "Node ACK": "إقرار العقدة",
  // ---- history
  "Scope": "النطاق", "Type": "النوع", "From": "من", "To": "إلى", "Apply": "تطبيق", "Export CSV": "تصدير CSV", "All": "الكل", "All companies": "جميع الشركات",
  "Received": "وقت الاستلام", "Velocity": "السرعة", "Battery V": "البطارية V", "Soil %": "التربة %", "EC µS": "EC ميكروسيمنز", "Power": "الطاقة",
  "Details": "التفاصيل", "Prev": "السابق", "Next": "التالي", "Telemetry": "القياسات", "No messages match these filters": "لا توجد رسائل مطابقة لهذه المرشحات",
  // ---- admin
  "MQTT ingestion": "استقبال MQTT", "System": "النظام", "Users": "المستخدمون", "Audit trail": "سجل التدقيق", "Tenants": "الشركات", "Server log": "سجل الخادم",
  "Change my password": "تغيير كلمة المرور", "Add user": "إضافة مستخدم", "Create user": "إنشاء مستخدم", "Role": "الدور", "Last login": "آخر تسجيل دخول",
  "Current password": "كلمة المرور الحالية", "New password": "كلمة المرور الجديدة", "Update password": "تحديث كلمة المرور",
  "Changing your password signs out every other session.": "تغيير كلمة المرور يُنهي جميع الجلسات الأخرى.", "When": "الوقت", "Actor": "المنفّذ",
  "Action": "الإجراء", "Target": "الهدف", "Connect": "اتصال", "Disconnect": "قطع الاتصال", "Host": "المضيف", "Port": "المنفذ", "Client ID": "معرّف العميل",
  "Uptime": "مدة التشغيل", "Environment": "البيئة", "Data directory": "مجلد البيانات", "Live sockets": "الاتصالات المباشرة", "Delete": "حذف",
  "Password (≥10, 3 classes)": "كلمة المرور (10 أحرف على الأقل، 3 أنواع)", "user (read-only)": "مستخدم (قراءة فقط)", "monitor (read-only)": "مراقب (قراءة فقط)",
  "admin (commands, users)": "مسؤول (الأوامر والمستخدمون)", "Add company": "إضافة شركة", "DOWNLOAD": "تنزيل", "Password updated": "تم تحديث كلمة المرور",
  "Only the supervisor controls shared ingestion.": "المشرف العام وحده يتحكم في الاستقبال المشترك.", "Connection (supervisor)": "الاتصال (المشرف العام)",
  "OpenAPI docs": "توثيق OpenAPI", "Readiness": "الجاهزية", "Prometheus metrics": "مقاييس Prometheus",
  // ---- analytics (headings)
  "Overview": "نظرة عامة", "Link reliability": "موثوقية الاتصال", "Power & energy": "الطاقة والاستهلاك", "Commands": "الأوامر", "What-if": "ماذا لو",
  "Firmware & project": "البرنامج الثابت والمشروع", "Key findings": "أهم النتائج", "Dataset": "مجموعة البيانات", "Re-run pipeline": "إعادة تشغيل التحليل",
  "Report (MD)": "التقرير (MD)", "Model performance · temporal hold-out": "أداء النموذج · اختبار زمني", "Risk tiers · what the operator sees": "مستويات المخاطر · ما يراه المشغّل",
  "Confusion matrices": "مصفوفات الالتباس", "Precision–recall (hold-out)": "الدقة–الاستدعاء (الاختبار)", "ROC (hold-out)": "منحنى ROC (الاختبار)",
  "Run prediction": "تشغيل التنبؤ", "Per-node health": "صحة كل عقدة", "Messages": "الرسائل", "Availability": "الإتاحة",
  // ---- charts
  "No data in range": "لا توجد بيانات في هذا النطاق", "Count": "العدد",
  // ---- organization
  "Companies, regions, nodes, gateways and integrations": "الشركات والمناطق والعقد والبوابات والتكاملات",
  "Companies": "الشركات", "Regions": "المناطق", "Nodes": "العقد", "Gateways": "البوابات", "API & webhooks": "واجهة البرمجة وخطافات الويب",
  "Country": "الدولة", "Time zone": "المنطقة الزمنية", "Units": "الوحدات", "Metric": "متري", "Imperial": "إمبراطوري",
  "Company ID (MQTT)": "معرّف الشركة (MQTT)", "Display name": "الاسم المعروض", "Default language": "اللغة الافتراضية",
  "Headquarters latitude": "خط عرض المقر", "Headquarters longitude": "خط طول المقر", "Provisioning": "التسجيل",
  "Strict: accept data only from registered nodes": "صارم: قبول البيانات من العقد المسجلة فقط", "Active (uncheck to archive)": "نشط (ألغِ التحديد للأرشفة)",
  "Notes": "ملاحظات", "Create": "إنشاء", "Save changes": "حفظ التغييرات", "New": "جديد", "Edit": "تعديل", "New company": "شركة جديدة",
  "Metric (m³, ha, °C)": "متري (م³، هكتار، °م)", "Imperial (gal, ac, °F)": "إمبراطوري (جالون، إيكر، °ف)", "— not set —": "— غير محدد —",
  "— company default —": "— افتراضي الشركة —", "— none —": "— لا شيء —", "company default": "افتراضي الشركة", "not set": "غير محدد",
  "Letters, digits, space, _ or -; used in MQTT topics": "أحرف وأرقام ومسافات و _ أو -؛ يُستخدم في مواضيع MQTT",
  "Letters, digits, _ or -; used in MQTT topics": "أحرف وأرقام و _ أو -؛ يُستخدم في مواضيع MQTT",
  "Company IDs are part of the MQTT topic (wiot/<company>/<region>/<node>/…) and cannot be renamed; the display name can change at any time. Archiving stops ingestion and hides the company but keeps its data.":
    "معرّف الشركة جزء من موضوع MQTT ‏(wiot/<company>/<region>/<node>/…) ولا يمكن إعادة تسميته؛ ويمكن تغيير الاسم المعروض في أي وقت. الأرشفة توقف استقبال البيانات وتخفي الشركة مع الاحتفاظ ببياناتها.",
  "Company created": "تم إنشاء الشركة", "Company updated": "تم تحديث الشركة", "Select your company to edit its profile.": "اختر شركتك لتعديل ملفها.",
  "Region ID (MQTT)": "معرّف المنطقة (MQTT)", "Latitude": "خط العرض", "Longitude": "خط الطول", "New region": "منطقة جديدة",
  "Registered nodes": "العقد المسجلة", "No regions registered yet.": "لا توجد مناطق مسجلة بعد.", "Discovered in telemetry": "مكتشفة من القياسات",
  "Nodes seen": "العقد المرصودة", "Register": "تسجيل", "Region created": "تم إنشاء المنطقة", "Region updated": "تم تحديث المنطقة", "Region removed": "تمت إزالة المنطقة",
  "Removing a region only removes its registration; stored telemetry is kept.": "إزالة المنطقة تحذف تسجيلها فقط؛ وتبقى القياسات المخزنة.",
  "Search name, ID or gateway": "ابحث بالاسم أو المعرّف أو البوابة", "All regions": "جميع المناطق", "Name": "الاسم", "Kind": "النوع", "Last seen": "آخر ظهور",
  "First seen": "أول ظهور", "Discovered in telemetry · not registered": "مكتشفة من القياسات · غير مسجلة", "Bulk import (CSV)": "استيراد جماعي (CSV)",
  "Columns": "الأعمدة", "existing nodes are updated, new ones created.": "تُحدَّث العقد الموجودة وتُنشأ الجديدة.", "Import": "استيراد",
  "No nodes match the filter.": "لا توجد عقد مطابقة للمرشح.", "No nodes registered yet — register discovered nodes below or add one.": "لا توجد عقد مسجلة بعد — سجّل العقد المكتشفة أدناه أو أضف عقدة.",
  "Expected report interval (s)": "فترة الإرسال المتوقعة (ث)", "Install date": "تاريخ التركيب", "Move to region": "نقل إلى منطقة", "Register node": "تسجيل عقدة",
  "Node registered": "تم تسجيل العقدة", "Node updated": "تم تحديث العقدة", "Node unregistered": "تم إلغاء تسجيل العقدة", "Unregister": "إلغاء التسجيل",
  "Unregistering keeps the node's stored data. With strict provisioning on, its new data is rejected.": "إلغاء التسجيل يحتفظ ببيانات العقدة المخزنة. ومع تفعيل التسجيل الصارم تُرفض بياناتها الجديدة.",
  "Choose a CSV file first": "اختر ملف CSV أولًا", "Imported": "تم الاستيراد", "new": "جديدة", "updated": "محدثة", "Line": "السطر",
  "Soil + flow + valve": "تربة + تدفق + محبس", "Flow meter": "عداد تدفق", "Valve controller": "وحدة تحكم بالمحبس", "Weather station": "محطة طقس", "Gateway bridge": "جسر بوابة",
  "Backhaul": "وسيلة الربط", "Backhaul links": "روابط الربط", "Primary backhaul": "وسيلة الربط الأساسية", "Gateway ID": "معرّف البوابة", "New gateway": "بوابة جديدة",
  "No gateways registered yet.": "لا توجد بوابات مسجلة بعد.", "Gateway created": "تم إنشاء البوابة", "Gateway updated": "تم تحديث البوابة", "Gateway removed": "تمت إزالة البوابة",
  "A gateway forwards LoRa node traffic to the server over its backhaul. Satellite-ready gateways can switch from cellular to satellite IoT without firmware changes.":
    "تمرر البوابة بيانات عقد LoRa إلى الخادم عبر وسيلة الربط. ويمكن للبوابات الجاهزة للأقمار الصناعية التحول من الشبكة الخلوية إلى إنترنت الأشياء عبر الأقمار الصناعية دون تعديل البرنامج الثابت.",
  "Delete this entry? This cannot be undone.": "حذف هذا العنصر؟ لا يمكن التراجع عن ذلك.",
  "API tokens": "رموز واجهة البرمجة", "active": "نشط", "Token": "الرمز", "Last used": "آخر استخدام", "Expires": "ينتهي", "Revoke": "إلغاء",
  "No API tokens yet.": "لا توجد رموز بعد.", "Create token": "إنشاء رمز", "Read & write (commands, registry)": "قراءة وكتابة (الأوامر والسجل)",
  "Expires after (days)": "ينتهي بعد (أيام)", "Use it as": "استخدمه بالصيغة",
  "on any /api/v2 endpoint. It is scoped to this company and can never manage users, tokens or webhooks.": "مع أي نقطة نهاية ‎/api/v2. وهو مقصور على هذه الشركة ولا يمكنه أبدًا إدارة المستخدمين أو الرموز أو خطافات الويب.",
  "API reference": "مرجع واجهة البرمجة", "Copy this token now — it will not be shown again.": "انسخ هذا الرمز الآن — لن يُعرض مرة أخرى.",
  "Copy": "نسخ", "Copied": "تم النسخ", "Done": "تم", "Token revoked": "تم إلغاء الرمز",
  "Revoke this token? Systems using it will stop working immediately.": "إلغاء هذا الرمز؟ ستتوقف الأنظمة التي تستخدمه فورًا.",
  "Webhooks": "خطافات الويب", "Events": "الأحداث", "Last delivery": "آخر تسليم", "Sent / failed": "مُرسل / فاشل", "Test": "اختبار", "No webhooks yet.": "لا توجد خطافات ويب بعد.",
  "Endpoint URL (https://…)": "عنوان نقطة النهاية (https://…)", "Command updates": "تحديثات الأوامر", "Irrigation automation": "أتمتة الري",
  "Alerts (offline / online / low battery)": "التنبيهات (انقطاع / عودة / بطارية منخفضة)", "Flash archive": "أرشيف الذاكرة",
  "Signing secret — copy it now, it will not be shown again.": "سر التوقيع — انسخه الآن، لن يُعرض مرة أخرى.", "Verify each delivery:": "تحقق من كل تسليم:",
  "Edit webhook": "تعديل خطاف الويب", "Add webhook": "إضافة خطاف ويب", "Rotate secret": "تغيير السر", "Recent deliveries": "آخر عمليات التسليم",
  "Each delivery is an HTTPS POST with a JSON body {id, event, company, ts, data}, retried up to 3 times. Private network addresses are blocked in production.":
    "كل تسليم هو طلب HTTPS POST بجسم JSON ‏{id, event, company, ts, data} مع إعادة المحاولة حتى 3 مرات. تُحظر عناوين الشبكات الخاصة في بيئة الإنتاج.",
  "Webhook updated": "تم تحديث خطاف الويب", "Webhook created": "تم إنشاء خطاف الويب", "Secret rotated": "تم تغيير السر", "Webhook deleted": "تم حذف خطاف الويب",
  "Delete this webhook?": "حذف خطاف الويب هذا؟", "No deliveries since the server started.": "لا توجد عمليات تسليم منذ بدء تشغيل الخادم.",
  "Test failed": "فشل الاختبار", "Test delivered": "تم تسليم الاختبار",
  // ---- world
  "Companies & sites": "الشركات والمواقع", "Countries": "الدول", "Sites": "المواقع", "Time zones": "المناطق الزمنية", "with live sites": "لها مواقع نشطة",
  "on the map": "على الخريطة", "offline": "غير متصلة", "late": "متأخرة", "all sites": "جميع المواقع", "Site status": "حالة الموقع",
  "All nodes online": "جميع العقد متصلة", "Some nodes need attention": "بعض العقد تحتاج انتباهًا", "All nodes offline": "جميع العقد غير متصلة",
  "No nodes reporting": "لا توجد عقد ترسل", "Marker size = number of nodes": "حجم العلامة = عدد العقد", "Open farm": "فتح المزرعة",
  "Country not set": "الدولة غير محددة", "site": "موقع", "sites": "مواقع", "not on map": "ليس على الخريطة",
  "Add coordinates on the Organization page": "أضف الإحداثيات في صفحة المؤسسة", "No sites yet — add regions on the Organization page.": "لا توجد مواقع بعد — أضف مناطق في صفحة المؤسسة.",
  "Set locations": "تحديد المواقع", "No companies": "لا توجد شركات",
  // ---- flash data
  "Flash data": "بيانات ذاكرة الفلاش", "Node": "العقدة", "Read status": "قراءة الحالة", "Download today": "تنزيل سجل اليوم",
  "Latest sample": "آخر عينة", "Previous": "السابق", "Cancel download": "إلغاء التنزيل", "Erase log": "مسح السجل", "Read-only role": "دور للقراءة فقط",
  "Flash chip": "شريحة الفلاش", "Records in log": "السجلات في الذاكرة", "Storage used": "المساحة المستخدمة",
  "Samples not logged": "عينات لم تُسجَّل", "Log clears in": "يُمسح السجل بعد", "Archived on server": "المؤرشف على الخادم", "samples": "عينة",
  "Capacity & 24-hour log window": "السعة ونافذة السجل لمدة 24 ساعة", "Logging quality & gap recovery": "جودة التسجيل واستعادة الفجوات",
  "Archived samples": "العينات المؤرشفة", "Log generations": "أجيال السجل", "History downloads": "تنزيلات السجل", "Archived records": "السجلات المؤرشفة",
  "Generation": "الجيل", "Samples taken": "فترة أخذ العينات", "On node": "على العقدة", "On server": "على الخادم", "Sequence": "التسلسل",
  "Completeness": "الاكتمال", "Spacing": "التباعد", "Gen.": "الجيل", "Progress": "التقدم", "Outcome": "النتيجة", "Last row": "آخر صف",
  "Gen / seq": "الجيل / التسلسل", "Sample time": "وقت العينة", "Velocity": "السرعة", "Forward total": "الإجمالي الأمامي", "Flags": "المؤشرات",
  "Record capacity": "سعة السجلات", "24-hour log window": "نافذة السجل لمدة 24 ساعة", "Usable for records": "المتاح للسجلات",
  "Reserved": "محجوز", "Free": "مساحة حرة", "Erase": "المسح", "Corrupt records": "سجلات تالفة", "Clock": "الساعة", "idle": "خامل",
  "RTC trusted — sample times are real": "ساعة RTC موثوقة — أوقات العينات حقيقية", "RTC trusted": "ساعة RTC موثوقة", "RTC not trusted": "ساعة RTC غير موثوقة",
  "Sampling outcome in this window": "نتيجة أخذ العينات في هذه النافذة", "Archived samples vs live uplinks": "العينات المؤرشفة مقابل الإرسال المباشر",
  "Silent link periods filled from flash": "فترات انقطاع الاتصال المستكملة من الفلاش", "Valid samples": "عينات صالحة",
  "Minimum": "الحد الأدنى", "Mean": "المتوسط", "Maximum": "الحد الأقصى", "Sample order": "ترتيب العينات", "Timeline": "الخط الزمني",
  "Soil moisture (Sondas)": "رطوبة التربة (Sondas)", "Soil temperature (Sondas)": "حرارة التربة (Sondas)",
  "Soil moisture (HNDA)": "رطوبة التربة (HNDA)", "Soil temperature (HNDA)": "حرارة التربة (HNDA)",
  "current": "الحالي", "cleared": "مُسح", "not downloaded": "غير منزّل", "Complete": "مكتمل", "Stalled": "متوقف",
  "Receiving": "قيد الاستلام", "Preparing": "قيد التحضير", "Stopped": "توقف", "Rejected": "مرفوض", "Cancelled": "أُلغي",
  "ACK timeout": "انتهت مهلة الإقرار", "projection pending": "التوقع قيد الانتظار", "no status received yet": "لم تُستلم حالة بعد",
  "send Read status": "أرسل قراءة الحالة", "No status from this node yet": "لا توجد حالة من هذه العقدة بعد", "Ready": "جاهز",
  "Too early in the window to project the fill rate.": "من المبكر في هذه النافذة توقع معدل الامتلاء.",
  "Only values whose validity flag was set when the node stored the sample are plotted. Colours follow the log generation (the node starts a new generation each time the log is cleared).":
    "تُرسم فقط القيم التي كان مؤشر صلاحيتها مفعّلًا عند تخزين العقدة للعينة. الألوان تتبع جيل السجل (تبدأ العقدة جيلًا جديدًا في كل مرة يُمسح فيها السجل).",
  "A sample is not logged while the node's clock is untrusted or the log window has not started (after boot, before time sync), or when the write queue is busy or the log is full. The counter includes skips since the node last booted.":
    "لا تُسجَّل العينة عندما تكون ساعة العقدة غير موثوقة أو لم تبدأ نافذة السجل (بعد الإقلاع وقبل مزامنة الوقت)، أو عندما تكون قائمة الكتابة مشغولة أو السجل ممتلئًا. يشمل العدّاد العينات المتجاوزة منذ آخر إقلاع للعقدة.",
};

const AGO = { s: "ث", m: "د", h: "س", d: "ي" };
const word = (s) => AR[s] ?? s;
// Dynamic phrases: [regex, (match) => Arabic].
const PATTERNS = [
  [/^(\d+)([smhd]) ago$/, (m) => `منذ ${m[1]} ${AGO[m[2]]}`],
  [/^(\d+) of (\d+) fields in target band$/, (m) => `${m[1]} من ${m[2]} حقول ضمن النطاق المستهدف`],
  [/^(\S+) (\S+) total flow · (\d+) on automatic$/, (m) => `إجمالي التدفق ${m[1]} ${m[2]} · ${m[3]} تلقائي`],
  [/^(\d+) dry · (\d+) wet · (\d+) offline$/, (m) => `${m[1]} جاف · ${m[2]} رطب · ${m[3]} غير متصل`],
  [/^(\S+) (\S+) under pivots$/, (m) => `${m[1]} ${m[2]} تحت الري المحوري`],
  [/^(\d+) FIELDS · (\d+) ALERTS$/i, (m) => `${m[1]} حقول · ${m[2]} تنبيهات`],
  [/^\/(\d+) ONLINE$/, (m) => `/${m[1]} متصل`],
  [/^(\d+)\/(\d+) online$/, (m) => `${m[1]}/${m[2]} متصل`],
  [/^([\d,]+) MESSAGES$/i, (m) => `${m[1]} رسالة`],
  [/^([\d,]+) nodes$/, (m) => `${m[1]} عقد`], [/^([\d,]+) uplinks$/, (m) => `${m[1]} إرسال`],
  [/^(\d+) accounts$/, (m) => `${m[1]} حسابات`], [/^(\d+) latest$/, (m) => `آخر ${m[1]}`],
  [/^([\d,]+)–([\d,]+) of ([\d,]+)$/, (m) => `${m[1]}–${m[2]} من ${m[3]}`],
  [/^node (\d+|–)$/, (m) => `العقدة ${m[1]}`],
  [/^last uplink (.+)$/, (m) => `آخر إرسال ${translate(m[1])}`],
  [/^Irrigate ≈(\d+) min \(([\d.]+) mm\) to reach (\d+)%\.$/, (m) => `ري لمدة ≈${m[1]} دقيقة (${m[2]} مم) للوصول إلى ${m[3]}%.`],
  [/^Dry, but ([\d.]+) mm rain is forecast in 24 h — hold irrigation\.$/, (m) => `جاف، لكن يُتوقع هطول ${m[1]} مم من المطر خلال 24 ساعة — أجّل الري.`],
  [/^Irrigating — ([\d.]+) mm still needed to reach (\d+)%\.$/, (m) => `جارٍ الري — ما زال يلزم ${m[1]} مم للوصول إلى ${m[2]}%.`],
  [/^(.+) below ([\d.]+)% soil moisture$/, (m) => `${m[1]} أقل من ${m[2]}% رطوبة تربة`],
  [/^(.+) over-irrigating$/, (m) => `${m[1]} ري زائد`],
  [/^(.+) node not reporting$/, (m) => `${m[1]} العقدة لا ترسل`],
  [/^(.+) soil probe invalid$/, (m) => `${m[1]} مجس التربة غير صالح`],
  [/^(\d+) soil probes$/, (m) => `${m[1]} مجسات تربة`],
  [/^Target band ([\d.]+)–([\d.]+)% VWC$/, (m) => `النطاق المستهدف ${m[1]}–${m[2]}% رطوبة حجمية`],
  [/^month (.+)$/, (m) => `الشهر ${m[1]}`],
  [/^(\d+)% RH$/, (m) => `رطوبة ${m[1]}%`],
  [/^Reporting within (\d+) msgs\/day budget$/, (m) => `الإرسال ضمن ميزانية ${m[1]} رسالة/يوم`],
  [/^Within (\d+)\/day$/, (m) => `ضمن ${m[1]}/يوم`],
  [/^Report ≥ (\d+) min$/, (m) => `إرسال كل ≥ ${m[1]} دقيقة`],
  [/^(\d+) nodes? reported for this company\. Place them on the satellite map as irrigation fields — this only saves the map; nothing is sent to the nodes\.$/,
    (m) => `${m[1]} عقدة أرسلت بيانات لهذه الشركة. ضعها على خريطة القمر الصناعي كحقول ري — يحفظ هذا الخريطة فقط؛ ولا يُرسل شيء إلى العقد.`],
  [/^Set up the farm map · (.+)$/, (m) => `إعداد خريطة المزرعة · ${m[1]}`],
  [/^No farm map for (.+) yet$/, (m) => `لا توجد خريطة مزرعة لـ ${m[1]} بعد`],
  [/^Cellular · (primary|standby)$/, (m) => `خلوي · ${m[1] === "primary" ? "أساسي" : "احتياطي"}`],
  [/^Satellite IoT · (primary|roadmap|not fitted)$/, (m) => `أقمار صناعية · ${({ primary: "أساسي", roadmap: "ضمن الخطة", "not fitted": "غير مركّب" })[m[1]]}`],
  // ---- flash data
  [/^Status received (.+)$/, (m) => `استُلمت الحالة ${translate(m[1])}`],
  [/^(\d+) Mbit$/, (m) => `${m[1]} ميغابت`],
  [/^generation (\d+)$/, (m) => `الجيل ${m[1]}`], [/^latest seq (\d+)$/, (m) => `آخر تسلسل ${m[1]}`],
  [/^Generation (\d+)$/, (m) => `الجيل ${m[1]}`],
  [/^of (.+) usable$/, (m) => `من ${m[1]} متاحة`],
  [/^([\d.]+ %) of attempts$/, (m) => `${m[1]} من المحاولات`],
  [/^RTC (trusted|NOT trusted)$/, (m) => (m[1] === "trusted" ? "ساعة RTC موثوقة" : "ساعة RTC غير موثوقة")],
  [/^window opened (.+)$/, (m) => `فُتحت النافذة ${m[1]}`],
  [/^(\d+) generations?$/, (m) => `${m[1]} أجيال`], [/^(\d+) downloads?$/, (m) => `${m[1]} تنزيلات`],
  [/^([\d,]+) now$/, (m) => `${m[1]} الآن`], [/^≈([\d,]+) at clear$/, (m) => `≈${m[1]} عند المسح`], [/^([\d,]+) max$/, (m) => `الحد الأقصى ${m[1]}`],
  [/^Stored now (.+)$/, (m) => `المخزّن الآن ${m[1]}`], [/^Projected by next clear (.+)$/, (m) => `المتوقع قبل المسح التالي ${m[1]}`],
  [/^At ([\d,]+) records\/h the log will hold about ([\d,]+) records \((.+)\) when it clears — no overflow expected\.$/,
    (m) => `بمعدل ${m[1]} سجل/ساعة سيحتوي السجل على نحو ${m[2]} سجل (${m[3]}) عند مسحه — لا يُتوقع امتلاء.`],
  [/^At ([\d,]+) records\/h the log reaches its ([\d,]+)-record limit at (.+), before the daily clear — later samples will not be logged\.$/,
    (m) => `بمعدل ${m[1]} سجل/ساعة يبلغ السجل حده البالغ ${m[2]} سجل في ${m[3]}، قبل المسح اليومي — لن تُسجَّل العينات اللاحقة.`],
  [/^([\d.]+ %) elapsed$/, (m) => `انقضى ${m[1]}`], [/^clears (.+)$/, (m) => `يُمسح ${m[1]}`],
  [/^Stored ([\d,]+)$/, (m) => `مخزّنة ${m[1]}`], [/^Not logged ([\d,]+) \((.+)\)$/, (m) => `لم تُسجَّل ${m[1]} (${m[2]})`],
  [/^Corrupt (\d+)$/, (m) => `تالفة ${m[1]}`], [/^([\d,]+) attempts$/, (m) => `${m[1]} محاولة`],
  [/^Also received live ([\d,]+)$/, (m) => `استُلمت مباشرة أيضًا ${m[1]}`], [/^Only in flash \(gap fill\) ([\d,]+)$/, (m) => `في الفلاش فقط (سدّ فجوات) ${m[1]}`],
  [/^([\d,]+) archived samples$/, (m) => `${m[1]} عينة مؤرشفة`],
  [/^A sample counts as covered when a live uplink from the node reached the server within ±(\d+) s of it\. Gap-fill samples were taken while the radio link was silent: data the server only has because of the flash log\.$/,
    (m) => `تُعد العينة مغطاة إذا وصل إرسال مباشر من العقدة إلى الخادم خلال ±${m[1]} ث منها. أُخذت عينات سدّ الفجوات أثناء انقطاع الاتصال اللاسلكي: بيانات لا يملكها الخادم إلا بفضل سجل الفلاش.`],
  [/^([\d,]+) samples?$/, (m) => `${m[1]} عينة`],
  [/^([\d,]+) not downloaded$/, (m) => `${m[1]} غير منزّلة`], [/^(\d+) missing in range$/, (m) => `${m[1]} مفقودة ضمن النطاق`],
  [/^([\d,]+) stored on server$/, (m) => `${m[1]} مخزّنة على الخادم`],
  [/^([\d.]+ [KM]?B) chip$/, (m) => `شريحة ${m[1]}`],
  [/^(.+) \(not used for sample records\)$/, (m) => `${m[1]} (لا تُستخدم لسجلات العينات)`],
  [/^([\d,]+) × (\d+) B slots$/, (m) => `${m[1]} خانة × ${m[2]} بايت`],
  [/^(\d+) d (\d+) h$/, (m) => `${m[1]} ي ${m[2]} س`], [/^(\d+) h (\d+) min$/, (m) => `${m[1]} س ${m[2]} د`], [/^(\d+) min$/, (m) => `${m[1]} د`],
];

function translate(s) {
  if (AR[s] !== undefined) return AR[s];
  for (const [re, fn] of PATTERNS) { const m = s.match(re); if (m) return fn(m); }
  if (s.includes(" · ")) { // "Wheat · 45.4 ha · node 1", "Backhaul · GW-01"
    const parts = s.split(" · "), out = parts.map((p) => translate(p));
    if (out.some((p, i) => p !== parts[i])) return out.join(" · ");
  }
  return s;
}

/** Translate an interface string for code that builds text itself. */
export function t(s) { return I18N.lang === "ar" && typeof s === "string" ? translate(s) : s; }

// ------------------------------------------------------------- DOM layer
const SKIP = "script,style,textarea,code,pre,[data-i18n-skip],.console,.leaflet-tile-pane";
const ATTRS = ["placeholder", "title", "aria-label", "data-tip"];
function textNode(n) {
  const v = n.nodeValue;
  if (!v || !/[A-Za-z]/.test(v)) return;
  const el = n.parentElement;
  if (!el || el.closest(SKIP)) return;
  const trimmed = v.trim(), tr = translate(trimmed);
  if (tr !== trimmed) n.nodeValue = v.replace(trimmed, tr);
}
function element(el) {
  if (el.closest(SKIP)) return;
  for (const a of ATTRS) {
    const v = el.getAttribute(a);
    if (v && /[A-Za-z]/.test(v)) { const tr = translate(v.trim()); if (tr !== v.trim()) el.setAttribute(a, tr); }
  }
}
export function translateTree(root) {
  if (I18N.lang !== "ar" || !root) return;
  if (root.nodeType === 3) { textNode(root); return; }
  if (root.nodeType !== 1 && root.nodeType !== 11) return;
  if (root.nodeType === 1) element(root);
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  let n;
  while ((n = walk.nextNode())) { if (n.nodeType === 3) textNode(n); else element(n); }
}
let observer = null;
function observe() {
  if (observer || !document.body) return;
  observer = new MutationObserver((muts) => {
    if (I18N.lang !== "ar") return;
    for (const m of muts) {
      if (m.type === "characterData") textNode(m.target);
      else if (m.type === "attributes") element(m.target);
      else m.addedNodes.forEach(translateTree);
    }
  });
  observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
}

export function savedLang() { try { return localStorage.getItem(KEY); } catch { return null; } }
export function setLang(lang, persist = true) {
  I18N.lang = LANGS[lang] ? lang : "en";
  const root = document.documentElement;
  root.lang = I18N.lang;
  root.dir = I18N.lang === "ar" ? "rtl" : "ltr";
  if (persist) { try { localStorage.setItem(KEY, I18N.lang); } catch { /* storage blocked */ } }
  observe();
  translateTree(document.body);
}
/** Initial language: the user's saved choice, else the company default, else the browser. */
export function initLang(companyDefault) {
  const lang = savedLang() || companyDefault || ((navigator.language || "").startsWith("ar") ? "ar" : "en");
  setLang(lang, false);
  return lang;
}
export function langToggleHtml(id = "lang-toggle") {
  return `<div class="theme-toggle lang-toggle" id="${id}" role="radiogroup" aria-label="Language" data-i18n-skip>
    <button type="button" data-lang="en" class="${I18N.lang === "en" ? "on" : ""}" aria-checked="${I18N.lang === "en"}">EN</button>
    <button type="button" data-lang="ar" class="${I18N.lang === "ar" ? "on" : ""}" aria-checked="${I18N.lang === "ar"}">ع</button></div>`;
}
