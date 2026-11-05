# 🤖 مواقع عربية + شات بوت ذكاء اصطناعي — ديموهات

تلات مواقع جاهزة لأنشطة مختلفة، كلهم مبنيين بـ Python (FastAPI)، وفي كل موقع شات بوت بيرد بالعامية من بيانات النشاط.

| الديمو | أهم المميزات | لينك لايف |
|---|---|---|
| 🦷 [عيادة أسنان](clinic-demo) | شات بوت بيرد على المرضى، وحجز مواعيد، ولوحة للحجوزات | [clinic-ai-demo-ww10.onrender.com](https://clinic-ai-demo-ww10.onrender.com) |
| 🔥 [مطعم](restaurant-demo) | منيو وسلة طلبات بتبعت الأوردر على واتساب، وحجز ترابيزات، ولوحة للمبيعات | [restaurant-ai-demo-h9vw.onrender.com](https://restaurant-ai-demo-h9vw.onrender.com) |
| 🏙️ [عقارات](realestate-demo) | بحث بالعامية، ومستشار ذكي بيعرض الوحدات، وحاسبة أقساط، وتقييم للعملاء | [realestate-ai-demo.onrender.com](https://realestate-ai-demo.onrender.com) |

## الرفع (مرة واحدة للتلاتة)
1. **GitHub:**
   - على ماك أو لينكس: شغّل `./deploy.sh`.
   - على ويندوز: دبل كليك على `deploy.bat`.
2. **Render:** ادخل https://dashboard.render.com/blueprints ، ودوس **New Blueprint Instance**، واختار الريبو. ملف `render.yaml` هيطلّع التلات مواقع على الخطة المجانية.
3. كلمة سر لوحة الإدارة (`ADMIN_TOKEN`) بتتولد لوحدها. هتلاقيها في Render: افتح الخدمة، وبعدين **Environment**.

> ملحوظة: الاستضافة المجانية بتوقف الموقع بعد 15 دقيقة من غير زيارات، فأول فتحة بعدها بتاخد حوالي دقيقة.
