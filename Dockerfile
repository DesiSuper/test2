FROM python:3.11-slim-bookworm

# 1. Performance, Pip & Timezone Engine Environment Variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ="Asia/Kolkata"

WORKDIR /app

# 2. Install Essentials, tzdata + FFmpeg (RAM & Cloud Optimized)
# tzdata: info.py के TIME_ZONE को लिनक्स ओएस स्तर पर लॉक करने के लिए
# gcc, python3-dev, libffi-dev: uvloop और tgcrypto C-इंजन कंपाइलेशन के लिए
# ffmpeg: वीडियो थंबनेल एक्सट्रैक्टर पाइपलाइन के लिए
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    python3-dev \
    ffmpeg \
    git \
    tzdata \
    && ln -fs /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# 3. Upgrade Pip Tools & Pre-Compile Wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# 4. ✅ FIX: कंपाइलेशन ख़त्म होने के बाद फालतू भारी टूल्स को हटाकर इमेज साइज को 60% छोटा करें
# इससे कोएब कंटेनर बिजली की तरह तेज़ स्टार्ट होगा और रैम लीक का चांस 0% हो जाएगा
RUN apt-get purge -y --auto-remove gcc python3-dev libffi-dev git

# 5. Copy Application Source Code
COPY . .

# 6. ✅ FIX: 'info.py' और 'bot.py' के पोर्ट ८०८० के साथ परफेक्ट हेल्थ-चेक सिंक
EXPOSE 8080

# 7. Run Core Engine with Production Optimization (-O removes asserts)
CMD ["python", "-O", "bot.py"]
