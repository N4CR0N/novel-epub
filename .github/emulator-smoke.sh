#!/bin/bash
# Emülatörde: APK'yı kur, aç, arayüzün geldiğini ekran ağacından (WebView metinleri) doğrula.
set -u
PKG=io.github.n4cr0n.novelepub
adb install -r android/app/build/outputs/apk/release/*.apk
adb shell pm grant $PKG android.permission.POST_NOTIFICATIONS 2>/dev/null || true
adb logcat -c
adb shell am start -n $PKG/.MainActivity
ok=0
for i in $(seq 1 30); do
  sleep 4
  adb shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1
  adb shell cat /sdcard/ui.xml > ui.xml 2>/dev/null
  if grep -q "İndir ve çevir\|Download &amp; translate\|Download & translate" ui.xml; then ok=1; break; fi
  if grep -q "Python başlatılamadı" ui.xml; then break; fi
done
echo "=== arayüz metinleri ==="
grep -o 'text="[^"]\+"' ui.xml | sort -u | head -40
echo "=== uygulama kayıtları ==="
APID=$(adb shell pidof $PKG | tr -d '\r')
echo "pid: ${APID:-yok}"
adb logcat -d -v brief | grep -vE "uiautomator|RoleController|Icing|CorpusConfig|BluetoothShim|ChimeraConfig|BaseSearchIndex|Cronet|^D/AndroidRuntime|^I/AndroidRuntime" \
  | grep -iE "novelepub|python|chromium|FATAL|ANR|has died|crash|Exception|ErrorId|Force finishing|Killing|WebView|console" | head -120
echo "=== etkin pencere ==="
adb shell dumpsys activity activities | grep -E "topResumedActivity|mResumedActivity|ResumedActivity" | head -5
echo "=== hizmet ==="
adb shell dumpsys activity services $PKG | grep -E "ServiceRecord|isForeground|foregroundId" | head -5
echo "=== çıkış nedenleri ==="
adb shell dumpsys activity exit-info $PKG | grep -E "reason|description|status|importance" | head -20
echo "=== gerçek iş: siteden 3 bölüm indir, kitap yap (çevirisiz) ==="
PORT=$(adb logcat -d | grep -o "WEBNOVEL_PORT=[0-9]*" | tail -1 | cut -d= -f2)
job_ok=0
if [ -n "$PORT" ]; then
  adb forward tcp:18765 tcp:$PORT
  JOB=$(curl -s -X POST http://127.0.0.1:18765/api/jobs -H "Content-Type: application/json" \
    -d '{"url":"https://freewebnovel.com/novel/cosmic-professional-gladiator","start":1,"end":3,"translate":false,"format":"epub"}')
  echo "iş: $JOB"
  ID=$(echo "$JOB" | python3 -c "import sys,json;print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
  [ -z "$ID" ] && echo "iş başlatılamadı"
  for i in $(seq 1 60); do
    [ -z "$ID" ] && break
    sleep 5
    ST=$(curl -s http://127.0.0.1:18765/api/jobs/$ID)
    PH=$(echo "$ST" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('phase'),d.get('done'),'/',d.get('total'))")
    echo "  $PH"
    case "$PH" in bitti*|hata*|iptal*) break;; esac
  done
  echo "$ST" | python3 -c "import sys,json;d=json.load(sys.stdin);print('sonuç:',d.get('result'),'hata:',d.get('error'));[print('  ',l[:160]) for l in d.get('logs',[])[-12:]]"
  BOOKS=$(curl -s http://127.0.0.1:18765/api/books)
  echo "kitaplar: $BOOKS"
  echo "$BOOKS" | grep -q '\.epub' && job_ok=1
fi
[ $job_ok = 1 ] && echo "SONUC: telefonda indirme + EPUB calisti" | tee -a "$GITHUB_STEP_SUMMARY" || echo "SONUC: telefonda indirme CALISMADI" | tee -a "$GITHUB_STEP_SUMMARY"
if [ $ok = 1 ]; then echo "SONUC: arayuz acildi" | tee -a "$GITHUB_STEP_SUMMARY"; else echo "SONUC: arayuz GELMEDI" | tee -a "$GITHUB_STEP_SUMMARY"; exit 1; fi
