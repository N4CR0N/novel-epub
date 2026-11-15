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
echo "=== hata kayıtları ==="
adb logcat -d | grep -E "FATAL|AndroidRuntime|python.stderr|Traceback|Error" | head -60
echo "=== hizmet ==="
adb shell dumpsys activity services $PKG | grep -E "ServiceRecord|isForeground" | head -5
if [ $ok = 1 ]; then echo "SONUC: arayuz acildi" | tee -a "$GITHUB_STEP_SUMMARY"; else echo "SONUC: arayuz GELMEDI" | tee -a "$GITHUB_STEP_SUMMARY"; exit 1; fi
