# 📦 BastaCount AI (বস্তা কাউন্টার)
### সিসিটিভি ক্যামেরা ও এনভিআর (NVR/DVR) ভিত্তিক স্বয়ংক্রিয় ব্যাগ/বস্তা ইন-আউট কাউন্টিং এআই সিস্টেম

![Dashboard Preview](frontend/css/style.css)

BastaCount AI হলো একটি পূর্ণাঙ্গ কম্পিউটার ভিশন ও ডিপ লার্নিং (YOLO + ByteTrack) ভিত্তিক সিস্টেম, যা যেকোনো সিসিটিভি ক্যামেরা, আইপি ক্যামেরা, কিংবা ডিভিআর/এনভিআর (Hikvision, Dahua, Uniview, CP Plus) থেকে রিয়েল-টাইমে অথবা রেকর্ডেড ভিডিওর মাধ্যমে বস্তা/ব্যাগ ভেতরে ঢোকা (**IN**) এবং বাইরে যাওয়া (**OUT**) নির্ভুলভাবে গণনা করে।

---

## ✨ প্রধান বৈশিষ্ট্যসমূহ (Key Features)

1. **রিয়েল-টাইম লাইভ ক্যামেরা ও এনভিআর ইন্টিগ্রেশন (Live RTSP & NVR Integration)**:
   - Hikvision, Dahua, Uniview, CP Plus সহ যেকোনো স্ট্যান্ডার্ড আইপি ক্যামেরার সরাসরি RTSP সংযোগ।
   - হাই-রেজোলিউশন (Main Stream) ও লো-ব্যান্ডউইথ (Sub Stream) সাপোর্ট।

2. **তারিখ ও সময় অনুযায়ী ভিডিও প্লেব্যাক (Date & Time-frame Analysis)**:
   - এনভিআর (NVR) স্টোরেজ থেকে নির্দিষ্ট তারিখ ও সময় ফ্রেম (Start Time & End Time) সিলেক্ট করে সরাসরি ফুটেজ প্রসেসিং।
   - পূর্বের রেকর্ডেড ভিডিও ফাইল (.mp4, .avi, .mkv) ড্র্যাগ-অ্যান্ড-ড্রপ করে আপলোড ও এনালাইসিস করার সুবিধা।

3. **দিকনির্দেশক ট্রিপওয়্যার লাইন ক্যালিব্রেশন (Directional Tripwire Calibration)**:
   - ভিডিও স্ক্রিনের উপর সরাসরি মাউস দিয়ে টেনে ভার্চুয়াল কাউন্টিং লাইন (Start ও End পয়েন্ট) সেট করা যায়।
   - স্বয়ংক্রিয় ভেক্টর ক্যালকুলেশন: বস্তা যেদিকেই মুভ করুক না কেন (কনভেয়ার বেল্ট, শ্রমিকের কাঁধে বা ট্রাকে লোডিং), লাইন অতিক্রম করলে সঠিক **IN** অথবা **OUT** হিসেবে গণনা হবে।

4. **ডুপ্লিকেট কাউন্ট প্রতিরোধ (Anti-Bounce & ByteTrack)**:
   - শ্রমিক বা বেল্ট থেমে গেলে বা সামান্য পেছনে গেলে যাতে একই বস্তা দুইবার কাউন্ট না হয়, সেজন্য প্রতিটি অবজেক্টের ইউনিক Track ID ও ট্র্যাজেক্টরি হিস্ট্রি ট্র্যাক করা হয়।

5. **অডিট স্ন্যাপশট ও ভেরিফিকেশন (Snapshot Audit Log)**:
   - প্রতিটি বস্তা লাইন পার হওয়ার সাথে সাথে ফুল ফ্রেম স্ন্যাপশট স্বয়ংক্রিয়ভাবে সেভ হয়।
   - কোনো ভুলের সন্দেহ হলে ছবিতে ক্লিক করে তারিখ, সময় এবং ট্র্যাক আইডি সহ যাচাই করা যায়।

6. **অটোমেটেড রিপোর্ট ও এক্সপোর্ট (Historical Reports & CSV Export)**:
   - তারিখ অনুযায়ী ফিল্টার করে মোট কতটি বস্তা ঢুকলো বা বের হলো তার সামারি।
   - এক ক্লিকে একাউন্টিং বা ইনভেন্টরি ম্যানেজমেন্টের জন্য CSV ফাইলে ডাউনলোড।

---

## 🚀 দ্রুত শুরু করার নিয়ম (Quick Start)

### ১. ডিপেন্ডেন্সি ইনস্টলেশন ও সার্ভার রান

টার্মিনালে সরাসরি নিচের কমান্ডটি চালান:
```bash
cd /Users/tauhidulislam/cctv_ai_bagCount
./run.sh
```
অথবা ম্যানুয়ালি:
```bash
source venv/bin/activate
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
```

### ২. ড্যাশবোর্ড ওপেন করুন
আপনার ব্রাউজারে প্রবেশ করুন:
👉 **`http://localhost:8000`**

---

## 📹 এনভিআর / সিসিটিভি ক্যামেরা সংযোগের নিয়ম (NVR Setup Guide)

ড্যাশবোর্ডের **"NVR & Video Inputs"** ট্যাবে যান:

1. **Hikvision / Ezviz**:
   - Brand সিলেক্ট করুন: `Hikvision`
   - IP: আপনার NVR এর আইপি (যেমন: `192.168.1.100`)
   - Channel: যে ক্যামেরায় বস্তা কাউন্ট করবেন (যেমন: `1`)
   - RTSP Port: `554`
   - Username ও Password দিন এবং "Connect NVR Stream" চাপুন।

2. **Dahua / Imou**:
   - Brand সিলেক্ট করুন: `Dahua`
   - আইপি ও ক্রেডেনশিয়াল দিন।

3. **রেকর্ডেড ভিডিও এনালাইসিস**:
   - যদি প্লেব্যাক মোড চান, "Mode" থেকে **Date & Time Playback** বেছে নিয়ে শুরুর সময় এবং শেষের সময় সিলেক্ট করুন।
   - অথবা আপনার পেনড্রাইভ/পিসি থেকে ভিডিওটি "Drag & Drop Video Footage Here" বক্সে ফেলে দিন।

---

## 📐 ভার্চুয়াল কাউন্টিং লাইন (Tripwire) সেট করার নিয়ম

1. **"Live Feed & Calibration"** ট্যাবে ভিডিওর উপরে সবুজ ও লাল দুটি হ্যান্ডেল দেখতে পাবেন।
2. সবুজ হ্যান্ডেলটি (START) এবং লাল হ্যান্ডেলটি (END) মাউস দিয়ে ড্র্যাগ করে কনভেয়ার বেল্ট বা গোডাউন দরজার মুখে বসিয়ে দিন।
3. দিক নির্দেশক তীরচিহ্ন (Arrow) যেদিকে নির্দেশ করবে সেদিকটি হবে **IN** (ভেতরে ঢোকা)।
4. নিচে **"Save Tripwire Line"** বাটনে ক্লিক করুন। সাথে সাথেই নতুন লাইন সক্রিয় হয়ে যাবে।

---

## 📁 ফাইল আর্কিটেকচার (Project Structure)

```
cctv_ai_bagCount/
├── backend/
│   ├── app.py              # FastAPI Web & API Server
│   ├── counter.py          # Directional Vector Tripwire Logic
│   ├── detector.py         # YOLOv8 + ByteTrack Object Tracker
│   ├── stream_manager.py   # Multi-source Video Capture & Real-time Loop
│   ├── nvr_client.py       # Hikvision/Dahua RTSP Live & Playback URL Builder
│   ├── database.py         # SQLite DB Connection
│   └── models.py           # DB Models (BagEvent, CountSession)
├── frontend/
│   ├── index.html          # Web Dashboard
│   ├── css/style.css       # Dark Mode Glassmorphic Styling
│   └── js/
│       ├── app.js          # Client WebSockets, Audio Chime & API sync
│       └── canvas_draw.js  # Interactive Line Calibration Canvas
├── data/
│   ├── snapshots/          # Captured Bag Crossing Proofs
│   ├── uploads/            # Uploaded Video Files
│   └── bag_counter.db      # SQLite Database
├── run.sh                  # One-click start script
└── requirements.txt        # Python Packages
```
